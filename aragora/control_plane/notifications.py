"""
Notification Dispatcher for Aragora Control Plane.

Provides resilient notification delivery with:
- Retry logic with exponential backoff
- Circuit breaker per channel
- Queue persistence via Redis Streams
- Email provider (SMTP/SendGrid)
- Async delivery with rate limiting

This module extends channels.py with enterprise-grade delivery guarantees.
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, TYPE_CHECKING
from collections.abc import Callable

from aragora.control_plane.channels import (
    ChannelConfig,
    ChannelProvider,
    NotificationChannel,
    NotificationEventType,
    NotificationManager,
    NotificationMessage,
    NotificationPriority,
    NotificationResult,
)
from aragora.resilience import CircuitBreaker

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_default_dispatcher: NotificationDispatcher | None = None

# =============================================================================
# Configuration
# =============================================================================


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for a retry attempt with exponential backoff."""
        delay = min(
            self.initial_delay_seconds * (self.exponential_base**attempt),
            self.max_delay_seconds,
        )
        if self.jitter:
            import random

            delay = delay * (0.5 + random.random())  # noqa: S311 -- retry jitter
        return delay


@dataclass
class NotificationDispatcherConfig:
    """Configuration for the notification dispatcher."""

    retry_config: RetryConfig = field(default_factory=RetryConfig)
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_cooldown_seconds: float = 120.0
    queue_enabled: bool = True
    queue_stream_key: str = "aragora:notifications:pending"
    queue_consumer_group: str = "notification-workers"
    queue_batch_size: int = 10
    max_concurrent_deliveries: int = 20
    rate_limit_per_channel: int = 100  # per minute


@dataclass
class QueuedNotification:
    """A notification queued for delivery."""

    id: str
    message: NotificationMessage
    channel_config: ChannelConfig
    attempt: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    next_retry_at: datetime | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for queue storage."""
        return {
            "id": self.id,
            "message": self.message.to_dict(),
            "channel_type": self.channel_config.channel_type.value,
            "channel_config": {
                "enabled": self.channel_config.enabled,
                "workspace_id": self.channel_config.workspace_id,
                "slack_webhook_url": self.channel_config.slack_webhook_url,
                "slack_channel": self.channel_config.slack_channel,
                "teams_webhook_url": self.channel_config.teams_webhook_url,
                "email_recipients": self.channel_config.email_recipients,
                "email_from": self.channel_config.email_from,
                "smtp_host": self.channel_config.smtp_host,
                "smtp_port": self.channel_config.smtp_port,
                "webhook_url": self.channel_config.webhook_url,
            },
            "attempt": self.attempt,
            "created_at": self.created_at.isoformat(),
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueuedNotification:
        """Deserialize from queue storage."""
        message_data = data["message"]
        message = NotificationMessage(
            event_type=NotificationEventType(message_data["event_type"]),
            title=message_data["title"],
            body=message_data["body"],
            priority=NotificationPriority(message_data["priority"]),
            metadata=message_data.get("metadata", {}),
            timestamp=datetime.fromisoformat(message_data["timestamp"]),
            workspace_id=message_data.get("workspace_id"),
            link_url=message_data.get("link_url"),
            link_text=message_data.get("link_text"),
        )

        config_data = data["channel_config"]
        channel_config = ChannelConfig(
            channel_type=NotificationChannel(data["channel_type"]),
            enabled=config_data.get("enabled", True),
            workspace_id=config_data.get("workspace_id"),
            slack_webhook_url=config_data.get("slack_webhook_url"),
            slack_channel=config_data.get("slack_channel"),
            teams_webhook_url=config_data.get("teams_webhook_url"),
            email_recipients=config_data.get("email_recipients", []),
            email_from=config_data.get("email_from"),
            smtp_host=config_data.get("smtp_host"),
            smtp_port=config_data.get("smtp_port", 587),
            webhook_url=config_data.get("webhook_url"),
        )

        return cls(
            id=data["id"],
            message=message,
            channel_config=channel_config,
            attempt=data.get("attempt", 0),
            created_at=datetime.fromisoformat(data["created_at"]),
            next_retry_at=(
                datetime.fromisoformat(data["next_retry_at"]) if data.get("next_retry_at") else None
            ),
            last_error=data.get("last_error"),
        )


# =============================================================================
# Email Provider
# =============================================================================


class EmailProvider(ChannelProvider):
    """Email notification provider using SMTP."""

    async def send(self, message: NotificationMessage, config: ChannelConfig) -> NotificationResult:
        """Send notification via email."""
        try:
            if not config.email_recipients:
                return NotificationResult(
                    success=False,
                    channel=NotificationChannel.EMAIL,
                    error="No email recipients configured",
                )

            if not config.smtp_host:
                return NotificationResult(
                    success=False,
                    channel=NotificationChannel.EMAIL,
                    error="No SMTP host configured",
                )

            html_content, text_content = self.format_message(message)

            # Run SMTP in thread pool to avoid blocking
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._send_smtp,
                config,
                message.title,
                html_content,
                text_content,
            )

            return NotificationResult(
                success=True,
                channel=NotificationChannel.EMAIL,
                message_id=str(uuid.uuid4()),
            )

        except (
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            ConnectionError,
            TimeoutError,
            smtplib.SMTPException,
        ) as e:
            logger.error("Email send error: %s", e)
            return NotificationResult(
                success=False,
                channel=NotificationChannel.EMAIL,
                error="Email delivery failed",
            )

    def _send_smtp(
        self,
        config: ChannelConfig,
        subject: str,
        html_content: str,
        text_content: str,
    ) -> None:
        """Send email via SMTP (blocking, run in thread pool)."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config.email_from or "noreply@aragora.ai"
        msg["To"] = ", ".join(config.email_recipients)

        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(config.smtp_host or "localhost", config.smtp_port) as server:
            server.starttls()
            # Note: In production, credentials would be passed via config
            server.send_message(msg)

    def format_message(self, message: NotificationMessage) -> tuple[str, str]:
        """Format message as HTML and plain text."""
        priority_color = {
            NotificationPriority.LOW: "#6b7280",
            NotificationPriority.NORMAL: "#3b82f6",
            NotificationPriority.HIGH: "#f59e0b",
            NotificationPriority.URGENT: "#ef4444",
        }.get(message.priority, "#3b82f6")

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                .header {{ background: {priority_color}; color: white; padding: 16px; }}
                .body {{ padding: 16px; }}
                .footer {{ padding: 16px; color: #6b7280; font-size: 12px; }}
                .button {{ background: {priority_color}; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>{message.title}</h2>
            </div>
            <div class="body">
                <p>{message.body}</p>
                {"<p><a class='button' href='" + message.link_url + "'>" + (message.link_text or "View Details") + "</a></p>" if message.link_url else ""}
            </div>
            <div class="footer">
                Aragora Control Plane | {message.event_type.value} | {message.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")}
            </div>
        </body>
        </html>
        """

        text = f"""
{message.title}

{message.body}

{message.link_url if message.link_url else ""}

---
Aragora Control Plane | {message.event_type.value} | {message.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")}
        """

        return html.strip(), text.strip()


# =============================================================================
# Notification Dispatcher
# =============================================================================


class NotificationDispatcher:
    """
    Resilient notification dispatcher with retry, circuit breaker, and queue persistence.

    Usage:
        # Create dispatcher
        dispatcher = NotificationDispatcher(
            manager=notification_manager,
            redis=redis_client,  # Optional, for queue persistence
        )

        # Dispatch notification (queued and retried automatically)
        results = await dispatcher.dispatch(
            event_type=NotificationEventType.TASK_COMPLETED,
            title="Task Completed",
            body="Your task finished successfully",
        )

        # Start background worker for queue processing
        await dispatcher.start_worker()
    """

    def __init__(
        self,
        manager: NotificationManager,
        redis: Redis | None = None,
        config: NotificationDispatcherConfig | None = None,
    ) -> None:
        self._manager = manager
        self._redis = redis
        self._config = config or NotificationDispatcherConfig()

        # Circuit breakers per channel
        self._circuit_breakers: dict[NotificationChannel, CircuitBreaker] = {}

        # Rate limiting
        self._rate_limiters: dict[NotificationChannel, list[float]] = {}

        # Metrics
        self._metrics: dict[str, Any] = {
            "total_dispatched": 0,
            "total_delivered": 0,
            "total_failed": 0,
            "total_retried": 0,
            "by_channel": {},
        }

        # Worker state
        self._worker_task: asyncio.Task[None] | None = None
        self._shutdown = False

        # Register email provider if not already registered
        if NotificationChannel.EMAIL not in self._manager._providers:
            self._manager._providers[NotificationChannel.EMAIL] = EmailProvider()

    def _get_circuit_breaker(self, channel: NotificationChannel) -> CircuitBreaker:
        """Get or create circuit breaker for a channel."""
        if channel not in self._circuit_breakers:
            self._circuit_breakers[channel] = CircuitBreaker(
                name=f"notification-{channel.value}",
                failure_threshold=self._config.circuit_breaker_failure_threshold,
                cooldown_seconds=self._config.circuit_breaker_cooldown_seconds,
            )
        return self._circuit_breakers[channel]

    def _check_rate_limit(self, channel: NotificationChannel) -> bool:
        """Check if we're within rate limits for a channel."""
        now = time.time()
        window_start = now - 60  # 1 minute window

        if channel not in self._rate_limiters:
            self._rate_limiters[channel] = []

        # Clean old entries
        self._rate_limiters[channel] = [t for t in self._rate_limiters[channel] if t > window_start]

        if len(self._rate_limiters[channel]) >= self._config.rate_limit_per_channel:
            return False

        self._rate_limiters[channel].append(now)
        return True

    async def dispatch(
        self,
        event_type: NotificationEventType,
        title: str,
        body: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        workspace_id: str | None = None,
        link_url: str | None = None,
        link_text: str | None = None,
    ) -> list[NotificationResult]:
        """
        Dispatch a notification to all applicable channels with resilience.

        The notification is:
        1. Checked against circuit breakers
        2. Rate limited per channel
        3. Queued for persistence (if Redis available)
        4. Delivered with automatic retry on failure

        Returns:
            List of NotificationResult for each channel attempted
        """
        message = NotificationMessage(
            event_type=event_type,
            title=title,
            body=body,
            priority=priority,
            metadata=metadata or {},
            workspace_id=workspace_id,
            link_url=link_url,
            link_text=link_text,
        )

        # Find applicable channels
        channels = self._manager._filter_channels(message)
        if not channels:
            logger.debug("No channels configured for event %s", event_type.value)
            return []

        self._metrics["total_dispatched"] += 1

        # Dispatch to each channel
        tasks = []
        for config in channels:
            tasks.append(self._dispatch_to_channel(message, config))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        notification_results: list[NotificationResult] = []
        for result in results:
            if isinstance(result, NotificationResult):
                notification_results.append(result)
            elif isinstance(result, Exception):
                logger.warning("Notification dispatch failed: %s", result)
                notification_results.append(
                    NotificationResult(
                        success=False,
                        channel=NotificationChannel.WEBHOOK,
                        error="Notification dispatch failed",
                    )
                )

        return notification_results

    async def _dispatch_to_channel(
        self,
        message: NotificationMessage,
        config: ChannelConfig,
    ) -> NotificationResult:
        """Dispatch to a single channel with circuit breaker and retry."""
        channel = config.channel_type
        breaker = self._get_circuit_breaker(channel)

        # Check circuit breaker
        if not breaker.can_proceed():
            logger.warning("Circuit breaker open for %s, skipping", channel.value)
            return NotificationResult(
                success=False,
                channel=channel,
                error="Circuit breaker open",
            )

        # Check rate limit
        if not self._check_rate_limit(channel):
            logger.warning("Rate limit exceeded for %s, queueing", channel.value)
            if self._config.queue_enabled and self._redis:
                await self._queue_notification(message, config)
            return NotificationResult(
                success=False,
                channel=channel,
                error="Rate limited - queued for later",
            )

        # Attempt delivery with retry
        return await self._deliver_with_retry(message, config)

    async def _deliver_with_retry(
        self,
        message: NotificationMessage,
        config: ChannelConfig,
        attempt: int = 0,
    ) -> NotificationResult:
        """Deliver notification with exponential backoff retry."""
        channel = config.channel_type
        breaker = self._get_circuit_breaker(channel)
        retry_config = self._config.retry_config

        try:
            result = await self._manager._send_to_channel(message, config)

            if result.success:
                breaker.record_success()
                self._metrics["total_delivered"] += 1
                self._update_channel_metrics(channel, success=True)
                return result

            # Delivery failed - consider retry
            breaker.record_failure()

            if attempt < retry_config.max_retries:
                delay = retry_config.get_delay(attempt)
                logger.info(
                    "Notification to %s failed, retrying in %.1fs (attempt %s/%s)",
                    channel.value,
                    delay,
                    attempt + 1,
                    retry_config.max_retries,
                )
                self._metrics["total_retried"] += 1

                await asyncio.sleep(delay)
                return await self._deliver_with_retry(message, config, attempt + 1)

            # Max retries exceeded - queue for later if possible
            if self._config.queue_enabled and self._redis:
                await self._queue_notification(message, config, attempt, result.error)

            self._metrics["total_failed"] += 1
            self._update_channel_metrics(channel, success=False)
            return result

        except (
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            ConnectionError,
            TimeoutError,
            AttributeError,
        ) as e:
            breaker.record_failure()
            self._metrics["total_failed"] += 1
            self._update_channel_metrics(channel, success=False)

            logger.error("Error delivering notification to %s: %s", channel.value, e)
            return NotificationResult(
                success=False,
                channel=channel,
                error="Notification delivery failed",
            )

    def _update_channel_metrics(self, channel: NotificationChannel, success: bool) -> None:
        """Update per-channel metrics."""
        channel_key = channel.value
        if channel_key not in self._metrics["by_channel"]:
            self._metrics["by_channel"][channel_key] = {"success": 0, "failed": 0}

        if success:
            self._metrics["by_channel"][channel_key]["success"] += 1
        else:
            self._metrics["by_channel"][channel_key]["failed"] += 1

    # =========================================================================
    # Queue Operations
    # =========================================================================

    async def _queue_notification(
        self,
        message: NotificationMessage,
        config: ChannelConfig,
        attempt: int = 0,
        last_error: str | None = None,
    ) -> None:
        """Queue a notification for later delivery."""
        if not self._redis:
            logger.warning("Redis not available, cannot queue notification")
            return

        retry_config = self._config.retry_config
        next_retry_at = None
        if attempt < retry_config.max_retries:
            delay_seconds = retry_config.get_delay(attempt)
            next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

        queued = QueuedNotification(
            id=str(uuid.uuid4()),
            message=message,
            channel_config=config,
            attempt=attempt,
            next_retry_at=next_retry_at,
            last_error=last_error,
        )

        try:
            await self._redis.xadd(
                self._config.queue_stream_key,
                {"data": json.dumps(queued.to_dict())},
            )
            logger.info("Queued notification %s for %s", queued.id, config.channel_type.value)
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            logger.error("Failed to queue notification: %s", e)

    async def start_worker(self) -> None:
        """Start background worker for processing queued notifications."""
        if self._worker_task is not None:
            logger.warning("Worker already running")
            return

        if not self._redis:
            logger.warning("Redis not available, cannot start worker")
            return

        self._shutdown = False
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Notification worker started")

    async def stop_worker(self) -> None:
        """Stop the background worker."""
        self._shutdown = True
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                logger.debug("Notification worker task cancelled cleanly")  # noqa: PERF203 -- expected on shutdown
            self._worker_task = None
        logger.info("Notification worker stopped")

    async def _worker_loop(self) -> None:
        """Background worker loop for processing queued notifications."""
        # Guard: start_worker checks redis availability, but mypy doesn't track this
        if self._redis is None:
            logger.error("Redis not available in worker loop")
            return

        # Ensure consumer group exists
        try:
            await self._redis.xgroup_create(
                self._config.queue_stream_key,
                self._config.queue_consumer_group,
                id="0",
                mkstream=True,
            )
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            if "BUSYGROUP" not in str(e):
                logger.error("Failed to create consumer group: %s", e)
                return

        consumer_name = f"worker-{uuid.uuid4().hex[:8]}"

        while not self._shutdown:
            try:
                # Read from queue
                messages = await self._redis.xreadgroup(
                    self._config.queue_consumer_group,
                    consumer_name,
                    {self._config.queue_stream_key: ">"},
                    count=self._config.queue_batch_size,
                    block=5000,  # 5 second timeout
                )

                if not messages:
                    continue

                for stream_name, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        await self._process_queued_message(message_id, fields)

            except asyncio.CancelledError:
                break
            except (
                ConnectionError,
                TimeoutError,
                OSError,
                RuntimeError,
                ValueError,
                TypeError,
            ) as e:
                logger.error("Worker error: %s", e)
                await asyncio.sleep(5)

    async def _process_queued_message(
        self,
        message_id: bytes,
        fields: dict[bytes, bytes],
    ) -> None:
        """Process a single queued notification."""
        # Guard: called from _worker_loop which already checked redis
        if self._redis is None:
            logger.error("Redis not available for message processing")
            return

        try:
            data = json.loads(fields[b"data"].decode())
            queued = QueuedNotification.from_dict(data)

            # Attempt delivery
            result = await self._deliver_with_retry(
                queued.message,
                queued.channel_config,
                queued.attempt,
            )

            if result.success:
                # Acknowledge and remove
                await self._redis.xack(
                    self._config.queue_stream_key,
                    self._config.queue_consumer_group,
                    message_id,
                )
                await self._redis.xdel(self._config.queue_stream_key, message_id)
                logger.info("Delivered queued notification %s", queued.id)
            else:
                # Re-queue with incremented attempt if not max retries
                if queued.attempt < self._config.retry_config.max_retries:
                    queued.attempt += 1
                    queued.last_error = result.error
                    await self._redis.xack(
                        self._config.queue_stream_key,
                        self._config.queue_consumer_group,
                        message_id,
                    )
                    await self._redis.xdel(self._config.queue_stream_key, message_id)
                    await self._queue_notification(
                        queued.message,
                        queued.channel_config,
                        queued.attempt,
                        result.error,
                    )
                else:
                    # Move to dead letter queue
                    await self._move_to_dlq(queued, result.error)
                    await self._redis.xack(
                        self._config.queue_stream_key,
                        self._config.queue_consumer_group,
                        message_id,
                    )
                    await self._redis.xdel(self._config.queue_stream_key, message_id)

        except (
            ConnectionError,
            TimeoutError,
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            KeyError,
        ) as e:
            logger.error("Error processing queued message: %s", e)

    async def _move_to_dlq(
        self,
        queued: QueuedNotification,
        error: str | None,
    ) -> None:
        """Move failed notification to dead letter queue."""
        if not self._redis:
            return

        dlq_key = f"{self._config.queue_stream_key}:dlq"
        queued.last_error = error

        try:
            await self._redis.xadd(
                dlq_key,
                {"data": json.dumps(queued.to_dict())},
                maxlen=10000,  # Keep last 10k failed notifications
            )
            logger.warning("Moved notification %s to DLQ after max retries", queued.id)
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            logger.error("Failed to move to DLQ: %s", e)

    # =========================================================================
    # Metrics and Status
    # =========================================================================

    def get_metrics(self) -> dict[str, Any]:
        """Get dispatcher metrics."""
        return {
            **self._metrics,
            "circuit_breakers": {
                channel.value: {
                    "state": breaker.get_status(),
                    "failures": breaker.failures,
                }
                for channel, breaker in self._circuit_breakers.items()
            },
            "worker_running": self._worker_task is not None and not self._worker_task.done(),
        }

    def get_circuit_breaker_status(self) -> dict[str, str]:
        """Get status of all circuit breakers."""
        return {
            channel.value: breaker.get_status()
            for channel, breaker in self._circuit_breakers.items()
        }

    async def get_queue_depth(self) -> int:
        """Get number of pending notifications in queue."""
        if not self._redis:
            return 0

        try:
            info = await self._redis.xinfo_stream(self._config.queue_stream_key)
            return info.get("length", 0)
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.debug("Redis connection error getting queue depth: %s", e)
            return 0
        except KeyError:
            # Stream doesn't exist yet
            return 0

    async def get_dlq_depth(self) -> int:
        """Get number of notifications in dead letter queue."""
        if not self._redis:
            return 0

        try:
            dlq_key = f"{self._config.queue_stream_key}:dlq"
            info = await self._redis.xinfo_stream(dlq_key)
            return info.get("length", 0)
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.debug("Redis connection error getting DLQ depth: %s", e)
            return 0
        except KeyError:
            # Stream doesn't exist yet
            return 0


# =============================================================================
# Factory Function
# =============================================================================


def create_notification_dispatcher(
    manager: NotificationManager | None = None,
    redis: Redis | None = None,
    config: NotificationDispatcherConfig | None = None,
) -> NotificationDispatcher:
    """
    Create a notification dispatcher with sensible defaults.

    Args:
        manager: Existing NotificationManager or None to create new one
        redis: Optional Redis client for queue persistence
        config: Optional dispatcher configuration

    Returns:
        Configured NotificationDispatcher instance
    """
    if manager is None and redis is None and config is None and _default_dispatcher is not None:
        return _default_dispatcher

    if manager is None:
        manager = NotificationManager()

    return NotificationDispatcher(
        manager=manager,
        redis=redis,
        config=config,
    )


def get_default_notification_dispatcher() -> NotificationDispatcher | None:
    """Get the default notification dispatcher, if configured."""
    return _default_dispatcher


def set_default_notification_dispatcher(dispatcher: NotificationDispatcher) -> None:
    """Set the default notification dispatcher."""
    global _default_dispatcher
    _default_dispatcher = dispatcher


# =============================================================================
# Event Handler Decorator
# =============================================================================


def on_notification_event(
    event_types: list[NotificationEventType],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to register a function as a notification event handler.

    Usage:
        @on_notification_event([NotificationEventType.TASK_COMPLETED])
        async def handle_task_completed(message: NotificationMessage) -> None:
            # Custom handling logic
            pass
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, "_notification_events", event_types)
        return func

    return decorator


# =============================================================================
# Security Notifications
# =============================================================================


async def send_security_notification(
    title: str,
    message: str,
    severity: str = "medium",
    metadata: dict[str, Any] | None = None,
) -> bool:
    """
    Send a security-related notification to the security team.

    This is a convenience function for break-glass access, suspicious activity,
    and other security events that require immediate attention.

    Args:
        title: Short notification title
        message: Detailed notification message
        severity: "low", "medium", "high", or "critical"
        metadata: Optional additional data to include

    Returns:
        True if notification was queued/sent successfully, False otherwise
    """
    dispatcher = get_default_notification_dispatcher()
    if dispatcher is None:
        logger.warning("Security notification not sent (no dispatcher): %s", title)
        return False

    # Map severity to priority
    priority_map = {
        "low": NotificationPriority.LOW,
        "medium": NotificationPriority.NORMAL,
        "high": NotificationPriority.HIGH,
        "critical": NotificationPriority.URGENT,
    }
    priority = priority_map.get(severity, NotificationPriority.HIGH)

    try:
        results = await dispatcher.dispatch(
            event_type=NotificationEventType.SYSTEM_ALERT,
            title=f"[SECURITY] {title}",
            body=message,
            priority=priority,
            metadata=metadata or {},
        )
        # Consider success if any channel delivered
        return any(r.success for r in results)
    except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
        logger.error("Failed to send security notification: %s", e)
        return False


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Config
    "RetryConfig",
    "NotificationDispatcherConfig",
    "QueuedNotification",
    # Providers
    "EmailProvider",
    # Dispatcher
    "NotificationDispatcher",
    "create_notification_dispatcher",
    "get_default_notification_dispatcher",
    "set_default_notification_dispatcher",
    # Decorators
    "on_notification_event",
    # Security
    "send_security_notification",
]
