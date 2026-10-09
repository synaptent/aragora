"""
Usage metering system with tenant integration.

Provides tenant-aware usage metering that integrates with quotas
and billing for enterprise deployments.

Usage:
    from aragora.billing import UsageMeter

    meter = UsageMeter()
    await meter.record_usage("api_calls", 1)

    # Get tenant billing events
    events = await meter.get_billing_events(start_date, end_date)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aragora.persistence.db_config import get_default_data_dir

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default database path for billing events
DEFAULT_BILLING_DB_PATH = get_default_data_dir() / "billing_events.db"


class BillingEventType(Enum):
    """Types of billing events."""

    API_CALL = "api_call"
    DEBATE = "debate"
    TOKENS = "tokens"
    STORAGE = "storage"
    CONNECTOR_SYNC = "connector_sync"
    KNOWLEDGE_QUERY = "knowledge_query"
    AGENT_CALL = "agent_call"
    EXPORT = "export"
    SSO_AUTH = "sso_auth"


class BillingPeriod(Enum):
    """Billing period types."""

    HOURLY = "hourly"
    DAILY = "daily"
    MONTHLY = "monthly"


@dataclass
class BillingEvent:
    """A billable event for a tenant."""

    id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = ""
    user_id: str | None = None
    event_type: BillingEventType = BillingEventType.API_CALL
    resource: str = ""

    # Quantities
    quantity: int = 1
    tokens_in: int = 0
    tokens_out: int = 0
    bytes_used: int = 0

    # Cost
    unit_cost: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    currency: str = "USD"

    # Context
    debate_id: str | None = None
    connector_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Timestamps
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    billing_period: str | None = None

    def calculate_cost(self) -> Decimal:
        """Calculate total cost from unit cost and quantity."""
        self.total_cost = self.unit_cost * Decimal(self.quantity)
        return self.total_cost

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "event_type": self.event_type.value,
            "resource": self.resource,
            "quantity": self.quantity,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "bytes_used": self.bytes_used,
            "unit_cost": str(self.unit_cost),
            "total_cost": str(self.total_cost),
            "currency": self.currency,
            "debate_id": self.debate_id,
            "connector_id": self.connector_id,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "billing_period": self.billing_period,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BillingEvent:
        """Create from dictionary."""
        event = cls(
            id=data.get("id", str(uuid4())),
            tenant_id=data.get("tenant_id", ""),
            user_id=data.get("user_id"),
            event_type=BillingEventType(data.get("event_type", "api_call")),
            resource=data.get("resource", ""),
            quantity=data.get("quantity", 1),
            tokens_in=data.get("tokens_in", 0),
            tokens_out=data.get("tokens_out", 0),
            bytes_used=data.get("bytes_used", 0),
            unit_cost=Decimal(data.get("unit_cost", "0")),
            total_cost=Decimal(data.get("total_cost", "0")),
            currency=data.get("currency", "USD"),
            debate_id=data.get("debate_id"),
            connector_id=data.get("connector_id"),
            metadata=data.get("metadata", {}),
            billing_period=data.get("billing_period"),
        )
        if "timestamp" in data and data["timestamp"]:
            if isinstance(data["timestamp"], str):
                event.timestamp = datetime.fromisoformat(data["timestamp"])
            else:
                event.timestamp = data["timestamp"]
        return event


@dataclass
class UsageSummary:
    """Summary of usage for billing."""

    tenant_id: str
    period_start: datetime
    period_end: datetime
    period_type: BillingPeriod = BillingPeriod.MONTHLY

    # Counts
    total_events: int = 0
    api_calls: int = 0
    debates: int = 0
    connector_syncs: int = 0
    knowledge_queries: int = 0

    # Tokens
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0

    # Storage
    storage_bytes: int = 0
    knowledge_bytes: int = 0

    # Costs
    total_cost: Decimal = Decimal("0")
    cost_by_type: dict[str, Decimal] = field(default_factory=dict)
    cost_by_day: dict[str, Decimal] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tenant_id": self.tenant_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period_type": self.period_type.value,
            "total_events": self.total_events,
            "api_calls": self.api_calls,
            "debates": self.debates,
            "connector_syncs": self.connector_syncs,
            "knowledge_queries": self.knowledge_queries,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "total_tokens": self.total_tokens,
            "storage_bytes": self.storage_bytes,
            "knowledge_bytes": self.knowledge_bytes,
            "total_cost": str(self.total_cost),
            "cost_by_type": {k: str(v) for k, v in self.cost_by_type.items()},
            "cost_by_day": {k: str(v) for k, v in self.cost_by_day.items()},
        }


@dataclass
class MeteringConfig:
    """Configuration for usage metering."""

    # Event buffering
    buffer_size: int = 100
    """Number of events to buffer before flushing."""

    flush_interval: float = 30.0
    """Seconds between automatic flushes."""

    # Persistence
    db_path: Path = field(default_factory=lambda: DEFAULT_BILLING_DB_PATH)
    """Path to SQLite database for billing events."""

    persist_events: bool = True
    """Whether to persist events to database (set False for testing)."""

    # Pricing (per unit)
    api_call_price: Decimal = Decimal("0.0001")
    """Price per API call."""

    debate_base_price: Decimal = Decimal("0.01")
    """Base price per debate."""

    token_price_per_1k: Decimal = Decimal("0.002")
    """Price per 1000 tokens."""

    storage_price_per_gb_month: Decimal = Decimal("0.10")
    """Price per GB per month storage."""

    connector_sync_price: Decimal = Decimal("0.005")
    """Price per connector sync operation."""

    knowledge_query_price: Decimal = Decimal("0.001")
    """Price per knowledge query."""

    # Tracking
    track_free_tier: bool = False
    """Whether to track events for free tier tenants."""

    detailed_logging: bool = True
    """Enable detailed event logging."""


class UsageMeter:
    """
    Tenant-aware usage metering system.

    Tracks billable events, integrates with tenant quotas,
    and provides billing summaries. Events are persisted to SQLite
    for durable billing data.
    """

    def __init__(self, config: MeteringConfig | None = None):
        """Initialize usage meter."""
        self.config = config or MeteringConfig()
        self._events: list[BillingEvent] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._running = False
        self._db_initialized = False

    def _ensure_db(self) -> None:
        """Ensure database and tables exist."""
        if self._db_initialized or not self.config.persist_events:
            return

        # Ensure directory exists
        self.config.db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(str(self.config.db_path), timeout=30.0) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS billing_events (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT,
                    event_type TEXT NOT NULL,
                    resource TEXT,
                    quantity INTEGER DEFAULT 1,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    bytes_used INTEGER DEFAULT 0,
                    unit_cost TEXT DEFAULT '0',
                    total_cost TEXT DEFAULT '0',
                    currency TEXT DEFAULT 'USD',
                    debate_id TEXT,
                    connector_id TEXT,
                    metadata TEXT,
                    timestamp TEXT NOT NULL,
                    billing_period TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Create indexes for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_billing_tenant_period
                ON billing_events(tenant_id, billing_period)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_billing_timestamp
                ON billing_events(timestamp)
            """)
            conn.commit()

        self._db_initialized = True
        logger.debug("Billing database initialized at %s", self.config.db_path)

    def _persist_events(self, events: list[BillingEvent]) -> None:
        """Persist events to database."""
        if not self.config.persist_events or not events:
            return

        self._ensure_db()

        with sqlite3.connect(str(self.config.db_path), timeout=30.0) as conn:
            for event in events:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO billing_events
                    (id, tenant_id, user_id, event_type, resource,
                     quantity, tokens_in, tokens_out, bytes_used,
                     unit_cost, total_cost, currency,
                     debate_id, connector_id, metadata,
                     timestamp, billing_period)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        event.id,
                        event.tenant_id,
                        event.user_id,
                        event.event_type.value,
                        event.resource,
                        event.quantity,
                        event.tokens_in,
                        event.tokens_out,
                        event.bytes_used,
                        str(event.unit_cost),
                        str(event.total_cost),
                        event.currency,
                        event.debate_id,
                        event.connector_id,
                        json.dumps(event.metadata) if event.metadata else None,
                        event.timestamp.isoformat(),
                        event.billing_period,
                    ),
                )
            conn.commit()

        logger.debug("Persisted %s billing events to database", len(events))

    def _query_events(
        self,
        start_date: datetime,
        end_date: datetime,
        tenant_id: str,
        event_type: BillingEventType | None = None,
    ) -> list[BillingEvent]:
        """Query events from database."""
        if not self.config.persist_events:
            return []

        self._ensure_db()

        query = """
            SELECT id, tenant_id, user_id, event_type, resource,
                   quantity, tokens_in, tokens_out, bytes_used,
                   unit_cost, total_cost, currency,
                   debate_id, connector_id, metadata,
                   timestamp, billing_period
            FROM billing_events
            WHERE tenant_id = ?
              AND timestamp >= ?
              AND timestamp <= ?
        """
        params: list[Any] = [tenant_id, start_date.isoformat(), end_date.isoformat()]

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type.value)

        query += " ORDER BY timestamp DESC"

        events = []
        with sqlite3.connect(str(self.config.db_path), timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            for row in cursor:
                event = BillingEvent(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    user_id=row["user_id"],
                    event_type=BillingEventType(row["event_type"]),
                    resource=row["resource"] or "",
                    quantity=row["quantity"],
                    tokens_in=row["tokens_in"],
                    tokens_out=row["tokens_out"],
                    bytes_used=row["bytes_used"],
                    unit_cost=Decimal(row["unit_cost"]),
                    total_cost=Decimal(row["total_cost"]),
                    currency=row["currency"],
                    debate_id=row["debate_id"],
                    connector_id=row["connector_id"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    billing_period=row["billing_period"],
                )
                if row["timestamp"]:
                    event.timestamp = datetime.fromisoformat(row["timestamp"])
                events.append(event)

        return events

    async def start(self) -> None:
        """Start the metering system."""
        if self._running:
            return
        self._ensure_db()
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        self._flush_task.add_done_callback(
            lambda t: logger.error("Usage metering flush loop crashed: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )
        logger.info("Usage metering started")

    async def stop(self) -> None:
        """Stop the metering system and flush remaining events."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                logger.debug("Flush task cancelled during stop")
        await self._flush_events()
        logger.info("Usage metering stopped")

    async def _flush_loop(self) -> None:
        """Background task to periodically flush events."""
        while self._running:
            try:
                await asyncio.sleep(self.config.flush_interval)
                await self._flush_events()
            except asyncio.CancelledError:
                break
            except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError) as e:
                logger.error("Error in flush loop: %s", e)

    async def _flush_events(self) -> None:
        """Flush buffered events to persistent storage."""
        async with self._lock:
            if not self._events:
                return

            events_to_flush = self._events.copy()
            self._events.clear()

        # Persist events to database
        logger.debug("Flushing %s billing events", len(events_to_flush))
        try:
            self._persist_events(events_to_flush)
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError) as e:
            logger.error("Failed to persist billing events: %s", e)
            # Re-add events to buffer on failure so they aren't lost
            async with self._lock:
                self._events = events_to_flush + self._events
            raise

        # Log events for monitoring
        for event in events_to_flush:
            if self.config.detailed_logging:
                logger.info(
                    "billing_event tenant=%s type=%s quantity=%s cost=$%.4f",
                    event.tenant_id,
                    event.event_type.value,
                    event.quantity,
                    event.total_cost,
                )

    def _get_tenant_id(self) -> str | None:
        """Get current tenant ID from context."""
        try:
            from aragora.tenancy.context import get_current_tenant_id

            return get_current_tenant_id()
        except ImportError:
            logger.debug("Tenancy module not available; skipping tenant ID lookup")
            return None

    def _get_billing_period(self, dt: datetime) -> str:
        """Get billing period string for a datetime."""
        return dt.strftime("%Y-%m")

    async def record_event(self, event: BillingEvent) -> None:
        """
        Record a billing event.

        Args:
            event: Billing event to record
        """
        # Set tenant if not provided
        if not event.tenant_id:
            tenant_id = self._get_tenant_id()
            if tenant_id:
                event.tenant_id = tenant_id

        # Skip if no tenant and we're not tracking anonymous
        if not event.tenant_id:
            return

        # Set billing period
        if not event.billing_period:
            event.billing_period = self._get_billing_period(event.timestamp)

        # Calculate cost if not set
        if event.total_cost == Decimal("0"):
            event.calculate_cost()

        async with self._lock:
            self._events.append(event)
            if len(self._events) >= self.config.buffer_size:
                # Trigger flush in background
                task = asyncio.create_task(self._flush_events())
                task.add_done_callback(
                    lambda t: logger.error(
                        "Billing event flush failed: %s — events may be lost",
                        t.exception(),
                    )
                    if not t.cancelled() and t.exception()
                    else None
                )

    async def record_api_call(
        self,
        resource: str = "api",
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BillingEvent:
        """Record an API call event."""
        event = BillingEvent(
            event_type=BillingEventType.API_CALL,
            resource=resource,
            quantity=1,
            unit_cost=self.config.api_call_price,
            user_id=user_id,
            metadata=metadata or {},
        )
        event.calculate_cost()
        await self.record_event(event)
        return event

    async def record_debate(
        self,
        debate_id: str,
        tokens_in: int,
        tokens_out: int,
        rounds: int = 1,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BillingEvent:
        """Record a debate event."""
        # Calculate cost: base + token cost
        token_cost = (
            Decimal(tokens_in + tokens_out) / Decimal(1000)
        ) * self.config.token_price_per_1k

        event = BillingEvent(
            event_type=BillingEventType.DEBATE,
            resource="debate",
            debate_id=debate_id,
            quantity=1,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            unit_cost=self.config.debate_base_price + token_cost,
            user_id=user_id,
            metadata={**(metadata or {}), "rounds": rounds},
        )
        event.calculate_cost()
        await self.record_event(event)
        return event

    async def record_tokens(
        self,
        tokens_in: int,
        tokens_out: int,
        provider: str = "",
        model: str = "",
        debate_id: str | None = None,
        user_id: str | None = None,
    ) -> BillingEvent:
        """Record token usage."""
        total_tokens = tokens_in + tokens_out
        token_cost = (Decimal(total_tokens) / Decimal(1000)) * self.config.token_price_per_1k

        event = BillingEvent(
            event_type=BillingEventType.TOKENS,
            resource=f"{provider}/{model}" if provider else "tokens",
            debate_id=debate_id,
            quantity=total_tokens,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            unit_cost=self.config.token_price_per_1k / Decimal(1000),
            total_cost=token_cost,
            user_id=user_id,
            metadata={"provider": provider, "model": model},
        )
        await self.record_event(event)
        return event

    async def record_storage(
        self,
        bytes_used: int,
        storage_type: str = "general",
        user_id: str | None = None,
    ) -> BillingEvent:
        """Record storage usage."""
        # Calculate monthly cost for storage
        gb_used = Decimal(bytes_used) / Decimal(1024 * 1024 * 1024)
        storage_cost = gb_used * self.config.storage_price_per_gb_month

        event = BillingEvent(
            event_type=BillingEventType.STORAGE,
            resource=storage_type,
            quantity=1,
            bytes_used=bytes_used,
            unit_cost=storage_cost,
            user_id=user_id,
            metadata={"storage_type": storage_type, "gb_used": float(gb_used)},
        )
        event.calculate_cost()
        await self.record_event(event)
        return event

    async def record_connector_sync(
        self,
        connector_id: str,
        connector_type: str,
        items_synced: int,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BillingEvent:
        """Record a connector sync event."""
        event = BillingEvent(
            event_type=BillingEventType.CONNECTOR_SYNC,
            resource=connector_type,
            connector_id=connector_id,
            quantity=1,
            unit_cost=self.config.connector_sync_price,
            user_id=user_id,
            metadata={**(metadata or {}), "items_synced": items_synced},
        )
        event.calculate_cost()
        await self.record_event(event)
        return event

    async def record_knowledge_query(
        self,
        query_type: str = "search",
        tokens_used: int = 0,
        user_id: str | None = None,
    ) -> BillingEvent:
        """Record a knowledge query event."""
        event = BillingEvent(
            event_type=BillingEventType.KNOWLEDGE_QUERY,
            resource=query_type,
            quantity=1,
            tokens_in=tokens_used,
            unit_cost=self.config.knowledge_query_price,
            user_id=user_id,
        )
        event.calculate_cost()
        await self.record_event(event)
        return event

    async def get_billing_events(
        self,
        start_date: datetime,
        end_date: datetime,
        tenant_id: str | None = None,
        event_type: BillingEventType | None = None,
    ) -> list[BillingEvent]:
        """
        Get billing events for a period.

        Queries from persistent storage and includes any buffered events
        that haven't been flushed yet.
        """
        tid = tenant_id or self._get_tenant_id()
        if not tid:
            return []

        # Query persisted events from database
        persisted_events = self._query_events(start_date, end_date, tid, event_type)

        # Also include any buffered events that match
        async with self._lock:
            buffered_events = [
                e
                for e in self._events
                if e.tenant_id == tid
                and start_date <= e.timestamp <= end_date
                and (event_type is None or e.event_type == event_type)
            ]

        # Combine and deduplicate by ID
        all_events = {e.id: e for e in persisted_events}
        for e in buffered_events:
            all_events[e.id] = e

        # Return sorted by timestamp descending
        return sorted(all_events.values(), key=lambda e: e.timestamp, reverse=True)

    async def get_usage_summary(
        self,
        start_date: datetime,
        end_date: datetime,
        tenant_id: str | None = None,
    ) -> UsageSummary:
        """
        Get usage summary for billing.

        Args:
            start_date: Start of period
            end_date: End of period
            tenant_id: Tenant ID (uses current context if not provided)

        Returns:
            Usage summary with costs
        """
        tid = tenant_id or self._get_tenant_id()
        if not tid:
            raise ValueError("No tenant context for usage summary")

        events = await self.get_billing_events(start_date, end_date, tid)

        summary = UsageSummary(
            tenant_id=tid,
            period_start=start_date,
            period_end=end_date,
        )

        for event in events:
            summary.total_events += 1
            summary.total_cost += event.total_cost

            # Type-specific counts
            if event.event_type == BillingEventType.API_CALL:
                summary.api_calls += event.quantity
            elif event.event_type == BillingEventType.DEBATE:
                summary.debates += event.quantity
            elif event.event_type == BillingEventType.CONNECTOR_SYNC:
                summary.connector_syncs += event.quantity
            elif event.event_type == BillingEventType.KNOWLEDGE_QUERY:
                summary.knowledge_queries += event.quantity

            # Token counts
            summary.tokens_in += event.tokens_in
            summary.tokens_out += event.tokens_out

            # Storage
            if event.event_type == BillingEventType.STORAGE:
                if event.resource == "knowledge":
                    summary.knowledge_bytes += event.bytes_used
                else:
                    summary.storage_bytes += event.bytes_used

            # Cost by type
            type_key = event.event_type.value
            if type_key not in summary.cost_by_type:
                summary.cost_by_type[type_key] = Decimal("0")
            summary.cost_by_type[type_key] += event.total_cost

            # Cost by day
            day_key = event.timestamp.strftime("%Y-%m-%d")
            if day_key not in summary.cost_by_day:
                summary.cost_by_day[day_key] = Decimal("0")
            summary.cost_by_day[day_key] += event.total_cost

        summary.total_tokens = summary.tokens_in + summary.tokens_out
        return summary

    async def estimate_monthly_cost(
        self,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Estimate monthly cost based on current usage.

        Returns projected costs based on usage patterns.
        """
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        summary = await self.get_usage_summary(month_start, now, tenant_id)

        # Calculate days elapsed and remaining
        days_elapsed = (now - month_start).days + 1
        days_in_month = 30  # Approximation
        days_remaining = max(0, days_in_month - days_elapsed)

        # Project to full month
        if days_elapsed > 0:
            daily_rate = summary.total_cost / Decimal(days_elapsed)
            projected_cost = summary.total_cost + (daily_rate * Decimal(days_remaining))
        else:
            projected_cost = Decimal("0")

        return {
            "tenant_id": summary.tenant_id,
            "period": self._get_billing_period(now),
            "current_cost": str(summary.total_cost),
            "projected_cost": str(projected_cost),
            "days_elapsed": days_elapsed,
            "days_remaining": days_remaining,
            "daily_average": str(summary.total_cost / Decimal(max(1, days_elapsed))),
            "usage": {
                "api_calls": summary.api_calls,
                "debates": summary.debates,
                "tokens": summary.total_tokens,
                "connector_syncs": summary.connector_syncs,
            },
        }


# Module-level meter instance
_meter: UsageMeter | None = None


def get_usage_meter() -> UsageMeter:
    """Get or create the global usage meter."""
    global _meter
    if _meter is None:
        _meter = UsageMeter()
    return _meter


async def record_usage(
    event_type: BillingEventType,
    quantity: int = 1,
    **kwargs: Any,
) -> BillingEvent:
    """
    Convenience function to record usage.

    Args:
        event_type: Type of billing event
        quantity: Quantity (default 1)
        **kwargs: Additional event fields

    Returns:
        Created billing event
    """
    meter = get_usage_meter()
    event = BillingEvent(
        event_type=event_type,
        quantity=quantity,
        **kwargs,
    )
    await meter.record_event(event)
    return event
