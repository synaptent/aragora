"""Debate-completed event for packages that react to finished debates.

The debate engine sits below ``aragora.analytics`` and must not import it. The debate
runner emits one :class:`DebateCompletedEvent` per finished debate through
:func:`emit_debate_completed`; upper packages subscribe from their own init.

A process that never imported a subscribing package still reaches it: the first emit
runs, once per process, the subscriptions declared under the
``aragora.debate_completed_subscribers`` entry-point group (aragora's own
``pyproject.toml`` declares the analytics subscription there). Subscriptions are keyed
by name, so subscribing again under the same name replaces the handler instead of
adding a second one. :func:`emit_debate_completed` raises
:class:`DebateCompletedNotSubscribedError` when nothing is subscribed after that.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

from aragora.utils.declared_registrations import DeclaredRegistrations

logger = logging.getLogger(__name__)

DEBATE_COMPLETED = "debate_completed"
DEBATE_COMPLETED_ENTRY_POINT_GROUP = "aragora.debate_completed_subscribers"

# Same non-critical set the debate runner swallowed around its analytics writes.
_SUBSCRIBER_ERRORS = (ImportError, RuntimeError, ValueError, TypeError, AttributeError, OSError)


@dataclass(frozen=True)
class AgentActivity:
    """One agent's usage in a completed debate."""

    agent_id: str
    response_time_ms: float
    tokens_in: int
    tokens_out: int
    cost: Decimal
    provider: str
    model: str


@dataclass(frozen=True)
class DebateCompletedEvent:
    """A finished debate, with the totals the debate runner measured."""

    event_type: ClassVar[str] = DEBATE_COMPLETED

    debate_id: str
    task: str
    rounds: int
    consensus_reached: bool
    duration_seconds: float
    agents: tuple[str, ...]
    status: str
    org_id: str | None = None
    user_id: str | None = None
    protocol: str | None = None
    total_messages: int = 0
    total_votes: int = 0
    total_cost: Decimal = Decimal("0")
    agent_activity: tuple[AgentActivity, ...] = ()


DebateCompletedSubscriber = Callable[[DebateCompletedEvent], Awaitable[None]]


class DebateCompletedNotSubscribedError(RuntimeError):
    """No debate-completed subscriber is registered."""


_subscribers: dict[str, DebateCompletedSubscriber] = {}
_declared = DeclaredRegistrations(DEBATE_COMPLETED_ENTRY_POINT_GROUP)


def subscribe_debate_completed(name: str, subscriber: DebateCompletedSubscriber) -> None:
    """Subscribe ``subscriber`` under ``name``; a later subscription under ``name`` replaces it."""
    _subscribers[name] = subscriber


def unsubscribe_debate_completed(name: str) -> bool:
    """Remove the subscriber registered under ``name``; return whether one was registered."""
    return _subscribers.pop(name, None) is not None


def registered_count() -> int:
    """Return how many debate-completed subscribers are registered."""
    return len(_subscribers)


async def emit_debate_completed(event: DebateCompletedEvent) -> int:
    """Deliver ``event`` to every subscriber and return how many handled it.

    A subscriber that fails with a non-critical error is logged and skipped, so one
    subscriber cannot stop the others or the debate.

    Raises:
        DebateCompletedNotSubscribedError: nothing is subscribed, even after the
            declared subscriptions ran.
    """
    _declared.load()
    if not _subscribers:
        raise DebateCompletedNotSubscribedError(
            "no debate_completed subscriber is registered; import aragora.analytics, or declare "
            f"one under the {DEBATE_COMPLETED_ENTRY_POINT_GROUP!r} entry-point group"
        )
    delivered = 0
    for name, subscriber in list(_subscribers.items()):
        try:
            await subscriber(event)
        except _SUBSCRIBER_ERRORS as exc:
            logger.debug("debate_completed subscriber %s failed (non-critical): %s", name, exc)
            continue
        delivered += 1
    return delivered


__all__ = [
    "AgentActivity",
    "DEBATE_COMPLETED",
    "DEBATE_COMPLETED_ENTRY_POINT_GROUP",
    "DebateCompletedEvent",
    "DebateCompletedNotSubscribedError",
    "DebateCompletedSubscriber",
    "emit_debate_completed",
    "registered_count",
    "subscribe_debate_completed",
    "unsubscribe_debate_completed",
]
