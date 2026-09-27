"""
Async Webhook Event Dispatcher.

Provides non-blocking webhook delivery using httpx for better performance
under high load. This complements the sync dispatcher for use in async contexts.

Features:
- Non-blocking HTTP delivery with httpx
- Connection pooling for efficiency
- Exponential backoff retry with async sleep
- Distributed tracing integration
- Prometheus metrics

Usage:
    from aragora.events.async_dispatcher import AsyncWebhookDispatcher

    async with AsyncWebhookDispatcher() as dispatcher:
        result = await dispatcher.dispatch(webhook, payload)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.storage.webhook_config_store import WebhookConfig

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Maximum concurrent webhook deliveries
MAX_CONNECTIONS = int(os.environ.get("ARAGORA_WEBHOOK_MAX_CONNECTIONS", "100"))
MAX_CONNECTIONS_PER_HOST = int(os.environ.get("ARAGORA_WEBHOOK_CONNECTIONS_PER_HOST", "10"))

# Retry configuration
MAX_RETRIES = int(os.environ.get("ARAGORA_WEBHOOK_MAX_RETRIES", "3"))
INITIAL_RETRY_DELAY = float(os.environ.get("ARAGORA_WEBHOOK_RETRY_DELAY", "1.0"))
MAX_RETRY_DELAY = float(os.environ.get("ARAGORA_WEBHOOK_MAX_RETRY_DELAY", "60.0"))

# Request timeout in seconds
REQUEST_TIMEOUT = float(os.environ.get("ARAGORA_WEBHOOK_TIMEOUT", "30.0"))
CONNECT_TIMEOUT = float(os.environ.get("ARAGORA_WEBHOOK_CONNECT_TIMEOUT", "10.0"))

# User agent for webhook requests
USER_AGENT = "Aragora-Webhooks/1.0 (async)"

# =============================================================================
# Result Types
# =============================================================================


@dataclass
class AsyncDeliveryResult:
    """Result of an async webhook delivery attempt."""

    success: bool
    status_code: int
    error: str | None = None
    retry_count: int = 0
    duration_ms: float = 0.0


# =============================================================================
# Async Dispatcher
# =============================================================================


class AsyncWebhookDispatcher:
    """
    Async webhook dispatcher using httpx for non-blocking delivery.

    Use as an async context manager:
        async with AsyncWebhookDispatcher() as dispatcher:
            result = await dispatcher.dispatch(webhook, payload)
    """

    def __init__(
        self,
        max_connections: int = MAX_CONNECTIONS,
        max_connections_per_host: int = MAX_CONNECTIONS_PER_HOST,
        timeout: float = REQUEST_TIMEOUT,
        connect_timeout: float = CONNECT_TIMEOUT,
    ):
        self.max_connections = max_connections
        self.max_connections_per_host = max_connections_per_host
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self._client: Any | None = None

    async def __aenter__(self) -> AsyncWebhookDispatcher:
        """Enter async context and create HTTP client."""
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context and close HTTP client."""
        await self.close()

    async def _ensure_client(self) -> Any:
        """Ensure httpx client is initialized."""
        if self._client is None:
            try:
                import httpx

                limits = httpx.Limits(
                    max_connections=self.max_connections,
                    max_keepalive_connections=self.max_connections_per_host,
                )
                timeout = httpx.Timeout(
                    timeout=self.timeout,
                    connect=self.connect_timeout,
                )
                self._client = httpx.AsyncClient(
                    limits=limits,
                    timeout=timeout,
                    follow_redirects=False,  # Security: don't follow redirects
                )
            except ImportError:
                raise ImportError(
                    "httpx is required for async webhook delivery. Install with: pip install httpx"
                )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def dispatch(
        self,
        webhook: WebhookConfig,
        payload: dict[str, Any],
    ) -> tuple[bool, int, str | None]:
        """
        Dispatch a single webhook asynchronously.

        Args:
            webhook: Webhook configuration
            payload: Event payload to send

        Returns:
            Tuple of (success, status_code, error_message)
        """
        from aragora.security.webhook_signing import generate_signature
        from aragora.observability.middleware.tracing import get_trace_id

        client = await self._ensure_client()

        try:
            # Serialize payload
            payload_json = json.dumps(payload, default=str)

            # Generate signature
            signature = generate_signature(payload_json, webhook.secret)

            # Build headers
            headers = {
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "X-Aragora-Signature": signature,
                "X-Aragora-Event": payload.get("event", "unknown"),
                "X-Aragora-Delivery": payload.get("delivery_id", ""),
                "X-Aragora-Timestamp": str(int(time.time())),
            }

            # Add correlation ID for distributed tracing
            correlation_id = (
                payload.get("data", {}).get("correlation_id")
                or payload.get("correlation_id")
                or get_trace_id()
            )
            if correlation_id:
                headers["X-Aragora-Correlation-ID"] = correlation_id

            # Send request
            start_time = time.time()
            response = await client.post(
                webhook.url,
                content=payload_json,
                headers=headers,
            )
            duration_ms = (time.time() - start_time) * 1000

            logger.debug(
                f"Async webhook delivered to {webhook.url}: "
                f"status={response.status_code}, duration={duration_ms:.1f}ms"
            )

            if 200 <= response.status_code < 300:
                return True, response.status_code, None
            else:
                return False, response.status_code, f"HTTP {response.status_code}"

        except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
            logger.warning("Async webhook delivery error for %s: %s", webhook.url, e)
            return False, 0, str(e)

    async def dispatch_with_retry(
        self,
        webhook: WebhookConfig,
        payload: dict[str, Any],
        max_retries: int = MAX_RETRIES,
        initial_delay: float = INITIAL_RETRY_DELAY,
        max_delay: float = MAX_RETRY_DELAY,
    ) -> AsyncDeliveryResult:
        """
        Dispatch webhook with exponential backoff retry.

        Args:
            webhook: Webhook configuration
            payload: Event payload
            max_retries: Maximum retry attempts
            initial_delay: Initial retry delay in seconds
            max_delay: Maximum retry delay in seconds

        Returns:
            AsyncDeliveryResult with outcome
        """
        # Import metrics and tracing lazily
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
        correlation_id = payload.get("correlation_id") or payload.get("data", {}).get(
            "correlation_id"
        )
        start_time = time.time()
        delay = initial_delay

        # Wrapper for delivery with optional tracing
        async def _deliver_with_trace() -> AsyncDeliveryResult:
            nonlocal delay

            for attempt in range(max_retries + 1):
                success, status_code, error = await self.dispatch(webhook, payload)

                if success:
                    return AsyncDeliveryResult(
                        success=True,
                        status_code=status_code,
                        retry_count=attempt,
                        duration_ms=(time.time() - start_time) * 1000,
                    )

                # Don't retry on 4xx errors (client errors)
                if 400 <= status_code < 500:
                    return AsyncDeliveryResult(
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

                    logger.info(
                        f"Retrying async webhook {webhook.id} in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, max_delay)

            return AsyncDeliveryResult(
                success=False,
                status_code=status_code,
                error=error,
                retry_count=max_retries,
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Execute with tracing if available
        if trace_webhook_delivery:
            with trace_webhook_delivery(
                event_type=event_type,
                webhook_id=webhook.id,
                webhook_url=webhook.url,
                correlation_id=correlation_id,
            ) as span:
                result = await _deliver_with_trace()
                span.set_attribute("webhook.success", result.success)
                span.set_attribute("webhook.status_code", result.status_code)
                span.set_attribute("webhook.retry_count", result.retry_count)
                span.set_attribute("webhook.duration_ms", result.duration_ms)
                if result.error:
                    span.set_attribute("webhook.error", result.error[:200])
                return result
        else:
            return await _deliver_with_trace()


# =============================================================================
# Global Async Dispatcher
# =============================================================================

_async_dispatcher: AsyncWebhookDispatcher | None = None


async def get_async_dispatcher() -> AsyncWebhookDispatcher:
    """Get or create the global async dispatcher."""
    global _async_dispatcher

    if _async_dispatcher is None:
        _async_dispatcher = AsyncWebhookDispatcher()
        await _async_dispatcher._ensure_client()

    return _async_dispatcher


async def dispatch_webhook_async(
    webhook: WebhookConfig,
    payload: dict[str, Any],
) -> tuple[bool, int, str | None]:
    """
    Dispatch a webhook asynchronously using the global dispatcher.

    Convenience function for simple async webhook delivery.

    Args:
        webhook: Webhook configuration
        payload: Event payload

    Returns:
        Tuple of (success, status_code, error_message)
    """
    dispatcher = await get_async_dispatcher()
    return await dispatcher.dispatch(webhook, payload)


async def dispatch_webhook_async_with_retry(
    webhook: WebhookConfig,
    payload: dict[str, Any],
    max_retries: int = MAX_RETRIES,
) -> AsyncDeliveryResult:
    """
    Dispatch a webhook asynchronously with retry using the global dispatcher.

    Args:
        webhook: Webhook configuration
        payload: Event payload
        max_retries: Maximum retry attempts

    Returns:
        AsyncDeliveryResult with outcome
    """
    dispatcher = await get_async_dispatcher()
    return await dispatcher.dispatch_with_retry(webhook, payload, max_retries=max_retries)


async def shutdown_async_dispatcher() -> None:
    """Shutdown the global async dispatcher."""
    global _async_dispatcher

    if _async_dispatcher is not None:
        await _async_dispatcher.close()
        _async_dispatcher = None


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AsyncWebhookDispatcher",
    "AsyncDeliveryResult",
    "get_async_dispatcher",
    "dispatch_webhook_async",
    "dispatch_webhook_async_with_retry",
    "shutdown_async_dispatcher",
]
