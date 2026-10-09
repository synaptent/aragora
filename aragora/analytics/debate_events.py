"""Records completed debates in the debate analytics store.

Subscribes to :mod:`aragora.events.debate_completion`, which the debate runner emits
once per finished debate. ``aragora.analytics`` subscribes from its own init, and the
``aragora.debate_completed_subscribers`` entry point in ``pyproject.toml`` reaches
:func:`subscribe_debate_analytics` in processes that never import this package.
"""

from __future__ import annotations

from aragora.analytics import debate_analytics
from aragora.events.debate_completion import DebateCompletedEvent, subscribe_debate_completed

SUBSCRIBER_NAME = "aragora.analytics.debate_analytics"


async def record_completed_debate(event: DebateCompletedEvent) -> None:
    """Write the debate and each agent's activity to the debate analytics store."""
    analytics = debate_analytics.get_debate_analytics()
    await analytics.record_debate(
        debate_id=event.debate_id,
        rounds=event.rounds,
        consensus_reached=event.consensus_reached,
        duration_seconds=event.duration_seconds,
        agents=list(event.agents),
        status=event.status,
        org_id=event.org_id,
        user_id=event.user_id,
        protocol=event.protocol,
        total_messages=event.total_messages,
        total_votes=event.total_votes,
        total_cost=event.total_cost,
    )
    for activity in event.agent_activity:
        await analytics.record_agent_activity(
            agent_id=activity.agent_id,
            debate_id=event.debate_id,
            response_time_ms=activity.response_time_ms,
            tokens_in=activity.tokens_in,
            tokens_out=activity.tokens_out,
            cost=activity.cost,
            error=False,
            agent_name=activity.agent_id,
            provider=activity.provider,
            model=activity.model,
        )


def subscribe_debate_analytics() -> None:
    """Subscribe the analytics recorder to debate completions; safe to call more than once."""
    subscribe_debate_completed(SUBSCRIBER_NAME, record_completed_debate)


__all__ = ["SUBSCRIBER_NAME", "record_completed_debate", "subscribe_debate_analytics"]
