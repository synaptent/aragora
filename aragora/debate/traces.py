"""
Debate Tracing and Replay System.

Provides deterministic, replayable debate artifacts with full event logging.
Enables audits, regression tests, and research reproducibility.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Iterator

if TYPE_CHECKING:
    from aragora.core import DebateResult

from aragora.config import DB_TIMEOUT_SECONDS
from aragora.debate.traces_database import TracesDatabase
from aragora.storage.base_store import SQLiteStore


class EventType(Enum):
    """Types of debate events."""

    DEBATE_START = "debate_start"
    DEBATE_END = "debate_end"
    ROUND_START = "round_start"
    ROUND_END = "round_end"
    MESSAGE = "message"  # Generic agent message
    AGENT_PROPOSAL = "agent_proposal"
    AGENT_CRITIQUE = "agent_critique"
    AGENT_SYNTHESIS = "agent_synthesis"
    CONSENSUS_CHECK = "consensus_check"
    FORK_DECISION = "fork_decision"
    FORK_CREATED = "fork_created"
    MERGE_RESULT = "merge_result"
    MEMORY_ACCESS = "memory_access"
    MEMORY_WRITE = "memory_write"
    HUMAN_INTERVENTION = "human_intervention"
    ERROR = "error"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


@dataclass
class TraceEvent:
    """A single event in the debate trace."""

    event_id: str
    event_type: EventType
    timestamp: str
    round_num: int
    agent: str | None
    content: dict
    parent_event_id: str | None = None
    duration_ms: int | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> TraceEvent:
        """Create from dictionary."""
        data["event_type"] = EventType(data["event_type"])
        return cls(**data)


@dataclass
class DebateTrace:
    """Complete trace of a debate for replay and analysis."""

    trace_id: str
    debate_id: str
    task: str
    agents: list[str]
    random_seed: int
    events: list[TraceEvent] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str | None = None
    final_result: dict | None = None
    metadata: dict = field(default_factory=dict)

    # Checksum caching fields (not serialized)
    _checksum_dirty: bool = field(default=True, repr=False, compare=False)
    _cached_checksum: str | None = field(default=None, repr=False, compare=False)
    _last_event_count: int = field(default=0, repr=False, compare=False)

    def _mark_checksum_dirty(self) -> None:
        """Mark checksum as needing recalculation."""
        object.__setattr__(self, "_checksum_dirty", True)

    def add_event(self, event: TraceEvent) -> None:
        """Add an event and mark checksum as dirty."""
        self.events.append(event)
        self._mark_checksum_dirty()

    def clear_events(self) -> None:
        """Clear all events and mark checksum as dirty."""
        self.events.clear()
        self._mark_checksum_dirty()

    @property
    def checksum(self) -> str:
        """Generate checksum for trace integrity verification (cached).

        Uses dirty flag pattern with event count fallback to detect direct
        list modifications for backward compatibility.
        """
        # Detect direct modifications to events list via count change
        current_count = len(self.events)
        if current_count != self._last_event_count:
            object.__setattr__(self, "_checksum_dirty", True)

        if self._checksum_dirty or self._cached_checksum is None:
            content = json.dumps([e.to_dict() for e in self.events], sort_keys=True)
            object.__setattr__(
                self, "_cached_checksum", hashlib.sha256(content.encode()).hexdigest()[:16]
            )
            object.__setattr__(self, "_checksum_dirty", False)
            object.__setattr__(self, "_last_event_count", current_count)
        if self._cached_checksum is None:  # pragma: no cover – unreachable after block above
            raise RuntimeError("_cached_checksum was not set during checksum computation")
        return self._cached_checksum

    @property
    def duration_ms(self) -> int | None:
        """Total debate duration in milliseconds."""
        if not self.completed_at:
            return None
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.completed_at)
        return int((end - start).total_seconds() * 1000)

    def get_events_by_type(self, event_type: EventType) -> list[TraceEvent]:
        """Filter events by type."""
        return [e for e in self.events if e.event_type == event_type]

    def get_events_by_agent(self, agent: str) -> list[TraceEvent]:
        """Filter events by agent."""
        return [e for e in self.events if e.agent == agent]

    def get_events_by_round(self, round_num: int) -> list[TraceEvent]:
        """Filter events by round."""
        return [e for e in self.events if e.round_num == round_num]

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON."""
        data = {
            "trace_id": self.trace_id,
            "debate_id": self.debate_id,
            "task": self.task,
            "agents": self.agents,
            "random_seed": self.random_seed,
            "events": [e.to_dict() for e in self.events],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "final_result": self.final_result,
            "metadata": self.metadata,
            "checksum": self.checksum,
        }
        return json.dumps(data, indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> DebateTrace:
        """Deserialize from JSON."""
        data = json.loads(json_str)
        stored_checksum = data.pop("checksum", None)
        events = [TraceEvent.from_dict(e) for e in data.pop("events", [])]
        trace = cls(**data, events=events)

        if stored_checksum and trace.checksum != stored_checksum:
            raise ValueError(
                f"Trace checksum mismatch: expected {stored_checksum}, got {trace.checksum}"
            )

        return trace

    def save(self, path: Path) -> None:
        """Save trace to file."""
        path.write_text(self.to_json())

    @classmethod
    def load(cls, path: Path) -> DebateTrace:
        """Load trace from file."""
        if not path.exists():
            raise FileNotFoundError(f"Debate trace not found: {path}")
        try:
            return cls.from_json(path.read_text())
        except OSError as e:
            raise OSError(f"Failed to read debate trace {path}: {e}") from e

    def to_debate_result(self) -> DebateResult:
        """Convert trace to a DebateResult for analysis.

        Reconstructs messages and critiques from trace events.
        """
        from aragora.core import Critique, DebateResult, Message

        messages: list[Message] = []
        critiques: list[Critique] = []
        consensus_reached = False
        confidence = 0.0
        final_answer = ""

        for event in self.events:
            if event.event_type == EventType.AGENT_PROPOSAL:
                messages.append(
                    Message(
                        role="proposer",
                        agent=event.agent or "unknown",
                        content=event.content.get("content", ""),
                        timestamp=datetime.fromisoformat(event.timestamp),
                        round=event.round_num,
                    )
                )
            elif event.event_type == EventType.AGENT_CRITIQUE:
                critiques.append(
                    Critique(
                        agent=event.agent or "unknown",
                        target_agent=event.content.get("target_agent", ""),
                        target_content="",  # Not stored in trace events
                        issues=event.content.get("issues", []),
                        suggestions=event.content.get("suggestions", []),
                        severity=event.content.get("severity", 0.0),
                        reasoning="",  # Not stored in trace events
                    )
                )
            elif event.event_type == EventType.AGENT_SYNTHESIS:
                messages.append(
                    Message(
                        role="synthesizer",
                        agent=event.agent or "unknown",
                        content=event.content.get("content", ""),
                        timestamp=datetime.fromisoformat(event.timestamp),
                        round=event.round_num,
                    )
                )
            elif event.event_type == EventType.CONSENSUS_CHECK:
                if event.content.get("reached", False):
                    consensus_reached = True
                    confidence = event.content.get("confidence", 0.0)
            elif event.event_type == EventType.MESSAGE:
                # Generic message event
                messages.append(
                    Message(
                        role=event.content.get("role", "proposer"),
                        agent=event.agent or "unknown",
                        content=event.content.get("content", ""),
                        timestamp=datetime.fromisoformat(event.timestamp),
                        round=event.round_num,
                    )
                )

        # Get final answer from final_result or last synthesis
        if self.final_result:
            final_answer = self.final_result.get("final_answer", "")
        elif messages:
            # Use last synthesizer message as final answer
            for msg in reversed(messages):
                if msg.role == "synthesizer":
                    final_answer = msg.content
                    break

        # Calculate rounds used
        rounds_used = max((e.round_num for e in self.events), default=0)

        return DebateResult(
            debate_id=self.debate_id,
            task=self.task,
            final_answer=final_answer,
            confidence=confidence,
            consensus_reached=consensus_reached,
            rounds_used=rounds_used,
            rounds_completed=rounds_used,
            participants=self.agents,
            messages=messages,
            critiques=critiques,
            duration_seconds=(self.duration_ms or 0) / 1000.0,
        )


class DebateTracer(SQLiteStore):
    """
    Records debate events for replay and analysis.

    Creates deterministic traces that can be replayed with identical results.
    """

    SCHEMA_NAME = "debate_tracer"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS traces (
            trace_id TEXT PRIMARY KEY,
            debate_id TEXT,
            task TEXT,
            agents TEXT,
            random_seed INTEGER,
            started_at TEXT,
            completed_at TEXT,
            checksum TEXT,
            trace_json TEXT
        );

        CREATE TABLE IF NOT EXISTS trace_events (
            event_id TEXT PRIMARY KEY,
            trace_id TEXT,
            event_type TEXT,
            timestamp TEXT,
            round_num INTEGER,
            agent TEXT,
            content TEXT,
            FOREIGN KEY (trace_id) REFERENCES traces(trace_id)
        );

        CREATE INDEX IF NOT EXISTS idx_trace_events_trace
        ON trace_events(trace_id);
    """

    def __init__(
        self,
        debate_id: str,
        task: str,
        agents: list[str],
        random_seed: int | None = None,
        db_path: str = "aragora_traces.db",
    ):
        # Initialize SQLiteStore first
        super().__init__(db_path, timeout=DB_TIMEOUT_SECONDS)

        self.debate_id = debate_id
        self.task = task
        self.agents = agents
        self.random_seed = random_seed or random.randint(0, 2**32 - 1)  # noqa: S311 -- deterministic seed for reproducibility

        # Seed random for determinism
        random.seed(self.random_seed)

        # Create trace
        self.trace = DebateTrace(
            trace_id=f"trace-{debate_id}",
            debate_id=debate_id,
            task=task,
            agents=agents,
            random_seed=self.random_seed,
        )

        self._event_counter = 0
        self._current_round = 0
        self._event_stack: list[str] = []  # For parent tracking

    def _generate_event_id(self) -> str:
        """Generate unique event ID."""
        self._event_counter += 1
        return f"{self.debate_id}-e{self._event_counter:04d}"

    def record(
        self,
        event_type: EventType,
        content: dict,
        agent: str | None = None,
        duration_ms: int | None = None,
        metadata: dict | None = None,
    ) -> TraceEvent:
        """Record a debate event."""
        event = TraceEvent(
            event_id=self._generate_event_id(),
            event_type=event_type,
            timestamp=datetime.now().isoformat(),
            round_num=self._current_round,
            agent=agent,
            content=content,
            parent_event_id=self._event_stack[-1] if self._event_stack else None,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

        self.trace.add_event(event)
        return event

    def start_round(self, round_num: int) -> None:
        """Mark start of a new round."""
        self._current_round = round_num
        event = self.record(
            EventType.ROUND_START,
            {"round": round_num},
        )
        self._event_stack.append(event.event_id)

    def end_round(self) -> None:
        """Mark end of current round."""
        if self._event_stack:
            self._event_stack.pop()
        self.record(
            EventType.ROUND_END,
            {"round": self._current_round},
        )

    def record_proposal(self, agent: str, content: str, confidence: float = 0.0) -> None:
        """Record an agent's proposal."""
        self.record(
            EventType.AGENT_PROPOSAL,
            {"content": content, "confidence": confidence},
            agent=agent,
        )

    def record_critique(
        self,
        agent: str,
        target_agent: str,
        issues: list[str],
        severity: float,
        suggestions: list[str],
    ) -> None:
        """Record a critique."""
        self.record(
            EventType.AGENT_CRITIQUE,
            {
                "target_agent": target_agent,
                "issues": issues,
                "severity": severity,
                "suggestions": suggestions,
            },
            agent=agent,
        )

    def record_synthesis(self, agent: str, content: str, incorporated: list[str]) -> None:
        """Record a synthesis."""
        self.record(
            EventType.AGENT_SYNTHESIS,
            {"content": content, "incorporated": incorporated},
            agent=agent,
        )

    def record_consensus(self, reached: bool, confidence: float, votes: dict[str, bool]) -> None:
        """Record consensus check result."""
        self.record(
            EventType.CONSENSUS_CHECK,
            {"reached": reached, "confidence": confidence, "votes": votes},
        )

    def record_tool_call(self, agent: str, tool: str, args: dict) -> str:
        """Record a tool call, return event ID for linking result."""
        event = self.record(
            EventType.TOOL_CALL,
            {"tool": tool, "args": args},
            agent=agent,
        )
        return event.event_id

    def record_tool_result(self, agent: str, tool: str, result: Any, call_event_id: str) -> None:
        """Record tool call result."""
        self.record(
            EventType.TOOL_RESULT,
            {"tool": tool, "result": str(result)[:1000]},  # Truncate large results
            agent=agent,
            metadata={"call_event_id": call_event_id},
        )

    def record_error(self, error: str, agent: str | None = None) -> None:
        """Record an error."""
        self.record(
            EventType.ERROR,
            {"error": error},
            agent=agent,
        )

    def finalize(self, result: dict) -> DebateTrace:
        """Finalize the trace with the debate result."""
        self.trace.completed_at = datetime.now().isoformat()
        self.trace.final_result = result

        self.record(
            EventType.DEBATE_END,
            {"result_summary": str(result)[:500]},
        )

        # Save to database
        self._save_trace()

        return self.trace

    def _save_trace(self):
        """Save trace to database."""
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT OR REPLACE INTO traces
                (trace_id, debate_id, task, agents, random_seed, started_at, completed_at, checksum, trace_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    self.trace.trace_id,
                    self.debate_id,
                    self.task,
                    json.dumps(self.agents),
                    self.random_seed,
                    self.trace.started_at,
                    self.trace.completed_at,
                    self.trace.checksum,
                    self.trace.to_json(),
                ),
            )

            # Save individual events for querying
            for event in self.trace.events:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO trace_events
                    (event_id, trace_id, event_type, timestamp, round_num, agent, content)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        event.event_id,
                        self.trace.trace_id,
                        event.event_type.value,
                        event.timestamp,
                        event.round_num,
                        event.agent,
                        json.dumps(event.content),
                    ),
                )

            conn.commit()

    def get_state_at_event(self, event_id: str) -> dict[str, Any]:
        """Reconstruct debate state at a specific event."""
        state: dict[str, Any] = {
            "round": 0,
            "messages": [],
            "critiques": [],
            "consensus": None,
            "agents_acted": set(),
        }

        for event in self.trace.events:
            if event.event_type == EventType.ROUND_START:
                state["round"] = event.content["round"]
                state["agents_acted"] = set()
            elif event.event_type == EventType.AGENT_PROPOSAL:
                state["messages"].append(
                    {
                        "agent": event.agent,
                        "content": event.content["content"],
                        "round": state["round"],
                    }
                )
                state["agents_acted"].add(event.agent)
            elif event.event_type == EventType.AGENT_CRITIQUE:
                state["critiques"].append(
                    {
                        "agent": event.agent,
                        "target": event.content["target_agent"],
                        "issues": event.content["issues"],
                    }
                )
            elif event.event_type == EventType.CONSENSUS_CHECK:
                state["consensus"] = event.content

            if event.event_id == event_id:
                break

        state["agents_acted"] = list(state["agents_acted"])
        return state


class DebateReplayer:
    """
    Replays recorded debates for analysis or continuation.

    Supports:
    - Full replay with same random seed
    - Forking from any point with modifications
    - Step-by-step execution with inspection
    """

    def __init__(self, trace: DebateTrace):
        self.trace = trace
        self._position = 0

        # Restore random state
        random.seed(trace.random_seed)

    @classmethod
    def from_file(cls, path: Path) -> DebateReplayer:
        """Load replayer from trace file."""
        return cls(DebateTrace.load(path))

    @classmethod
    def from_database(cls, trace_id: str, db_path: str = "aragora_traces.db") -> DebateReplayer:
        """Load replayer from database."""
        db = TracesDatabase(db_path)
        with db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT trace_json FROM traces WHERE trace_id = ?", (trace_id,))
            row = cursor.fetchone()

        if not row:
            raise ValueError(f"Trace not found: {trace_id}")

        return cls(DebateTrace.from_json(row[0]))

    def reset(self) -> None:
        """Reset replay position to start."""
        self._position = 0
        random.seed(self.trace.random_seed)

    def step(self) -> TraceEvent | None:
        """Advance one event and return it."""
        if self._position >= len(self.trace.events):
            return None

        event = self.trace.events[self._position]
        self._position += 1
        return event

    def step_to_round(self, round_num: int) -> list[TraceEvent]:
        """Advance to start of specified round."""
        events = []
        while self._position < len(self.trace.events):
            event = self.trace.events[self._position]
            if event.event_type == EventType.ROUND_START and event.content["round"] == round_num:
                break
            events.append(event)
            self._position += 1
        return events

    def get_state(self) -> dict:
        """Get current replay state."""
        if self._position == 0:
            return {"round": 0, "messages": [], "critiques": []}

        current_event = self.trace.events[self._position - 1]
        tracer = DebateTracer(
            self.trace.debate_id,
            self.trace.task,
            self.trace.agents,
            self.trace.random_seed,
        )
        tracer.trace = self.trace
        return tracer.get_state_at_event(current_event.event_id)

    def fork_at(self, event_id: str, new_seed: int | None = None) -> DebateTracer:
        """
        Create a new tracer forked from a specific event.

        The new tracer contains all events up to the fork point
        and can continue with new events.
        """
        # Find fork point
        fork_idx = None
        for i, event in enumerate(self.trace.events):
            if event.event_id == event_id:
                fork_idx = i
                break

        if fork_idx is None:
            raise ValueError(f"Event not found: {event_id}")

        # Create new tracer with events up to fork
        new_tracer = DebateTracer(
            debate_id=f"{self.trace.debate_id}-fork",
            task=self.trace.task,
            agents=self.trace.agents,
            random_seed=new_seed,
        )

        # Copy events up to fork point (use clear + add to properly track checksum)
        new_tracer.trace.clear_events()
        for event in self.trace.events[: fork_idx + 1]:
            new_tracer.trace.add_event(event)
        new_tracer._event_counter = fork_idx + 1

        # Set current round from last round event
        for event in reversed(new_tracer.trace.events):
            if event.event_type == EventType.ROUND_START:
                new_tracer._current_round = event.content["round"]
                break

        return new_tracer

    def events(self) -> Iterator[TraceEvent]:
        """Iterate through all events."""
        for event in self.trace.events:
            yield event

    def generate_diff(self, other: DebateTrace) -> list[dict]:
        """
        Generate diff between this trace and another.

        Useful for comparing different runs or forks.
        """
        diffs = []

        max_len = max(len(self.trace.events), len(other.events))

        for i in range(max_len):
            event_a = self.trace.events[i] if i < len(self.trace.events) else None
            event_b = other.events[i] if i < len(other.events) else None

            if event_a is None:
                if event_b is not None:
                    diffs.append({"type": "added", "position": i, "event": event_b.to_dict()})
            elif event_b is None:
                diffs.append({"type": "removed", "position": i, "event": event_a.to_dict()})
            elif event_a.to_dict() != event_b.to_dict():
                diffs.append(
                    {
                        "type": "changed",
                        "position": i,
                        "from": event_a.to_dict(),
                        "to": event_b.to_dict(),
                    }
                )

        return diffs

    def generate_markdown_report(self) -> str:
        """Generate a readable Markdown report of the debate."""
        lines = [
            "# Debate Trace Report",
            "",
            f"**Trace ID:** {self.trace.trace_id}",
            f"**Task:** {self.trace.task}",
            f"**Agents:** {', '.join(self.trace.agents)}",
            f"**Duration:** {self.trace.duration_ms}ms" if self.trace.duration_ms else "",
            f"**Checksum:** {self.trace.checksum}",
            "",
            "---",
            "",
        ]

        current_round = -1

        for event in self.trace.events:
            if event.event_type == EventType.ROUND_START:
                current_round = event.content["round"]
                lines.append(f"## Round {current_round}")
                lines.append("")

            elif event.event_type == EventType.AGENT_PROPOSAL:
                lines.append(f"### {event.agent} (Proposal)")
                lines.append("")
                lines.append(event.content["content"][:500])
                if len(event.content["content"]) > 500:
                    lines.append("...")
                lines.append("")

            elif event.event_type == EventType.AGENT_CRITIQUE:
                lines.append(f"### {event.agent} → {event.content['target_agent']} (Critique)")
                lines.append("")
                lines.append(f"**Severity:** {event.content['severity']:.1f}")
                lines.append("")
                lines.append("**Issues:**")
                for issue in event.content["issues"]:
                    lines.append(f"- {issue}")
                lines.append("")

            elif event.event_type == EventType.CONSENSUS_CHECK:
                lines.append("### Consensus Check")
                lines.append("")
                lines.append(f"**Reached:** {'Yes' if event.content['reached'] else 'No'}")
                lines.append(f"**Confidence:** {event.content['confidence']:.0%}")
                lines.append("")

        if self.trace.final_result:
            lines.append("---")
            lines.append("")
            lines.append("## Final Result")
            lines.append("")
            lines.append(str(self.trace.final_result))

        return "\n".join(lines)


def list_traces(db_path: str = "aragora_traces.db", limit: int = 20) -> list[dict]:
    """List recent traces from database."""
    db = TracesDatabase(db_path)
    with db.connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT trace_id, debate_id, task, agents, started_at, completed_at, checksum
            FROM traces
            ORDER BY started_at DESC
            LIMIT ?
        """,
            (limit,),
        )

        traces = []
        for row in cursor.fetchall():
            traces.append(
                {
                    "trace_id": row[0],
                    "debate_id": row[1],
                    "task": row[2][:100],
                    "agents": json.loads(row[3]),
                    "started_at": row[4],
                    "completed_at": row[5],
                    "checksum": row[6],
                }
            )

    return traces
