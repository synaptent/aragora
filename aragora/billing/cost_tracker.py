"""
Cost Tracking for Workspace and Agent-Level Attribution.

Provides granular cost tracking with:
- Per-workspace cost attribution
- Per-agent cost breakdown
- Budget management with alerts
- Cost projections and anomaly detection
- Real-time cost streaming
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol
from collections.abc import Callable
from uuid import uuid4

from aragora.billing.budget_manager import get_budget_manager
from aragora.billing.notification_sink import notify_cost_anomaly
from aragora.billing.usage import (
    UsageEvent,
    UsageEventType,
    UsageTracker,
    calculate_token_cost,
)

# Import Prometheus metrics for cost tracking
try:
    from aragora.observability.prometheus import record_cost_usd

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

    def record_cost_usd(provider: str, model: str, agent_id: str, cost_usd: float) -> None:
        pass  # No-op if Prometheus not available


logger = logging.getLogger(__name__)


class CostKnowledgeSink(Protocol):
    """Knowledge-side capability used for cost history and anomaly persistence."""

    def store_alert(self, alert: Any) -> Any: ...

    def get_cost_patterns(self, workspace_id: str, agent_id: str | None = None) -> dict: ...

    def get_workspace_alerts(
        self,
        workspace_id: str,
        min_level: str = "warning",
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def detect_anomalies(
        self,
        *,
        workspace_id: str,
        current_cost: float,
        current_tokens: int,
        current_calls: int,
    ) -> list[Any]: ...

    def store_anomaly(self, anomaly: Any) -> str | None: ...


class BudgetAlertLevel(str, Enum):
    """Budget alert severity levels."""

    INFO = "info"  # 50% of budget
    WARNING = "warning"  # 75% of budget
    CRITICAL = "critical"  # 90% of budget
    EXCEEDED = "exceeded"  # Over budget


class DebateBudgetExceededError(Exception):
    """Raised when a debate exceeds its cost budget."""

    def __init__(
        self,
        debate_id: str,
        current_cost: Decimal,
        limit: Decimal,
        message: str = "",
    ):
        self.debate_id = debate_id
        self.current_cost = current_cost
        self.limit = limit
        super().__init__(
            message or f"Debate {debate_id} exceeded budget: ${current_cost:.4f} > ${limit:.4f}"
        )


class CostGranularity(str, Enum):
    """Cost aggregation granularity."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class TokenUsage:
    """Token usage for a single API call."""

    id: str = field(default_factory=lambda: str(uuid4()))
    workspace_id: str = ""
    agent_id: str = ""
    agent_name: str = ""
    debate_id: str | None = None
    session_id: str | None = None

    # Provider info
    provider: str = ""
    model: str = ""

    # Token counts
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0  # Cached/prompt caching tokens (if supported)

    # Computed cost
    cost_usd: Decimal = Decimal("0")

    # Timing
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Additional metadata
    operation: str = ""  # e.g., "debate_round", "analysis", "summarization"
    metadata: dict[str, Any] = field(default_factory=dict)

    def calculate_cost(self) -> Decimal:
        """Calculate cost based on token usage."""
        self.cost_usd = calculate_token_cost(
            self.provider, self.model, self.tokens_in, self.tokens_out
        )
        return self.cost_usd

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "debate_id": self.debate_id,
            "session_id": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_cached": self.tokens_cached,
            "cost_usd": str(self.cost_usd),
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
            "operation": self.operation,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenUsage:
        """Create from dictionary."""
        usage = cls(
            id=data.get("id", str(uuid4())),
            workspace_id=data.get("workspace_id", ""),
            agent_id=data.get("agent_id", ""),
            agent_name=data.get("agent_name", ""),
            debate_id=data.get("debate_id"),
            session_id=data.get("session_id"),
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            tokens_in=data.get("tokens_in", 0),
            tokens_out=data.get("tokens_out", 0),
            tokens_cached=data.get("tokens_cached", 0),
            cost_usd=Decimal(data.get("cost_usd", "0")),
            latency_ms=data.get("latency_ms", 0.0),
            operation=data.get("operation", ""),
            metadata=data.get("metadata", {}),
        )
        if "timestamp" in data and data["timestamp"]:
            if isinstance(data["timestamp"], str):
                usage.timestamp = datetime.fromisoformat(data["timestamp"])
            else:
                usage.timestamp = data["timestamp"]
        return usage


@dataclass
class Budget:
    """Budget configuration for a workspace or organization."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    workspace_id: str | None = None
    org_id: str | None = None

    # Budget limits
    monthly_limit_usd: Decimal | None = None
    daily_limit_usd: Decimal | None = None
    per_debate_limit_usd: Decimal | None = None
    per_agent_limit_usd: Decimal | None = None

    # Alert thresholds (as percentages)
    alert_threshold_50: bool = True
    alert_threshold_75: bool = True
    alert_threshold_90: bool = True

    # Current spend (for quick access)
    current_monthly_spend: Decimal = Decimal("0")
    current_daily_spend: Decimal = Decimal("0")

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def check_alert_level(self) -> BudgetAlertLevel | None:
        """Check if budget threshold is exceeded."""
        if self.monthly_limit_usd is None or self.monthly_limit_usd <= 0:
            return None

        percentage = (self.current_monthly_spend / self.monthly_limit_usd) * 100

        if percentage >= 100:
            return BudgetAlertLevel.EXCEEDED
        elif percentage >= 90 and self.alert_threshold_90:
            return BudgetAlertLevel.CRITICAL
        elif percentage >= 75 and self.alert_threshold_75:
            return BudgetAlertLevel.WARNING
        elif percentage >= 50 and self.alert_threshold_50:
            return BudgetAlertLevel.INFO

        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "workspace_id": self.workspace_id,
            "org_id": self.org_id,
            "monthly_limit_usd": str(self.monthly_limit_usd) if self.monthly_limit_usd else None,
            "daily_limit_usd": str(self.daily_limit_usd) if self.daily_limit_usd else None,
            "per_debate_limit_usd": (
                str(self.per_debate_limit_usd) if self.per_debate_limit_usd else None
            ),
            "per_agent_limit_usd": (
                str(self.per_agent_limit_usd) if self.per_agent_limit_usd else None
            ),
            "current_monthly_spend": str(self.current_monthly_spend),
            "current_daily_spend": str(self.current_daily_spend),
            "alert_level": level.value if (level := self.check_alert_level()) else None,
        }


@dataclass
class BudgetAlert:
    """A budget alert event."""

    id: str = field(default_factory=lambda: str(uuid4()))
    budget_id: str = ""
    workspace_id: str | None = None
    org_id: str | None = None
    level: BudgetAlertLevel = BudgetAlertLevel.INFO
    message: str = ""
    current_spend: Decimal = Decimal("0")
    limit: Decimal = Decimal("0")
    percentage: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None


@dataclass
class CostReport:
    """Aggregated cost report."""

    workspace_id: str | None = None
    org_id: str | None = None
    period_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    period_end: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    granularity: CostGranularity = CostGranularity.DAILY

    # Total costs
    total_cost_usd: Decimal = Decimal("0")
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_api_calls: int = 0

    # Breakdowns
    cost_by_agent: dict[str, Decimal] = field(default_factory=dict)
    cost_by_model: dict[str, Decimal] = field(default_factory=dict)
    cost_by_provider: dict[str, Decimal] = field(default_factory=dict)
    cost_by_operation: dict[str, Decimal] = field(default_factory=dict)

    # Time series
    cost_over_time: list[dict[str, Any]] = field(default_factory=list)

    # Efficiency metrics
    avg_cost_per_call: Decimal = Decimal("0")
    avg_tokens_per_call: float = 0.0
    avg_latency_ms: float = 0.0

    # Top consumers
    top_debates_by_cost: list[dict[str, Any]] = field(default_factory=list)
    top_agents_by_cost: list[dict[str, Any]] = field(default_factory=list)

    # Projections
    projected_monthly_cost: Decimal | None = None
    projected_daily_rate: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "workspace_id": self.workspace_id,
            "org_id": self.org_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "granularity": self.granularity.value,
            "total_cost_usd": str(self.total_cost_usd),
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "total_api_calls": self.total_api_calls,
            "cost_by_agent": {k: str(v) for k, v in self.cost_by_agent.items()},
            "cost_by_model": {k: str(v) for k, v in self.cost_by_model.items()},
            "cost_by_provider": {k: str(v) for k, v in self.cost_by_provider.items()},
            "cost_by_operation": {k: str(v) for k, v in self.cost_by_operation.items()},
            "cost_over_time": self.cost_over_time,
            "avg_cost_per_call": str(self.avg_cost_per_call),
            "avg_tokens_per_call": self.avg_tokens_per_call,
            "avg_latency_ms": self.avg_latency_ms,
            "top_debates_by_cost": self.top_debates_by_cost,
            "top_agents_by_cost": self.top_agents_by_cost,
            "projected_monthly_cost": (
                str(self.projected_monthly_cost) if self.projected_monthly_cost else None
            ),
            "projected_daily_rate": (
                str(self.projected_daily_rate) if self.projected_daily_rate else None
            ),
        }


@dataclass
class CostAdvisory:
    """Advisory recommendation based on cost anomaly detection.

    Maps anomaly severity to recommended actions for automated or
    human-in-the-loop cost management.
    """

    recommended_action: str  # "downgrade_tier", "reduce_rounds", "pause_workspace", "none"
    severity: str  # "critical", "high", "warning", "info", "none"
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    workspace_id: str = ""
    anomaly_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "recommended_action": self.recommended_action,
            "severity": self.severity,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "workspace_id": self.workspace_id,
            "anomaly_count": self.anomaly_count,
        }

    @staticmethod
    def no_action(workspace_id: str = "") -> CostAdvisory:
        """Create a no-action advisory (no anomalies detected)."""
        return CostAdvisory(
            recommended_action="none",
            severity="none",
            reason="No cost anomalies detected",
            workspace_id=workspace_id,
        )

    @staticmethod
    def severity_to_action(severity: str) -> str:
        """Map anomaly severity to a recommended action."""
        mapping = {
            "critical": "downgrade_tier",
            "high": "reduce_rounds",
            "warning": "pause_workspace",
            "info": "none",
        }
        return mapping.get(severity, "none")


AlertCallback = Callable[[BudgetAlert], None]


class CostTracker:
    """
    Real-time cost tracking with workspace/agent attribution.

    Provides comprehensive cost monitoring with budget management,
    alerting, and detailed reporting.

    Supports optional Knowledge Mound integration via a registered sink for
    persisting budget alerts and cost anomalies to organizational memory.
    """

    def __init__(
        self,
        usage_tracker: UsageTracker | None = None,
        km_adapter: CostKnowledgeSink | None = None,
        event_emitter: Any | None = None,
    ):
        """
        Initialize cost tracker.

        Args:
            usage_tracker: Optional UsageTracker for persistence
            km_adapter: Optional knowledge sink for cost history integration
            event_emitter: Optional event emitter for streaming budget events
        """
        self._usage_tracker = usage_tracker
        self._km_adapter = km_adapter
        self._event_emitter = event_emitter

        # In-memory tracking for real-time updates
        self._usage_buffer: list[TokenUsage] = []
        self._buffer_lock = asyncio.Lock()
        self._buffer_max_size = 1000

        # Budget management
        self._budgets: dict[str, Budget] = {}  # budget_id -> Budget
        self._workspace_budgets: dict[str, str] = {}  # workspace_id -> budget_id
        self._org_budgets: dict[str, str] = {}  # org_id -> budget_id
        # Per-debate budget tracking
        self._debate_costs: dict[str, Decimal] = {}
        self._debate_limits: dict[str, Decimal] = {}

        # Alert management
        self._alert_callbacks: list[AlertCallback] = []
        self._sent_alerts: set[str] = set()  # Deduplicate alerts

        # Advisory cache (workspace_id -> last advisory)
        self._last_advisory: dict[str, CostAdvisory] = {}

        # Aggregated stats (refreshed periodically)
        self._workspace_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "total_cost": Decimal("0"),
                "tokens_in": 0,
                "tokens_out": 0,
                "api_calls": 0,
                "by_agent": defaultdict(lambda: Decimal("0")),
                "by_model": defaultdict(lambda: Decimal("0")),
            }
        )

    async def record(self, usage: TokenUsage) -> None:
        """
        Record a token usage event.

        Args:
            usage: Token usage to record
        """
        # Calculate cost if not already done
        if usage.cost_usd == Decimal("0"):
            usage.calculate_cost()

        # Update in-memory stats
        async with self._buffer_lock:
            self._usage_buffer.append(usage)

            # Flush buffer if too large
            if len(self._usage_buffer) >= self._buffer_max_size:
                await self._flush_buffer()

        # Update workspace stats
        stats = self._workspace_stats[usage.workspace_id]
        stats["total_cost"] += usage.cost_usd
        stats["tokens_in"] += usage.tokens_in
        stats["tokens_out"] += usage.tokens_out
        stats["api_calls"] += 1
        stats["by_agent"][usage.agent_name] += usage.cost_usd
        stats["by_model"][usage.model] += usage.cost_usd

        # Update per-debate cost tracking
        if usage.debate_id:
            if usage.debate_id not in self._debate_costs:
                self._debate_costs[usage.debate_id] = Decimal("0")
            self._debate_costs[usage.debate_id] += usage.cost_usd

        # Update budget tracking
        await self._update_budget(usage)

        # Persist to usage tracker
        if self._usage_tracker:
            event = UsageEvent(
                user_id=usage.metadata.get("user_id", ""),
                org_id=usage.metadata.get("org_id", ""),
                event_type=UsageEventType.AGENT_CALL,
                debate_id=usage.debate_id,
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                provider=usage.provider,
                model=usage.model,
                cost_usd=usage.cost_usd,
                metadata={
                    "workspace_id": usage.workspace_id,
                    "agent_id": usage.agent_id,
                    "agent_name": usage.agent_name,
                    "session_id": usage.session_id,
                    "operation": usage.operation,
                    "latency_ms": usage.latency_ms,
                },
            )
            self._usage_tracker.record(event)

        # Record to Prometheus metrics for dashboards
        record_cost_usd(
            provider=usage.provider,
            model=usage.model,
            agent_id=usage.agent_id or usage.agent_name,
            cost_usd=float(usage.cost_usd),
        )

        logger.debug(
            f"cost_recorded workspace={usage.workspace_id} agent={usage.agent_name} "
            f"cost=${usage.cost_usd:.6f} tokens={usage.tokens_in + usage.tokens_out}"
        )

    async def record_batch(self, usages: list[TokenUsage]) -> None:
        """Record multiple usage events."""
        for usage in usages:
            await self.record(usage)

    async def _flush_buffer(self) -> None:
        """Flush usage buffer (called when buffer is full)."""
        if not self._usage_buffer:
            return

        # For now, just clear the buffer
        # In production, this would persist to a time-series database
        buffer_size = len(self._usage_buffer)
        self._usage_buffer = []
        logger.debug("Flushed %s usage records from buffer", buffer_size)

    async def _update_budget(self, usage: TokenUsage) -> None:
        """Update budget tracking and check for alerts."""
        # Find applicable budget
        budget = None

        if usage.workspace_id and usage.workspace_id in self._workspace_budgets:
            budget_id = self._workspace_budgets[usage.workspace_id]
            budget = self._budgets.get(budget_id)

        org_id = usage.metadata.get("org_id", "")
        if not budget and org_id and org_id in self._org_budgets:
            budget_id = self._org_budgets[org_id]
            budget = self._budgets.get(budget_id)

        if not budget:
            return

        # Update spend
        budget.current_daily_spend += usage.cost_usd
        budget.current_monthly_spend += usage.cost_usd
        budget.updated_at = datetime.now(timezone.utc)

        # Check for alerts
        await self._check_budget_alerts(budget)

    async def _check_budget_alerts(self, budget: Budget) -> None:
        """Check if budget thresholds are exceeded and send alerts."""
        alert_level = budget.check_alert_level()
        if not alert_level:
            return

        # Create unique key to avoid duplicate alerts
        alert_key = (
            f"{budget.id}:{alert_level.value}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        )
        if alert_key in self._sent_alerts:
            return

        self._sent_alerts.add(alert_key)

        # Calculate percentage
        percentage = (
            float((budget.current_monthly_spend / budget.monthly_limit_usd) * 100)
            if budget.monthly_limit_usd
            else 0
        )

        alert = BudgetAlert(
            budget_id=budget.id,
            workspace_id=budget.workspace_id,
            org_id=budget.org_id,
            level=alert_level,
            message=f"Budget {budget.name}: {percentage:.1f}% used (${budget.current_monthly_spend:.2f} of ${budget.monthly_limit_usd:.2f})",
            current_spend=budget.current_monthly_spend,
            limit=budget.monthly_limit_usd or Decimal("0"),
            percentage=percentage,
        )

        # Notify callbacks
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except (TypeError, ValueError, RuntimeError, OSError) as e:
                logger.error("Alert callback failed: %s", e)

        # Store to Knowledge Mound if adapter configured
        if self._km_adapter:
            try:
                self._km_adapter.store_alert(alert)
            except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                logger.error("Failed to store alert to KM: %s", e)

        # Emit stream event for real-time budget monitoring
        if self._event_emitter:
            try:
                from aragora.events.types import StreamEvent, StreamEventType

                self._event_emitter.emit(
                    StreamEvent(
                        type=StreamEventType.BUDGET_ALERT,
                        data={
                            "budget_id": budget.id,
                            "workspace_id": budget.workspace_id,
                            "org_id": budget.org_id,
                            "level": alert_level.value,
                            "percentage": percentage,
                            "current_spend": float(budget.current_monthly_spend),
                            "limit": float(budget.monthly_limit_usd or 0),
                        },
                    )
                )
            except ImportError:
                pass
            except (AttributeError, TypeError) as exc:
                logger.debug("budget_alert_webhook_failed: %s", exc)

        logger.warning("budget_alert %s", alert.message)

    def set_budget(self, budget: Budget) -> None:
        """
        Set a budget for a workspace or organization.

        Args:
            budget: Budget configuration
        """
        self._budgets[budget.id] = budget

        if budget.workspace_id:
            self._workspace_budgets[budget.workspace_id] = budget.id
        if budget.org_id:
            self._org_budgets[budget.org_id] = budget.id

    def get_budget(
        self,
        workspace_id: str | None = None,
        org_id: str | None = None,
    ) -> Budget | None:
        """Get budget for workspace or organization."""
        if workspace_id and workspace_id in self._workspace_budgets:
            return self._budgets.get(self._workspace_budgets[workspace_id])
        if org_id and org_id in self._org_budgets:
            return self._budgets.get(self._org_budgets[org_id])
        return None

    def set_km_adapter(self, adapter: CostKnowledgeSink) -> None:
        """
        Set Knowledge Mound adapter for alert/anomaly persistence.

        Args:
            adapter: Knowledge-side cost sink
        """
        self._km_adapter = adapter

    def add_alert_callback(self, callback: AlertCallback) -> None:
        """Register a callback for budget alerts."""
        self._alert_callbacks.append(callback)

    def remove_alert_callback(self, callback: AlertCallback) -> None:
        """Remove an alert callback."""
        if callback in self._alert_callbacks:
            self._alert_callbacks.remove(callback)

    def get_workspace_stats(self, workspace_id: str) -> dict[str, Any]:
        """
        Get real-time cost stats for a workspace.

        Args:
            workspace_id: Workspace ID

        Returns:
            Cost statistics
        """
        stats = self._workspace_stats.get(workspace_id, {})
        return {
            "workspace_id": workspace_id,
            "total_cost_usd": str(stats.get("total_cost", Decimal("0"))),
            "total_tokens_in": stats.get("tokens_in", 0),
            "total_tokens_out": stats.get("tokens_out", 0),
            "total_api_calls": stats.get("api_calls", 0),
            "cost_by_agent": {k: str(v) for k, v in stats.get("by_agent", {}).items()},
            "cost_by_model": {k: str(v) for k, v in stats.get("by_model", {}).items()},
        }

    async def generate_report(
        self,
        workspace_id: str | None = None,
        org_id: str | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        granularity: CostGranularity = CostGranularity.DAILY,
    ) -> CostReport:
        """
        Generate a comprehensive cost report.

        Args:
            workspace_id: Filter by workspace
            org_id: Filter by organization
            period_start: Report start time
            period_end: Report end time
            granularity: Time aggregation granularity

        Returns:
            Cost report
        """
        if period_end is None:
            period_end = datetime.now(timezone.utc)
        if period_start is None:
            period_start = period_end - timedelta(days=30)

        report = CostReport(
            workspace_id=workspace_id,
            org_id=org_id,
            period_start=period_start,
            period_end=period_end,
            granularity=granularity,
        )

        # Aggregate from in-memory stats if workspace specified
        if workspace_id and workspace_id in self._workspace_stats:
            stats = self._workspace_stats[workspace_id]
            report.total_cost_usd = stats.get("total_cost", Decimal("0"))
            report.total_tokens_in = stats.get("tokens_in", 0)
            report.total_tokens_out = stats.get("tokens_out", 0)
            report.total_api_calls = stats.get("api_calls", 0)
            report.cost_by_agent = dict(stats.get("by_agent", {}))
            report.cost_by_model = dict(stats.get("by_model", {}))

            # Calculate averages
            if report.total_api_calls > 0:
                report.avg_cost_per_call = report.total_cost_usd / report.total_api_calls
                report.avg_tokens_per_call = (
                    report.total_tokens_in + report.total_tokens_out
                ) / report.total_api_calls

        # If we have a usage tracker, get historical data
        if self._usage_tracker and org_id:
            summary = self._usage_tracker.get_summary(
                org_id=org_id,
                period_start=period_start,
                period_end=period_end,
            )

            # Merge with in-memory if not already populated
            if report.total_cost_usd == Decimal("0"):
                report.total_cost_usd = summary.total_cost_usd
                report.total_tokens_in = summary.total_tokens_in
                report.total_tokens_out = summary.total_tokens_out
                report.total_api_calls = summary.total_agent_calls + summary.total_debates

            report.cost_by_provider = summary.cost_by_provider

        # Calculate projections
        if report.total_api_calls > 0:
            days_in_period = max(1, (period_end - period_start).days)
            report.projected_daily_rate = report.total_cost_usd / days_in_period

            # Project to full month
            days_in_month = 30
            report.projected_monthly_cost = report.projected_daily_rate * days_in_month

        # Get top agents
        if report.cost_by_agent:
            sorted_agents = sorted(
                report.cost_by_agent.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:10]
            report.top_agents_by_cost = [{"agent": k, "cost_usd": str(v)} for k, v in sorted_agents]

        return report

    def get_dashboard_summary(
        self,
        workspace_id: str | None = None,
        org_id: str | None = None,
    ) -> dict[str, Any]:
        """Get a consolidated dashboard summary for SMB customers.

        Provides a simple, unified view of current spend, budget status,
        top cost drivers, and projected costs suitable for non-technical users.

        Args:
            workspace_id: Filter by workspace
            org_id: Filter by organization

        Returns:
            Dashboard summary with spend, budget, and projections.
        """
        # Current spend from workspace stats
        stats: dict[str, Any] = {}
        if workspace_id:
            stats = self._workspace_stats.get(workspace_id, {})

        total_cost = stats.get("total_cost", Decimal("0"))
        api_calls = stats.get("api_calls", 0)

        # Budget status
        budget = self.get_budget(workspace_id=workspace_id, org_id=org_id)
        budget_info: dict[str, Any] = {"configured": False}
        if budget:
            budget_info = {
                "configured": True,
                "monthly_limit_usd": str(budget.monthly_limit_usd or 0),
                "current_monthly_spend": str(budget.current_monthly_spend or Decimal("0")),
                "utilization_pct": float(
                    (budget.current_monthly_spend / budget.monthly_limit_usd * 100)
                    if budget.monthly_limit_usd
                    else 0
                ),
                "alert_level": getattr(budget.check_alert_level(), "value", None),
            }

        # Top cost drivers
        by_agent = stats.get("by_agent", {})
        top_agents = sorted(by_agent.items(), key=lambda x: x[1], reverse=True)[:5]

        by_model = stats.get("by_model", {})
        top_models = sorted(by_model.items(), key=lambda x: x[1], reverse=True)[:5]

        # Simple projection (daily rate * 30)
        projected_monthly = None
        if api_calls > 0 and total_cost > 0:
            # Assume data is for current month so far
            now = datetime.now(timezone.utc)
            days_elapsed = max(1, now.day)
            daily_rate = total_cost / days_elapsed
            projected_monthly = str(daily_rate * 30)

        return {
            "workspace_id": workspace_id,
            "org_id": org_id,
            "current_spend": {
                "total_cost_usd": str(total_cost),
                "total_api_calls": api_calls,
                "total_tokens": stats.get("tokens_in", 0) + stats.get("tokens_out", 0),
            },
            "budget": budget_info,
            "top_cost_drivers": {
                "by_agent": [{"agent": k, "cost_usd": str(v)} for k, v in top_agents],
                "by_model": [{"model": k, "cost_usd": str(v)} for k, v in top_models],
            },
            "projections": {
                "projected_monthly_usd": projected_monthly,
            },
        }

    async def get_agent_costs(
        self,
        workspace_id: str,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Get cost breakdown by agent.

        Args:
            workspace_id: Workspace ID
            period_start: Start of period
            period_end: End of period

        Returns:
            Cost breakdown by agent name
        """
        stats = self._workspace_stats.get(workspace_id, {})
        by_agent = stats.get("by_agent", {})

        result: dict[str, dict[str, Any]] = {}
        total_cost = stats.get("total_cost", Decimal("0"))

        for agent_name, cost in by_agent.items():
            percentage = (cost / total_cost * 100) if total_cost > 0 else 0
            result[agent_name] = {
                "cost_usd": str(cost),
                "percentage": float(percentage),
            }

        return result

    async def get_debate_cost(self, debate_id: str) -> dict[str, Any]:
        """
        Get total cost for a debate.

        Args:
            debate_id: Debate ID

        Returns:
            Debate cost breakdown
        """
        total_cost = Decimal("0")
        total_tokens_in = 0
        total_tokens_out = 0
        by_agent: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

        # Check buffer for recent debate data
        async with self._buffer_lock:
            for usage in self._usage_buffer:
                if usage.debate_id == debate_id:
                    total_cost += usage.cost_usd
                    total_tokens_in += usage.tokens_in
                    total_tokens_out += usage.tokens_out
                    by_agent[usage.agent_name] += usage.cost_usd

        # Also check persistent storage
        if self._usage_tracker:
            db_cost = self._usage_tracker.get_debate_cost(debate_id)
            if db_cost > total_cost:
                total_cost = db_cost

        return {
            "debate_id": debate_id,
            "total_cost_usd": str(total_cost),
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "cost_by_agent": {k: str(v) for k, v in by_agent.items()},
        }

    def set_debate_limit(
        self,
        debate_id: str,
        limit_usd: Decimal,
    ) -> None:
        """
        Set a cost limit for a specific debate.

        When the debate's accumulated cost exceeds this limit, further
        operations will be blocked.

        Args:
            debate_id: Debate ID to set limit for
            limit_usd: Maximum cost in USD for this debate
        """
        self._debate_limits[debate_id] = limit_usd
        if debate_id not in self._debate_costs:
            self._debate_costs[debate_id] = Decimal("0")
        logger.info("Set debate cost limit: debate=%s limit=$%s", debate_id, limit_usd)

    def check_debate_budget(
        self,
        debate_id: str,
        estimated_cost_usd: Decimal = Decimal("0"),
    ) -> dict[str, Any]:
        """
        Check if a debate is within its budget.

        Args:
            debate_id: Debate ID to check
            estimated_cost_usd: Estimated cost of the next operation

        Returns:
            Dict with:
                - allowed: bool - whether operation can proceed
                - current_cost: str - current total cost
                - limit: str - cost limit (or "unlimited")
                - remaining: str - remaining budget
                - message: str - human-readable status
        """
        current_cost = self._debate_costs.get(debate_id, Decimal("0"))
        limit = self._debate_limits.get(debate_id)

        if limit is None:
            return {
                "allowed": True,
                "current_cost": str(current_cost),
                "limit": "unlimited",
                "remaining": "unlimited",
                "message": "No limit set for this debate",
            }

        remaining = limit - current_cost
        projected_total = current_cost + estimated_cost_usd

        if projected_total > limit:
            return {
                "allowed": False,
                "current_cost": str(current_cost),
                "limit": str(limit),
                "remaining": str(max(Decimal("0"), remaining)),
                "message": f"Debate budget exceeded: ${current_cost:.4f} spent of ${limit:.4f} limit",
            }

        return {
            "allowed": True,
            "current_cost": str(current_cost),
            "limit": str(limit),
            "remaining": str(remaining),
            "message": f"Within budget: ${current_cost:.4f} of ${limit:.4f} ({(current_cost / limit * 100):.1f}%)",
        }

    def record_debate_cost(
        self,
        debate_id: str,
        cost_usd: Decimal,
    ) -> dict[str, Any]:
        """
        Record cost against a debate's budget.

        Args:
            debate_id: Debate ID
            cost_usd: Cost to record

        Returns:
            Budget status after recording
        """
        if debate_id not in self._debate_costs:
            self._debate_costs[debate_id] = Decimal("0")

        self._debate_costs[debate_id] += cost_usd

        return self.check_debate_budget(debate_id)

    def get_debate_budget_status(self, debate_id: str) -> dict[str, Any]:
        """
        Get the current budget status for a debate.

        Args:
            debate_id: Debate ID

        Returns:
            Budget status dict
        """
        return self.check_debate_budget(debate_id)

    def clear_debate_budget(self, debate_id: str) -> None:
        """
        Clear budget tracking for a completed debate.

        Call this when a debate ends to free memory.

        Args:
            debate_id: Debate ID to clear
        """
        self._debate_costs.pop(debate_id, None)
        self._debate_limits.pop(debate_id, None)

    def query_km_cost_patterns(
        self,
        workspace_id: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Query Knowledge Mound for historical cost patterns.

        Args:
            workspace_id: Workspace to get patterns for
            agent_id: Optional agent filter

        Returns:
            Cost pattern dict with averages, stddev, etc.
        """
        if not self._km_adapter:
            return {}

        try:
            return self._km_adapter.get_cost_patterns(workspace_id, agent_id)
        except (OSError, ConnectionError, RuntimeError, ValueError, KeyError) as e:
            logger.error("Failed to query KM cost patterns: %s", e)
            return {}

    def query_km_workspace_alerts(
        self,
        workspace_id: str,
        min_level: str = "warning",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Query Knowledge Mound for historical budget alerts.

        Args:
            workspace_id: Workspace to get alerts for
            min_level: Minimum alert level
            limit: Maximum results

        Returns:
            List of historical alerts
        """
        if not self._km_adapter:
            return []

        try:
            return self._km_adapter.get_workspace_alerts(workspace_id, min_level, limit)
        except (OSError, ConnectionError, RuntimeError, ValueError, KeyError) as e:
            logger.error("Failed to query KM alerts: %s", e)
            return []

    async def detect_and_store_anomalies(
        self,
        workspace_id: str,
    ) -> tuple[list[dict[str, Any]], CostAdvisory]:
        """
        Detect cost anomalies and store them to Knowledge Mound.

        Compares current workspace stats against historical patterns
        to identify unusual cost spikes. Returns both the raw anomaly
        list and a CostAdvisory with a recommended action.

        Args:
            workspace_id: Workspace to check

        Returns:
            Tuple of (anomalies list, CostAdvisory with recommended action)
        """
        no_action = CostAdvisory.no_action(workspace_id)

        if not self._km_adapter:
            return [], no_action

        stats = self._workspace_stats.get(workspace_id)
        if not stats:
            return [], no_action

        try:
            anomalies = self._km_adapter.detect_anomalies(
                workspace_id=workspace_id,
                current_cost=float(stats.get("total_cost", 0)),
                current_tokens=stats.get("tokens_in", 0) + stats.get("tokens_out", 0),
                current_calls=stats.get("api_calls", 0),
            )

            # Store detected anomalies and send notifications
            stored = []
            for anomaly in anomalies:
                anomaly_id = self._km_adapter.store_anomaly(anomaly)
                if anomaly_id:
                    anomaly_dict = anomaly.to_dict()
                    stored.append(anomaly_dict)

                    # Send cost anomaly notification
                    try:
                        await notify_cost_anomaly(
                            anomaly_type=anomaly_dict.get("type", "unknown"),
                            severity=anomaly_dict.get("severity", "warning"),
                            amount=anomaly_dict.get("actual", 0.0),
                            expected=anomaly_dict.get("expected", 0.0),
                            workspace_id=workspace_id,
                            details=anomaly_dict.get("description"),
                        )
                    except (ImportError, RuntimeError, OSError, TypeError, ValueError):
                        logger.debug(
                            "Failed to send cost anomaly notification",
                            exc_info=True,
                        )

            # Enforce budget suspension for critical anomalies
            for anomaly_dict in stored:
                if anomaly_dict.get("severity") == "critical":
                    try:
                        mgr = get_budget_manager()
                        mgr.handle_cost_anomaly(
                            org_id=workspace_id,
                            anomaly_type=anomaly_dict.get("type", "unknown"),
                            severity="critical",
                            amount=anomaly_dict.get("actual", 0.0),
                            expected=anomaly_dict.get("expected", 0.0),
                        )
                    except (RuntimeError, OSError, sqlite3.Error, ValueError) as enforce_err:
                        logger.warning(
                            "Budget enforcement failed for critical anomaly: %s",
                            enforce_err,
                        )

            # Build advisory from the highest-severity anomaly
            advisory = self._build_advisory(stored, workspace_id)
            self._last_advisory[workspace_id] = advisory

            return stored, advisory
        except (OSError, ConnectionError, RuntimeError, ValueError, KeyError, TypeError) as e:
            logger.error("Failed to detect/store anomalies: %s", e)
            return [], no_action

    def _build_advisory(
        self,
        anomalies: list[dict[str, Any]],
        workspace_id: str,
    ) -> CostAdvisory:
        """Build a CostAdvisory from detected anomalies.

        Uses the highest severity anomaly to determine the recommended action.
        """
        if not anomalies:
            return CostAdvisory.no_action(workspace_id)

        severity_rank = {"critical": 4, "high": 3, "warning": 2, "info": 1}
        worst = max(anomalies, key=lambda a: severity_rank.get(a.get("severity", "info"), 0))
        severity = worst.get("severity", "info")

        return CostAdvisory(
            recommended_action=CostAdvisory.severity_to_action(severity),
            severity=severity,
            reason=worst.get("description", f"{len(anomalies)} anomalies detected"),
            workspace_id=workspace_id,
            anomaly_count=len(anomalies),
        )

    def get_workspace_cost_advisory(self, workspace_id: str) -> CostAdvisory:
        """Get the cached cost advisory for a workspace.

        Returns the advisory from the last detect_and_store_anomalies() call,
        or a no-action advisory if none exists.

        Args:
            workspace_id: Workspace to get advisory for

        Returns:
            The most recent CostAdvisory for this workspace
        """
        return self._last_advisory.get(
            workspace_id,
            CostAdvisory.no_action(workspace_id),
        )

    def reset_daily_budgets(self) -> None:
        """Reset daily budget counters (called at midnight)."""
        for budget in self._budgets.values():
            budget.current_daily_spend = Decimal("0")

        # Clear daily alert dedup keys
        keys_to_remove = [k for k in self._sent_alerts if "daily" in k]
        for key in keys_to_remove:
            self._sent_alerts.discard(key)

    def reset_monthly_budgets(self) -> None:
        """Reset monthly budget counters (called at month start)."""
        for budget in self._budgets.values():
            budget.current_monthly_spend = Decimal("0")
            budget.current_daily_spend = Decimal("0")

        # Clear all alert dedup keys
        self._sent_alerts.clear()

        # Reset workspace stats
        self._workspace_stats.clear()


# Global cost tracker instance
_cost_tracker: CostTracker | None = None


def get_cost_tracker() -> CostTracker:
    """Get or create the global cost tracker."""
    global _cost_tracker
    if _cost_tracker is None:
        try:
            usage_tracker = UsageTracker()
        except (ImportError, ModuleNotFoundError) as e:
            logger.debug("UsageTracker dependency not available: %s", e)
            usage_tracker = None
        except (RuntimeError, ConnectionError) as e:
            logger.warning("UsageTracker initialization failed: %s", e)
            usage_tracker = None
        except (OSError, sqlite3.Error, ValueError, TypeError) as e:
            logger.exception("Unexpected error creating UsageTracker: %s", e)
            usage_tracker = None
        _cost_tracker = CostTracker(usage_tracker=usage_tracker)

    return _cost_tracker


async def record_usage(
    workspace_id: str,
    agent_name: str,
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    debate_id: str | None = None,
    operation: str = "",
    latency_ms: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> TokenUsage:
    """
    Convenience function to record token usage.

    Args:
        workspace_id: Workspace ID
        agent_name: Name of the agent
        provider: LLM provider
        model: Model used
        tokens_in: Input tokens
        tokens_out: Output tokens
        debate_id: Optional debate ID
        operation: Operation type
        latency_ms: Request latency
        metadata: Additional metadata

    Returns:
        Created TokenUsage record
    """
    usage = TokenUsage(
        workspace_id=workspace_id,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        debate_id=debate_id,
        operation=operation,
        latency_ms=latency_ms,
        metadata=metadata or {},
    )

    tracker = get_cost_tracker()
    await tracker.record(usage)

    return usage


__all__ = [
    "CostAdvisory",
    "CostKnowledgeSink",
    "CostTracker",
    "TokenUsage",
    "Budget",
    "BudgetAlert",
    "BudgetAlertLevel",
    "CostReport",
    "CostGranularity",
    "DebateBudgetExceededError",
    "get_budget_manager",
    "get_cost_tracker",
    "record_usage",
]
