"""
Debate Witness - Progress Observer for Multi-Agent Debates.

The Witness pattern provides real-time monitoring of debate progress:
- Progress tracking per agent per round
- Detection of repeated proposals/critiques via semantic similarity
- Stall detection with configurable thresholds
- Integration with protocol messages for audit trails
- Callback hooks for recovery coordination

Inspired by gastown's witness pattern for distributed work observation.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable

from aragora.debate.protocol_messages import (
    ProtocolMessage,
    ProtocolMessageType,
)

logger = logging.getLogger(__name__)


class ProgressStatus(str, Enum):
    """Status of agent progress in a debate round."""

    HEALTHY = "healthy"  # Making progress
    SLOW = "slow"  # Behind expected pace
    STALLED = "stalled"  # No progress detected
    REPEATED = "repeated"  # Repeating previous content
    FAILED = "failed"  # Agent failed to respond


class StallReason(str, Enum):
    """Reason for a detected stall."""

    TIMEOUT = "timeout"  # No response within threshold
    REPEATED_CONTENT = "repeated_content"  # Content too similar to previous
    CIRCULAR_ARGUMENTS = "circular_arguments"  # Arguments forming a cycle
    NO_PROGRESS = "no_progress"  # Round not advancing
    AGENT_FAILURE = "agent_failure"  # Agent threw an error


@dataclass
class AgentProgress:
    """Track progress for a single agent in the debate."""

    agent_id: str
    debate_id: str
    proposals_submitted: int = 0
    critiques_submitted: int = 0
    revisions_submitted: int = 0
    votes_cast: int = 0
    last_activity: datetime | None = None
    current_round: int = 0
    status: ProgressStatus = ProgressStatus.HEALTHY
    stall_reason: StallReason | None = None
    failure_count: int = 0
    recovery_count: int = 0
    content_hashes: list[str] = field(default_factory=list)  # For repetition detection

    def record_activity(self, activity_type: str) -> None:
        """Record an activity for this agent."""
        self.last_activity = datetime.now(timezone.utc)

        if activity_type == "proposal":
            self.proposals_submitted += 1
        elif activity_type == "critique":
            self.critiques_submitted += 1
        elif activity_type == "revision":
            self.revisions_submitted += 1
        elif activity_type == "vote":
            self.votes_cast += 1

    def time_since_activity(self) -> float | None:
        """Get seconds since last activity."""
        if not self.last_activity:
            return None
        return (datetime.now(timezone.utc) - self.last_activity).total_seconds()


@dataclass
class RoundProgress:
    """Track progress for a debate round."""

    round_number: int
    debate_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    proposals_expected: int = 0
    proposals_received: int = 0
    critiques_expected: int = 0
    critiques_received: int = 0
    revisions_expected: int = 0
    revisions_received: int = 0
    phase: str = "proposal"  # proposal, critique, revision, voting

    @property
    def is_complete(self) -> bool:
        """Check if round is complete."""
        return self.completed_at is not None

    @property
    def duration_seconds(self) -> float | None:
        """Get round duration in seconds."""
        if not self.completed_at:
            return None
        return (self.completed_at - self.started_at).total_seconds()


@dataclass
class WitnessConfig:
    """Configuration for the debate witness."""

    # Timing thresholds (seconds)
    slow_threshold_seconds: float = 30.0
    stall_threshold_seconds: float = 120.0

    # Repetition detection
    similarity_threshold: float = 0.9  # Content similarity threshold for repetition
    max_content_history: int = 10  # Content hashes to retain per agent

    # Recovery settings
    max_failures_before_replacement: int = 3
    max_stalls_before_escalation: int = 2
    auto_recovery_enabled: bool = True

    # Callbacks
    emit_protocol_messages: bool = True
    check_interval_seconds: float = 5.0


@dataclass
class StallEvent:
    """Event representing a detected stall."""

    debate_id: str
    agent_id: str | None
    round_number: int
    reason: StallReason
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolution: str | None = None


class DebateWitness:
    """
    Observer that monitors debate progress and detects issues.

    The Witness maintains a view of debate state without modifying it,
    similar to an audit observer. It tracks:
    - Per-agent activity and progress
    - Per-round completion status
    - Content similarity for repetition detection
    - Stall patterns across rounds

    Usage:
        witness = DebateWitness(debate_id="debate-123", config=WitnessConfig())

        # Register agents
        witness.register_agent("claude-opus")
        witness.register_agent("gpt-4")

        # Observe protocol messages
        witness.observe(proposal_message)
        witness.observe(critique_message)

        # Check for issues
        stalls = witness.detect_stalls()
        if stalls:
            await recovery_coordinator.handle_stalls(stalls)

        # Get progress summary
        summary = witness.get_progress_summary()
    """

    def __init__(
        self,
        debate_id: str,
        config: WitnessConfig | None = None,
        on_stall: Callable[[StallEvent], None] | None = None,
        on_progress: Callable[[AgentProgress], None] | None = None,
    ):
        """
        Initialize the witness.

        Args:
            debate_id: ID of the debate being witnessed
            config: Witness configuration
            on_stall: Callback when a stall is detected
            on_progress: Callback when progress is updated
        """
        self.debate_id = debate_id
        self.config = config or WitnessConfig()
        self.on_stall = on_stall
        self.on_progress = on_progress

        # State tracking
        self._agents: dict[str, AgentProgress] = {}
        self._rounds: dict[int, RoundProgress] = {}
        self._current_round: int = 0
        self._stall_events: list[StallEvent] = []
        self._message_log: list[ProtocolMessage] = []
        self._started_at: datetime = datetime.now(timezone.utc)
        self._monitoring_task: asyncio.Task | None = None
        self._running: bool = False
        self._lock = asyncio.Lock()

    def register_agent(self, agent_id: str) -> AgentProgress:
        """Register an agent for tracking."""
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentProgress(
                agent_id=agent_id,
                debate_id=self.debate_id,
            )
            logger.debug("Witness registered agent: %s", agent_id)
        return self._agents[agent_id]

    def start_round(
        self,
        round_number: int,
        proposals_expected: int = 0,
        critiques_expected: int = 0,
        revisions_expected: int = 0,
    ) -> RoundProgress:
        """Start tracking a new round."""
        self._current_round = round_number
        self._rounds[round_number] = RoundProgress(
            round_number=round_number,
            debate_id=self.debate_id,
            proposals_expected=proposals_expected,
            critiques_expected=critiques_expected,
            revisions_expected=revisions_expected,
        )

        # Reset agent round tracking
        for agent in self._agents.values():
            agent.current_round = round_number

        logger.debug("Witness started round %s", round_number)
        return self._rounds[round_number]

    def complete_round(self, round_number: int) -> RoundProgress | None:
        """Mark a round as complete."""
        if round_number in self._rounds:
            self._rounds[round_number].completed_at = datetime.now(timezone.utc)
            return self._rounds[round_number]
        return None

    def observe(self, message: ProtocolMessage) -> None:
        """
        Observe a protocol message and update tracking state.

        Args:
            message: The protocol message to observe
        """
        self._message_log.append(message)

        # Update round progress
        if message.round_number is not None:
            if message.round_number not in self._rounds:
                self.start_round(message.round_number)
            self._update_round_progress(message)

        # Update agent progress
        if message.agent_id:
            if message.agent_id not in self._agents:
                self.register_agent(message.agent_id)
            self._update_agent_progress(message)

    def _update_round_progress(self, message: ProtocolMessage) -> None:
        """Update round progress based on message."""
        round_progress = self._rounds.get(message.round_number)
        if not round_progress:
            return

        if message.message_type == ProtocolMessageType.PROPOSAL_SUBMITTED:
            round_progress.proposals_received += 1
            round_progress.phase = "proposal"

        elif message.message_type == ProtocolMessageType.CRITIQUE_SUBMITTED:
            round_progress.critiques_received += 1
            round_progress.phase = "critique"

        elif message.message_type == ProtocolMessageType.REVISION_SUBMITTED:
            round_progress.revisions_received += 1
            round_progress.phase = "revision"

        elif message.message_type == ProtocolMessageType.ROUND_COMPLETED:
            round_progress.completed_at = datetime.now(timezone.utc)

    def _update_agent_progress(self, message: ProtocolMessage) -> None:
        """Update agent progress based on message."""
        agent = self._agents.get(message.agent_id)
        if not agent:
            return

        # Map message types to activity types
        activity_map = {
            ProtocolMessageType.PROPOSAL_SUBMITTED: "proposal",
            ProtocolMessageType.PROPOSAL_REVISED: "revision",
            ProtocolMessageType.CRITIQUE_SUBMITTED: "critique",
            ProtocolMessageType.REBUTTAL_SUBMITTED: "critique",
            ProtocolMessageType.REVISION_SUBMITTED: "revision",
            ProtocolMessageType.VOTE_CAST: "vote",
        }

        activity_type = activity_map.get(message.message_type)
        if activity_type:
            agent.record_activity(activity_type)
            agent.status = ProgressStatus.HEALTHY
            agent.stall_reason = None

            # Track content hash for repetition detection
            if message.payload and hasattr(message.payload, "content"):
                content = (
                    message.payload.content
                    if hasattr(message.payload, "content")
                    else str(message.payload)
                )
                content_hash = self._hash_content(content)
                agent.content_hashes.append(content_hash)
                if len(agent.content_hashes) > self.config.max_content_history:
                    agent.content_hashes = agent.content_hashes[-self.config.max_content_history :]

        # Track failures
        if message.message_type == ProtocolMessageType.AGENT_FAILED:
            agent.failure_count += 1
            agent.status = ProgressStatus.FAILED
            agent.stall_reason = StallReason.AGENT_FAILURE

        # Notify callback
        if self.on_progress:
            self.on_progress(agent)

    def _hash_content(self, content: str) -> str:
        """Create a hash of content for repetition detection."""
        # Normalize content before hashing
        normalized = " ".join(content.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def detect_stalls(self) -> list[StallEvent]:
        """
        Detect stalls across all agents and rounds.

        Returns:
            List of new stall events detected
        """
        new_stalls = []
        now = datetime.now(timezone.utc)

        # Check each agent
        for agent_id, agent in self._agents.items():
            stall = self._check_agent_stall(agent, now)
            if stall:
                new_stalls.append(stall)
                self._stall_events.append(stall)

                if self.on_stall:
                    self.on_stall(stall)

        # Check round progress
        round_stall = self._check_round_stall(now)
        if round_stall:
            new_stalls.append(round_stall)
            self._stall_events.append(round_stall)

            if self.on_stall:
                self.on_stall(round_stall)

        return new_stalls

    def _check_agent_stall(self, agent: AgentProgress, now: datetime) -> StallEvent | None:
        """Check if an agent has stalled."""
        time_since = agent.time_since_activity()

        # Already marked as stalled
        if agent.status == ProgressStatus.STALLED:
            return None

        # Check timeout
        if time_since and time_since > self.config.stall_threshold_seconds:
            agent.status = ProgressStatus.STALLED
            agent.stall_reason = StallReason.TIMEOUT
            return StallEvent(
                debate_id=self.debate_id,
                agent_id=agent.agent_id,
                round_number=self._current_round,
                reason=StallReason.TIMEOUT,
                details={"seconds_inactive": time_since},
            )

        # Check slow progress
        elif time_since and time_since > self.config.slow_threshold_seconds:
            if agent.status != ProgressStatus.SLOW:
                agent.status = ProgressStatus.SLOW
                logger.warning("Agent %s slow: %.1fs since activity", agent.agent_id, time_since)

        return None

    def _check_round_stall(self, now: datetime) -> StallEvent | None:
        """Check if the current round has stalled."""
        round_progress = self._rounds.get(self._current_round)
        if not round_progress or round_progress.is_complete:
            return None

        round_duration = (now - round_progress.started_at).total_seconds()

        # Check if round is taking too long relative to expected completions
        total_expected = (
            round_progress.proposals_expected
            + round_progress.critiques_expected
            + round_progress.revisions_expected
        )
        total_received = (
            round_progress.proposals_received
            + round_progress.critiques_received
            + round_progress.revisions_received
        )

        if total_expected > 0:
            completion_rate = total_received / total_expected
            expected_duration = self.config.stall_threshold_seconds * total_expected

            if round_duration > expected_duration and completion_rate < 0.5:
                return StallEvent(
                    debate_id=self.debate_id,
                    agent_id=None,
                    round_number=self._current_round,
                    reason=StallReason.NO_PROGRESS,
                    details={
                        "completion_rate": completion_rate,
                        "duration_seconds": round_duration,
                        "received": total_received,
                        "expected": total_expected,
                    },
                )

        return None

    def check_content_repetition(self, agent_id: str, new_content: str) -> tuple[bool, float]:
        """
        Check if content is repeated from previous submissions.

        Args:
            agent_id: Agent submitting the content
            new_content: Content to check

        Returns:
            Tuple of (is_repeated, similarity_score)
        """
        agent = self._agents.get(agent_id)
        if not agent or not agent.content_hashes:
            return False, 0.0

        new_hash = self._hash_content(new_content)

        # Exact match check via hash
        if new_hash in agent.content_hashes:
            return True, 1.0

        # For more sophisticated similarity, we'd use embeddings
        # This is a simplified version using hash prefix matching
        for old_hash in agent.content_hashes:
            # Check if hashes share prefix (very rough similarity proxy)
            common_prefix = 0
            for i in range(min(len(new_hash), len(old_hash))):
                if new_hash[i] == old_hash[i]:
                    common_prefix += 1
                else:
                    break
            similarity = common_prefix / len(new_hash)
            if similarity >= self.config.similarity_threshold:
                return True, similarity

        return False, 0.0

    async def start_monitoring(self) -> None:
        """Start continuous monitoring in the background."""
        if self._running:
            return

        self._running = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Witness monitoring started for debate %s", self.debate_id)

    async def stop_monitoring(self) -> None:
        """Stop continuous monitoring."""
        self._running = False
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            self._monitoring_task = None
        logger.info("Witness monitoring stopped for debate %s", self.debate_id)

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                stalls = self.detect_stalls()
                if stalls:
                    logger.warning(
                        "Witness detected %s stalls in debate %s", len(stalls), self.debate_id
                    )
                await asyncio.sleep(self.config.check_interval_seconds)
            except asyncio.CancelledError:
                break
            except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
                logger.error("Witness monitoring error: %s", e)
                await asyncio.sleep(1)

    def get_agent_progress(self, agent_id: str) -> AgentProgress | None:
        """Get progress for a specific agent."""
        return self._agents.get(agent_id)

    def get_round_progress(self, round_number: int) -> RoundProgress | None:
        """Get progress for a specific round."""
        return self._rounds.get(round_number)

    def get_progress_summary(self) -> dict[str, Any]:
        """
        Get a summary of debate progress.

        Returns:
            Summary dict with agent and round progress
        """
        return {
            "debate_id": self.debate_id,
            "current_round": self._current_round,
            "started_at": self._started_at.isoformat(),
            "duration_seconds": (datetime.now(timezone.utc) - self._started_at).total_seconds(),
            "total_messages": len(self._message_log),
            "total_stalls": len(self._stall_events),
            "unresolved_stalls": len([s for s in self._stall_events if not s.resolved]),
            "agents": {
                agent_id: {
                    "status": agent.status.value,
                    "proposals": agent.proposals_submitted,
                    "critiques": agent.critiques_submitted,
                    "revisions": agent.revisions_submitted,
                    "votes": agent.votes_cast,
                    "failures": agent.failure_count,
                    "last_activity": (
                        agent.last_activity.isoformat() if agent.last_activity else None
                    ),
                }
                for agent_id, agent in self._agents.items()
            },
            "rounds": {
                str(round_num): {
                    "phase": rp.phase,
                    "is_complete": rp.is_complete,
                    "proposals": f"{rp.proposals_received}/{rp.proposals_expected}",
                    "critiques": f"{rp.critiques_received}/{rp.critiques_expected}",
                    "revisions": f"{rp.revisions_received}/{rp.revisions_expected}",
                    "duration_seconds": rp.duration_seconds,
                }
                for round_num, rp in self._rounds.items()
            },
        }

    def get_stall_history(self, include_resolved: bool = True) -> list[dict[str, Any]]:
        """Get history of stall events."""
        events = self._stall_events
        if not include_resolved:
            events = [s for s in events if not s.resolved]

        return [
            {
                "debate_id": s.debate_id,
                "agent_id": s.agent_id,
                "round_number": s.round_number,
                "reason": s.reason.value,
                "timestamp": s.timestamp.isoformat(),
                "details": s.details,
                "resolved": s.resolved,
                "resolution": s.resolution,
            }
            for s in events
        ]

    def resolve_stall(self, agent_id: str | None, resolution: str) -> int:
        """
        Mark stalls as resolved.

        Args:
            agent_id: Agent whose stalls to resolve (None for round stalls)
            resolution: Description of how stall was resolved

        Returns:
            Number of stalls resolved
        """
        resolved_count = 0
        for stall in self._stall_events:
            if not stall.resolved and stall.agent_id == agent_id:
                stall.resolved = True
                stall.resolution = resolution
                resolved_count += 1

        # Also update agent status
        if agent_id and agent_id in self._agents:
            agent = self._agents[agent_id]
            if agent.status in (ProgressStatus.STALLED, ProgressStatus.FAILED):
                agent.status = ProgressStatus.HEALTHY
                agent.stall_reason = None
                agent.recovery_count += 1

        return resolved_count


# Global witness registry
_witnesses: dict[str, DebateWitness] = {}
_witnesses_lock = asyncio.Lock()


async def get_witness(debate_id: str, config: WitnessConfig | None = None) -> DebateWitness:
    """Get or create a witness for a debate."""
    async with _witnesses_lock:
        if debate_id not in _witnesses:
            _witnesses[debate_id] = DebateWitness(debate_id, config)
        return _witnesses[debate_id]


async def remove_witness(debate_id: str) -> bool:
    """Remove a witness when debate is complete."""
    async with _witnesses_lock:
        if debate_id in _witnesses:
            witness = _witnesses[debate_id]
            await witness.stop_monitoring()
            del _witnesses[debate_id]
            return True
        return False


def reset_witnesses() -> None:
    """Reset all witnesses (for testing)."""
    global _witnesses
    _witnesses = {}
