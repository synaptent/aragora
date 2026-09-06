"""
Usage-Based Billing Metering Service for ENTERPRISE Tier.

Provides comprehensive token-level metering with:
- Per-model, per-provider cost tracking
- Debate and API call metering
- Hourly aggregation for efficient storage
- Integration with billing infrastructure

Phase 4.3 Implementation as per development roadmap.

Usage:
    from aragora.services.usage_metering import UsageMeter, get_usage_meter

    meter = get_usage_meter()

    # Record token usage
    await meter.record_token_usage(
        org_id="org_123",
        input_tokens=1000,
        output_tokens=500,
        model="claude-opus-4",
    )

    # Record debate usage
    await meter.record_debate_usage(
        org_id="org_123",
        debate_id="debate_456",
        agent_count=3,
    )

    # Get usage summary
    summary = await meter.get_usage_summary(org_id="org_123", period="month")
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from aragora.persistence.db_config import get_nomic_dir

# Re-export all models for backward compatibility
from aragora.services.metering_models import (
    ApiCallRecord,
    DebateUsageRecord,
    HourlyAggregate,
    MeteringPeriod,
    MODEL_PRICING,
    TIER_USAGE_CAPS,
    TokenUsageRecord,
    UsageBreakdown,
    UsageLimits,
    UsageSummary,
    UsageType,
)

logger = logging.getLogger(__name__)

# Default database path (respects ARAGORA_DATA_DIR)
DEFAULT_METERING_DB = get_nomic_dir() / "usage_metering.db"


class UsageMeter:
    """
    Usage metering service for ENTERPRISE tier.

    Provides comprehensive token-level tracking, hourly aggregation,
    and billing integration.
    """

    def __init__(self, db_path: Path | None = None):
        """
        Initialize usage meter.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path or DEFAULT_METERING_DB
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._initialized = False

        # In-memory buffer for batching writes
        self._token_buffer: list[TokenUsageRecord] = []
        self._debate_buffer: list[DebateUsageRecord] = []
        self._api_buffer: list[ApiCallRecord] = []
        self._buffer_size = 50

    async def initialize(self) -> None:
        """Initialize database and schema."""
        if self._initialized:
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        await self._init_schema()
        self._initialized = True
        logger.info("Usage metering initialized: %s", self.db_path)

    def _require_connection(self) -> sqlite3.Connection:
        """Return the initialized database connection."""
        if self._conn is None:
            raise RuntimeError("Usage metering database is not initialized")
        return self._conn

    async def _init_schema(self) -> None:
        """Initialize database schema."""
        connection = self._require_connection()
        cursor = connection.cursor()

        # Token usage records
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                user_id TEXT,
                model TEXT NOT NULL,
                provider TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                input_cost TEXT DEFAULT '0',
                output_cost TEXT DEFAULT '0',
                total_cost TEXT DEFAULT '0',
                debate_id TEXT,
                endpoint TEXT,
                metadata TEXT,
                timestamp TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Debate usage records
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS debate_usage (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                user_id TEXT,
                debate_id TEXT NOT NULL,
                agent_count INTEGER DEFAULT 0,
                rounds INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                total_cost TEXT DEFAULT '0',
                duration_seconds INTEGER DEFAULT 0,
                metadata TEXT,
                timestamp TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # API call records
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_usage (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                user_id TEXT,
                endpoint TEXT NOT NULL,
                method TEXT DEFAULT 'GET',
                status_code INTEGER DEFAULT 200,
                response_time_ms INTEGER DEFAULT 0,
                metadata TEXT,
                timestamp TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Hourly aggregates for efficient queries
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hourly_aggregates (
                org_id TEXT NOT NULL,
                hour TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                token_cost TEXT DEFAULT '0',
                debate_count INTEGER DEFAULT 0,
                api_call_count INTEGER DEFAULT 0,
                tokens_by_model TEXT DEFAULT '{}',
                cost_by_model TEXT DEFAULT '{}',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (org_id, hour)
            )
        """)

        # Indexes for efficient querying
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_org_time
            ON token_usage(org_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_model
            ON token_usage(provider, model)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_debate_usage_org_time
            ON debate_usage(org_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_usage_org_time
            ON api_usage(org_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_hourly_agg_org_hour
            ON hourly_aggregates(org_id, hour)
        """)

        connection.commit()

    def _calculate_token_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate input and output costs for token usage.

        Args:
            provider: Provider name (anthropic, openai, etc.)
            model: Model name
            input_tokens: Input token count
            output_tokens: Output token count

        Returns:
            Tuple of (input_cost, output_cost)

        Delegates to ``aragora.billing.usage.calculate_token_cost`` so there
        is ONE pricing implementation in the repo (2026-09-05 wave-2
        re-review). This method used to be a second, independent one: a flat
        lookup in ``MODEL_PRICING`` keyed on the caller's provider LABEL,
        which meant the path that actually bills tenants could not price a
        documented long-context tier at all, and quoted the $2/$8 default for
        any label that did not match the model's own bucket even when the
        model had a real, reachable rate.

        The split into a pair is preserved by costing the input half on its
        own and taking the output half by subtraction, so the two always sum
        to the canonical total and the input half carries any tier.
        """
        from aragora.billing.usage import calculate_token_cost

        provider_lower = provider.lower()
        input_cost = calculate_token_cost(
            provider_lower, model, input_tokens, 0, extra_prices=MODEL_PRICING
        )
        total_cost = calculate_token_cost(
            provider_lower, model, input_tokens, output_tokens, extra_prices=MODEL_PRICING
        )
        return input_cost, total_cost - input_cost

    async def record_token_usage(
        self,
        org_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str,
        provider: str = "openrouter",
        user_id: str | None = None,
        debate_id: str | None = None,
        endpoint: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TokenUsageRecord:
        """
        Record token usage for billing.

        Args:
            org_id: Organization identifier
            input_tokens: Input token count
            output_tokens: Output token count
            model: Model name
            provider: Provider name
            user_id: Optional user identifier
            debate_id: Optional debate identifier
            endpoint: Optional endpoint that generated the usage
            metadata: Additional metadata

        Returns:
            Created token usage record
        """
        if not self._initialized:
            await self.initialize()

        # Calculate costs
        input_cost, output_cost = self._calculate_token_cost(
            provider, model, input_tokens, output_tokens
        )
        total_cost = input_cost + output_cost

        record = TokenUsageRecord(
            org_id=org_id,
            user_id=user_id,
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=total_cost,
            debate_id=debate_id,
            endpoint=endpoint,
            metadata=metadata or {},
        )

        async with self._lock:
            self._token_buffer.append(record)
            if len(self._token_buffer) >= self._buffer_size:
                await self._flush_token_buffer()

        # Update hourly aggregate
        await self._update_hourly_aggregate(
            org_id=org_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            token_cost=total_cost,
            model=f"{provider}/{model}",
        )

        logger.debug(
            f"Token usage recorded: org={org_id} model={model} "
            f"tokens={input_tokens + output_tokens} cost=${total_cost:.4f}"
        )

        return record

    async def record_debate_usage(
        self,
        org_id: str,
        debate_id: str,
        agent_count: int,
        rounds: int = 0,
        total_tokens: int = 0,
        total_cost: Decimal | None = None,
        duration_seconds: int = 0,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DebateUsageRecord:
        """
        Record debate usage for billing.

        Args:
            org_id: Organization identifier
            debate_id: Debate identifier
            agent_count: Number of agents in debate
            rounds: Number of debate rounds
            total_tokens: Total tokens used in debate
            total_cost: Total cost (calculated if not provided)
            duration_seconds: Debate duration
            user_id: Optional user identifier
            metadata: Additional metadata

        Returns:
            Created debate usage record
        """
        if not self._initialized:
            await self.initialize()

        # Calculate cost if not provided
        if total_cost is None:
            # Estimate cost based on tokens
            _, output_cost = self._calculate_token_cost(
                "openrouter", "default", total_tokens // 2, total_tokens // 2
            )
            total_cost = output_cost * 2

        record = DebateUsageRecord(
            org_id=org_id,
            user_id=user_id,
            debate_id=debate_id,
            agent_count=agent_count,
            rounds=rounds,
            total_tokens=total_tokens,
            total_cost=total_cost,
            duration_seconds=duration_seconds,
            metadata=metadata or {},
        )

        async with self._lock:
            self._debate_buffer.append(record)
            if len(self._debate_buffer) >= self._buffer_size:
                await self._flush_debate_buffer()

        # Update hourly aggregate
        await self._update_hourly_aggregate(
            org_id=org_id,
            debate_count=1,
        )

        logger.debug(
            f"Debate usage recorded: org={org_id} debate={debate_id} "
            f"agents={agent_count} cost=${total_cost:.4f}"
        )

        return record

    async def record_api_call(
        self,
        org_id: str,
        endpoint: str,
        method: str = "GET",
        status_code: int = 200,
        response_time_ms: int = 0,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApiCallRecord:
        """
        Record API call for metering.

        Args:
            org_id: Organization identifier
            endpoint: API endpoint called
            method: HTTP method
            status_code: Response status code
            response_time_ms: Response time in milliseconds
            user_id: Optional user identifier
            metadata: Additional metadata

        Returns:
            Created API call record
        """
        if not self._initialized:
            await self.initialize()

        record = ApiCallRecord(
            org_id=org_id,
            user_id=user_id,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            response_time_ms=response_time_ms,
            metadata=metadata or {},
        )

        async with self._lock:
            self._api_buffer.append(record)
            if len(self._api_buffer) >= self._buffer_size:
                await self._flush_api_buffer()

        # Update hourly aggregate
        await self._update_hourly_aggregate(
            org_id=org_id,
            api_call_count=1,
        )

        return record

    async def _update_hourly_aggregate(
        self,
        org_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        token_cost: Decimal = Decimal("0"),
        model: str = "",
        debate_count: int = 0,
        api_call_count: int = 0,
    ) -> None:
        """Update hourly aggregate with new usage."""
        connection = self._require_connection()
        now = datetime.now(timezone.utc)
        hour = now.replace(minute=0, second=0, microsecond=0)
        hour_str = hour.isoformat()

        cursor = connection.cursor()

        # Get existing aggregate
        cursor.execute(
            """
            SELECT * FROM hourly_aggregates
            WHERE org_id = ? AND hour = ?
            """,
            (org_id, hour_str),
        )
        row = cursor.fetchone()

        if row:
            # Update existing aggregate
            tokens_by_model = json.loads(row["tokens_by_model"] or "{}")
            cost_by_model = json.loads(row["cost_by_model"] or "{}")

            if model:
                tokens_by_model[model] = (
                    tokens_by_model.get(model, 0) + input_tokens + output_tokens
                )
                cost_by_model[model] = str(Decimal(cost_by_model.get(model, "0")) + token_cost)

            cursor.execute(
                """
                UPDATE hourly_aggregates
                SET input_tokens = input_tokens + ?,
                    output_tokens = output_tokens + ?,
                    total_tokens = total_tokens + ?,
                    token_cost = CAST((CAST(token_cost AS REAL) + ?) AS TEXT),
                    debate_count = debate_count + ?,
                    api_call_count = api_call_count + ?,
                    tokens_by_model = ?,
                    cost_by_model = ?,
                    updated_at = ?
                WHERE org_id = ? AND hour = ?
                """,
                (
                    input_tokens,
                    output_tokens,
                    input_tokens + output_tokens,
                    float(token_cost),
                    debate_count,
                    api_call_count,
                    json.dumps(tokens_by_model),
                    json.dumps(cost_by_model),
                    now.isoformat(),
                    org_id,
                    hour_str,
                ),
            )
        else:
            # Create new aggregate
            tokens_by_model = {}
            cost_by_model = {}
            if model:
                tokens_by_model[model] = input_tokens + output_tokens
                cost_by_model[model] = str(token_cost)

            cursor.execute(
                """
                INSERT INTO hourly_aggregates
                (org_id, hour, input_tokens, output_tokens, total_tokens,
                 token_cost, debate_count, api_call_count,
                 tokens_by_model, cost_by_model, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    org_id,
                    hour_str,
                    input_tokens,
                    output_tokens,
                    input_tokens + output_tokens,
                    str(token_cost),
                    debate_count,
                    api_call_count,
                    json.dumps(tokens_by_model),
                    json.dumps(cost_by_model),
                    now.isoformat(),
                ),
            )

        connection.commit()

    async def _flush_token_buffer(self) -> None:
        """Flush token usage buffer to database."""
        if not self._token_buffer:
            return

        records = self._token_buffer.copy()
        self._token_buffer.clear()

        connection = self._require_connection()
        cursor = connection.cursor()
        for record in records:
            cursor.execute(
                """
                INSERT INTO token_usage
                (id, org_id, user_id, model, provider, input_tokens, output_tokens,
                 total_tokens, input_cost, output_cost, total_cost,
                 debate_id, endpoint, metadata, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.org_id,
                    record.user_id,
                    record.model,
                    record.provider,
                    record.input_tokens,
                    record.output_tokens,
                    record.total_tokens,
                    str(record.input_cost),
                    str(record.output_cost),
                    str(record.total_cost),
                    record.debate_id,
                    record.endpoint,
                    json.dumps(record.metadata) if record.metadata else None,
                    record.timestamp.isoformat(),
                ),
            )
        connection.commit()
        logger.debug("Flushed %s token usage records", len(records))

    async def _flush_debate_buffer(self) -> None:
        """Flush debate usage buffer to database."""
        if not self._debate_buffer:
            return

        records = self._debate_buffer.copy()
        self._debate_buffer.clear()

        connection = self._require_connection()
        cursor = connection.cursor()
        for record in records:
            cursor.execute(
                """
                INSERT INTO debate_usage
                (id, org_id, user_id, debate_id, agent_count, rounds,
                 total_tokens, total_cost, duration_seconds, metadata, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.org_id,
                    record.user_id,
                    record.debate_id,
                    record.agent_count,
                    record.rounds,
                    record.total_tokens,
                    str(record.total_cost),
                    record.duration_seconds,
                    json.dumps(record.metadata) if record.metadata else None,
                    record.timestamp.isoformat(),
                ),
            )
        connection.commit()
        logger.debug("Flushed %s debate usage records", len(records))

    async def _flush_api_buffer(self) -> None:
        """Flush API call buffer to database."""
        if not self._api_buffer:
            return

        records = self._api_buffer.copy()
        self._api_buffer.clear()

        connection = self._require_connection()
        cursor = connection.cursor()
        for record in records:
            cursor.execute(
                """
                INSERT INTO api_usage
                (id, org_id, user_id, endpoint, method, status_code,
                 response_time_ms, metadata, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.org_id,
                    record.user_id,
                    record.endpoint,
                    record.method,
                    record.status_code,
                    record.response_time_ms,
                    json.dumps(record.metadata) if record.metadata else None,
                    record.timestamp.isoformat(),
                ),
            )
        connection.commit()
        logger.debug("Flushed %s API call records", len(records))

    async def flush_all(self) -> None:
        """Flush all buffers to database."""
        async with self._lock:
            await self._flush_token_buffer()
            await self._flush_debate_buffer()
            await self._flush_api_buffer()

    def _get_period_dates(
        self,
        period: str,
        reference_date: datetime | None = None,
    ) -> tuple[datetime, datetime]:
        """
        Get start and end dates for a period.

        Args:
            period: Period type (hour, day, week, month, quarter, year)
            reference_date: Reference date (default: now)

        Returns:
            Tuple of (start_date, end_date)
        """
        if reference_date is None:
            reference_date = datetime.now(timezone.utc)

        if period == "hour":
            start = reference_date.replace(minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=1)
        elif period == "day":
            start = reference_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif period == "week":
            start = reference_date - timedelta(days=reference_date.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(weeks=1)
        elif period == "month":
            start = reference_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # Get first day of next month
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
        elif period == "quarter":
            quarter_month = ((reference_date.month - 1) // 3) * 3 + 1
            start = reference_date.replace(
                month=quarter_month, day=1, hour=0, minute=0, second=0, microsecond=0
            )
            if quarter_month + 3 > 12:
                end = start.replace(year=start.year + 1, month=(quarter_month + 3) % 12 or 12)
            else:
                end = start.replace(month=quarter_month + 3)
        elif period == "year":
            start = reference_date.replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )
            end = start.replace(year=start.year + 1)
        else:
            # Default to month
            start = reference_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)

        return start, end

    async def get_usage_summary(
        self,
        org_id: str,
        period: str = "month",
        tier: str = "enterprise",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> UsageSummary:
        """
        Get usage summary for a billing period.

        Args:
            org_id: Organization identifier
            period: Period type (hour, day, week, month, quarter, year)
            tier: Subscription tier for limits
            start_date: Optional explicit start date
            end_date: Optional explicit end date

        Returns:
            Usage summary with costs and limits
        """
        if not self._initialized:
            await self.initialize()
        connection = self._require_connection()

        # Get period dates
        if start_date is None or end_date is None:
            start_date, end_date = self._get_period_dates(period)

        summary = UsageSummary(
            org_id=org_id,
            period_start=start_date,
            period_end=end_date,
            period_type=(
                MeteringPeriod(period)
                if period in [p.value for p in MeteringPeriod]
                else MeteringPeriod.MONTH
            ),
        )

        cursor = connection.cursor()

        # Query hourly aggregates for the period
        cursor.execute(
            """
            SELECT
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(total_tokens) as total_tokens,
                SUM(CAST(token_cost AS REAL)) as token_cost,
                SUM(debate_count) as debate_count,
                SUM(api_call_count) as api_call_count
            FROM hourly_aggregates
            WHERE org_id = ?
              AND hour >= ?
              AND hour < ?
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        row = cursor.fetchone()

        if row:
            summary.input_tokens = row["input_tokens"] or 0
            summary.output_tokens = row["output_tokens"] or 0
            summary.total_tokens = row["total_tokens"] or 0
            summary.token_cost = Decimal(str(row["token_cost"] or 0))
            summary.debate_count = row["debate_count"] or 0
            summary.api_call_count = row["api_call_count"] or 0

        # Get breakdown by model
        cursor.execute(
            """
            SELECT provider || '/' || model as model_key,
                   SUM(total_tokens) as tokens,
                   SUM(CAST(total_cost AS REAL)) as cost
            FROM token_usage
            WHERE org_id = ?
              AND timestamp >= ?
              AND timestamp < ?
            GROUP BY provider, model
            ORDER BY cost DESC
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            summary.tokens_by_model[row["model_key"]] = row["tokens"] or 0
            summary.cost_by_model[row["model_key"]] = Decimal(str(row["cost"] or 0))

        # Get breakdown by provider
        cursor.execute(
            """
            SELECT provider,
                   SUM(total_tokens) as tokens,
                   SUM(CAST(total_cost AS REAL)) as cost
            FROM token_usage
            WHERE org_id = ?
              AND timestamp >= ?
              AND timestamp < ?
            GROUP BY provider
            ORDER BY cost DESC
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            summary.tokens_by_provider[row["provider"]] = row["tokens"] or 0
            summary.cost_by_provider[row["provider"]] = Decimal(str(row["cost"] or 0))

        # Get breakdown by day
        cursor.execute(
            """
            SELECT DATE(hour) as day,
                   SUM(CAST(token_cost AS REAL)) as cost
            FROM hourly_aggregates
            WHERE org_id = ?
              AND hour >= ?
              AND hour < ?
            GROUP BY DATE(hour)
            ORDER BY day
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            summary.cost_by_day[row["day"]] = Decimal(str(row["cost"] or 0))

        # Set limits based on tier
        caps = TIER_USAGE_CAPS.get(tier, TIER_USAGE_CAPS["enterprise"])
        summary.token_limit = caps["max_tokens"]
        summary.debate_limit = caps["max_debates"]
        summary.api_call_limit = caps["max_api_calls"]

        # Calculate usage percentages
        if summary.token_limit > 0:
            summary.token_usage_percent = (summary.total_tokens / summary.token_limit) * 100
        if summary.debate_limit > 0:
            summary.debate_usage_percent = (summary.debate_count / summary.debate_limit) * 100
        if summary.api_call_limit > 0:
            summary.api_call_usage_percent = (summary.api_call_count / summary.api_call_limit) * 100

        return summary

    async def get_usage_breakdown(
        self,
        org_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> UsageBreakdown:
        """
        Get detailed usage breakdown for billing.

        Args:
            org_id: Organization identifier
            start_date: Start of period
            end_date: End of period

        Returns:
            Detailed usage breakdown
        """
        if not self._initialized:
            await self.initialize()
        connection = self._require_connection()

        if start_date is None or end_date is None:
            start_date, end_date = self._get_period_dates("month")

        breakdown = UsageBreakdown(
            org_id=org_id,
            period_start=start_date,
            period_end=end_date,
        )

        cursor = connection.cursor()

        # Get totals
        cursor.execute(
            """
            SELECT
                SUM(CAST(token_cost AS REAL)) as total_cost,
                SUM(total_tokens) as total_tokens
            FROM hourly_aggregates
            WHERE org_id = ?
              AND hour >= ?
              AND hour < ?
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        row = cursor.fetchone()
        if row:
            breakdown.total_cost = Decimal(str(row["total_cost"] or 0))
            breakdown.total_tokens = row["total_tokens"] or 0

        cursor.execute(
            """
            SELECT COUNT(*) as count FROM debate_usage
            WHERE org_id = ? AND timestamp >= ? AND timestamp < ?
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        row = cursor.fetchone()
        breakdown.total_debates = row["count"] if row else 0

        cursor.execute(
            """
            SELECT COUNT(*) as count FROM api_usage
            WHERE org_id = ? AND timestamp >= ? AND timestamp < ?
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        row = cursor.fetchone()
        breakdown.total_api_calls = row["count"] if row else 0

        # By model
        cursor.execute(
            """
            SELECT provider || '/' || model as model_key,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(total_tokens) as total_tokens,
                   SUM(CAST(total_cost AS REAL)) as cost,
                   COUNT(*) as requests
            FROM token_usage
            WHERE org_id = ? AND timestamp >= ? AND timestamp < ?
            GROUP BY provider, model
            ORDER BY cost DESC
            LIMIT 20
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            breakdown.by_model.append(
                {
                    "model": row["model_key"],
                    "input_tokens": row["input_tokens"] or 0,
                    "output_tokens": row["output_tokens"] or 0,
                    "total_tokens": row["total_tokens"] or 0,
                    "cost": str(Decimal(str(row["cost"] or 0)).quantize(Decimal("0.0001"))),
                    "requests": row["requests"] or 0,
                }
            )

        # By provider
        cursor.execute(
            """
            SELECT provider,
                   SUM(total_tokens) as total_tokens,
                   SUM(CAST(total_cost AS REAL)) as cost,
                   COUNT(*) as requests
            FROM token_usage
            WHERE org_id = ? AND timestamp >= ? AND timestamp < ?
            GROUP BY provider
            ORDER BY cost DESC
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            breakdown.by_provider.append(
                {
                    "provider": row["provider"],
                    "total_tokens": row["total_tokens"] or 0,
                    "cost": str(Decimal(str(row["cost"] or 0)).quantize(Decimal("0.0001"))),
                    "requests": row["requests"] or 0,
                }
            )

        # By day
        cursor.execute(
            """
            SELECT DATE(hour) as day,
                   SUM(total_tokens) as total_tokens,
                   SUM(CAST(token_cost AS REAL)) as cost,
                   SUM(debate_count) as debates,
                   SUM(api_call_count) as api_calls
            FROM hourly_aggregates
            WHERE org_id = ? AND hour >= ? AND hour < ?
            GROUP BY DATE(hour)
            ORDER BY day
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            breakdown.by_day.append(
                {
                    "day": row["day"],
                    "total_tokens": row["total_tokens"] or 0,
                    "cost": str(Decimal(str(row["cost"] or 0)).quantize(Decimal("0.0001"))),
                    "debates": row["debates"] or 0,
                    "api_calls": row["api_calls"] or 0,
                }
            )

        # By user
        cursor.execute(
            """
            SELECT COALESCE(user_id, 'unknown') as user_id,
                   SUM(total_tokens) as total_tokens,
                   SUM(CAST(total_cost AS REAL)) as cost,
                   COUNT(*) as requests
            FROM token_usage
            WHERE org_id = ? AND timestamp >= ? AND timestamp < ?
            GROUP BY user_id
            ORDER BY cost DESC
            LIMIT 50
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        for row in cursor:
            breakdown.by_user.append(
                {
                    "user_id": row["user_id"],
                    "total_tokens": row["total_tokens"] or 0,
                    "cost": str(Decimal(str(row["cost"] or 0)).quantize(Decimal("0.0001"))),
                    "requests": row["requests"] or 0,
                }
            )

        return breakdown

    async def get_usage_limits(
        self,
        org_id: str,
        tier: str = "enterprise",
    ) -> UsageLimits:
        """
        Get current usage limits and utilization.

        Args:
            org_id: Organization identifier
            tier: Subscription tier

        Returns:
            Current limits and usage percentages
        """
        if not self._initialized:
            await self.initialize()
        connection = self._require_connection()

        # Get current month's usage
        start_date, end_date = self._get_period_dates("month")

        limits = UsageLimits(
            org_id=org_id,
            tier=tier,
        )

        # Set limits based on tier
        caps = TIER_USAGE_CAPS.get(tier, TIER_USAGE_CAPS["enterprise"])
        limits.max_tokens = caps["max_tokens"]
        limits.max_debates = caps["max_debates"]
        limits.max_api_calls = caps["max_api_calls"]

        # Get current usage from aggregates
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                SUM(total_tokens) as tokens,
                SUM(debate_count) as debates,
                SUM(api_call_count) as api_calls
            FROM hourly_aggregates
            WHERE org_id = ?
              AND hour >= ?
              AND hour < ?
            """,
            (org_id, start_date.isoformat(), end_date.isoformat()),
        )
        row = cursor.fetchone()

        if row:
            limits.tokens_used = row["tokens"] or 0
            limits.debates_used = row["debates"] or 0
            limits.api_calls_used = row["api_calls"] or 0

        # Calculate percentages
        if limits.max_tokens > 0:
            limits.tokens_percent = (limits.tokens_used / limits.max_tokens) * 100
            limits.tokens_exceeded = limits.tokens_used >= limits.max_tokens
        if limits.max_debates > 0:
            limits.debates_percent = (limits.debates_used / limits.max_debates) * 100
            limits.debates_exceeded = limits.debates_used >= limits.max_debates
        if limits.max_api_calls > 0:
            limits.api_calls_percent = (limits.api_calls_used / limits.max_api_calls) * 100
            limits.api_calls_exceeded = limits.api_calls_used >= limits.max_api_calls

        return limits

    async def close(self) -> None:
        """Close resources and flush buffers."""
        await self.flush_all()
        if self._conn:
            self._conn.close()
            self._conn = None


# Module-level instance
_usage_meter: UsageMeter | None = None


def get_usage_meter() -> UsageMeter:
    """Get or create the global usage meter."""
    global _usage_meter
    if _usage_meter is None:
        _usage_meter = UsageMeter()
    return _usage_meter


__all__ = [
    "UsageMeter",
    "UsageSummary",
    "UsageBreakdown",
    "UsageLimits",
    "TokenUsageRecord",
    "DebateUsageRecord",
    "ApiCallRecord",
    "HourlyAggregate",
    "MeteringPeriod",
    "UsageType",
    "MODEL_PRICING",
    "TIER_USAGE_CAPS",
    "get_usage_meter",
]
