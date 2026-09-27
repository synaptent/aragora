"""
Debate Intervention Manager.

Provides real-time human intervention capabilities for live debates,
including pause/resume, nudges, challenges, and evidence injection.

Thread-safe state management ensures correct behavior under concurrent access.

Usage:
    from aragora.debate.intervention import InterventionManager

    manager = InterventionManager(debate_id="abc-123")
    manager.pause(user_id="admin-1")
    manager.nudge("Consider the economic implications", user_id="admin-1")
    manager.resume(user_id="admin-1")
    log = manager.get_log()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class InterventionType(Enum):
    """Types of interventions that can be applied to a debate."""

    PAUSE = "pause"
    RESUME = "resume"
    NUDGE = "nudge"
    CHALLENGE = "challenge"
    INJECT_EVIDENCE = "inject_evidence"


class DebateInterventionState(Enum):
    """Current state of a debate with respect to interventions."""

    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


@dataclass
class InterventionEntry:
    """A single intervention record."""

    intervention_type: InterventionType
    timestamp: float
    user_id: str | None = None
    message: str | None = None
    target_agent: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "type": self.intervention_type.value,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "message": self.message,
            "target_agent": self.target_agent,
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass
class InterventionLog:
    """Full log of all interventions for a debate."""

    debate_id: str
    entries: list[InterventionEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "debate_id": self.debate_id,
            "entry_count": len(self.entries),
            "entries": [e.to_dict() for e in self.entries],
        }


class InterventionManager:
    """Manages real-time human interventions for a live debate.

    Thread-safe: all public methods acquire the internal lock before mutating state.

    Args:
        debate_id: The debate this manager controls.
        emitter: Optional SyncEventEmitter for broadcasting WebSocket events.
    """

    def __init__(
        self,
        debate_id: str,
        emitter: Any | None = None,
    ) -> None:
        self._debate_id = debate_id
        self._state = DebateInterventionState.RUNNING
        self._log = InterventionLog(debate_id=debate_id)
        self._lock = threading.Lock()
        self._emitter = emitter

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def debate_id(self) -> str:
        """Return the debate ID managed by this instance."""
        return self._debate_id

    @property
    def state(self) -> DebateInterventionState:
        """Return the current intervention state."""
        with self._lock:
            return self._state

    @property
    def is_paused(self) -> bool:
        """Return True if the debate is currently paused."""
        with self._lock:
            return self._state == DebateInterventionState.PAUSED

    @property
    def is_running(self) -> bool:
        """Return True if the debate is currently running."""
        with self._lock:
            return self._state == DebateInterventionState.RUNNING

    @property
    def is_completed(self) -> bool:
        """Return True if the debate is completed."""
        with self._lock:
            return self._state == DebateInterventionState.COMPLETED

    # ------------------------------------------------------------------
    # Intervention Operations
    # ------------------------------------------------------------------

    def restore_paused(self) -> None:
        """Mark a freshly reconstructed manager as paused without logging.

        Used when a manager is recreated for a debate whose durable status
        is "paused" (the in-memory manager was lost, e.g. across a restart):
        a new manager starts RUNNING, which would make resume() fail. This
        restores the paused state silently — no intervention entry and no
        event, because no pause happened now. No-op unless currently RUNNING.
        """
        with self._lock:
            if self._state == DebateInterventionState.RUNNING:
                self._state = DebateInterventionState.PAUSED

    def pause(self, user_id: str | None = None) -> InterventionEntry:
        """Pause a running debate.

        Args:
            user_id: ID of the user initiating the pause.

        Returns:
            The recorded intervention entry.

        Raises:
            ValueError: If the debate is not in a running state.
        """
        with self._lock:
            if self._state != DebateInterventionState.RUNNING:
                raise ValueError(
                    f"Cannot pause debate {self._debate_id}: current state is {self._state.value}"
                )
            self._state = DebateInterventionState.PAUSED
            entry = self._record(InterventionType.PAUSE, user_id=user_id)
            self._emit_event("debate_paused", entry)
            logger.info("Debate %s paused by %s", self._debate_id, user_id or "unknown")
            return entry

    def resume(self, user_id: str | None = None) -> InterventionEntry:
        """Resume a paused debate.

        Args:
            user_id: ID of the user initiating the resume.

        Returns:
            The recorded intervention entry.

        Raises:
            ValueError: If the debate is not in a paused state.
        """
        with self._lock:
            if self._state != DebateInterventionState.PAUSED:
                raise ValueError(
                    f"Cannot resume debate {self._debate_id}: current state is {self._state.value}"
                )
            self._state = DebateInterventionState.RUNNING
            entry = self._record(InterventionType.RESUME, user_id=user_id)
            self._emit_event("debate_resumed", entry)
            logger.info("Debate %s resumed by %s", self._debate_id, user_id or "unknown")
            return entry

    def nudge(
        self,
        message: str,
        user_id: str | None = None,
        target_agent: str | None = None,
    ) -> InterventionEntry:
        """Send a nudge/hint to the debate.

        Args:
            message: The nudge message.
            user_id: ID of the user sending the nudge.
            target_agent: Optional specific agent to nudge.

        Returns:
            The recorded intervention entry.

        Raises:
            ValueError: If the debate is completed or message is empty.
        """
        if not message or not message.strip():
            raise ValueError("Nudge message cannot be empty")

        with self._lock:
            if self._state == DebateInterventionState.COMPLETED:
                raise ValueError(f"Cannot nudge completed debate {self._debate_id}")
            entry = self._record(
                InterventionType.NUDGE,
                user_id=user_id,
                message=message.strip(),
                target_agent=target_agent,
            )
            self._emit_event("debate_nudge", entry)
            logger.info(
                "Nudge sent to debate %s%s by %s",
                self._debate_id,
                f" (agent: {target_agent})" if target_agent else "",
                user_id or "unknown",
            )
            return entry

    def challenge(
        self,
        challenge_text: str,
        user_id: str | None = None,
    ) -> InterventionEntry:
        """Inject a challenge/counterargument into the debate.

        Args:
            challenge_text: The challenge to inject.
            user_id: ID of the user injecting the challenge.

        Returns:
            The recorded intervention entry.

        Raises:
            ValueError: If the debate is completed or challenge is empty.
        """
        if not challenge_text or not challenge_text.strip():
            raise ValueError("Challenge text cannot be empty")

        with self._lock:
            if self._state == DebateInterventionState.COMPLETED:
                raise ValueError(f"Cannot challenge completed debate {self._debate_id}")
            entry = self._record(
                InterventionType.CHALLENGE,
                user_id=user_id,
                message=challenge_text.strip(),
            )
            self._emit_event("debate_challenge", entry)
            logger.info(
                "Challenge injected into debate %s by %s",
                self._debate_id,
                user_id or "unknown",
            )
            return entry

    def inject_evidence(
        self,
        evidence: str,
        source: str | None = None,
        user_id: str | None = None,
    ) -> InterventionEntry:
        """Inject evidence into the debate.

        Args:
            evidence: The evidence text to inject.
            source: The source/citation for the evidence.
            user_id: ID of the user injecting the evidence.

        Returns:
            The recorded intervention entry.

        Raises:
            ValueError: If the debate is completed or evidence is empty.
        """
        if not evidence or not evidence.strip():
            raise ValueError("Evidence text cannot be empty")

        with self._lock:
            if self._state == DebateInterventionState.COMPLETED:
                raise ValueError(f"Cannot inject evidence into completed debate {self._debate_id}")
            entry = self._record(
                InterventionType.INJECT_EVIDENCE,
                user_id=user_id,
                message=evidence.strip(),
                source=source,
            )
            self._emit_event("debate_evidence_injected", entry)
            logger.info(
                "Evidence injected into debate %s by %s (source: %s)",
                self._debate_id,
                user_id or "unknown",
                source or "unspecified",
            )
            return entry

    def mark_completed(self) -> None:
        """Mark the debate as completed, preventing further interventions."""
        with self._lock:
            self._state = DebateInterventionState.COMPLETED
            logger.info("Debate %s marked as completed for interventions", self._debate_id)

    def get_log(self) -> InterventionLog:
        """Return the full intervention log.

        Returns:
            A copy of the InterventionLog with all entries.
        """
        with self._lock:
            return InterventionLog(
                debate_id=self._log.debate_id,
                entries=list(self._log.entries),
            )

    def get_state_dict(self) -> dict[str, Any]:
        """Return a dict summarising the current intervention state."""
        with self._lock:
            return {
                "debate_id": self._debate_id,
                "state": self._state.value,
                "intervention_count": len(self._log.entries),
            }

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _record(
        self,
        intervention_type: InterventionType,
        user_id: str | None = None,
        message: str | None = None,
        target_agent: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> InterventionEntry:
        """Record an intervention entry (caller must hold _lock)."""
        entry = InterventionEntry(
            intervention_type=intervention_type,
            timestamp=time.time(),
            user_id=user_id,
            message=message,
            target_agent=target_agent,
            source=source,
            metadata=metadata or {},
        )
        self._log.entries.append(entry)
        return entry

    def _emit_event(self, event_name: str, entry: InterventionEntry) -> None:
        """Emit a WebSocket event for the intervention (caller must hold _lock)."""
        if self._emitter is None:
            return

        try:
            from aragora.events.types import StreamEvent, StreamEventType

            self._emitter.emit(
                StreamEvent(
                    type=StreamEventType.BREAKPOINT,
                    data={
                        "event": event_name,
                        "debate_id": self._debate_id,
                        "intervention": entry.to_dict(),
                        "state": self._state.value,
                    },
                    loop_id=self._debate_id,
                )
            )
        except (ImportError, AttributeError, TypeError, RuntimeError) as exc:
            logger.debug("Failed to emit intervention event: %s", exc)


# ---------------------------------------------------------------------------
# Module-level registry for active intervention managers
# ---------------------------------------------------------------------------

_managers: dict[str, InterventionManager] = {}
_managers_lock = threading.Lock()


def get_intervention_manager(
    debate_id: str,
    emitter: Any | None = None,
    create: bool = True,
) -> InterventionManager | None:
    """Get or create the InterventionManager for a debate.

    Args:
        debate_id: The debate to look up.
        emitter: Optional emitter passed to a newly created manager.
        create: If True (default), create a new manager when one does not exist.

    Returns:
        The InterventionManager, or None if *create* is False and none exists.
    """
    with _managers_lock:
        manager = _managers.get(debate_id)
        if manager is not None:
            return manager
        if not create:
            return None
        manager = InterventionManager(debate_id=debate_id, emitter=emitter)
        _managers[debate_id] = manager
        return manager


def remove_intervention_manager(debate_id: str) -> InterventionManager | None:
    """Remove and return the InterventionManager for a debate.

    Args:
        debate_id: The debate whose manager should be removed.

    Returns:
        The removed manager, or None if not found.
    """
    with _managers_lock:
        return _managers.pop(debate_id, None)


def list_intervention_managers() -> dict[str, InterventionManager]:
    """Return a copy of all active intervention managers."""
    with _managers_lock:
        return dict(_managers)


def _reset_managers() -> None:
    """Reset the global manager registry (for testing)."""
    with _managers_lock:
        _managers.clear()


########################################################################
# Round-Boundary Intervention Queue
#
# Allows users to submit typed interventions (redirect, constraint,
# challenge, evidence request) that are queued and applied at the next
# round boundary.  This complements the existing pause/nudge system by
# providing structured, trackable interventions with effect measurement.
########################################################################


class QueuedInterventionType(str, Enum):
    """Structured intervention types applied at round boundaries."""

    REDIRECT_TOPIC = "redirect"
    ADD_CONSTRAINT = "constraint"
    CHALLENGE_CLAIM = "challenge"
    REQUEST_EVIDENCE = "evidence_request"


class QueuedInterventionStatus(str, Enum):
    """Lifecycle states for a queued intervention."""

    QUEUED = "queued"
    APPLIED = "applied"
    EXPIRED = "expired"
    REJECTED = "rejected"


@dataclass
class QueuedIntervention:
    """A structured intervention queued for round-boundary application.

    Attributes:
        intervention_id: Unique identifier
        debate_id: ID of the target debate
        intervention_type: Structured intervention type
        content: User-provided content/guidance
        status: Current lifecycle status
        created_at: Timestamp when queued
        apply_at_round: Target round (0 = next available)
        applied_at_round: Round at which it was actually applied
        user_id: Optional identifier for the submitting user
        effect_summary: Description of how the intervention affected outcomes
        metadata: Additional context
    """

    intervention_id: str
    debate_id: str
    intervention_type: QueuedInterventionType
    content: str
    status: QueuedInterventionStatus = QueuedInterventionStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    apply_at_round: int = 0
    applied_at_round: int | None = None
    user_id: str = ""
    effect_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "intervention_id": self.intervention_id,
            "debate_id": self.debate_id,
            "type": self.intervention_type.value,
            "content": self.content,
            "status": self.status.value,
            "created_at": self.created_at,
            "apply_at_round": self.apply_at_round,
            "applied_at_round": self.applied_at_round,
            "user_id": self.user_id,
            "effect_summary": self.effect_summary,
            "metadata": self.metadata,
        }


@dataclass
class InterventionEffect:
    """Tracks the measured effect of an intervention on debate outcomes.

    Attributes:
        intervention_id: ID of the intervention
        pre_confidence: Debate confidence before intervention
        post_confidence: Debate confidence after intervention
        agents_affected: Names of agents whose output changed
        topic_shift_detected: Whether the topic shifted as a result
        description: Human-readable summary of the effect
    """

    intervention_id: str
    pre_confidence: float = 0.0
    post_confidence: float = 0.0
    agents_affected: list[str] = field(default_factory=list)
    topic_shift_detected: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "intervention_id": self.intervention_id,
            "pre_confidence": self.pre_confidence,
            "post_confidence": self.post_confidence,
            "agents_affected": self.agents_affected,
            "topic_shift_detected": self.topic_shift_detected,
            "description": self.description,
        }


class InterventionQueue:
    """Manages queued interventions for round-boundary application.

    Thread-safe queue that supports:
    - Queuing typed interventions for active debates
    - Retrieving pending interventions at round boundaries
    - Marking interventions as applied with effect tracking
    - Expiring stale interventions
    - Building prompt injections from interventions

    Integrates with the existing InterventionManager for per-debate state.
    """

    # Maximum queued interventions per debate to prevent abuse
    MAX_INTERVENTIONS_PER_DEBATE = 20
    # Default expiry: interventions expire after 5 minutes if not applied
    DEFAULT_EXPIRY_SECONDS = 300.0

    def __init__(self) -> None:
        """Initialize the intervention queue."""
        self._interventions: dict[str, QueuedIntervention] = {}
        # debate_id -> list of intervention_ids
        self._debate_interventions: dict[str, list[str]] = {}
        self._effects: dict[str, InterventionEffect] = {}
        self._lock = threading.Lock()

    def queue_intervention(
        self,
        debate_id: str,
        intervention_type: str | QueuedInterventionType,
        content: str,
        user_id: str = "",
        apply_at_round: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> QueuedIntervention:
        """Queue a new intervention for an active debate.

        Args:
            debate_id: ID of the target debate
            intervention_type: Type of intervention
            content: User-provided content/guidance
            user_id: Optional user identifier
            apply_at_round: Target round (0 = next available)
            metadata: Additional context

        Returns:
            The queued QueuedIntervention object

        Raises:
            ValueError: If intervention type is invalid or queue is full
        """
        import uuid as _uuid

        # Normalize intervention type
        if isinstance(intervention_type, str):
            try:
                iv_type = QueuedInterventionType(intervention_type)
            except ValueError:
                valid = [t.value for t in QueuedInterventionType]
                raise ValueError(
                    f"Invalid intervention type: {intervention_type}. Must be one of: {valid}"
                )
        else:
            iv_type = intervention_type

        if not content or not content.strip():
            raise ValueError("Intervention content must not be empty")

        intervention_id = str(_uuid.uuid4())

        intervention = QueuedIntervention(
            intervention_id=intervention_id,
            debate_id=debate_id,
            intervention_type=iv_type,
            content=content.strip(),
            user_id=user_id,
            apply_at_round=apply_at_round,
            metadata=metadata or {},
        )

        with self._lock:
            # Check per-debate limit
            debate_ivs = self._debate_interventions.get(debate_id, [])
            active_count = sum(
                1
                for iv_id in debate_ivs
                if iv_id in self._interventions
                and self._interventions[iv_id].status == QueuedInterventionStatus.QUEUED
            )
            if active_count >= self.MAX_INTERVENTIONS_PER_DEBATE:
                raise ValueError(
                    f"Maximum interventions ({self.MAX_INTERVENTIONS_PER_DEBATE}) "
                    f"reached for debate {debate_id}"
                )

            self._interventions[intervention_id] = intervention
            if debate_id not in self._debate_interventions:
                self._debate_interventions[debate_id] = []
            self._debate_interventions[debate_id].append(intervention_id)

        logger.info(
            "queued_intervention id=%s debate=%s type=%s round=%s",
            intervention_id,
            debate_id,
            iv_type.value,
            apply_at_round,
        )

        return intervention

    def get_pending_interventions(
        self,
        debate_id: str,
        current_round: int = 0,
    ) -> list[QueuedIntervention]:
        """Get all pending interventions for a debate ready to be applied.

        Filters out expired interventions and returns only those targeted
        at the current round or earlier (round=0 means "next available").

        Args:
            debate_id: ID of the debate
            current_round: Current round number for filtering

        Returns:
            List of QueuedIntervention objects ready to apply
        """
        now = time.time()
        pending: list[QueuedIntervention] = []

        with self._lock:
            iv_ids = self._debate_interventions.get(debate_id, [])
            for iv_id in iv_ids:
                iv = self._interventions.get(iv_id)
                if iv is None:
                    continue
                if iv.status != QueuedInterventionStatus.QUEUED:
                    continue
                # Check expiry
                if now - iv.created_at > self.DEFAULT_EXPIRY_SECONDS:
                    iv.status = QueuedInterventionStatus.EXPIRED
                    logger.info("queued_intervention_expired id=%s debate=%s", iv_id, debate_id)
                    continue
                # Check round targeting
                if iv.apply_at_round == 0 or iv.apply_at_round <= current_round:
                    pending.append(iv)

        return pending

    def mark_applied(
        self,
        intervention_id: str,
        round_num: int,
        effect_summary: str = "",
    ) -> bool:
        """Mark an intervention as applied.

        Args:
            intervention_id: ID of the intervention
            round_num: Round at which it was applied
            effect_summary: Description of the effect

        Returns:
            True if marked successfully, False if not found or already applied
        """
        with self._lock:
            iv = self._interventions.get(intervention_id)
            if iv is None or iv.status != QueuedInterventionStatus.QUEUED:
                return False
            iv.status = QueuedInterventionStatus.APPLIED
            iv.applied_at_round = round_num
            iv.effect_summary = effect_summary

        logger.info(
            "queued_intervention_applied id=%s debate=%s round=%s",
            intervention_id,
            iv.debate_id,
            round_num,
        )
        return True

    def record_effect(
        self,
        intervention_id: str,
        pre_confidence: float = 0.0,
        post_confidence: float = 0.0,
        agents_affected: list[str] | None = None,
        topic_shift_detected: bool = False,
        description: str = "",
    ) -> InterventionEffect:
        """Record the measured effect of an intervention.

        Args:
            intervention_id: ID of the intervention
            pre_confidence: Debate confidence before intervention
            post_confidence: Debate confidence after intervention
            agents_affected: Names of agents whose output changed
            topic_shift_detected: Whether the topic shifted
            description: Human-readable summary

        Returns:
            The recorded InterventionEffect
        """
        effect = InterventionEffect(
            intervention_id=intervention_id,
            pre_confidence=pre_confidence,
            post_confidence=post_confidence,
            agents_affected=agents_affected or [],
            topic_shift_detected=topic_shift_detected,
            description=description,
        )
        with self._lock:
            self._effects[intervention_id] = effect
        return effect

    def get_intervention(self, intervention_id: str) -> QueuedIntervention | None:
        """Get a specific queued intervention by ID."""
        with self._lock:
            return self._interventions.get(intervention_id)

    def get_debate_interventions(self, debate_id: str) -> list[QueuedIntervention]:
        """Get all queued interventions for a debate (all statuses)."""
        with self._lock:
            iv_ids = self._debate_interventions.get(debate_id, [])
            return [self._interventions[iv_id] for iv_id in iv_ids if iv_id in self._interventions]

    def get_effect(self, intervention_id: str) -> InterventionEffect | None:
        """Get the recorded effect for an intervention."""
        with self._lock:
            return self._effects.get(intervention_id)

    def build_intervention_prompt(self, intervention: QueuedIntervention) -> str:
        """Build a prompt injection string from a queued intervention.

        Transforms the intervention into a format that can be prepended
        to agent prompts at round boundaries.

        Args:
            intervention: The intervention to convert

        Returns:
            Formatted prompt string for injection
        """
        type_labels = {
            QueuedInterventionType.REDIRECT_TOPIC: "TOPIC REDIRECT",
            QueuedInterventionType.ADD_CONSTRAINT: "NEW CONSTRAINT",
            QueuedInterventionType.CHALLENGE_CLAIM: "CLAIM CHALLENGE",
            QueuedInterventionType.REQUEST_EVIDENCE: "EVIDENCE REQUEST",
        }
        label = type_labels.get(intervention.intervention_type, "USER INPUT")
        return (
            f"\n[{label} from debate participant]: {intervention.content}\n"
            f"Please address this {label.lower()} in your next response.\n"
        )

    def get_reasoning_summary(self, debate_id: str) -> dict[str, Any]:
        """Build a reasoning summary for all queued interventions in a debate.

        Args:
            debate_id: ID of the debate

        Returns:
            Dict with intervention summaries and their effects
        """
        interventions = self.get_debate_interventions(debate_id)
        summaries = []
        for iv in interventions:
            summary: dict[str, Any] = iv.to_dict()
            effect = self.get_effect(iv.intervention_id)
            if effect:
                summary["effect"] = effect.to_dict()
            summaries.append(summary)
        return {
            "debate_id": debate_id,
            "total_interventions": len(summaries),
            "applied": sum(1 for s in summaries if s["status"] == "applied"),
            "queued": sum(1 for s in summaries if s["status"] == "queued"),
            "interventions": summaries,
        }

    def cleanup_debate(self, debate_id: str) -> int:
        """Clean up all queued interventions for a completed debate.

        Args:
            debate_id: ID of the debate to clean up

        Returns:
            Number of interventions cleaned up
        """
        with self._lock:
            iv_ids = self._debate_interventions.pop(debate_id, [])
            count = 0
            for iv_id in iv_ids:
                self._interventions.pop(iv_id, None)
                self._effects.pop(iv_id, None)
                count += 1
        if count:
            logger.info("queued_intervention_cleanup debate=%s count=%s", debate_id, count)
        return count


# ---------------------------------------------------------------------------
# Module-level singleton for the intervention queue
# ---------------------------------------------------------------------------

_global_queue: InterventionQueue | None = None
_global_queue_lock = threading.Lock()


def get_intervention_queue() -> InterventionQueue:
    """Get or create the global InterventionQueue singleton.

    Returns:
        The global InterventionQueue instance
    """
    global _global_queue
    if _global_queue is None:
        with _global_queue_lock:
            if _global_queue is None:
                _global_queue = InterventionQueue()
    return _global_queue


__all__ = [
    "InterventionType",
    "DebateInterventionState",
    "InterventionEntry",
    "InterventionLog",
    "InterventionManager",
    "get_intervention_manager",
    "remove_intervention_manager",
    "list_intervention_managers",
    # Round-boundary queued interventions
    "QueuedInterventionType",
    "QueuedInterventionStatus",
    "QueuedIntervention",
    "InterventionEffect",
    "InterventionQueue",
    "get_intervention_queue",
]
