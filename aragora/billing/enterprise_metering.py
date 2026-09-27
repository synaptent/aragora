"""
Enterprise Usage Metering for ENTERPRISE Tier.

Provides granular token-level metering with:
- Per-model, per-provider cost tracking
- Budget management and alerts
- Invoice generation
- Usage forecasting
- Real-time cost dashboards

Usage:
    from aragora.billing.enterprise_metering import EnterpriseMeter

    meter = EnterpriseMeter()
    await meter.initialize()

    # Record token usage
    await meter.record_token_usage(
        provider="anthropic",
        model="claude-opus-4",
        tokens_in=1000,
        tokens_out=500,
        debate_id="debate_123",
    )

    # Get cost breakdown
    breakdown = await meter.get_cost_breakdown(tenant_id="tenant_1")

    # Generate invoice
    invoice = await meter.generate_invoice(tenant_id="tenant_1", period="2025-01")
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from .usage import PROVIDER_PRICING

logger = logging.getLogger(__name__)


class BudgetAlertLevel(Enum):
    """Budget alert threshold levels."""

    INFO = "info"  # 50% of budget
    WARNING = "warning"  # 75% of budget
    CRITICAL = "critical"  # 90% of budget
    EXCEEDED = "exceeded"  # Over budget


class InvoiceStatus(Enum):
    """Invoice statuses."""

    DRAFT = "draft"
    PENDING = "pending"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


@dataclass
class TokenUsageRecord:
    """Record of token usage for a single API call."""

    id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = ""
    user_id: str | None = None
    workspace_id: str | None = None

    # Provider/model info
    provider: str = ""
    model: str = ""
    model_version: str | None = None

    # Token counts
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0  # Tokens from cache (discounted)

    # Cost
    input_cost: Decimal = Decimal("0")
    output_cost: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    discount_applied: Decimal = Decimal("0")

    # Context
    debate_id: str | None = None
    agent_id: str | None = None
    request_type: str = "chat"  # chat, debate, analysis, etc.
    endpoint: str | None = None

    # Metadata
    latency_ms: int | None = None
    success: bool = True
    error_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "input_cost": str(self.input_cost),
            "output_cost": str(self.output_cost),
            "total_cost": str(self.total_cost),
            "discount_applied": str(self.discount_applied),
            "debate_id": self.debate_id,
            "agent_id": self.agent_id,
            "request_type": self.request_type,
            "endpoint": self.endpoint,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "error_code": self.error_code,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class BudgetConfig:
    """Budget configuration for a tenant."""

    tenant_id: str
    monthly_budget: Decimal = Decimal("0")  # 0 = unlimited
    daily_limit: Decimal = Decimal("0")  # 0 = unlimited
    alert_thresholds: list[int] = field(default_factory=lambda: [50, 75, 90])
    alert_emails: list[str] = field(default_factory=list)
    auto_suspend_on_exceed: bool = False
    rollover_unused: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CostBreakdown:
    """Detailed cost breakdown for a period."""

    tenant_id: str
    period_start: datetime
    period_end: datetime

    # Totals
    total_cost: Decimal = Decimal("0")
    total_tokens: int = 0
    total_requests: int = 0

    # By provider
    cost_by_provider: dict[str, Decimal] = field(default_factory=dict)
    tokens_by_provider: dict[str, int] = field(default_factory=dict)

    # By model
    cost_by_model: dict[str, Decimal] = field(default_factory=dict)
    tokens_by_model: dict[str, int] = field(default_factory=dict)

    # By request type
    cost_by_type: dict[str, Decimal] = field(default_factory=dict)

    # By user (for multi-user tenants)
    cost_by_user: dict[str, Decimal] = field(default_factory=dict)

    # By day
    cost_by_day: dict[str, Decimal] = field(default_factory=dict)

    # Efficiency metrics
    avg_cost_per_request: Decimal = Decimal("0")
    avg_tokens_per_request: int = 0
    cache_hit_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tenant_id": self.tenant_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "total_cost": str(self.total_cost),
            "total_tokens": self.total_tokens,
            "total_requests": self.total_requests,
            "by_provider": {
                "cost": {k: str(v) for k, v in self.cost_by_provider.items()},
                "tokens": self.tokens_by_provider,
            },
            "by_model": {
                "cost": {k: str(v) for k, v in self.cost_by_model.items()},
                "tokens": self.tokens_by_model,
            },
            "by_type": {k: str(v) for k, v in self.cost_by_type.items()},
            "by_user": {k: str(v) for k, v in self.cost_by_user.items()},
            "by_day": {k: str(v) for k, v in self.cost_by_day.items()},
            "efficiency": {
                "avg_cost_per_request": str(self.avg_cost_per_request),
                "avg_tokens_per_request": self.avg_tokens_per_request,
                "cache_hit_rate": self.cache_hit_rate,
            },
        }


@dataclass
class Invoice:
    """Invoice for a billing period."""

    id: str = field(default_factory=lambda: f"INV-{uuid4().hex[:8].upper()}")
    tenant_id: str = ""
    period_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    period_end: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Amounts
    subtotal: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total: Decimal = Decimal("0")

    # Line items
    line_items: list[dict[str, Any]] = field(default_factory=list)

    # Status
    status: InvoiceStatus = InvoiceStatus.DRAFT
    due_date: datetime | None = None
    paid_at: datetime | None = None

    # Metadata
    currency: str = "USD"
    notes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "subtotal": str(self.subtotal),
            "discount": str(self.discount),
            "tax": str(self.tax),
            "total": str(self.total),
            "line_items": self.line_items,
            "status": self.status.value,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "currency": self.currency,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class UsageForecast:
    """Usage forecast for a tenant."""

    tenant_id: str
    forecast_date: datetime
    period_end: datetime

    # Projections
    projected_cost: Decimal = Decimal("0")
    projected_tokens: int = 0
    projected_requests: int = 0

    # Trend
    daily_avg_cost: Decimal = Decimal("0")
    daily_avg_tokens: int = 0
    growth_rate_percent: float = 0.0

    # Budget status
    budget_remaining: Decimal = Decimal("0")
    days_until_budget_exceeded: int | None = None
    will_exceed_budget: bool = False

    # Confidence
    confidence: float = 0.0
    data_points_used: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tenant_id": self.tenant_id,
            "forecast_date": self.forecast_date.isoformat(),
            "period_end": self.period_end.isoformat(),
            "projected_cost": str(self.projected_cost),
            "projected_tokens": self.projected_tokens,
            "projected_requests": self.projected_requests,
            "trend": {
                "daily_avg_cost": str(self.daily_avg_cost),
                "daily_avg_tokens": self.daily_avg_tokens,
                "growth_rate_percent": self.growth_rate_percent,
            },
            "budget": {
                "remaining": str(self.budget_remaining),
                "days_until_exceeded": self.days_until_budget_exceeded,
                "will_exceed": self.will_exceed_budget,
            },
            "confidence": self.confidence,
            "data_points_used": self.data_points_used,
        }


class EnterpriseMeter:
    """
    Enterprise-grade usage metering for ENTERPRISE tier.

    Provides granular token-level tracking, budget management,
    and invoice generation.
    """

    def __init__(self, db_path: Path | None = None):
        """
        Initialize enterprise meter.

        Args:
            db_path: Path to SQLite database
        """
        if db_path is None:
            from aragora.persistence.db_config import get_nomic_dir

            db_path = get_nomic_dir() / "enterprise_billing.db"
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._initialized = False

        # In-memory buffers
        self._usage_buffer: list[TokenUsageRecord] = []
        self._buffer_size = 50
        self._flush_task: asyncio.Task | None = None

    @property
    def _connection(self) -> sqlite3.Connection:
        return cast(sqlite3.Connection, self._conn)

    async def initialize(self) -> None:
        """Initialize database and start background tasks."""
        if self._initialized:
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        await self._init_schema()
        self._initialized = True
        logger.info("Enterprise metering initialized: %s", self.db_path)

    async def _init_schema(self) -> None:
        """Initialize database schema."""
        cursor = self._connection.cursor()

        # Token usage records
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                user_id TEXT,
                workspace_id TEXT,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                model_version TEXT,
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cached_tokens INTEGER DEFAULT 0,
                input_cost TEXT DEFAULT '0',
                output_cost TEXT DEFAULT '0',
                total_cost TEXT DEFAULT '0',
                discount_applied TEXT DEFAULT '0',
                debate_id TEXT,
                agent_id TEXT,
                request_type TEXT DEFAULT 'chat',
                endpoint TEXT,
                latency_ms INTEGER,
                success BOOLEAN DEFAULT TRUE,
                error_code TEXT,
                metadata TEXT,
                timestamp TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indexes for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_tenant_time
            ON token_usage(tenant_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_provider_model
            ON token_usage(provider, model)
        """)

        # Budget configurations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS budget_configs (
                tenant_id TEXT PRIMARY KEY,
                monthly_budget TEXT DEFAULT '0',
                daily_limit TEXT DEFAULT '0',
                alert_thresholds TEXT DEFAULT '[50, 75, 90]',
                alert_emails TEXT DEFAULT '[]',
                auto_suspend_on_exceed BOOLEAN DEFAULT FALSE,
                rollover_unused BOOLEAN DEFAULT FALSE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Budget alerts sent
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS budget_alerts (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                alert_level TEXT NOT NULL,
                threshold_percent INTEGER,
                current_spend TEXT,
                budget TEXT,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                acknowledged BOOLEAN DEFAULT FALSE
            )
        """)

        # Invoices
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                subtotal TEXT DEFAULT '0',
                discount TEXT DEFAULT '0',
                tax TEXT DEFAULT '0',
                total TEXT DEFAULT '0',
                line_items TEXT DEFAULT '[]',
                status TEXT DEFAULT 'draft',
                due_date TEXT,
                paid_at TEXT,
                currency TEXT DEFAULT 'USD',
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_invoices_tenant
            ON invoices(tenant_id, period_start)
        """)

        self._connection.commit()

    async def record_token_usage(
        self,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        tenant_id: str | None = None,
        user_id: str | None = None,
        debate_id: str | None = None,
        agent_id: str | None = None,
        request_type: str = "chat",
        cached_tokens: int = 0,
        latency_ms: int | None = None,
        success: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TokenUsageRecord:
        """
        Record token usage for billing.

        Args:
            provider: Provider name (anthropic, openai, etc.)
            model: Model name
            tokens_in: Input tokens
            tokens_out: Output tokens
            tenant_id: Tenant identifier
            user_id: User identifier
            debate_id: Associated debate
            agent_id: Agent that made the call
            request_type: Type of request
            cached_tokens: Tokens served from cache
            latency_ms: Request latency
            success: Whether request succeeded
            metadata: Additional metadata

        Returns:
            Created usage record
        """
        if not self._initialized:
            await self.initialize()

        # Calculate costs
        input_cost, output_cost = self._calculate_costs(provider, model, tokens_in, tokens_out)

        # Apply cache discount (cached tokens are free)
        discount = Decimal("0")
        if cached_tokens > 0:
            cache_ratio = min(cached_tokens / max(tokens_in, 1), 1.0)
            discount = input_cost * Decimal(str(cache_ratio)) * Decimal("0.5")

        total_cost = input_cost + output_cost - discount

        record = TokenUsageRecord(
            tenant_id=tenant_id or self._get_tenant_id() or "default",
            user_id=user_id,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            total_tokens=tokens_in + tokens_out,
            cached_tokens=cached_tokens,
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=total_cost,
            discount_applied=discount,
            debate_id=debate_id,
            agent_id=agent_id,
            request_type=request_type,
            latency_ms=latency_ms,
            success=success,
            metadata=metadata or {},
        )

        async with self._lock:
            self._usage_buffer.append(record)
            if len(self._usage_buffer) >= self._buffer_size:
                await self._flush_buffer()

        # Check budget alerts
        await self._check_budget_alerts(record.tenant_id, record.total_cost)

        return record

    def _calculate_costs(
        self,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
    ) -> tuple[Decimal, Decimal]:
        """Calculate input and output costs."""
        provider_prices = PROVIDER_PRICING.get(
            provider.lower(),
            PROVIDER_PRICING["openrouter"],
        )

        # Get input price
        input_key = model if model in provider_prices else "default"
        input_price = provider_prices.get(input_key, Decimal("2.00"))

        # Get output price
        output_key = f"{model}-output" if f"{model}-output" in provider_prices else "default-output"
        output_price = provider_prices.get(output_key, Decimal("8.00"))

        # Calculate costs (prices are per 1M tokens)
        input_cost = (Decimal(tokens_in) / Decimal("1000000")) * input_price
        output_cost = (Decimal(tokens_out) / Decimal("1000000")) * output_price

        return input_cost, output_cost

    async def _flush_buffer(self) -> None:
        """Flush usage buffer to database."""
        if not self._usage_buffer:
            return

        records = self._usage_buffer.copy()
        self._usage_buffer.clear()

        cursor = self._connection.cursor()
        for record in records:
            cursor.execute(
                """
                INSERT INTO token_usage
                (id, tenant_id, user_id, workspace_id, provider, model,
                 model_version, tokens_in, tokens_out, total_tokens,
                 cached_tokens, input_cost, output_cost, total_cost,
                 discount_applied, debate_id, agent_id, request_type,
                 endpoint, latency_ms, success, error_code, metadata, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.tenant_id,
                    record.user_id,
                    record.workspace_id,
                    record.provider,
                    record.model,
                    record.model_version,
                    record.tokens_in,
                    record.tokens_out,
                    record.total_tokens,
                    record.cached_tokens,
                    str(record.input_cost),
                    str(record.output_cost),
                    str(record.total_cost),
                    str(record.discount_applied),
                    record.debate_id,
                    record.agent_id,
                    record.request_type,
                    record.endpoint,
                    record.latency_ms,
                    record.success,
                    record.error_code,
                    json.dumps(record.metadata) if record.metadata else None,
                    record.timestamp.isoformat(),
                ),
            )
        self._connection.commit()
        logger.debug("Flushed %s token usage records", len(records))

    async def get_cost_breakdown(
        self,
        tenant_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> CostBreakdown:
        """
        Get detailed cost breakdown for a tenant.

        Args:
            tenant_id: Tenant identifier
            start_date: Start of period (default: start of month)
            end_date: End of period (default: now)

        Returns:
            CostBreakdown with detailed metrics
        """
        if not self._initialized:
            await self.initialize()

        now = datetime.now(timezone.utc)
        if not start_date:
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if not end_date:
            end_date = now

        breakdown = CostBreakdown(
            tenant_id=tenant_id,
            period_start=start_date,
            period_end=end_date,
        )

        cursor = self._connection.cursor()

        # Get totals and breakdowns
        cursor.execute(
            """
            SELECT
                COUNT(*) as total_requests,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(CAST(total_cost AS REAL)), 0) as total_cost,
                COALESCE(SUM(cached_tokens), 0) as cached_tokens
            FROM token_usage
            WHERE tenant_id = ?
              AND timestamp >= ?
              AND timestamp <= ?
            """,
            (tenant_id, start_date.isoformat(), end_date.isoformat()),
        )
        row = cursor.fetchone()
        if row:
            breakdown.total_requests = row["total_requests"]
            breakdown.total_tokens = row["total_tokens"]
            breakdown.total_cost = Decimal(str(row["total_cost"]))
            total_cached = row["cached_tokens"] or 0

            if breakdown.total_requests > 0:
                breakdown.avg_cost_per_request = breakdown.total_cost / breakdown.total_requests
                breakdown.avg_tokens_per_request = (
                    breakdown.total_tokens // breakdown.total_requests
                )
            if breakdown.total_tokens > 0:
                breakdown.cache_hit_rate = total_cached / breakdown.total_tokens

        # By provider
        cursor.execute(
            """
            SELECT
                provider,
                SUM(CAST(total_cost AS REAL)) as cost,
                SUM(total_tokens) as tokens
            FROM token_usage
            WHERE tenant_id = ?
              AND timestamp >= ?
              AND timestamp <= ?
            GROUP BY provider
            """,
            (tenant_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            breakdown.cost_by_provider[row["provider"]] = Decimal(str(row["cost"]))
            breakdown.tokens_by_provider[row["provider"]] = row["tokens"]

        # By model
        cursor.execute(
            """
            SELECT
                provider || '/' || model as model_key,
                SUM(CAST(total_cost AS REAL)) as cost,
                SUM(total_tokens) as tokens
            FROM token_usage
            WHERE tenant_id = ?
              AND timestamp >= ?
              AND timestamp <= ?
            GROUP BY provider, model
            ORDER BY cost DESC
            LIMIT 20
            """,
            (tenant_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            breakdown.cost_by_model[row["model_key"]] = Decimal(str(row["cost"]))
            breakdown.tokens_by_model[row["model_key"]] = row["tokens"]

        # By request type
        cursor.execute(
            """
            SELECT
                request_type,
                SUM(CAST(total_cost AS REAL)) as cost
            FROM token_usage
            WHERE tenant_id = ?
              AND timestamp >= ?
              AND timestamp <= ?
            GROUP BY request_type
            """,
            (tenant_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            breakdown.cost_by_type[row["request_type"]] = Decimal(str(row["cost"]))

        # By user
        cursor.execute(
            """
            SELECT
                COALESCE(user_id, 'unknown') as user_id,
                SUM(CAST(total_cost AS REAL)) as cost
            FROM token_usage
            WHERE tenant_id = ?
              AND timestamp >= ?
              AND timestamp <= ?
            GROUP BY user_id
            ORDER BY cost DESC
            LIMIT 50
            """,
            (tenant_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            breakdown.cost_by_user[row["user_id"]] = Decimal(str(row["cost"]))

        # By day
        cursor.execute(
            """
            SELECT
                DATE(timestamp) as day,
                SUM(CAST(total_cost AS REAL)) as cost
            FROM token_usage
            WHERE tenant_id = ?
              AND timestamp >= ?
              AND timestamp <= ?
            GROUP BY DATE(timestamp)
            ORDER BY day
            """,
            (tenant_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            breakdown.cost_by_day[row["day"]] = Decimal(str(row["cost"]))

        return breakdown

    async def set_budget(
        self,
        tenant_id: str,
        monthly_budget: Decimal,
        daily_limit: Decimal | None = None,
        alert_emails: list[str] | None = None,
        auto_suspend: bool = False,
    ) -> BudgetConfig:
        """
        Set budget configuration for a tenant.

        Args:
            tenant_id: Tenant identifier
            monthly_budget: Monthly budget limit
            daily_limit: Optional daily spending limit
            alert_emails: Emails for budget alerts
            auto_suspend: Whether to suspend on budget exceed

        Returns:
            Created/updated budget config
        """
        if not self._initialized:
            await self.initialize()

        config = BudgetConfig(
            tenant_id=tenant_id,
            monthly_budget=monthly_budget,
            daily_limit=daily_limit or Decimal("0"),
            alert_emails=alert_emails or [],
            auto_suspend_on_exceed=auto_suspend,
        )

        cursor = self._connection.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO budget_configs
            (tenant_id, monthly_budget, daily_limit, alert_emails,
             auto_suspend_on_exceed, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                str(monthly_budget),
                str(config.daily_limit),
                json.dumps(config.alert_emails),
                config.auto_suspend_on_exceed,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._connection.commit()

        logger.info("Set budget for tenant %s: $%s", tenant_id, monthly_budget)
        return config

    async def get_budget(self, tenant_id: str) -> BudgetConfig | None:
        """Get budget configuration for a tenant."""
        if not self._initialized:
            await self.initialize()

        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT * FROM budget_configs WHERE tenant_id = ?",
            (tenant_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return BudgetConfig(
            tenant_id=row["tenant_id"],
            monthly_budget=Decimal(row["monthly_budget"]),
            daily_limit=Decimal(row["daily_limit"]),
            alert_thresholds=json.loads(row["alert_thresholds"]),
            alert_emails=json.loads(row["alert_emails"]),
            auto_suspend_on_exceed=row["auto_suspend_on_exceed"],
            rollover_unused=row["rollover_unused"],
        )

    async def _check_budget_alerts(
        self,
        tenant_id: str,
        cost_added: Decimal,
    ) -> BudgetAlertLevel | None:
        """Check if budget alerts should be sent."""
        config = await self.get_budget(tenant_id)
        if not config or config.monthly_budget == Decimal("0"):
            return None

        # Get current month's spend
        breakdown = await self.get_cost_breakdown(tenant_id)
        current_spend = breakdown.total_cost

        # Calculate percentage
        percent = (current_spend / config.monthly_budget) * 100

        # Determine alert level
        alert_level = None
        if percent >= 100:
            alert_level = BudgetAlertLevel.EXCEEDED
        elif percent >= 90:
            alert_level = BudgetAlertLevel.CRITICAL
        elif percent >= 75:
            alert_level = BudgetAlertLevel.WARNING
        elif percent >= 50:
            alert_level = BudgetAlertLevel.INFO

        if alert_level:
            # Check if we've already sent this alert
            cursor = self._connection.cursor()
            cursor.execute(
                """
                SELECT id FROM budget_alerts
                WHERE tenant_id = ?
                  AND alert_level = ?
                  AND sent_at >= date('now', 'start of month')
                """,
                (tenant_id, alert_level.value),
            )
            if not cursor.fetchone():
                # Record alert
                cursor.execute(
                    """
                    INSERT INTO budget_alerts
                    (id, tenant_id, alert_level, threshold_percent, current_spend, budget)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        tenant_id,
                        alert_level.value,
                        int(percent),
                        str(current_spend),
                        str(config.monthly_budget),
                    ),
                )
                self._connection.commit()

                logger.warning(
                    f"Budget alert for tenant {tenant_id}: {alert_level.value} ({percent:.1f}%)"
                )

                # Send email notifications to configured alert recipients
                if config.alert_emails:
                    await self._send_budget_alert_emails(
                        tenant_id=tenant_id,
                        config=config,
                        alert_level=alert_level,
                        current_spend=current_spend,
                        percent=float(percent),
                    )

        return alert_level

    async def _send_budget_alert_emails(
        self,
        tenant_id: str,
        config: BudgetConfig,
        alert_level: BudgetAlertLevel,
        current_spend: Decimal,
        percent: float,
    ) -> None:
        """Send budget alert emails to all configured recipients."""
        try:
            from aragora.billing.notifications import get_billing_notifier

            notifier = get_billing_notifier()
            sent_count = 0
            failed_count = 0

            for email in config.alert_emails:
                result = notifier.notify_budget_alert(
                    tenant_id=tenant_id,
                    email=email,
                    alert_level=alert_level.value,
                    current_spend=f"${current_spend:.2f}",
                    budget_limit=f"${config.monthly_budget:.2f}",
                    percent_used=percent,
                )

                if result.success:
                    sent_count += 1
                else:
                    failed_count += 1
                    logger.warning("Failed to send budget alert to %s: %s", email, result.error)

            if sent_count > 0:
                logger.info("Sent %s budget alert email(s) for tenant %s", sent_count, tenant_id)
            if failed_count > 0:
                logger.warning(
                    "Failed to send %s budget alert email(s) for tenant %s", failed_count, tenant_id
                )
        except (ImportError, OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
            logger.error("Error sending budget alert emails: %s", e)

    async def forecast_usage(
        self,
        tenant_id: str,
        days_ahead: int = 30,
    ) -> UsageForecast:
        """
        Forecast future usage based on historical patterns.

        Args:
            tenant_id: Tenant identifier
            days_ahead: Days to forecast

        Returns:
            UsageForecast with projections
        """
        if not self._initialized:
            await self.initialize()

        now = datetime.now(timezone.utc)
        end_date = now + timedelta(days=days_ahead)

        # Get historical data (last 30 days)
        start_historical = now - timedelta(days=30)
        breakdown = await self.get_cost_breakdown(tenant_id, start_historical, now)

        forecast = UsageForecast(
            tenant_id=tenant_id,
            forecast_date=now,
            period_end=end_date,
            data_points_used=len(breakdown.cost_by_day),
        )

        if not breakdown.cost_by_day:
            return forecast

        # Calculate daily averages
        days_with_data = len(breakdown.cost_by_day)
        if days_with_data > 0:
            forecast.daily_avg_cost = breakdown.total_cost / days_with_data
            forecast.daily_avg_tokens = breakdown.total_tokens // days_with_data

            # Simple linear projection
            forecast.projected_cost = forecast.daily_avg_cost * days_ahead
            forecast.projected_tokens = forecast.daily_avg_tokens * days_ahead
            forecast.projected_requests = (breakdown.total_requests // days_with_data) * days_ahead

        # Calculate growth rate
        if len(breakdown.cost_by_day) >= 7:
            days = sorted(breakdown.cost_by_day.keys())
            first_week = sum(breakdown.cost_by_day[d] for d in days[:7])
            last_week = sum(breakdown.cost_by_day[d] for d in days[-7:])
            if first_week > 0:
                forecast.growth_rate_percent = float(((last_week - first_week) / first_week) * 100)

        # Check budget
        config = await self.get_budget(tenant_id)
        if config and config.monthly_budget > 0:
            forecast.budget_remaining = config.monthly_budget - breakdown.total_cost
            if forecast.daily_avg_cost > 0:
                days_until = int(forecast.budget_remaining / forecast.daily_avg_cost)
                forecast.days_until_budget_exceeded = max(0, days_until)
                forecast.will_exceed_budget = days_until < days_ahead

        # Confidence based on data points
        forecast.confidence = min(days_with_data / 30, 1.0)

        return forecast

    async def generate_invoice(
        self,
        tenant_id: str,
        period: str,  # "YYYY-MM"
        tax_rate: Decimal = Decimal("0"),
        discount_percent: Decimal = Decimal("0"),
    ) -> Invoice:
        """
        Generate an invoice for a billing period.

        Args:
            tenant_id: Tenant identifier
            period: Billing period (YYYY-MM format)
            tax_rate: Tax rate as decimal (0.1 = 10%)
            discount_percent: Discount percentage

        Returns:
            Generated invoice
        """
        if not self._initialized:
            await self.initialize()

        # Parse period
        year, month = map(int, period.split("-"))
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1) - timedelta(seconds=1)
        else:
            end_date = datetime(year, month + 1, 1) - timedelta(seconds=1)

        # Get cost breakdown
        breakdown = await self.get_cost_breakdown(tenant_id, start_date, end_date)

        # Create line items
        line_items = []

        # Add by-model line items
        for model, cost in sorted(
            breakdown.cost_by_model.items(),
            key=lambda x: x[1],
            reverse=True,
        ):
            tokens = breakdown.tokens_by_model.get(model, 0)
            line_items.append(
                {
                    "description": f"API Usage - {model}",
                    "quantity": tokens,
                    "unit": "tokens",
                    "unit_price": str((cost / Decimal(max(tokens, 1))) * Decimal("1000000")),
                    "amount": str(cost),
                }
            )

        # Calculate totals
        subtotal = breakdown.total_cost
        discount = subtotal * (discount_percent / Decimal("100"))
        taxable = subtotal - discount
        tax = taxable * tax_rate
        total = taxable + tax

        invoice = Invoice(
            tenant_id=tenant_id,
            period_start=start_date,
            period_end=end_date,
            subtotal=subtotal.quantize(Decimal("0.01"), ROUND_HALF_UP),
            discount=discount.quantize(Decimal("0.01"), ROUND_HALF_UP),
            tax=tax.quantize(Decimal("0.01"), ROUND_HALF_UP),
            total=total.quantize(Decimal("0.01"), ROUND_HALF_UP),
            line_items=line_items,
            status=InvoiceStatus.DRAFT,
            due_date=end_date + timedelta(days=30),
        )

        # Save invoice
        cursor = self._connection.cursor()
        cursor.execute(
            """
            INSERT INTO invoices
            (id, tenant_id, period_start, period_end, subtotal, discount,
             tax, total, line_items, status, due_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice.id,
                invoice.tenant_id,
                invoice.period_start.isoformat(),
                invoice.period_end.isoformat(),
                str(invoice.subtotal),
                str(invoice.discount),
                str(invoice.tax),
                str(invoice.total),
                json.dumps(invoice.line_items),
                invoice.status.value,
                invoice.due_date.isoformat() if invoice.due_date else None,
            ),
        )
        self._connection.commit()

        logger.info("Generated invoice %s for tenant %s: $%s", invoice.id, tenant_id, total)
        return invoice

    async def get_invoices(
        self,
        tenant_id: str,
        status: InvoiceStatus | None = None,
        limit: int = 20,
    ) -> list[Invoice]:
        """Get invoices for a tenant."""
        if not self._initialized:
            await self.initialize()

        cursor = self._connection.cursor()
        query = "SELECT * FROM invoices WHERE tenant_id = ?"
        params: list[Any] = [tenant_id]

        if status:
            query += " AND status = ?"
            params.append(status.value)

        query += " ORDER BY period_start DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        invoices = []
        for row in cursor:
            invoice = Invoice(
                id=row["id"],
                tenant_id=row["tenant_id"],
                period_start=datetime.fromisoformat(row["period_start"]),
                period_end=datetime.fromisoformat(row["period_end"]),
                subtotal=Decimal(row["subtotal"]),
                discount=Decimal(row["discount"]),
                tax=Decimal(row["tax"]),
                total=Decimal(row["total"]),
                line_items=json.loads(row["line_items"]),
                status=InvoiceStatus(row["status"]),
                currency=row["currency"],
                notes=row["notes"],
            )
            if row["due_date"]:
                invoice.due_date = datetime.fromisoformat(row["due_date"])
            if row["paid_at"]:
                invoice.paid_at = datetime.fromisoformat(row["paid_at"])
            invoices.append(invoice)

        return invoices

    def _get_tenant_id(self) -> str | None:
        """Get current tenant ID from context."""
        try:
            from aragora.tenancy.context import get_current_tenant_id

            return get_current_tenant_id()
        except ImportError:
            return None

    async def close(self) -> None:
        """Close resources."""
        async with self._lock:
            await self._flush_buffer()

        if self._conn:
            self._conn.close()
            self._conn = None


# Module-level instance
_enterprise_meter: EnterpriseMeter | None = None


def get_enterprise_meter() -> EnterpriseMeter:
    """Get or create the enterprise meter."""
    global _enterprise_meter
    if _enterprise_meter is None:
        _enterprise_meter = EnterpriseMeter()
    return _enterprise_meter


__all__ = [
    "EnterpriseMeter",
    "TokenUsageRecord",
    "BudgetConfig",
    "BudgetAlertLevel",
    "CostBreakdown",
    "Invoice",
    "InvoiceStatus",
    "UsageForecast",
    "get_enterprise_meter",
]
