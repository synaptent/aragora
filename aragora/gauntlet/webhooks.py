"""Webhook notifications for gauntlet events.

Provides async webhook delivery with:
- Configurable endpoints per event type
- Retry logic with exponential backoff
- HMAC signature verification
- Rate limiting and circuit breaking
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class WebhookEventType(Enum):
    """Webhook event types."""

    GAUNTLET_STARTED = "gauntlet.started"
    GAUNTLET_PROGRESS = "gauntlet.progress"
    GAUNTLET_COMPLETED = "gauntlet.completed"
    GAUNTLET_FAILED = "gauntlet.failed"
    FINDING_CRITICAL = "finding.critical"


@dataclass
class WebhookConfig:
    """Configuration for a webhook endpoint."""

    url: str
    secret: str | None = None
    events: list[WebhookEventType] = field(default_factory=list)
    enabled: bool = True
    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    retry_backoff_multiplier: float = 2.0
    headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not self.url:
            raise ValueError("Webhook URL is required")
        if not self.url.startswith(("http://", "https://")):
            raise ValueError("Webhook URL must be HTTP or HTTPS")
        if self.url.startswith("http://localhost") or self.url.startswith("http://127.0.0.1"):
            allow_localhost = os.getenv("ARAGORA_WEBHOOK_ALLOW_LOCALHOST", "false")
            if allow_localhost.lower() != "true":
                raise ValueError(
                    "Localhost webhooks disabled. Set ARAGORA_WEBHOOK_ALLOW_LOCALHOST=true to enable."
                )
        if not self.events:
            self.events = list(WebhookEventType)


@dataclass
class WebhookPayload:
    """Payload for a webhook delivery."""

    event_type: WebhookEventType
    timestamp: str
    gauntlet_id: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event": self.event_type.value,
            "timestamp": self.timestamp,
            "gauntlet_id": self.gauntlet_id,
            "data": self.data,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)


@dataclass
class WebhookDeliveryResult:
    """Result of a webhook delivery attempt."""

    success: bool
    status_code: int | None = None
    response_body: str | None = None
    error: str | None = None
    attempts: int = 0
    duration_ms: float = 0.0


class WebhookManager:
    """Manages webhook subscriptions and deliveries."""

    def __init__(self) -> None:
        self._configs: dict[str, WebhookConfig] = {}
        self._delivery_queue: asyncio.Queue[tuple[str, WebhookPayload]] = asyncio.Queue()
        self._running = False
        self._worker_task: asyncio.Task[None] | None = None
        self._circuit_breaker: dict[
            str, tuple[int, float]
        ] = {}  # url -> (failures, last_failure_time)
        self._circuit_breaker_threshold = 5
        self._circuit_breaker_reset_seconds = 60.0

    def register(self, name: str, config: WebhookConfig) -> None:
        """Register a webhook endpoint."""
        self._configs[name] = config
        logger.info(
            "Registered webhook '%s' -> %s for events: %s",
            name,
            config.url,
            [e.value for e in config.events],
        )

    def unregister(self, name: str) -> bool:
        """Unregister a webhook endpoint."""
        if name in self._configs:
            del self._configs[name]
            return True
        return False

    def list_webhooks(self) -> list[dict[str, Any]]:
        """List all registered webhooks."""
        return [
            {
                "name": name,
                "url": config.url,
                "enabled": config.enabled,
                "events": [e.value for e in config.events],
            }
            for name, config in self._configs.items()
        ]

    async def start(self) -> None:
        """Start the webhook delivery worker."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._delivery_worker())
        logger.info("Webhook delivery worker started")

    async def stop(self) -> None:
        """Stop the webhook delivery worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Webhook delivery worker stopped")

    async def emit(
        self,
        event_type: WebhookEventType,
        gauntlet_id: str,
        data: dict[str, Any],
    ) -> None:
        """Emit a webhook event to all subscribed endpoints."""
        from datetime import datetime, timezone

        payload = WebhookPayload(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            gauntlet_id=gauntlet_id,
            data=data,
        )

        for name, config in self._configs.items():
            if not config.enabled:
                continue
            if event_type not in config.events:
                continue

            await self._delivery_queue.put((name, payload))

    async def emit_gauntlet_started(
        self,
        gauntlet_id: str,
        input_type: str,
        input_summary: str,
        agents: list[str],
    ) -> None:
        """Emit gauntlet started event."""
        await self.emit(
            WebhookEventType.GAUNTLET_STARTED,
            gauntlet_id,
            {
                "input_type": input_type,
                "input_summary": input_summary[:500],
                "agents": agents,
            },
        )

    async def emit_gauntlet_progress(
        self,
        gauntlet_id: str,
        progress: float,
        phase: str,
        message: str,
    ) -> None:
        """Emit gauntlet progress event."""
        await self.emit(
            WebhookEventType.GAUNTLET_PROGRESS,
            gauntlet_id,
            {
                "progress": progress,
                "phase": phase,
                "message": message,
            },
        )

    async def emit_gauntlet_completed(
        self,
        gauntlet_id: str,
        verdict: str,
        confidence: float,
        total_findings: int,
        critical_count: int,
        high_count: int,
        robustness_score: float,
        duration_seconds: float,
    ) -> None:
        """Emit gauntlet completed event."""
        await self.emit(
            WebhookEventType.GAUNTLET_COMPLETED,
            gauntlet_id,
            {
                "verdict": verdict,
                "confidence": confidence,
                "total_findings": total_findings,
                "critical_count": critical_count,
                "high_count": high_count,
                "robustness_score": robustness_score,
                "duration_seconds": duration_seconds,
            },
        )

    async def emit_gauntlet_failed(
        self,
        gauntlet_id: str,
        error: str,
    ) -> None:
        """Emit gauntlet failed event."""
        await self.emit(
            WebhookEventType.GAUNTLET_FAILED,
            gauntlet_id,
            {"error": error},
        )

    async def emit_critical_finding(
        self,
        gauntlet_id: str,
        finding_id: str,
        title: str,
        category: str,
        description: str,
    ) -> None:
        """Emit critical finding event (immediate notification)."""
        await self.emit(
            WebhookEventType.FINDING_CRITICAL,
            gauntlet_id,
            {
                "finding_id": finding_id,
                "title": title,
                "category": category,
                "description": description[:500],
            },
        )

    def _is_circuit_open(self, url: str) -> bool:
        """Check if circuit breaker is open for a URL."""
        if url not in self._circuit_breaker:
            return False
        failures, last_failure = self._circuit_breaker[url]
        if failures >= self._circuit_breaker_threshold:
            if time.time() - last_failure < self._circuit_breaker_reset_seconds:
                return True
            # Reset circuit after timeout
            del self._circuit_breaker[url]
        return False

    def _record_failure(self, url: str) -> None:
        """Record a delivery failure for circuit breaker."""
        if url in self._circuit_breaker:
            failures, _ = self._circuit_breaker[url]
            self._circuit_breaker[url] = (failures + 1, time.time())
        else:
            self._circuit_breaker[url] = (1, time.time())

    def _record_success(self, url: str) -> None:
        """Record a delivery success (resets circuit breaker)."""
        if url in self._circuit_breaker:
            del self._circuit_breaker[url]

    async def _delivery_worker(self) -> None:
        """Background worker that processes webhook deliveries."""
        while self._running:
            try:
                name, payload = await asyncio.wait_for(
                    self._delivery_queue.get(),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue

            config = self._configs.get(name)
            if not config or not config.enabled:
                continue

            if self._is_circuit_open(config.url):
                logger.warning("Circuit open for webhook '%s', skipping delivery", name)
                continue

            result = await self._deliver_with_retry(config, payload)

            if result.success:
                self._record_success(config.url)
                logger.debug(
                    "Webhook '%s' delivered: %s (%s attempts, %.0fms)",
                    name,
                    payload.event_type.value,
                    result.attempts,
                    result.duration_ms,
                )
            else:
                self._record_failure(config.url)
                logger.warning(
                    "Webhook '%s' failed: %s (%s attempts)", name, result.error, result.attempts
                )

    async def _deliver_with_retry(
        self,
        config: WebhookConfig,
        payload: WebhookPayload,
    ) -> WebhookDeliveryResult:
        """Deliver webhook with retry logic."""
        import aiohttp

        attempts = 0
        delay = config.retry_delay_seconds
        last_error: str | None = None
        start_time = time.time()

        while attempts < config.max_retries:
            attempts += 1

            try:
                result = await self._deliver_once(config, payload)
                if result.success:
                    result.attempts = attempts
                    result.duration_ms = (time.time() - start_time) * 1000
                    return result
                last_error = result.error
            except aiohttp.ClientError as e:
                last_error = str(e)
            except asyncio.TimeoutError:
                last_error = "Request timed out"

            if attempts < config.max_retries:
                await asyncio.sleep(delay)
                delay *= config.retry_backoff_multiplier

        return WebhookDeliveryResult(
            success=False,
            error=last_error or "Unknown error",
            attempts=attempts,
            duration_ms=(time.time() - start_time) * 1000,
        )

    async def _deliver_once(
        self,
        config: WebhookConfig,
        payload: WebhookPayload,
    ) -> WebhookDeliveryResult:
        """Deliver a single webhook request."""
        import aiohttp

        body = payload.to_json()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Aragora-Webhook/1.0",
            "X-Aragora-Event": payload.event_type.value,
            "X-Aragora-Delivery": f"{payload.gauntlet_id}-{int(time.time())}",
            **config.headers,
        }

        if config.secret:
            signature = hmac.new(
                config.secret.encode(),
                body.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Aragora-Signature"] = f"sha256={signature}"

        timeout = aiohttp.ClientTimeout(total=config.timeout_seconds)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                config.url,
                data=body,
                headers=headers,
            ) as response:
                response_body = await response.text()

                if 200 <= response.status < 300:
                    return WebhookDeliveryResult(
                        success=True,
                        status_code=response.status,
                        response_body=response_body[:1000],
                    )

                return WebhookDeliveryResult(
                    success=False,
                    status_code=response.status,
                    response_body=response_body[:1000],
                    error=f"HTTP {response.status}",
                )


# Global singleton instance
_webhook_manager: WebhookManager | None = None


def get_webhook_manager() -> WebhookManager:
    """Get the global webhook manager instance."""
    global _webhook_manager
    if _webhook_manager is None:
        _webhook_manager = WebhookManager()
        _load_env_webhooks(_webhook_manager)
    return _webhook_manager


def _load_env_webhooks(manager: WebhookManager) -> None:
    """Load webhook configurations from environment variables."""
    notification_url = os.getenv("ARAGORA_NOTIFICATION_WEBHOOK")
    if notification_url:
        try:
            manager.register(
                "default",
                WebhookConfig(
                    url=notification_url,
                    secret=os.getenv("ARAGORA_WEBHOOK_SECRET"),
                    timeout_seconds=float(os.getenv("ARAGORA_WEBHOOK_TIMEOUT", "30.0")),
                    max_retries=int(os.getenv("ARAGORA_WEBHOOK_MAX_RETRIES", "3")),
                ),
            )
        except ValueError as e:
            logger.warning("Failed to load webhook from environment: %s", e)


async def notify_gauntlet_completed(
    gauntlet_id: str,
    verdict: str,
    confidence: float,
    total_findings: int,
    critical_count: int = 0,
    high_count: int = 0,
    robustness_score: float = 0.0,
    duration_seconds: float = 0.0,
) -> None:
    """Convenience function to notify on gauntlet completion."""
    manager = get_webhook_manager()
    await manager.emit_gauntlet_completed(
        gauntlet_id=gauntlet_id,
        verdict=verdict,
        confidence=confidence,
        total_findings=total_findings,
        critical_count=critical_count,
        high_count=high_count,
        robustness_score=robustness_score,
        duration_seconds=duration_seconds,
    )


__all__ = [
    "WebhookConfig",
    "WebhookEventType",
    "WebhookManager",
    "WebhookPayload",
    "WebhookDeliveryResult",
    "get_webhook_manager",
    "notify_gauntlet_completed",
]
