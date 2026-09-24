"""
Webhook Delivery Manager.

Provides reliable webhook delivery with:
- Delivery status tracking (pending, delivered, failed, dead-lettered)
- Retry queue with exponential backoff
- Dead-letter queue for consistently failing webhooks
- Delivery SLA metrics
- SQLite persistence for queue durability

Usage:
    from aragora.server.webhook_delivery import (
        WebhookDeliveryManager,
        get_delivery_manager,
        deliver_webhook,
    )

    manager = await get_delivery_manager()
    result = await manager.deliver(webhook_id, event_type, payload)
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Trace context imports for distributed tracing
try:
    from aragora.observability.middleware.tracing import (
        get_trace_id,
        get_span_id,
        TRACE_ID_HEADER as CUSTOM_TRACE_ID_HEADER,
        SPAN_ID_HEADER,
        TRACEPARENT_HEADER,
    )

    _TRACING_AVAILABLE = True
except ImportError:
    _TRACING_AVAILABLE = False

    def get_trace_id() -> str | None:
        return None

    def get_span_id() -> str | None:
        return None

    CUSTOM_TRACE_ID_HEADER = "X-Trace-ID"
    SPAN_ID_HEADER = "X-Span-ID"
    TRACEPARENT_HEADER = "traceparent"


def _build_trace_headers() -> dict[str, str]:
    """Build trace context headers for outgoing webhook requests.

    Returns W3C Trace Context (traceparent) and custom headers for
    distributed tracing across services.

    Returns:
        Dictionary of trace headers to include in HTTP requests
    """
    headers = {}

    trace_id = get_trace_id()
    span_id = get_span_id()

    if trace_id:
        # Custom headers (simple)
        headers[CUSTOM_TRACE_ID_HEADER] = trace_id
        if span_id:
            headers[SPAN_ID_HEADER] = span_id

        # W3C Trace Context (traceparent)
        # Format: version-trace_id-parent_id-flags
        # Version 00 is current, flags 01 means sampled
        parent_id = span_id or "0000000000000000"
        # Ensure trace_id is 32 chars and parent_id is 16 chars
        trace_id_padded = trace_id.ljust(32, "0")[:32]
        parent_id_padded = parent_id.ljust(16, "0")[:16]
        headers[TRACEPARENT_HEADER] = f"00-{trace_id_padded}-{parent_id_padded}-01"

    return headers


# Default database path (respects ARAGORA_DATA_DIR)
def _get_default_db_path() -> str:
    custom = os.environ.get("ARAGORA_WEBHOOK_DB")
    if custom:
        return custom
    from aragora.persistence.db_config import get_nomic_dir

    return str(get_nomic_dir() / "webhook_delivery.db")


_DEFAULT_DB_PATH = _get_default_db_path()


class DeliveryStatus(str, Enum):
    """Webhook delivery status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTERED = "dead_lettered"


@dataclass
class WebhookDelivery:
    """Represents a webhook delivery attempt."""

    delivery_id: str
    webhook_id: str
    event_type: str
    payload: dict[str, Any]
    status: DeliveryStatus = DeliveryStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attempts: int = 0
    max_attempts: int = 5
    next_retry_at: datetime | None = None
    last_error: str | None = None
    last_status_code: int | None = None
    delivered_at: datetime | None = None
    dead_lettered_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "delivery_id": self.delivery_id,
            "webhook_id": self.webhook_id,
            "event_type": self.event_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "last_error": self.last_error,
            "last_status_code": self.last_status_code,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "dead_lettered_at": (
                self.dead_lettered_at.isoformat() if self.dead_lettered_at else None
            ),
        }


@dataclass
class DeliveryMetrics:
    """Metrics for webhook delivery."""

    total_deliveries: int = 0
    successful_deliveries: int = 0
    failed_deliveries: int = 0
    dead_lettered: int = 0
    retries: int = 0
    total_latency_ms: float = 0.0
    endpoints_by_status: dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """Delivery success rate."""
        if self.total_deliveries == 0:
            return 0.0
        return (self.successful_deliveries / self.total_deliveries) * 100

    @property
    def avg_latency_ms(self) -> float:
        """Average delivery latency."""
        if self.successful_deliveries == 0:
            return 0.0
        return self.total_latency_ms / self.successful_deliveries

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_deliveries": self.total_deliveries,
            "successful_deliveries": self.successful_deliveries,
            "failed_deliveries": self.failed_deliveries,
            "dead_lettered": self.dead_lettered,
            "retries": self.retries,
            "success_rate": round(self.success_rate, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
        }


class DeliveryPersistence:
    """SQLite persistence for webhook delivery queues.

    Ensures retry and dead-letter queues survive server restarts.
    Uses context-local connections for async safety with proper cleanup tracking.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self._db_path = db_path
        # ContextVar for per-async-context connection (async-safe replacement for threading.local)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"delivery_conn_{id(self)}", default=None
        )
        self._initialized = False
        self._init_lock = threading.Lock()
        # Track all connections for proper cleanup across contexts
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()

    def _get_connection(self) -> sqlite3.Connection:
        """Get context-local database connection (async-safe)."""
        conn = self._conn_var.get()
        if conn is None:
            # Ensure directory exists
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                timeout=30.0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._conn_var.set(conn)
            # Track connection for cleanup
            with self._connections_lock:
                self._connections.add(conn)
        return conn

    def initialize(self) -> None:
        """Initialize database schema."""
        with self._init_lock:
            if self._initialized:
                return

            conn = self._get_connection()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    webhook_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 5,
                    next_retry_at TEXT,
                    last_error TEXT,
                    last_status_code INTEGER,
                    delivered_at TEXT,
                    dead_lettered_at TEXT,
                    metadata TEXT,
                    url TEXT,
                    secret TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_deliveries_status
                    ON webhook_deliveries(status);
                CREATE INDEX IF NOT EXISTS idx_deliveries_next_retry
                    ON webhook_deliveries(next_retry_at) WHERE status = 'retrying';
                CREATE INDEX IF NOT EXISTS idx_deliveries_webhook
                    ON webhook_deliveries(webhook_id);
            """)
            conn.commit()
            self._initialized = True
            logger.info("Webhook delivery persistence initialized at %s", self._db_path)

    def save_delivery(self, delivery: WebhookDelivery, url: str, secret: str | None = None) -> None:
        """Save or update a delivery record."""
        conn = self._get_connection()
        metadata = delivery.metadata.copy()
        # Store url/secret in metadata for retries
        if url:
            metadata["retry_url"] = url
        if secret:
            metadata["retry_secret"] = secret

        conn.execute(
            """
            INSERT OR REPLACE INTO webhook_deliveries (
                delivery_id, webhook_id, event_type, payload, status,
                created_at, updated_at, attempts, max_attempts,
                next_retry_at, last_error, last_status_code,
                delivered_at, dead_lettered_at, metadata, url, secret
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                delivery.delivery_id,
                delivery.webhook_id,
                delivery.event_type,
                json.dumps(delivery.payload),
                delivery.status.value,
                delivery.created_at.isoformat(),
                delivery.updated_at.isoformat(),
                delivery.attempts,
                delivery.max_attempts,
                delivery.next_retry_at.isoformat() if delivery.next_retry_at else None,
                delivery.last_error,
                delivery.last_status_code,
                delivery.delivered_at.isoformat() if delivery.delivered_at else None,
                delivery.dead_lettered_at.isoformat() if delivery.dead_lettered_at else None,
                json.dumps(metadata),
                url,
                secret,
            ),
        )
        conn.commit()

    def delete_delivery(self, delivery_id: str) -> None:
        """Delete a delivery record (after successful delivery)."""
        conn = self._get_connection()
        conn.execute("DELETE FROM webhook_deliveries WHERE delivery_id = ?", (delivery_id,))
        conn.commit()

    def load_pending_retries(self) -> list[sqlite3.Row]:
        """Load all deliveries that need retry (for recovery on startup)."""
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT * FROM webhook_deliveries
            WHERE status IN ('pending', 'retrying', 'in_progress')
            ORDER BY next_retry_at ASC NULLS LAST
        """)
        return cursor.fetchall()

    def load_dead_letter_queue(self, limit: int = 100) -> list[sqlite3.Row]:
        """Load dead-lettered deliveries."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM webhook_deliveries
            WHERE status = 'dead_lettered'
            ORDER BY dead_lettered_at DESC
            LIMIT ?
        """,
            (limit,),
        )
        return cursor.fetchall()

    def _row_to_delivery(self, row: sqlite3.Row) -> tuple[WebhookDelivery, str | None, str | None]:
        """Convert database row to (WebhookDelivery, url, secret) tuple."""
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}

        delivery = WebhookDelivery(
            delivery_id=row["delivery_id"],
            webhook_id=row["webhook_id"],
            event_type=row["event_type"],
            payload=json.loads(row["payload"]),
            status=DeliveryStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            next_retry_at=(
                datetime.fromisoformat(row["next_retry_at"]) if row["next_retry_at"] else None
            ),
            last_error=row["last_error"],
            last_status_code=row["last_status_code"],
            delivered_at=(
                datetime.fromisoformat(row["delivered_at"]) if row["delivered_at"] else None
            ),
            dead_lettered_at=(
                datetime.fromisoformat(row["dead_lettered_at"]) if row["dead_lettered_at"] else None
            ),
            metadata=metadata,
        )
        return delivery, row["url"], row["secret"]

    def get_metrics_from_db(self) -> dict[str, int]:
        """Get aggregate metrics from database."""
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM webhook_deliveries
            GROUP BY status
        """)
        return {row["status"]: row["count"] for row in cursor.fetchall()}

    def cleanup_old_delivered(self, days: int = 7) -> int:
        """Remove delivered records older than N days."""
        conn = self._get_connection()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cursor = conn.execute(
            """
            DELETE FROM webhook_deliveries
            WHERE status = 'delivered' AND delivered_at < ?
        """,
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        """Close all database connections across all contexts."""
        # Close all tracked connections
        with self._connections_lock:
            for conn in self._connections:
                try:
                    conn.close()
                except (sqlite3.Error, OSError):
                    pass  # Connection may already be closed
            self._connections.clear()
        # Clear context-local reference
        try:
            self._conn_var.set(None)
        except LookupError:
            pass  # No context, nothing to clear


class WebhookDeliveryManager:
    """
    Manages webhook delivery with reliability guarantees.

    Features:
    - Async delivery with HTTP client
    - Exponential backoff retry
    - Dead-letter queue for failed deliveries
    - Delivery tracking and metrics
    - Circuit breaker per endpoint
    - SQLite persistence for queue durability
    """

    def __init__(
        self,
        max_retries: int = 5,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 300.0,
        timeout_seconds: float = 30.0,
        circuit_breaker_threshold: int = 5,
        db_path: str | None = None,
        enable_persistence: bool = True,
    ):
        """
        Initialize the delivery manager.

        Args:
            max_retries: Maximum retry attempts per delivery
            base_delay_seconds: Base delay for exponential backoff
            max_delay_seconds: Maximum delay between retries
            timeout_seconds: HTTP timeout for delivery
            circuit_breaker_threshold: Failures before circuit opens
            db_path: Path to SQLite database for persistence
            enable_persistence: Whether to enable SQLite persistence
        """
        self._max_retries = max_retries
        self._base_delay = base_delay_seconds
        self._max_delay = max_delay_seconds
        self._timeout = timeout_seconds
        self._circuit_threshold = circuit_breaker_threshold

        # In-memory caches (backed by SQLite when persistence enabled)
        self._pending: dict[str, WebhookDelivery] = {}
        self._retry_queue: dict[str, WebhookDelivery] = {}
        self._dead_letter_queue: dict[str, WebhookDelivery] = {}
        self._delivered: dict[str, WebhookDelivery] = {}

        # URL/secret mapping for retries
        self._delivery_urls: dict[str, str] = {}
        self._delivery_secrets: dict[str, str | None] = {}

        # Circuit breaker state per endpoint
        self._circuit_failures: dict[str, int] = {}
        self._circuit_open_until: dict[str, datetime] = {}

        # Metrics
        self._metrics = DeliveryMetrics()

        # Background retry processor
        self._retry_task: asyncio.Task | None = None
        self._running = False

        # HTTP sender (can be mocked for testing)
        self._sender: Callable | None = None

        # Persistence layer
        self._enable_persistence = enable_persistence
        self._persistence: DeliveryPersistence | None = None
        self._persistence_initialized = False
        if enable_persistence:
            self._persistence = DeliveryPersistence(db_path or _DEFAULT_DB_PATH)

    def _ensure_persistence_initialized(self) -> None:
        """Ensure persistence layer is initialized (lazy initialization)."""
        if self._persistence and not self._persistence_initialized:
            self._persistence.initialize()
            self._persistence_initialized = True

    async def start(self) -> None:
        """Start the background retry processor and recover pending deliveries."""
        if self._running:
            return

        # Initialize persistence and recover pending deliveries
        if self._persistence:
            self._ensure_persistence_initialized()
            await self._recover_pending_deliveries()

        self._running = True
        self._retry_task = asyncio.create_task(self._process_retries())
        logger.info("Webhook delivery manager started")

    async def _recover_pending_deliveries(self) -> None:
        """Recover pending deliveries from database on startup."""
        if not self._persistence:
            return

        try:
            rows = self._persistence.load_pending_retries()
            recovered = 0

            for row in rows:
                delivery, url, secret = self._persistence._row_to_delivery(row)

                # Store URL/secret for retries
                self._delivery_urls[delivery.delivery_id] = url or ""
                self._delivery_secrets[delivery.delivery_id] = secret

                # Add to appropriate queue based on status
                if delivery.status == DeliveryStatus.RETRYING:
                    self._retry_queue[delivery.delivery_id] = delivery
                elif delivery.status in (DeliveryStatus.PENDING, DeliveryStatus.IN_PROGRESS):
                    # Treat in-progress as needing retry (server may have crashed)
                    delivery.status = DeliveryStatus.RETRYING
                    delivery.next_retry_at = datetime.now(timezone.utc)
                    self._retry_queue[delivery.delivery_id] = delivery
                    self._persistence.save_delivery(delivery, url or "", secret)

                recovered += 1

            if recovered > 0:
                logger.info("Recovered %s pending webhook deliveries from database", recovered)

        except (sqlite3.Error, OSError, KeyError, json.JSONDecodeError) as e:
            logger.error("Failed to recover pending deliveries: %s", e)

    async def stop(self) -> None:
        """Stop the background retry processor."""
        self._running = False
        if self._retry_task:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass
        if self._persistence:
            self._persistence.close()
        logger.info("Webhook delivery manager stopped")

    async def cleanup_old_records(self, days: int = 7) -> int:
        """Remove delivered records older than N days.

        Args:
            days: Number of days to retain delivered records

        Returns:
            Number of records cleaned up
        """
        if self._persistence:
            return self._persistence.cleanup_old_delivered(days)
        return 0

    def set_sender(self, sender: Callable) -> None:
        """
        Set the HTTP sender function for testing.

        Args:
            sender: Async function(url, payload, headers) -> (status_code, response_body)
        """
        self._sender = sender

    async def deliver(
        self,
        webhook_id: str,
        event_type: str,
        payload: dict[str, Any],
        url: str,
        secret: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WebhookDelivery:
        """
        Deliver a webhook with retry guarantees.

        Args:
            webhook_id: Webhook configuration ID
            event_type: Event type being delivered
            payload: Event payload
            url: Delivery URL
            secret: Signing secret for HMAC signature
            metadata: Additional metadata

        Returns:
            WebhookDelivery with status
        """
        # Capture trace context at creation time
        delivery_metadata = metadata.copy() if metadata else {}
        trace_id = get_trace_id()
        if trace_id and isinstance(trace_id, str):
            delivery_metadata["trace_id"] = trace_id
            span_id = get_span_id()
            if span_id and isinstance(span_id, str):
                delivery_metadata["span_id"] = span_id

        delivery = WebhookDelivery(
            delivery_id=str(uuid.uuid4()),
            webhook_id=webhook_id,
            event_type=event_type,
            payload=payload,
            metadata=delivery_metadata,
        )

        self._pending[delivery.delivery_id] = delivery
        self._delivery_urls[delivery.delivery_id] = url
        self._delivery_secrets[delivery.delivery_id] = secret
        self._metrics.total_deliveries += 1

        # Persist delivery record (lazy init if needed)
        if self._persistence:
            self._ensure_persistence_initialized()
            self._persistence.save_delivery(delivery, url, secret)

        # Check circuit breaker
        if self._is_circuit_open(url):
            delivery.status = DeliveryStatus.RETRYING
            delivery.last_error = "Circuit breaker open"
            self._schedule_retry(delivery, url, secret)
            return delivery

        # Attempt delivery
        success = await self._attempt_delivery(delivery, url, secret)

        if success:
            delivery.status = DeliveryStatus.DELIVERED
            delivery.delivered_at = datetime.now(timezone.utc)
            self._delivered[delivery.delivery_id] = delivery
            del self._pending[delivery.delivery_id]
            self._metrics.successful_deliveries += 1
            self._reset_circuit(url)
            # Remove from persistent storage on success
            if self._persistence:
                self._persistence.delete_delivery(delivery.delivery_id)
        else:
            self._record_circuit_failure(url)
            if delivery.attempts >= self._max_retries:
                self._move_to_dead_letter(delivery)
            else:
                self._schedule_retry(delivery, url, secret)

        return delivery

    async def _attempt_delivery(
        self,
        delivery: WebhookDelivery,
        url: str,
        secret: str | None,
    ) -> bool:
        """
        Attempt to deliver the webhook.

        Returns:
            True if delivery succeeded
        """
        delivery.status = DeliveryStatus.IN_PROGRESS
        delivery.attempts += 1
        delivery.updated_at = datetime.now(timezone.utc)

        # Build headers
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Delivery-Id": delivery.delivery_id,
            "X-Webhook-Event-Type": delivery.event_type,
            "X-Webhook-Timestamp": str(int(time.time())),
        }

        # Add distributed tracing headers (W3C Trace Context + custom)
        trace_headers = _build_trace_headers()
        headers.update(trace_headers)

        # Add HMAC signature if secret provided
        if secret:
            payload_bytes = json.dumps(delivery.payload).encode()
            signature = hashlib.sha256(
                (headers["X-Webhook-Timestamp"] + "." + payload_bytes.decode()).encode()
                + secret.encode()
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        start_time = time.time()

        try:
            if self._sender:
                # Use mock sender for testing
                status_code, _ = await self._sender(url, delivery.payload, headers)
            else:
                # Use real HTTP client
                status_code = await self._http_send(url, delivery.payload, headers)

            latency_ms = (time.time() - start_time) * 1000
            delivery.last_status_code = status_code

            if 200 <= status_code < 300:
                self._metrics.total_latency_ms += latency_ms
                return True
            else:
                delivery.last_error = f"HTTP {status_code}"
                self._metrics.failed_deliveries += 1
                return False

        except asyncio.TimeoutError:
            delivery.last_error = "Timeout"
            self._metrics.failed_deliveries += 1
            return False
        except (ConnectionError, OSError, RuntimeError, ValueError) as e:
            logger.warning("Webhook delivery attempt failed: %s", e)
            delivery.last_error = "Delivery failed"
            self._metrics.failed_deliveries += 1
            return False

    async def _http_send(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> int:
        """Send HTTP POST request."""
        try:
            from aragora.observability.http_client_pool import get_http_pool

            pool = get_http_pool()
            async with pool.get_session("webhook") as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )
                return response.status_code
        except ImportError:
            logger.error("httpx not available for HTTP client pool")
            raise RuntimeError("No HTTP client available")

    def _schedule_retry(
        self,
        delivery: WebhookDelivery,
        url: str,
        secret: str | None,
    ) -> None:
        """Schedule delivery for retry with exponential backoff."""
        delivery.status = DeliveryStatus.RETRYING
        delivery.updated_at = datetime.now(timezone.utc)

        # Exponential backoff with jitter
        delay = min(
            self._base_delay * (2 ** (delivery.attempts - 1)),
            self._max_delay,
        )
        # Add jitter (±25%)
        import random

        delay *= 0.75 + random.random() * 0.5  # noqa: S311 -- retry jitter

        delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        delivery.metadata["retry_url"] = url
        delivery.metadata["retry_secret"] = secret

        self._retry_queue[delivery.delivery_id] = delivery
        self._delivery_urls[delivery.delivery_id] = url
        self._delivery_secrets[delivery.delivery_id] = secret
        if delivery.delivery_id in self._pending:
            del self._pending[delivery.delivery_id]

        # Persist retry status
        if self._persistence:
            self._persistence.save_delivery(delivery, url, secret)

        self._metrics.retries += 1
        logger.debug(
            f"Scheduled retry for {delivery.delivery_id} in {delay:.1f}s "
            f"(attempt {delivery.attempts}/{self._max_retries})"
        )

    def _move_to_dead_letter(self, delivery: WebhookDelivery) -> None:
        """Move delivery to dead-letter queue."""
        delivery.status = DeliveryStatus.DEAD_LETTERED
        delivery.dead_lettered_at = datetime.now(timezone.utc)
        delivery.updated_at = datetime.now(timezone.utc)

        self._dead_letter_queue[delivery.delivery_id] = delivery

        # Remove from other queues
        for queue in [self._pending, self._retry_queue]:
            if delivery.delivery_id in queue:
                del queue[delivery.delivery_id]

        # Persist dead-letter status
        if self._persistence:
            url = self._delivery_urls.get(delivery.delivery_id, "")
            secret = self._delivery_secrets.get(delivery.delivery_id)
            self._persistence.save_delivery(delivery, url, secret)

        self._metrics.dead_lettered += 1
        logger.warning(
            "Moved delivery %s to dead-letter queue after %s attempts: %s",
            delivery.delivery_id,
            delivery.attempts,
            delivery.last_error,
        )

    async def _process_retries(self) -> None:
        """Background task to process retry queue."""
        while self._running:
            try:
                now = datetime.now(timezone.utc)

                # Find deliveries ready for retry
                ready = [
                    d
                    for d in self._retry_queue.values()
                    if d.next_retry_at and d.next_retry_at <= now
                ]

                for delivery in ready:
                    # Get URL/secret from our maps or metadata
                    url = self._delivery_urls.get(delivery.delivery_id) or delivery.metadata.get(
                        "retry_url", ""
                    )
                    secret = self._delivery_secrets.get(
                        delivery.delivery_id
                    ) or delivery.metadata.get("retry_secret")

                    if not url:
                        self._move_to_dead_letter(delivery)
                        continue

                    # Remove from retry queue before attempting
                    if delivery.delivery_id in self._retry_queue:
                        del self._retry_queue[delivery.delivery_id]

                    # Check circuit breaker
                    if self._is_circuit_open(url):
                        self._schedule_retry(delivery, url, secret)
                        continue

                    # Attempt delivery
                    success = await self._attempt_delivery(delivery, url, secret)

                    if success:
                        delivery.status = DeliveryStatus.DELIVERED
                        delivery.delivered_at = datetime.now(timezone.utc)
                        self._delivered[delivery.delivery_id] = delivery
                        self._metrics.successful_deliveries += 1
                        self._reset_circuit(url)
                        # Remove from persistent storage on success
                        if self._persistence:
                            self._persistence.delete_delivery(delivery.delivery_id)
                        # Clean up URL/secret maps
                        self._delivery_urls.pop(delivery.delivery_id, None)
                        self._delivery_secrets.pop(delivery.delivery_id, None)
                    else:
                        self._record_circuit_failure(url)
                        if delivery.attempts >= self._max_retries:
                            self._move_to_dead_letter(delivery)
                        else:
                            self._schedule_retry(delivery, url, secret)

            except (RuntimeError, KeyError, asyncio.CancelledError) as e:
                logger.error("Error processing retries: %s", e)

            await asyncio.sleep(1.0)  # Check every second

    def _is_circuit_open(self, url: str) -> bool:
        """Check if circuit breaker is open for an endpoint."""
        if url in self._circuit_open_until:
            if datetime.now(timezone.utc) < self._circuit_open_until[url]:
                return True
            # Circuit timeout expired, reset
            del self._circuit_open_until[url]
            self._circuit_failures[url] = 0
        return False

    def _record_circuit_failure(self, url: str) -> None:
        """Record a failure for circuit breaker."""
        self._circuit_failures[url] = self._circuit_failures.get(url, 0) + 1

        if self._circuit_failures[url] >= self._circuit_threshold:
            # Open circuit for 30 seconds * failure count (max 5 minutes)
            timeout = min(30 * self._circuit_failures[url], 300)
            self._circuit_open_until[url] = datetime.now(timezone.utc) + timedelta(seconds=timeout)
            logger.warning("Circuit breaker opened for %s for %ss", url, timeout)

    def _reset_circuit(self, url: str) -> None:
        """Reset circuit breaker on success."""
        self._circuit_failures[url] = 0
        if url in self._circuit_open_until:
            del self._circuit_open_until[url]

    async def get_delivery(self, delivery_id: str) -> WebhookDelivery | None:
        """Get delivery by ID."""
        for queue in [self._pending, self._retry_queue, self._dead_letter_queue, self._delivered]:
            if delivery_id in queue:
                return queue[delivery_id]
        return None

    async def get_pending_count(self) -> int:
        """Get count of pending deliveries."""
        return len(self._pending) + len(self._retry_queue)

    async def get_dead_letter_queue(self, limit: int = 100) -> list[WebhookDelivery]:
        """Get deliveries in dead-letter queue."""
        # Merge in-memory with persisted (persisted is source of truth)
        if self._persistence:
            rows = self._persistence.load_dead_letter_queue(limit)
            result = []
            for row in rows:
                delivery, _, _ = self._persistence._row_to_delivery(row)
                result.append(delivery)
                # Update in-memory cache
                self._dead_letter_queue[delivery.delivery_id] = delivery
            return result
        return list(self._dead_letter_queue.values())[:limit]

    async def retry_dead_letter(self, delivery_id: str) -> bool:
        """
        Retry a dead-lettered delivery.

        Args:
            delivery_id: The delivery to retry

        Returns:
            True if moved back to retry queue
        """
        if delivery_id not in self._dead_letter_queue:
            return False

        delivery = self._dead_letter_queue[delivery_id]
        delivery.status = DeliveryStatus.RETRYING
        delivery.attempts = 0  # Reset attempts
        delivery.dead_lettered_at = None
        delivery.next_retry_at = datetime.now(timezone.utc)
        delivery.updated_at = datetime.now(timezone.utc)

        self._retry_queue[delivery_id] = delivery
        del self._dead_letter_queue[delivery_id]

        # Persist status change
        if self._persistence:
            self._ensure_persistence_initialized()
            url = self._delivery_urls.get(delivery_id, delivery.metadata.get("retry_url", ""))
            secret = self._delivery_secrets.get(delivery_id, delivery.metadata.get("retry_secret"))
            self._persistence.save_delivery(delivery, url, secret)

        self._metrics.dead_lettered -= 1
        logger.info("Retrying dead-lettered delivery %s", delivery_id)
        return True

    async def get_metrics(self) -> dict[str, Any]:
        """Get delivery metrics."""
        return {
            **self._metrics.to_dict(),
            "pending_count": len(self._pending),
            "retry_queue_size": len(self._retry_queue),
            "dead_letter_queue_size": len(self._dead_letter_queue),
            "delivered_count": len(self._delivered),
            "open_circuits": len(self._circuit_open_until),
        }


# Global manager instance
_manager: WebhookDeliveryManager | None = None
_manager_lock = asyncio.Lock()


async def get_delivery_manager() -> WebhookDeliveryManager:
    """Get or create the global delivery manager."""
    global _manager
    async with _manager_lock:
        if _manager is None:
            _manager = WebhookDeliveryManager()
            await _manager.start()
        return _manager


async def deliver_webhook(
    webhook_id: str,
    event_type: str,
    payload: dict[str, Any],
    url: str,
    secret: str | None = None,
) -> WebhookDelivery:
    """
    Deliver a webhook with retry guarantees.

    Convenience function that uses the global manager.
    """
    manager = await get_delivery_manager()
    return await manager.deliver(webhook_id, event_type, payload, url, secret)


async def get_webhook_delivery_metrics() -> dict[str, Any]:
    """Get webhook delivery metrics."""
    manager = await get_delivery_manager()
    return await manager.get_metrics()


def reset_delivery_manager() -> None:
    """Reset the global manager (for testing)."""
    global _manager
    _manager = None


__all__ = [
    "DeliveryStatus",
    "WebhookDelivery",
    "DeliveryMetrics",
    "WebhookDeliveryManager",
    "get_delivery_manager",
    "deliver_webhook",
    "get_webhook_delivery_metrics",
    "reset_delivery_manager",
]
