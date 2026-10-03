"""
Webhook Event Dispatcher.

Handles delivery of events to registered webhook endpoints.
Supports async delivery with retry logic and signature verification.

Features:
- HMAC-SHA256 payload signing
- Async non-blocking delivery
- Exponential backoff retry
- Delivery status tracking
- Rate limiting per endpoint

Usage:
    from aragora.events.dispatcher import get_dispatcher

    # Get global dispatcher
    dispatcher = get_dispatcher()

    # Connect to event stream
    dispatcher.subscribe_to_stream(event_emitter)

    # Events are automatically delivered to registered webhooks
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aragora.observability.middleware.tracing import get_trace_id

if TYPE_CHECKING:
    from aragora.events.types import EventEmitter, StreamEvent
    from aragora.storage.webhook_config_store import WebhookConfig

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Maximum concurrent webhook deliveries
MAX_WORKERS = int(os.environ.get("ARAGORA_WEBHOOK_WORKERS", "10"))

# Retry configuration
MAX_RETRIES = int(os.environ.get("ARAGORA_WEBHOOK_MAX_RETRIES", "3"))
INITIAL_RETRY_DELAY = float(os.environ.get("ARAGORA_WEBHOOK_RETRY_DELAY", "1.0"))
MAX_RETRY_DELAY = float(os.environ.get("ARAGORA_WEBHOOK_MAX_RETRY_DELAY", "60.0"))

# Request timeout in seconds
REQUEST_TIMEOUT = float(os.environ.get("ARAGORA_WEBHOOK_TIMEOUT", "30.0"))

# User agent for webhook requests
USER_AGENT = "Aragora-Webhooks/1.0"

# Event rate limiting configuration
EVENT_RATE_LIMIT_ENABLED = (
    os.environ.get("ARAGORA_EVENT_RATE_LIMIT_ENABLED", "true").lower() == "true"
)
EVENT_RATE_LIMIT_PER_SECOND = float(os.environ.get("ARAGORA_EVENT_RATE_LIMIT_PER_SECOND", "100.0"))
EVENT_RATE_LIMIT_BURST = int(os.environ.get("ARAGORA_EVENT_RATE_LIMIT_BURST", "200"))

# =============================================================================
# Event Rate Limiter
# =============================================================================


class EventRateLimiter:
    """
    Token bucket rate limiter for events.

    Limits event throughput per event type to prevent DoS via event flooding.
    Uses the shared KeyedTokenBucket for per-type rate limiting.
    """

    def __init__(
        self,
        rate_per_second: float = EVENT_RATE_LIMIT_PER_SECOND,
        burst_capacity: int = EVENT_RATE_LIMIT_BURST,
    ):
        """
        Initialize rate limiter.

        Args:
            rate_per_second: Tokens added per second (event throughput)
            burst_capacity: Maximum tokens (allows burst traffic)
        """
        from aragora.shared.rate_limiting import KeyedTokenBucket

        # Convert rate per second to rate per minute for KeyedTokenBucket
        rate_per_minute = rate_per_second * 60.0

        # Delegate to shared implementation
        self._bucket = KeyedTokenBucket(
            rate_per_minute=rate_per_minute,
            burst=burst_capacity,
            name="event",
        )

        # Store original config for stats
        self.rate = rate_per_second
        self.burst = burst_capacity

    def is_allowed(self, event_type: str) -> bool:
        """
        Check if an event should be allowed through.

        Args:
            event_type: Type of event to check

        Returns:
            True if event is allowed, False if rate limited
        """
        return self._bucket.try_acquire(event_type)

    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        bucket_stats = self._bucket.stats
        return {
            "accepted": bucket_stats.get("acquired", 0),
            "rejected": bucket_stats.get("rejected", 0),
            "rate_per_second": self.rate,
            "burst_capacity": self.burst,
            "active_buckets": bucket_stats.get("active_keys", 0),
        }

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._bucket.reset_stats()


# Global event rate limiter
_event_rate_limiter: EventRateLimiter | None = None


def get_event_rate_limiter() -> EventRateLimiter | None:
    """Get the global event rate limiter (if enabled)."""
    global _event_rate_limiter

    if not EVENT_RATE_LIMIT_ENABLED:
        return None

    if _event_rate_limiter is None:
        _event_rate_limiter = EventRateLimiter()

    return _event_rate_limiter


# =============================================================================
# Webhook Delivery
# =============================================================================


@dataclass
class DeliveryResult:
    """Result of a webhook delivery attempt."""

    success: bool
    status_code: int
    error: str | None = None
    retry_count: int = 0
    duration_ms: float = 0.0


class WebhookStore(Protocol):
    """Lower-layer contract for webhook lookup and delivery recording."""

    def get_for_event(self, event_type: str) -> list[WebhookConfig]:
        """Return active webhooks interested in an event type."""
        ...

    def record_delivery(
        self,
        webhook_id: str,
        status_code: int,
        success: bool = True,
    ) -> None:
        """Record a webhook delivery result."""
        ...


WebhookStoreProvider = Callable[[], WebhookStore | None]
_webhook_store_provider: WebhookStoreProvider | None = None
_webhook_store_provider_lock = threading.Lock()
_webhook_store_provider_last_warning: float | None = None
WEBHOOK_STORE_PROVIDER_WARNING_INTERVAL = 60.0


def register_webhook_store_provider(provider: WebhookStoreProvider | None) -> None:
    """Register the higher-layer provider used by the webhook dispatcher."""
    global _webhook_store_provider, _webhook_store_provider_last_warning
    with _webhook_store_provider_lock:
        _webhook_store_provider = provider
        _webhook_store_provider_last_warning = None


def _warn_webhook_store_provider_failure(error: Exception) -> None:
    """Emit a throttled warning when a registered provider cannot resolve."""
    global _webhook_store_provider_last_warning

    now = time.monotonic()
    with _webhook_store_provider_lock:
        last_warning = _webhook_store_provider_last_warning
        if (
            last_warning is not None
            and now - last_warning < WEBHOOK_STORE_PROVIDER_WARNING_INTERVAL
        ):
            return
        _webhook_store_provider_last_warning = now

    logger.warning("Webhook store provider failed: %s", error)


def _resolve_webhook_store() -> WebhookStore | None:
    """Resolve webhook storage without importing a server composition surface."""
    with _webhook_store_provider_lock:
        provider = _webhook_store_provider
    if provider is None:
        return None
    try:
        return provider()
    except (ImportError, OSError, RuntimeError, ValueError, sqlite3.Error) as e:
        _warn_webhook_store_provider_failure(e)
        return None


def dispatch_webhook(
    webhook: WebhookConfig,
    payload: dict,
    timeout: float = REQUEST_TIMEOUT,
) -> tuple[bool, int, str | None]:
    """
    Dispatch a single webhook synchronously.

    Args:
        webhook: Webhook configuration
        payload: Event payload to send
        timeout: Request timeout in seconds

    Returns:
        Tuple of (success, status_code, error_message)
    """
    from aragora.security.webhook_signing import generate_signature

    # SSRF protection: validate webhook URL before making outbound request
    from aragora.security.ssrf_protection import validate_url

    url_check = validate_url(webhook.url)
    if not url_check.is_safe:
        logger.warning("SSRF blocked for webhook %s: %s", webhook.id, url_check.error)
        return False, 0, f"URL validation failed: {url_check.error}"

    try:
        # Serialize payload
        payload_json = json.dumps(payload, default=str)

        # Generate signature
        signature = generate_signature(payload_json, webhook.secret)

        # Build headers with distributed tracing support
        headers = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "X-Aragora-Signature": signature,
            "X-Aragora-Event": payload.get("event", "unknown"),
            "X-Aragora-Delivery": payload.get("delivery_id", ""),
            "X-Aragora-Timestamp": str(int(time.time())),
        }

        # Add correlation ID for distributed tracing
        # Check payload first (from event data), then current trace context
        correlation_id = (
            payload.get("data", {}).get("correlation_id")
            or payload.get("correlation_id")
            or get_trace_id()
        )
        if correlation_id:
            headers["X-Aragora-Correlation-ID"] = correlation_id

        # Build request
        request = Request(  # noqa: S310 -- registered webhook URL
            webhook.url,
            data=payload_json.encode("utf-8"),
            headers=headers,
            method="POST",
        )

        # Send request
        start_time = time.time()
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 -- registered webhook URL
            status_code = response.status
            duration_ms = (time.time() - start_time) * 1000

            logger.debug(
                f"Webhook delivered to {webhook.url}: "
                f"status={status_code}, duration={duration_ms:.1f}ms"
            )

            return True, status_code, None

    except HTTPError as e:
        logger.warning("Webhook HTTP error for %s: %s %s", webhook.url, e.code, e.reason)
        return False, e.code, f"HTTP {e.code}: {e.reason}"

    except URLError as e:
        logger.warning("Webhook URL error for %s: %s", webhook.url, e.reason)
        return False, 0, f"Connection failed: {e.reason}"

    except TimeoutError:
        logger.warning("Webhook timeout for %s", webhook.url)
        return False, 0, "Request timed out"

    except (OSError, ValueError, TypeError, RuntimeError) as e:
        logger.error("Webhook delivery error for %s: %s", webhook.url, e)
        return False, 0, str(e)


def dispatch_webhook_with_retry(
    webhook: WebhookConfig,
    payload: dict,
    max_retries: int = MAX_RETRIES,
    initial_delay: float = INITIAL_RETRY_DELAY,
    max_delay: float = MAX_RETRY_DELAY,
) -> DeliveryResult:
    """
    Dispatch webhook with exponential backoff retry.

    Args:
        webhook: Webhook configuration
        payload: Event payload
        max_retries: Maximum retry attempts
        initial_delay: Initial retry delay in seconds
        max_delay: Maximum retry delay in seconds

    Returns:
        DeliveryResult with outcome
    """
    # Import metrics and tracing (lazy to avoid circular imports)
    record_webhook_retry: Callable[[str, int], None] | None
    try:
        from aragora.observability.metrics.webhook import (
            record_webhook_retry as _record_webhook_retry,
        )
    except ImportError:
        record_webhook_retry = None
    else:
        record_webhook_retry = _record_webhook_retry

    trace_webhook_delivery: Callable[..., Any] | None
    try:
        from aragora.observability.tracing import (
            trace_webhook_delivery as _trace_webhook_delivery,
        )
    except ImportError:
        trace_webhook_delivery = None
    else:
        trace_webhook_delivery = _trace_webhook_delivery

    event_type = payload.get("event", "unknown")
    correlation_id = (
        payload.get("data", {}).get("correlation_id")
        or payload.get("correlation_id")
        or get_trace_id()
    )
    start_time = time.time()
    delay = initial_delay

    # Create tracing span for the entire delivery (including retries)
    if trace_webhook_delivery:
        # Use the context manager
        with trace_webhook_delivery(
            event_type=event_type,
            webhook_id=webhook.id,
            webhook_url=webhook.url,
            correlation_id=correlation_id,
        ) as span:
            result = _dispatch_with_retry_impl(
                webhook,
                payload,
                max_retries,
                initial_delay,
                max_delay,
                start_time,
                delay,
                event_type,
                record_webhook_retry,
                span,
            )
            # Add result attributes to span
            span.set_attribute("webhook.success", result.success)
            span.set_attribute("webhook.status_code", result.status_code)
            span.set_attribute("webhook.retry_count", result.retry_count)
            span.set_attribute("webhook.duration_ms", result.duration_ms)
            if result.error:
                span.set_attribute("webhook.error", result.error[:200])
            return result
    else:
        return _dispatch_with_retry_impl(
            webhook,
            payload,
            max_retries,
            initial_delay,
            max_delay,
            start_time,
            delay,
            event_type,
            record_webhook_retry,
            None,
        )


def _dispatch_with_retry_impl(
    webhook: WebhookConfig,
    payload: dict,
    max_retries: int,
    initial_delay: float,
    max_delay: float,
    start_time: float,
    delay: float,
    event_type: str,
    record_webhook_retry,
    span,
) -> DeliveryResult:
    """Internal implementation of dispatch with retry logic."""
    for attempt in range(max_retries + 1):
        success, status_code, error = dispatch_webhook(webhook, payload)

        if success:
            return DeliveryResult(
                success=True,
                status_code=status_code,
                retry_count=attempt,
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Don't retry on 4xx errors (client errors)
        if 400 <= status_code < 500:
            return DeliveryResult(
                success=False,
                status_code=status_code,
                error=error,
                retry_count=attempt,
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Retry on 5xx or connection errors
        if attempt < max_retries:
            # Record retry metric
            if record_webhook_retry:
                record_webhook_retry(event_type, attempt + 1)

            # Add retry event to span
            if span:
                span.add_event("retry", {"attempt": attempt + 1, "delay_seconds": delay})

            logger.info(
                f"Retrying webhook {webhook.id} in {delay:.1f}s "
                f"(attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(delay)
            delay = min(delay * 2, max_delay)  # Exponential backoff

    return DeliveryResult(
        success=False,
        status_code=status_code,
        error=error,
        retry_count=max_retries,
        duration_ms=(time.time() - start_time) * 1000,
    )


# =============================================================================
# Webhook Dispatcher
# =============================================================================


class WebhookDispatcher:
    """
    Async webhook event dispatcher.

    Subscribes to event streams and delivers webhooks in background threads.
    """

    def __init__(self, max_workers: int = MAX_WORKERS):
        """Initialize dispatcher with thread pool."""
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="webhook-",
        )
        self._subscriptions: list[Callable] = []
        self._shutdown = False

        # Stats
        self._deliveries = 0
        self._successes = 0
        self._failures = 0
        self._rate_limited = 0
        self._lock = threading.Lock()

    def subscribe_to_stream(self, event_emitter: EventEmitter) -> None:
        """
        Subscribe to an event emitter to receive events.

        Args:
            event_emitter: Events-layer emitter interface to subscribe to
        """

        def on_event(event: StreamEvent):
            if not self._shutdown:
                self.dispatch_event(event.type.value, event.to_dict())

        event_emitter.subscribe(on_event)
        self._subscriptions.append(on_event)
        logger.info("Webhook dispatcher subscribed to event stream")

    def dispatch_event(self, event_type: str, data: dict) -> None:
        """
        Dispatch event to all registered webhooks.

        Args:
            event_type: Event type string
            data: Event data
        """
        if self._shutdown:
            return

        # Check rate limit
        rate_limiter = get_event_rate_limiter()
        if rate_limiter and not rate_limiter.is_allowed(event_type):
            logger.warning("Event rate limited: %s", event_type)
            with self._lock:
                self._rate_limited += 1
            return

        store = _resolve_webhook_store()
        if store is None:
            return
        webhooks = store.get_for_event(event_type)

        if not webhooks:
            return

        # Create payload
        delivery_id = f"{event_type}-{int(time.time() * 1000)}"
        payload = {
            "event": event_type,
            "delivery_id": delivery_id,
            "timestamp": time.time(),
            "data": data,
        }

        # Submit deliveries to thread pool
        for webhook in webhooks:
            self._executor.submit(
                self._deliver_webhook,
                webhook,
                payload.copy(),
                store,
            )

    def _deliver_webhook(
        self,
        webhook: WebhookConfig,
        payload: dict,
        store: WebhookStore,
    ) -> None:
        """Deliver webhook in background thread."""
        # Import metrics (lazy to avoid circular imports)
        try:
            from aragora.observability.metrics.webhook import record_webhook_delivery
        except ImportError:
            record_webhook_delivery = None

        event_type = payload.get("event", "unknown")
        result = dispatch_webhook_with_retry(webhook, payload)

        # Update stats
        with self._lock:
            self._deliveries += 1
            if result.success:
                self._successes += 1
            else:
                self._failures += 1

        # Record Prometheus metrics
        if record_webhook_delivery:
            record_webhook_delivery(
                event_type=event_type,
                success=result.success,
                duration_seconds=result.duration_ms / 1000.0,
                status_code=result.status_code if not result.success else None,
            )

        # Record delivery in store
        store.record_delivery(
            webhook_id=webhook.id,
            status_code=result.status_code,
            success=result.success,
        )

        if not result.success:
            logger.warning(
                "Webhook delivery failed: %s -> %s: %s", webhook.id, webhook.url, result.error
            )

    def get_stats(self) -> dict:
        """Get dispatcher statistics."""
        with self._lock:
            stats: dict[str, Any] = {
                "deliveries": self._deliveries,
                "successes": self._successes,
                "failures": self._failures,
                "rate_limited": self._rate_limited,
                "success_rate": (
                    self._successes / self._deliveries if self._deliveries > 0 else 1.0
                ),
                "active_workers": len(self._executor._threads),
            }

        # Add rate limiter stats if enabled
        rate_limiter = get_event_rate_limiter()
        if rate_limiter:
            stats["rate_limiter"] = rate_limiter.get_stats()

        return stats

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the dispatcher."""
        self._shutdown = True
        self._executor.shutdown(wait=wait)
        logger.info("Webhook dispatcher shutdown")


# =============================================================================
# Global Dispatcher
# =============================================================================

_dispatcher: WebhookDispatcher | None = None


def get_dispatcher() -> WebhookDispatcher:
    """Get or create the global webhook dispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = WebhookDispatcher()
    return _dispatcher


def dispatch_event(event_type: str, data: dict) -> None:
    """
    Dispatch an event to all registered webhooks.

    Convenience function that uses the global dispatcher.

    Args:
        event_type: Event type string (e.g., "debate_end")
        data: Event data dict
    """
    dispatcher = get_dispatcher()
    dispatcher.dispatch_event(event_type, data)


def shutdown_dispatcher(wait: bool = True) -> None:
    """Shutdown the global dispatcher."""
    global _dispatcher
    if _dispatcher is not None:
        _dispatcher.shutdown(wait=wait)
        _dispatcher = None


# =============================================================================
# Receipt Delivery Helpers
# =============================================================================


def dispatch_receipt_ready(
    gauntlet_id: str,
    receipt_id: str,
    verdict: str,
    confidence: float,
    formats_available: list | None = None,
) -> None:
    """
    Dispatch a receipt_ready event when a gauntlet receipt is generated.

    Args:
        gauntlet_id: The gauntlet run ID
        receipt_id: The receipt ID
        verdict: The verdict (PASS, FAIL, INCONCLUSIVE)
        confidence: Confidence score
        formats_available: List of available export formats
    """
    dispatch_event(
        "receipt_ready",
        {
            "gauntlet_id": gauntlet_id,
            "receipt_id": receipt_id,
            "verdict": verdict,
            "confidence": confidence,
            "formats_available": formats_available or ["json", "sarif", "csv", "pdf"],
            "receipt_url": f"/api/v1/gauntlet/{gauntlet_id}/receipt",
        },
    )


def dispatch_receipt_exported(
    gauntlet_id: str,
    receipt_id: str,
    format: str,
    size_bytes: int = 0,
) -> None:
    """
    Dispatch a receipt_exported event when a receipt is exported.

    Args:
        gauntlet_id: The gauntlet run ID
        receipt_id: The receipt ID
        format: Export format used (json, sarif, csv, pdf)
        size_bytes: Size of the exported data
    """
    dispatch_event(
        "receipt_exported",
        {
            "gauntlet_id": gauntlet_id,
            "receipt_id": receipt_id,
            "format": format,
            "size_bytes": size_bytes,
        },
    )


def dispatch_explanation_ready(
    debate_id: str,
    confidence: float,
    consensus_reached: bool,
) -> None:
    """
    Dispatch an explanation_ready event when a decision explanation is available.

    Args:
        debate_id: The debate ID
        confidence: Confidence score
        consensus_reached: Whether consensus was reached
    """
    dispatch_event(
        "explanation_ready",
        {
            "debate_id": debate_id,
            "confidence": confidence,
            "consensus_reached": consensus_reached,
            "explanation_url": f"/api/v1/debates/{debate_id}/explanation",
        },
    )


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "WebhookDispatcher",
    "get_dispatcher",
    "dispatch_event",
    "dispatch_webhook",
    "dispatch_webhook_with_retry",
    "register_webhook_store_provider",
    "shutdown_dispatcher",
    "DeliveryResult",
    # Receipt delivery helpers
    "dispatch_receipt_ready",
    "dispatch_receipt_exported",
    "dispatch_explanation_ready",
]
