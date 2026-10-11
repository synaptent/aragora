"""
Budget Manager - Cost tracking and enforcement.

Tracks resource usage and enforces budget limits per agent, user, and tenant.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import (
    BudgetConfig,
    BudgetStatus,
    Usage,
    UsageReport,
)

logger = logging.getLogger(__name__)


class BudgetManager:
    """
    Tracks and enforces budget limits for agents.

    Features:
    - Token, compute, and cost tracking
    - Per-agent, per-user, per-tenant limits
    - Soft and hard limit enforcement
    - Usage alerts and notifications
    - Usage reports and projections
    """

    def __init__(
        self,
        alert_callback: Any | None = None,
    ) -> None:
        self._alert_callback = alert_callback
        self._configs: dict[str, BudgetConfig] = {}
        self._usage_records: dict[str, list[Usage]] = defaultdict(list)
        self._period_start: dict[str, datetime] = {}
        self._alert_triggered: dict[str, bool] = defaultdict(bool)
        self._lock = asyncio.Lock()

    async def set_budget(
        self,
        entity_id: str,
        config: BudgetConfig,
    ) -> None:
        """Set budget configuration for an entity."""
        async with self._lock:
            self._configs[entity_id] = config
            if entity_id not in self._period_start:
                self._period_start[entity_id] = self._get_period_start()
            logger.debug("Set budget for %s", entity_id)

    async def get_budget(self, entity_id: str) -> BudgetConfig | None:
        """Get budget configuration for an entity."""
        return self._configs.get(entity_id)

    async def track(
        self,
        usage: Usage,
    ) -> BudgetStatus:
        """
        Track resource usage.

        Args:
            usage: Usage record to track

        Returns:
            Current budget status
        """
        async with self._lock:
            entity_id = usage.agent_id
            self._usage_records[entity_id].append(usage)
            self._cleanup_old_records(entity_id)

            status = await self._calculate_status(entity_id)

            if status.alert_triggered and not self._alert_triggered[entity_id]:
                self._alert_triggered[entity_id] = True
                await self._send_alert(entity_id, status)

            return status

    async def check_budget(
        self,
        entity_id: str,
        estimated_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> tuple[bool, BudgetStatus]:
        """
        Check if an operation is within budget.

        Args:
            entity_id: Entity to check
            estimated_tokens: Estimated token usage
            estimated_cost_usd: Estimated cost

        Returns:
            Tuple of (allowed, status)
        """
        async with self._lock:
            config = self._configs.get(entity_id)
            if not config:
                return True, BudgetStatus(
                    entity_id=entity_id,
                    entity_type="agent",
                    period_start=datetime.now(timezone.utc),
                    period_end=datetime.now(timezone.utc) + timedelta(days=1),
                )

            status = await self._calculate_status(entity_id)

            projected_tokens = status.tokens_used + estimated_tokens
            projected_cost = status.cost_used_usd + estimated_cost_usd

            will_exceed = False
            if config.max_tokens_per_day and projected_tokens > config.max_tokens_per_day:
                will_exceed = True
            if config.max_cost_per_day_usd and projected_cost > config.max_cost_per_day_usd:
                will_exceed = True

            if will_exceed and config.hard_limit:
                logger.warning("Budget exceeded for %s", entity_id)
                return False, status

            return True, status

    async def get_usage(
        self,
        entity_id: str,
        period_days: int = 1,
    ) -> UsageReport:
        """Get usage report for an entity."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            period_start = now - timedelta(days=period_days)
            period_end = now

            records = [
                r for r in self._usage_records.get(entity_id, []) if r.timestamp >= period_start
            ]

            total_tokens = sum(r.tokens_input + r.tokens_output for r in records)
            total_compute = sum(r.compute_seconds for r in records)
            total_cost = sum(r.cost_usd for r in records)

            by_model: dict[str, dict[str, Any]] = defaultdict(
                lambda: {"tokens": 0, "cost": 0.0, "requests": 0}
            )
            for r in records:
                by_model[r.model]["tokens"] += r.tokens_input + r.tokens_output
                by_model[r.model]["cost"] += r.cost_usd
                by_model[r.model]["requests"] += 1

            by_day: list[dict[str, Any]] = []
            for day_offset in range(period_days):
                day_start = period_start + timedelta(days=day_offset)
                day_end = day_start + timedelta(days=1)
                day_records = [r for r in records if day_start <= r.timestamp < day_end]
                by_day.append(
                    {
                        "date": day_start.date().isoformat(),
                        "tokens": sum(r.tokens_input + r.tokens_output for r in day_records),
                        "cost": sum(r.cost_usd for r in day_records),
                        "requests": len(day_records),
                    }
                )

            return UsageReport(
                entity_id=entity_id,
                period_start=period_start,
                period_end=period_end,
                total_tokens=total_tokens,
                total_compute_seconds=total_compute,
                total_cost_usd=total_cost,
                tasks_completed=len(records),
                tasks_failed=0,
                by_model=dict(by_model),
                by_day=by_day,
            )

    async def _calculate_status(self, entity_id: str) -> BudgetStatus:
        """Calculate current budget status for an entity."""
        config = self._configs.get(entity_id)
        period_start = self._period_start.get(entity_id, self._get_period_start())
        period_end = period_start + timedelta(days=1)

        records = [r for r in self._usage_records.get(entity_id, []) if r.timestamp >= period_start]

        tokens_used = sum(r.tokens_input + r.tokens_output for r in records)
        compute_used = sum(r.compute_seconds for r in records)
        cost_used = sum(r.cost_usd for r in records)

        usage_percent = 0.0
        over_limit = False
        alert_triggered = False

        if config:
            if config.max_tokens_per_day:
                token_pct = (tokens_used / config.max_tokens_per_day) * 100
                usage_percent = max(usage_percent, token_pct)
                if tokens_used >= config.max_tokens_per_day:
                    over_limit = True
            if config.max_cost_per_day_usd:
                cost_pct = (cost_used / config.max_cost_per_day_usd) * 100
                usage_percent = max(usage_percent, cost_pct)
                if cost_used >= config.max_cost_per_day_usd:
                    over_limit = True
            if usage_percent >= config.alert_threshold_percent:
                alert_triggered = True

        return BudgetStatus(
            entity_id=entity_id,
            entity_type="agent",
            period_start=period_start,
            period_end=period_end,
            tokens_used=tokens_used,
            tokens_limit=config.max_tokens_per_day if config else None,
            compute_seconds_used=compute_used,
            compute_seconds_limit=config.max_compute_seconds_per_day if config else None,
            cost_used_usd=cost_used,
            cost_limit_usd=config.max_cost_per_day_usd if config else None,
            usage_percent=usage_percent,
            over_limit=over_limit,
            alert_triggered=alert_triggered,
        )

    def _get_period_start(self) -> datetime:
        """Get the start of the current budget period (midnight UTC)."""
        now = datetime.now(timezone.utc)
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    def _cleanup_old_records(self, entity_id: str) -> None:
        """Remove records older than 7 days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        self._usage_records[entity_id] = [
            r for r in self._usage_records[entity_id] if r.timestamp >= cutoff
        ]

    async def _send_alert(self, entity_id: str, status: BudgetStatus) -> None:
        """Send a budget alert."""
        logger.warning("Budget alert for %s: %.1f%% used", entity_id, status.usage_percent)
        if self._alert_callback:
            try:
                await self._alert_callback(entity_id, status)
            except (RuntimeError, ValueError, AttributeError) as e:  # user-supplied callback
                logger.error("Alert callback error: %s", e)

    async def reset_period(self, entity_id: str) -> None:
        """Reset the budget period for an entity."""
        async with self._lock:
            self._period_start[entity_id] = self._get_period_start()
            self._alert_triggered[entity_id] = False
            logger.debug("Reset budget period for %s", entity_id)

    async def get_stats(self) -> dict[str, Any]:
        """Get budget manager statistics."""
        async with self._lock:
            return {
                "entities_tracked": len(self._configs),
                "total_usage_records": sum(len(r) for r in self._usage_records.values()),
                "alerts_triggered": sum(1 for v in self._alert_triggered.values() if v),
            }
