"""
Usage Metering Integration with Aragora Debate System.

Provides integration hooks between the debate orchestration system
and the usage metering service for ENTERPRISE tier billing.

Usage:
    from aragora.billing.usage_metering_integration import (
        record_debate_tokens,
        record_agent_tokens,
        get_metered_usage_tracker,
    )

    # Record debate completion
    await record_debate_tokens(
        org_id="org_123",
        debate_id="debate_456",
        agents=agents,
        user_id="user_789",
    )

    # Get a usage tracker wrapper that meters to both systems
    tracker = get_metered_usage_tracker(org_id="org_123")
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from aragora.core import Agent

logger = logging.getLogger(__name__)


async def record_debate_tokens(
    org_id: str,
    debate_id: str,
    agents: list[Agent],
    user_id: str | None = None,
    rounds: int = 0,
    duration_seconds: int = 0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Record token usage from debate completion to usage metering.

    This function should be called after a debate completes to record
    token usage for billing. It extracts token counts from each agent
    and records both individual agent usage and aggregate debate usage.

    Args:
        org_id: Organization identifier
        debate_id: Debate identifier
        agents: List of agents that participated
        user_id: Optional user identifier
        rounds: Number of debate rounds
        duration_seconds: Debate duration
        metadata: Additional metadata

    Returns:
        Dict with recorded usage summary:
        {
            "total_tokens": 12500,
            "total_cost": "0.0325",
            "agents_recorded": 3,
            "debate_recorded": True
        }
    """
    from aragora.services.usage_metering import get_usage_meter

    meter = get_usage_meter()

    total_input = 0
    total_output = 0
    total_cost = Decimal("0")
    agents_recorded = 0

    # Record per-agent token usage
    for agent in agents:
        agent_input = 0
        agent_output = 0

        # Try to get token usage from different agent types
        metrics = getattr(agent, "metrics", None)
        if metrics:
            agent_input = getattr(metrics, "total_input_tokens", 0)
            agent_output = getattr(metrics, "total_output_tokens", 0)
        else:
            # Try API agent style (total_tokens_in/out)
            agent_input = getattr(agent, "total_tokens_in", 0)
            agent_output = getattr(agent, "total_tokens_out", 0)

        if agent_input > 0 or agent_output > 0:
            # Get provider and model info
            provider = getattr(agent, "provider", None) or getattr(agent, "agent_type", "unknown")
            model = getattr(agent, "model", "unknown")
            agent_name = getattr(agent, "name", str(agent))

            try:
                record = await meter.record_token_usage(
                    org_id=org_id,
                    input_tokens=agent_input,
                    output_tokens=agent_output,
                    model=model,
                    provider=cast(str, provider),
                    user_id=user_id,
                    debate_id=debate_id,
                    metadata={
                        "agent_name": agent_name,
                        "rounds": rounds,
                        **(metadata or {}),
                    },
                )
                total_cost += record.total_cost
                agents_recorded += 1
            except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
                logger.warning("Failed to record agent token usage: %s", e)

            total_input += agent_input
            total_output += agent_output

    # Record debate summary
    debate_recorded = False
    if total_input > 0 or total_output > 0:
        try:
            await meter.record_debate_usage(
                org_id=org_id,
                debate_id=debate_id,
                agent_count=len(agents),
                rounds=rounds,
                total_tokens=total_input + total_output,
                total_cost=total_cost,
                duration_seconds=duration_seconds,
                user_id=user_id,
                metadata=metadata,
            )
            debate_recorded = True
        except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("Failed to record debate usage: %s", e)

    logger.info(
        f"Debate tokens recorded: org={org_id} debate={debate_id} "
        f"tokens={total_input + total_output} cost=${total_cost:.4f}"
    )

    return {
        "total_tokens": total_input + total_output,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_cost": str(total_cost),
        "agents_recorded": agents_recorded,
        "debate_recorded": debate_recorded,
    }


async def record_agent_tokens(
    org_id: str,
    agent_name: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    user_id: str | None = None,
    debate_id: str | None = None,
    endpoint: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Record token usage from a single agent API call.

    This function can be called from agent implementations to record
    token usage in real-time as API calls are made.

    Args:
        org_id: Organization identifier
        agent_name: Name of the agent
        provider: Provider name (anthropic, openai, etc.)
        model: Model name
        input_tokens: Input token count
        output_tokens: Output token count
        user_id: Optional user identifier
        debate_id: Optional debate identifier
        endpoint: Optional API endpoint
        metadata: Additional metadata

    Returns:
        Dict with recorded usage:
        {
            "record_id": "...",
            "total_cost": "0.0125"
        }
    """
    from aragora.services.usage_metering import get_usage_meter

    meter = get_usage_meter()

    try:
        record = await meter.record_token_usage(
            org_id=org_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            provider=provider,
            user_id=user_id,
            debate_id=debate_id,
            endpoint=endpoint,
            metadata={
                "agent_name": agent_name,
                **(metadata or {}),
            },
        )
        return {
            "record_id": record.id,
            "total_cost": str(record.total_cost),
            "input_cost": str(record.input_cost),
            "output_cost": str(record.output_cost),
        }
    except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
        logger.warning("Failed to record agent tokens: %s", e)
        return {
            "record_id": None,
            "total_cost": "0",
            "error": "Failed to record agent token usage",
        }


async def record_api_call(
    org_id: str,
    endpoint: str,
    method: str = "GET",
    status_code: int = 200,
    response_time_ms: int = 0,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Record an API call for metering.

    This function should be called from API handlers to record
    API call volume for usage-based billing.

    Args:
        org_id: Organization identifier
        endpoint: API endpoint called
        method: HTTP method
        status_code: Response status code
        response_time_ms: Response time in milliseconds
        user_id: Optional user identifier
        metadata: Additional metadata

    Returns:
        Dict with recorded call info
    """
    from aragora.services.usage_metering import get_usage_meter

    meter = get_usage_meter()

    try:
        record = await meter.record_api_call(
            org_id=org_id,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            response_time_ms=response_time_ms,
            user_id=user_id,
            metadata=metadata,
        )
        return {
            "record_id": record.id,
            "endpoint": endpoint,
        }
    except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
        logger.warning("Failed to record API call: %s", e)
        return {
            "record_id": None,
            "error": "Failed to record API call",
        }


class MeteredUsageTracker:
    """
    Usage tracker wrapper that records to both the legacy UsageTracker
    and the new usage metering service.

    This provides a migration path from the existing UsageTracker to
    the new metering system without breaking existing code.
    """

    def __init__(
        self,
        org_id: str,
        user_id: str | None = None,
        legacy_tracker: Any = None,
    ):
        """
        Initialize metered usage tracker.

        Args:
            org_id: Organization identifier
            user_id: Optional user identifier
            legacy_tracker: Optional legacy UsageTracker instance
        """
        self.org_id = org_id
        self.user_id = user_id
        self._legacy_tracker = legacy_tracker
        self._meter = None

    def _get_meter(self):
        """Lazy-load the usage meter."""
        if self._meter is None:
            from aragora.services.usage_metering import get_usage_meter

            self._meter = get_usage_meter()
        return self._meter

    def record_debate(
        self,
        user_id: str,
        org_id: str,
        debate_id: str,
        tokens_in: int,
        tokens_out: int,
        provider: str,
        model: str,
        metadata: dict | None = None,
    ) -> Any:
        """Record debate usage to both systems."""
        # Record to legacy tracker if available
        if self._legacy_tracker:
            try:
                self._legacy_tracker.record_debate(
                    user_id=user_id,
                    org_id=org_id,
                    debate_id=debate_id,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    provider=provider,
                    model=model,
                    metadata=metadata,
                )
            except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
                logger.warning("Legacy tracker failed: %s", e)

        # Record to new metering system (async wrapper)
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                asyncio.create_task(
                    self._record_debate_async(
                        user_id=user_id,
                        org_id=org_id,
                        debate_id=debate_id,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        provider=provider,
                        model=model,
                        metadata=metadata,
                    )
                )
            else:
                loop.run_until_complete(
                    self._record_debate_async(
                        user_id=user_id,
                        org_id=org_id,
                        debate_id=debate_id,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        provider=provider,
                        model=model,
                        metadata=metadata,
                    )
                )
        except RuntimeError:
            # No event loop, run in new loop
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    self._record_debate_async(
                        user_id=user_id,
                        org_id=org_id,
                        debate_id=debate_id,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        provider=provider,
                        model=model,
                        metadata=metadata,
                    )
                )
            finally:
                loop.close()

    async def _record_debate_async(
        self,
        user_id: str,
        org_id: str,
        debate_id: str,
        tokens_in: int,
        tokens_out: int,
        provider: str,
        model: str,
        metadata: dict | None = None,
    ) -> None:
        """Async debate recording."""
        meter = self._get_meter()

        # Record token usage
        await meter.record_token_usage(
            org_id=org_id,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            model=model,
            provider=provider,
            user_id=user_id,
            debate_id=debate_id,
            metadata=metadata,
        )

        # Record debate
        await meter.record_debate_usage(
            org_id=org_id,
            debate_id=debate_id,
            agent_count=1,  # Will be updated by actual debate recording
            total_tokens=tokens_in + tokens_out,
            user_id=user_id,
            metadata=metadata,
        )

    def record_agent_call(
        self,
        user_id: str,
        org_id: str,
        debate_id: str | None,
        agent_name: str,
        tokens_in: int,
        tokens_out: int,
        provider: str,
        model: str,
    ) -> Any:
        """Record agent call to both systems."""
        # Record to legacy tracker if available
        if self._legacy_tracker:
            try:
                self._legacy_tracker.record_agent_call(
                    user_id=user_id,
                    org_id=org_id,
                    debate_id=debate_id,
                    agent_name=agent_name,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    provider=provider,
                    model=model,
                )
            except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
                logger.warning("Legacy tracker failed: %s", e)

        # Record to new metering system
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                asyncio.create_task(
                    record_agent_tokens(
                        org_id=org_id,
                        agent_name=agent_name,
                        provider=provider,
                        model=model,
                        input_tokens=tokens_in,
                        output_tokens=tokens_out,
                        user_id=user_id,
                        debate_id=debate_id,
                    )
                )
            else:
                loop.run_until_complete(
                    record_agent_tokens(
                        org_id=org_id,
                        agent_name=agent_name,
                        provider=provider,
                        model=model,
                        input_tokens=tokens_in,
                        output_tokens=tokens_out,
                        user_id=user_id,
                        debate_id=debate_id,
                    )
                )
        except RuntimeError:
            # No event loop
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    record_agent_tokens(
                        org_id=org_id,
                        agent_name=agent_name,
                        provider=provider,
                        model=model,
                        input_tokens=tokens_in,
                        output_tokens=tokens_out,
                        user_id=user_id,
                        debate_id=debate_id,
                    )
                )
            finally:
                loop.close()

    def get_summary(
        self,
        org_id: str,
        period_start: Any | None = None,
    ) -> Any:
        """Get usage summary (delegates to legacy tracker)."""
        if self._legacy_tracker:
            return self._legacy_tracker.get_summary(
                org_id=org_id,
                period_start=period_start,
            )
        return None


def get_metered_usage_tracker(
    org_id: str,
    user_id: str | None = None,
    legacy_tracker: Any = None,
) -> MeteredUsageTracker:
    """
    Get a metered usage tracker for an organization.

    This returns a wrapper that records to both the legacy UsageTracker
    and the new usage metering service.

    Args:
        org_id: Organization identifier
        user_id: Optional user identifier
        legacy_tracker: Optional existing UsageTracker instance

    Returns:
        MeteredUsageTracker instance
    """
    return MeteredUsageTracker(
        org_id=org_id,
        user_id=user_id,
        legacy_tracker=legacy_tracker,
    )


__all__ = [
    "record_debate_tokens",
    "record_agent_tokens",
    "record_api_call",
    "MeteredUsageTracker",
    "get_metered_usage_tracker",
]
