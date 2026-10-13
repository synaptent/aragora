"""
Nomic Loop Event Definitions.

Events are the triggers that cause state transitions. Each event
carries data needed for the transition and can be logged for auditing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any


class EventType(Enum):
    """Types of events that can trigger state transitions."""

    # Lifecycle events
    START = auto()  # Start a new cycle
    STOP = auto()  # Stop the current cycle
    PAUSE = auto()  # Pause the current cycle
    RESUME = auto()  # Resume a paused cycle

    # Phase completion events
    CONTEXT_COMPLETE = auto()  # Context gathering finished
    DEBATE_COMPLETE = auto()  # Debate phase finished
    DESIGN_COMPLETE = auto()  # Design phase finished
    IMPLEMENT_COMPLETE = auto()  # Implementation finished
    VERIFY_COMPLETE = auto()  # Verification finished
    COMMIT_COMPLETE = auto()  # Commit finished

    # Error events
    ERROR = auto()  # An error occurred
    TIMEOUT = auto()  # A timeout occurred
    RETRY = auto()  # Retry the current phase
    SKIP = auto()  # Skip to next phase

    # Recovery events
    RECOVER = auto()  # Attempt recovery
    ROLLBACK = auto()  # Rollback changes
    ABORT = auto()  # Abort the cycle

    # Agent events
    AGENT_FAILED = auto()  # An agent failed
    AGENT_RECOVERED = auto()  # An agent recovered
    CIRCUIT_OPEN = auto()  # Circuit breaker opened
    CIRCUIT_CLOSE = auto()  # Circuit breaker closed

    # External events
    USER_INPUT = auto()  # User provided input
    CHECKPOINT_LOADED = auto()  # Checkpoint was loaded
    CONFIG_CHANGED = auto()  # Configuration changed

    # Approval gate events
    GATE_CHECK = auto()  # Gate check started
    GATE_APPROVED = auto()  # Gate approved
    GATE_REJECTED = auto()  # Gate rejected
    GATE_SKIPPED = auto()  # Gate skipped (disabled)


@dataclass
class Event:
    """
    An event in the nomic loop state machine.

    Events are immutable records of something that happened.
    They trigger state transitions and are logged for auditing.

    Includes distributed tracing fields for correlation across services,
    consistent with DebateEvent in aragora.debate.event_bus.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    event_type: EventType = EventType.START
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""  # Who/what generated this event
    data: dict[str, Any] = field(default_factory=dict)

    # Error information (for ERROR events)
    error_message: str | None = None
    error_type: str | None = None
    recoverable: bool = True

    # Agent information (for agent events)
    agent_name: str | None = None
    agent_error: str | None = None

    # Distributed tracing fields for correlation across services
    correlation_id: str | None = None  # Links related events across service boundaries
    trace_id: str | None = None  # OpenTelemetry-style trace identifier
    span_id: str | None = None  # Current operation span

    def __post_init__(self) -> None:
        """Auto-populate tracing fields from current context if not provided."""
        if self.correlation_id is None and self.trace_id is None:
            try:
                from aragora.observability.middleware.tracing import get_trace_id, get_span_id

                self.trace_id = get_trace_id()
                self.span_id = get_span_id()
                self.correlation_id = self.trace_id  # Use trace_id as correlation_id
            except ImportError:
                pass

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to dictionary."""
        result = {
            "event_id": self.event_id,
            "event_type": self.event_type.name,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "data": self.data,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "recoverable": self.recoverable,
            "agent_name": self.agent_name,
            "agent_error": self.agent_error,
        }
        # Include tracing fields if present
        if self.correlation_id:
            result["correlation_id"] = self.correlation_id
        if self.trace_id:
            result["trace_id"] = self.trace_id
        if self.span_id:
            result["span_id"] = self.span_id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        """Deserialize event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())[:8]),
            event_type=EventType[data.get("event_type", "START")],
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if data.get("timestamp")
                else datetime.now(timezone.utc)
            ),
            source=data.get("source", ""),
            data=data.get("data", {}),
            error_message=data.get("error_message"),
            error_type=data.get("error_type"),
            recoverable=data.get("recoverable", True),
            agent_name=data.get("agent_name"),
            agent_error=data.get("agent_error"),
        )


# Factory functions for common events
def start_event(trigger: str = "manual", config: dict | None = None) -> Event:
    """Create a START event."""
    return Event(
        event_type=EventType.START,
        source=trigger,
        data={"config": config or {}},
    )


def stop_event(reason: str = "manual") -> Event:
    """Create a STOP event."""
    return Event(
        event_type=EventType.STOP,
        source="user",
        data={"reason": reason},
    )


def pause_event(reason: str = "manual") -> Event:
    """Create a PAUSE event."""
    return Event(
        event_type=EventType.PAUSE,
        source="user",
        data={"reason": reason},
    )


def resume_event() -> Event:
    """Create a RESUME event."""
    return Event(
        event_type=EventType.RESUME,
        source="user",
    )


def phase_complete_event(
    phase: str,
    result: dict[str, Any],
    duration_seconds: float = 0,
    tokens_used: int = 0,
) -> Event:
    """Create a phase completion event."""
    event_types = {
        "context": EventType.CONTEXT_COMPLETE,
        "debate": EventType.DEBATE_COMPLETE,
        "design": EventType.DESIGN_COMPLETE,
        "implement": EventType.IMPLEMENT_COMPLETE,
        "verify": EventType.VERIFY_COMPLETE,
        "commit": EventType.COMMIT_COMPLETE,
    }
    return Event(
        event_type=event_types.get(phase, EventType.CONTEXT_COMPLETE),
        source=phase,
        data={
            "result": result,
            "duration_seconds": duration_seconds,
            "tokens_used": tokens_used,
        },
    )


def error_event(
    phase: str,
    error: Exception,
    recoverable: bool = True,
) -> Event:
    """Create an ERROR event."""
    return Event(
        event_type=EventType.ERROR,
        source=phase,
        error_message=str(error),
        error_type=type(error).__name__,
        recoverable=recoverable,
        data={"traceback": getattr(error, "__traceback__", None) is not None},
    )


def timeout_event(phase: str, timeout_seconds: int) -> Event:
    """Create a TIMEOUT event."""
    return Event(
        event_type=EventType.TIMEOUT,
        source=phase,
        error_message=f"Phase {phase} timed out after {timeout_seconds}s",
        recoverable=True,
        data={"timeout_seconds": timeout_seconds},
    )


def retry_event(phase: str, attempt: int, max_attempts: int) -> Event:
    """Create a RETRY event."""
    return Event(
        event_type=EventType.RETRY,
        source=phase,
        data={
            "attempt": attempt,
            "max_attempts": max_attempts,
        },
    )


def agent_failed_event(
    agent_name: str,
    error: str,
    failure_count: int = 1,
) -> Event:
    """Create an AGENT_FAILED event."""
    return Event(
        event_type=EventType.AGENT_FAILED,
        source="agent_monitor",
        agent_name=agent_name,
        agent_error=error,
        data={"failure_count": failure_count},
    )


def circuit_open_event(agent_name: str, failures: int) -> Event:
    """Create a CIRCUIT_OPEN event."""
    return Event(
        event_type=EventType.CIRCUIT_OPEN,
        source="circuit_breaker",
        agent_name=agent_name,
        data={"failures": failures},
    )


def rollback_event(reason: str, files_affected: list[str]) -> Event:
    """Create a ROLLBACK event."""
    return Event(
        event_type=EventType.ROLLBACK,
        source="recovery",
        data={
            "reason": reason,
            "files_affected": files_affected,
        },
    )


def checkpoint_loaded_event(checkpoint_path: str, state: str) -> Event:
    """Create a CHECKPOINT_LOADED event."""
    return Event(
        event_type=EventType.CHECKPOINT_LOADED,
        source="checkpoint",
        data={
            "path": checkpoint_path,
            "state": state,
        },
    )


def gate_approved_event(
    gate_type: str,
    approver: str,
    artifact_hash: str,
    reason: str = "",
) -> Event:
    """Create a GATE_APPROVED event."""
    return Event(
        event_type=EventType.GATE_APPROVED,
        source=f"gate_{gate_type}",
        data={
            "gate_type": gate_type,
            "approver": approver,
            "artifact_hash": artifact_hash,
            "reason": reason,
        },
    )


def gate_rejected_event(
    gate_type: str,
    reason: str,
    artifact_hash: str = "",
) -> Event:
    """Create a GATE_REJECTED event."""
    return Event(
        event_type=EventType.GATE_REJECTED,
        source=f"gate_{gate_type}",
        error_message=reason,
        recoverable=True,
        data={
            "gate_type": gate_type,
            "artifact_hash": artifact_hash,
            "reason": reason,
        },
    )


@dataclass
class EventLog:
    """
    Log of events for a nomic loop cycle.

    Provides event sourcing - the complete history of what happened.
    """

    cycle_id: str = ""
    events: list[Event] = field(default_factory=list)

    def append(self, event: Event) -> None:
        """Add an event to the log."""
        self.events.append(event)

    def get_events_by_type(self, event_type: EventType) -> list[Event]:
        """Get all events of a specific type."""
        return [e for e in self.events if e.event_type == event_type]

    def get_errors(self) -> list[Event]:
        """Get all error events."""
        return self.get_events_by_type(EventType.ERROR)

    def get_phase_events(self, phase: str) -> list[Event]:
        """Get all events from a specific phase."""
        return [e for e in self.events if e.source == phase]

    def to_dict(self) -> dict[str, Any]:
        """Serialize event log to dictionary."""
        return {
            "cycle_id": self.cycle_id,
            "events": [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventLog:
        """Deserialize event log from dictionary."""
        log = cls(cycle_id=data.get("cycle_id", ""))
        log.events = [Event.from_dict(e) for e in data.get("events", [])]
        return log

    def summary(self) -> dict[str, Any]:
        """Get a summary of the event log."""
        return {
            "total_events": len(self.events),
            "errors": len(self.get_errors()),
            "event_types": {
                et.name: len(self.get_events_by_type(et))
                for et in EventType
                if self.get_events_by_type(et)
            },
            "duration_seconds": (
                (self.events[-1].timestamp - self.events[0].timestamp).total_seconds()
                if len(self.events) >= 2
                else 0
            ),
        }
