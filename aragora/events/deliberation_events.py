"""
Deliberation event types for Control Plane streaming.

Defines event types emitted during deliberation execution for real-time
monitoring via ControlPlaneStreamServer.
"""

from __future__ import annotations

from enum import Enum, unique
from types import MappingProxyType


_CATEGORY_LIFECYCLE = "lifecycle"
_CATEGORY_ROUND = "round"
_CATEGORY_AGENT = "agent"
_CATEGORY_CONSENSUS = "consensus"
_CATEGORY_SLA = "sla"
_CATEGORY_PROGRESS = "progress"
_CATEGORY_ERROR = "error"

CATEGORIES: tuple[str, ...] = (
    _CATEGORY_LIFECYCLE,
    _CATEGORY_ROUND,
    _CATEGORY_AGENT,
    _CATEGORY_CONSENSUS,
    _CATEGORY_SLA,
    _CATEGORY_PROGRESS,
    _CATEGORY_ERROR,
)


@unique
class DeliberationEventType(str, Enum):
    """Event types for deliberation lifecycle and progress."""

    # Lifecycle events
    DELIBERATION_STARTED = "deliberation.started"
    DELIBERATION_COMPLETED = "deliberation.completed"
    DELIBERATION_FAILED = "deliberation.failed"
    DELIBERATION_CANCELLED = "deliberation.cancelled"

    # Round events
    ROUND_START = "deliberation.round_start"
    ROUND_END = "deliberation.round_end"

    # Agent interaction events
    AGENT_MESSAGE = "deliberation.agent_message"
    AGENT_PROPOSAL = "deliberation.agent_proposal"
    AGENT_CRITIQUE = "deliberation.agent_critique"
    AGENT_REVISION = "deliberation.agent_revision"

    # Voting and consensus events
    VOTE = "deliberation.vote"
    CONSENSUS_CHECK = "deliberation.consensus_check"
    CONSENSUS_REACHED = "deliberation.consensus_reached"
    NO_CONSENSUS = "deliberation.no_consensus"

    # SLA events
    SLA_WARNING = "deliberation.sla_warning"
    SLA_CRITICAL = "deliberation.sla_critical"
    SLA_VIOLATED = "deliberation.sla_violated"

    # Progress events
    PROGRESS_UPDATE = "deliberation.progress"
    CONVERGENCE_UPDATE = "deliberation.convergence"

    # Error events
    AGENT_ERROR = "deliberation.agent_error"
    RECOVERY_ATTEMPTED = "deliberation.recovery_attempted"

    @property
    def category(self) -> str:
        """Return the category this event belongs to."""
        return _EVENT_CATEGORIES[self]

    @property
    def is_terminal(self) -> bool:
        """True if this event signals the end of a deliberation."""
        return self in TERMINAL_EVENT_TYPES

    @classmethod
    def by_category(cls, category: str) -> frozenset["DeliberationEventType"]:
        """Return all events belonging to *category*.

        Raises ``ValueError`` for unknown categories.
        """
        if category not in CATEGORIES:
            raise ValueError(f"Unknown category {category!r}; choose from {CATEGORIES}")
        return EVENT_TYPES_BY_CATEGORY[category]


_EVENT_CATEGORIES: dict[DeliberationEventType, str] = {
    DeliberationEventType.DELIBERATION_STARTED: _CATEGORY_LIFECYCLE,
    DeliberationEventType.DELIBERATION_COMPLETED: _CATEGORY_LIFECYCLE,
    DeliberationEventType.DELIBERATION_FAILED: _CATEGORY_LIFECYCLE,
    DeliberationEventType.DELIBERATION_CANCELLED: _CATEGORY_LIFECYCLE,
    DeliberationEventType.ROUND_START: _CATEGORY_ROUND,
    DeliberationEventType.ROUND_END: _CATEGORY_ROUND,
    DeliberationEventType.AGENT_MESSAGE: _CATEGORY_AGENT,
    DeliberationEventType.AGENT_PROPOSAL: _CATEGORY_AGENT,
    DeliberationEventType.AGENT_CRITIQUE: _CATEGORY_AGENT,
    DeliberationEventType.AGENT_REVISION: _CATEGORY_AGENT,
    DeliberationEventType.VOTE: _CATEGORY_CONSENSUS,
    DeliberationEventType.CONSENSUS_CHECK: _CATEGORY_CONSENSUS,
    DeliberationEventType.CONSENSUS_REACHED: _CATEGORY_CONSENSUS,
    DeliberationEventType.NO_CONSENSUS: _CATEGORY_CONSENSUS,
    DeliberationEventType.SLA_WARNING: _CATEGORY_SLA,
    DeliberationEventType.SLA_CRITICAL: _CATEGORY_SLA,
    DeliberationEventType.SLA_VIOLATED: _CATEGORY_SLA,
    DeliberationEventType.PROGRESS_UPDATE: _CATEGORY_PROGRESS,
    DeliberationEventType.CONVERGENCE_UPDATE: _CATEGORY_PROGRESS,
    DeliberationEventType.AGENT_ERROR: _CATEGORY_ERROR,
    DeliberationEventType.RECOVERY_ATTEMPTED: _CATEGORY_ERROR,
}

EVENT_TYPES_BY_CATEGORY = MappingProxyType(
    {
        category: frozenset(
            event
            for event, mapped_category in _EVENT_CATEGORIES.items()
            if mapped_category == category
        )
        for category in CATEGORIES
    }
)

TERMINAL_EVENT_TYPES: frozenset[DeliberationEventType] = frozenset(
    {
        DeliberationEventType.DELIBERATION_COMPLETED,
        DeliberationEventType.DELIBERATION_FAILED,
        DeliberationEventType.DELIBERATION_CANCELLED,
    }
)


__all__ = [
    "CATEGORIES",
    "DeliberationEventType",
    "EVENT_TYPES_BY_CATEGORY",
    "TERMINAL_EVENT_TYPES",
]
