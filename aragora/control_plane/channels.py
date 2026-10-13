"""
Channel Notifications for the Aragora Control Plane.

Provides notification routing to external channels:
- Slack integration for team notifications
- Microsoft Teams webhooks
- Email notifications (via SMTP or SendGrid)
- Custom webhook endpoints

Notifications are triggered by control plane events:
- Task completions
- Deliberation consensus
- SLA violations
- Agent failures
- Policy violations

This module integrates with the existing connectors for Slack/Teams.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TYPE_CHECKING, cast
from collections.abc import Callable

from aragora.events.notification_types import NotificationEventType, NotificationPriority

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# =============================================================================
# Enums and Types
# =============================================================================


class NotificationChannel(Enum):
    """Supported notification channels."""

    SLACK = "slack"
    TEAMS = "teams"
    EMAIL = "email"
    WEBHOOK = "webhook"


class DeliveryStatus(Enum):
    """Status of notification delivery."""

    PENDING = "pending"  # Queued for delivery
    SENT = "sent"  # Sent to provider
    DELIVERED = "delivered"  # Confirmed delivered (if provider supports)
    FAILED = "failed"  # Delivery failed
    BOUNCED = "bounced"  # Email bounced
    REJECTED = "rejected"  # Rejected by provider
    RATE_LIMITED = "rate_limited"  # Hit rate limit


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NotificationMessage:
    """A notification message to be sent."""

    event_type: NotificationEventType
    title: str
    body: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    workspace_id: str | None = None
    link_url: str | None = None
    link_text: str | None = None

    # Correlation and tracking
    correlation_id: str | None = None  # For request tracing across services
    parent_correlation_id: str | None = None  # For hierarchical tracing
    idempotency_key: str | None = None  # Prevent duplicate deliveries

    def __post_init__(self) -> None:
        """Generate correlation_id if not provided."""
        import uuid

        if self.correlation_id is None:
            self.correlation_id = str(uuid.uuid4())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_type": self.event_type.value,
            "title": self.title,
            "body": self.body,
            "priority": self.priority.value,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "workspace_id": self.workspace_id,
            "link_url": self.link_url,
            "link_text": self.link_text,
            "correlation_id": self.correlation_id,
            "parent_correlation_id": self.parent_correlation_id,
            "idempotency_key": self.idempotency_key,
        }


@dataclass
class ChannelConfig:
    """Configuration for a notification channel."""

    channel_type: NotificationChannel
    enabled: bool = True
    workspace_id: str | None = None
    config_id: str | None = None  # Unique identifier for persistence

    # Slack settings
    slack_webhook_url: str | None = None
    slack_channel: str | None = None
    slack_bot_token: str | None = None

    # Teams settings
    teams_webhook_url: str | None = None

    # Email settings
    email_recipients: list[str] = field(default_factory=list)
    email_from: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587

    # Webhook settings
    webhook_url: str | None = None
    webhook_headers: dict[str, str] = field(default_factory=dict)

    # Filtering
    event_types: list[NotificationEventType] | None = None  # None = all events
    min_priority: NotificationPriority = NotificationPriority.LOW

    def __post_init__(self) -> None:
        """Generate a config_id if not provided."""
        import uuid

        if self.config_id is None:
            self.config_id = str(uuid.uuid4())

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for persistence."""
        return {
            "config_id": self.config_id,
            "channel_type": self.channel_type.value,
            "enabled": self.enabled,
            "workspace_id": self.workspace_id,
            "slack_webhook_url": self.slack_webhook_url,
            "slack_channel": self.slack_channel,
            "slack_bot_token": self.slack_bot_token,
            "teams_webhook_url": self.teams_webhook_url,
            "email_recipients": self.email_recipients,
            "email_from": self.email_from,
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "webhook_url": self.webhook_url,
            "webhook_headers": self.webhook_headers,
            "event_types": [e.value for e in self.event_types] if self.event_types else None,
            "min_priority": self.min_priority.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChannelConfig:
        """Deserialize from dictionary."""
        event_types = None
        if data.get("event_types"):
            event_types = [NotificationEventType(e) for e in data["event_types"]]

        return cls(
            config_id=data.get("config_id"),
            channel_type=NotificationChannel(data["channel_type"]),
            enabled=data.get("enabled", True),
            workspace_id=data.get("workspace_id"),
            slack_webhook_url=data.get("slack_webhook_url"),
            slack_channel=data.get("slack_channel"),
            slack_bot_token=data.get("slack_bot_token"),
            teams_webhook_url=data.get("teams_webhook_url"),
            email_recipients=data.get("email_recipients", []),
            email_from=data.get("email_from"),
            smtp_host=data.get("smtp_host"),
            smtp_port=data.get("smtp_port", 587),
            webhook_url=data.get("webhook_url"),
            webhook_headers=data.get("webhook_headers", {}),
            event_types=event_types,
            min_priority=NotificationPriority(data.get("min_priority", "low")),
        )


@dataclass
class NotificationResult:
    """Result of sending a notification."""

    success: bool
    channel: NotificationChannel
    message_id: str | None = None
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Delivery confirmation fields
    correlation_id: str | None = None  # Correlation ID from request
    delivery_status: DeliveryStatus = DeliveryStatus.PENDING
    delivered_at: datetime | None = None
    provider_response: dict[str, Any] | None = None  # Raw provider response
    retry_count: int = 0
    next_retry_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "channel": self.channel.value,
            "message_id": self.message_id,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "delivery_status": self.delivery_status.value,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "provider_response": self.provider_response,
            "retry_count": self.retry_count,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
        }


# =============================================================================
# Channel Providers
# =============================================================================


class ChannelProvider(ABC):
    """Abstract base class for notification channel providers."""

    @abstractmethod
    async def send(self, message: NotificationMessage, config: ChannelConfig) -> NotificationResult:
        """Send a notification through this channel."""
        pass

    @abstractmethod
    def format_message(self, message: NotificationMessage) -> Any:
        """Format message for this channel."""
        pass


class SlackProvider(ChannelProvider):
    """Slack notification provider using webhooks or Bot API."""

    async def send(self, message: NotificationMessage, config: ChannelConfig) -> NotificationResult:
        """Send notification to Slack."""
        try:
            from aragora.server.http_client_pool import get_http_pool
            from aragora.security.ssrf_protection import validate_url

            payload = self.format_message(message)

            # Use webhook or Bot API
            if config.slack_webhook_url:
                url = config.slack_webhook_url
                headers = {"Content-Type": "application/json"}
            elif config.slack_bot_token and config.slack_channel:
                url = "https://slack.com/api/chat.postMessage"
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {config.slack_bot_token}",
                }
                payload["channel"] = config.slack_channel
            else:
                return NotificationResult(
                    success=False,
                    channel=NotificationChannel.SLACK,
                    error="No Slack webhook URL or bot token configured",
                )

            # SSRF protection: validate URL before making outbound request
            url_check = validate_url(url)
            if not url_check.is_safe:
                return NotificationResult(
                    success=False,
                    channel=NotificationChannel.SLACK,
                    error=f"SSRF blocked: {url_check.error}",
                )

            pool = get_http_pool()
            async with pool.get_session("slack") as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return NotificationResult(
                        success=True,
                        channel=NotificationChannel.SLACK,
                        message_id=data.get("ts"),
                    )
                else:
                    error_text = resp.text
                    return NotificationResult(
                        success=False,
                        channel=NotificationChannel.SLACK,
                        error=f"Slack API error: {resp.status_code} - {error_text}",
                    )

        except ImportError:
            return NotificationResult(
                success=False,
                channel=NotificationChannel.SLACK,
                error="httpx not installed",
            )
        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
            logger.warning("Slack notification failed: %s", e)
            return NotificationResult(
                success=False,
                channel=NotificationChannel.SLACK,
                error="Slack notification delivery failed",
            )

    def format_message(self, message: NotificationMessage) -> dict[str, Any]:
        """Format message as Slack Block Kit."""
        # Priority emoji
        priority_emoji = {
            NotificationPriority.LOW: ":small_blue_diamond:",
            NotificationPriority.NORMAL: ":large_blue_diamond:",
            NotificationPriority.HIGH: ":warning:",
            NotificationPriority.URGENT: ":rotating_light:",
        }.get(message.priority, ":large_blue_diamond:")

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{priority_emoji} {message.title}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message.body,
                },
            },
        ]

        # Add link button if provided
        if message.link_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": message.link_text or "View Details",
                            },
                            "url": message.link_url,
                        }
                    ],
                }
            )

        # Add context footer
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Aragora Control Plane | {message.event_type.value} | {message.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
                    }
                ],
            }
        )

        return {"blocks": blocks}


class TeamsProvider(ChannelProvider):
    """Microsoft Teams notification provider using webhooks."""

    async def send(self, message: NotificationMessage, config: ChannelConfig) -> NotificationResult:
        """Send notification to Microsoft Teams."""
        try:
            from aragora.server.http_client_pool import get_http_pool
            from aragora.security.ssrf_protection import validate_url

            if not config.teams_webhook_url:
                return NotificationResult(
                    success=False,
                    channel=NotificationChannel.TEAMS,
                    error="No Teams webhook URL configured",
                )

            # SSRF protection: validate URL before making outbound request
            url_check = validate_url(config.teams_webhook_url)
            if not url_check.is_safe:
                return NotificationResult(
                    success=False,
                    channel=NotificationChannel.TEAMS,
                    error=f"SSRF blocked: {url_check.error}",
                )

            payload = self.format_message(message)

            pool = get_http_pool()
            async with pool.get_session("teams") as client:
                resp = await client.post(
                    config.teams_webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    return NotificationResult(
                        success=True,
                        channel=NotificationChannel.TEAMS,
                    )
                else:
                    error_text = resp.text
                    return NotificationResult(
                        success=False,
                        channel=NotificationChannel.TEAMS,
                        error=f"Teams webhook error: {resp.status_code} - {error_text}",
                    )

        except ImportError:
            return NotificationResult(
                success=False,
                channel=NotificationChannel.TEAMS,
                error="httpx not installed",
            )
        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
            logger.warning("Teams notification failed: %s", e)
            return NotificationResult(
                success=False,
                channel=NotificationChannel.TEAMS,
                error="Teams notification delivery failed",
            )

    def format_message(self, message: NotificationMessage) -> dict[str, Any]:
        """Format message as Teams Adaptive Card."""
        # Priority color
        priority_color = {
            NotificationPriority.LOW: "default",
            NotificationPriority.NORMAL: "accent",
            NotificationPriority.HIGH: "warning",
            NotificationPriority.URGENT: "attention",
        }.get(message.priority, "accent")

        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": message.title,
                                "weight": "bolder",
                                "size": "large",
                                "color": priority_color,
                            },
                            {
                                "type": "TextBlock",
                                "text": message.body,
                                "wrap": True,
                            },
                            {
                                "type": "TextBlock",
                                "text": f"Event: {message.event_type.value} | {message.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
                                "size": "small",
                                "isSubtle": True,
                            },
                        ],
                    },
                }
            ],
        }

        # Add action button if link provided
        if message.link_url:
            attachments: list[dict[str, Any]] = cast(list[dict[str, Any]], card["attachments"])
            content: dict[str, Any] = attachments[0]["content"]
            content["actions"] = [
                {
                    "type": "Action.OpenUrl",
                    "title": message.link_text or "View Details",
                    "url": message.link_url,
                }
            ]

        return card


class WebhookProvider(ChannelProvider):
    """Generic webhook notification provider."""

    async def send(self, message: NotificationMessage, config: ChannelConfig) -> NotificationResult:
        """Send notification to a webhook endpoint."""
        try:
            from aragora.server.http_client_pool import get_http_pool
            from aragora.security.ssrf_protection import validate_url

            if not config.webhook_url:
                return NotificationResult(
                    success=False,
                    channel=NotificationChannel.WEBHOOK,
                    error="No webhook URL configured",
                )

            # SSRF protection: validate URL before making outbound request
            url_check = validate_url(config.webhook_url)
            if not url_check.is_safe:
                return NotificationResult(
                    success=False,
                    channel=NotificationChannel.WEBHOOK,
                    error=f"SSRF blocked: {url_check.error}",
                )

            payload = self.format_message(message)
            headers = {"Content-Type": "application/json", **config.webhook_headers}

            pool = get_http_pool()
            async with pool.get_session("webhook") as client:
                resp = await client.post(config.webhook_url, json=payload, headers=headers)
                if resp.status_code < 300:
                    return NotificationResult(
                        success=True,
                        channel=NotificationChannel.WEBHOOK,
                    )
                else:
                    error_text = resp.text
                    return NotificationResult(
                        success=False,
                        channel=NotificationChannel.WEBHOOK,
                        error=f"Webhook error: {resp.status_code} - {error_text}",
                    )

        except ImportError:
            return NotificationResult(
                success=False,
                channel=NotificationChannel.WEBHOOK,
                error="httpx not installed",
            )
        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
            logger.warning("Webhook notification failed: %s", e)
            return NotificationResult(
                success=False,
                channel=NotificationChannel.WEBHOOK,
                error="Webhook notification delivery failed",
            )

    def format_message(self, message: NotificationMessage) -> dict[str, Any]:
        """Format message as generic JSON payload."""
        return message.to_dict()


# =============================================================================
# Notification Manager
# =============================================================================


class NotificationManager:
    """
    Manages notification routing to configured channels.

    Usage:
        manager = NotificationManager()

        # Configure channels
        manager.add_channel(ChannelConfig(
            channel_type=NotificationChannel.SLACK,
            slack_webhook_url="https://hooks.slack.com/...",
            event_types=[NotificationEventType.TASK_COMPLETED],
        ))

        # Send notification
        await manager.notify(
            event_type=NotificationEventType.TASK_COMPLETED,
            title="Task Completed",
            body="Task xyz finished successfully",
        )

        # With persistence (Redis):
        manager = NotificationManager(redis_client=redis_client)
        await manager.load_channels()  # Load persisted configs
    """

    REDIS_CHANNEL_KEY = "aragora:notification_channels"

    def __init__(self, redis_client: Any | None = None) -> None:
        """
        Initialize the notification manager.

        Args:
            redis_client: Optional Redis client for channel config persistence.
                         If provided, channel configs will be persisted to Redis.
        """
        self._channels: list[ChannelConfig] = []
        self._providers: dict[NotificationChannel, ChannelProvider] = {
            NotificationChannel.SLACK: SlackProvider(),
            NotificationChannel.TEAMS: TeamsProvider(),
            NotificationChannel.WEBHOOK: WebhookProvider(),
        }
        self._event_handlers: dict[NotificationEventType, list[Callable[..., None]]] = {}
        self._notification_history: list[NotificationResult] = []
        self._max_history = 1000
        self._redis = redis_client

    async def load_channels(self) -> int:
        """
        Load channel configurations from persistent storage.

        Returns:
            Number of channels loaded
        """
        if not self._redis:
            logger.debug("No Redis client configured, skipping channel load")
            return 0

        try:
            import json

            raw_configs = await self._redis.hgetall(self.REDIS_CHANNEL_KEY)
            loaded = 0
            for config_id, config_json in raw_configs.items():
                try:
                    data = json.loads(config_json)
                    config = ChannelConfig.from_dict(data)
                    self._channels.append(config)
                    loaded += 1
                except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
                    logger.warning("Failed to load channel config %s: %s", config_id, e)

            logger.info("Loaded %s notification channel configs from Redis", loaded)
            return loaded
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to load channel configs: %s", e)
            return 0

    async def _persist_channel(self, config: ChannelConfig) -> bool:
        """Persist a channel configuration to Redis."""
        if not self._redis:
            return False

        try:
            import json

            await self._redis.hset(
                self.REDIS_CHANNEL_KEY,
                config.config_id,
                json.dumps(config.to_dict()),
            )
            return True
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to persist channel config: %s", e)
            return False

    async def _delete_persisted_channel(self, config_id: str) -> bool:
        """Delete a channel configuration from Redis."""
        if not self._redis:
            return False

        try:
            await self._redis.hdel(self.REDIS_CHANNEL_KEY, config_id)
            return True
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning("Failed to delete channel config: %s", e)
            return False

    def add_channel(self, config: ChannelConfig) -> None:
        """Add a notification channel configuration."""
        self._channels.append(config)
        logger.info(
            "Added notification channel: %s",
            config.channel_type.value,
            extra={"workspace_id": config.workspace_id, "config_id": config.config_id},
        )

        # Persist asynchronously if Redis is available
        if self._redis:
            asyncio.create_task(self._persist_channel(config))

    async def add_channel_async(self, config: ChannelConfig) -> bool:
        """Add and persist a notification channel configuration (async)."""
        self._channels.append(config)
        logger.info(
            "Added notification channel: %s",
            config.channel_type.value,
            extra={"workspace_id": config.workspace_id, "config_id": config.config_id},
        )

        if self._redis:
            return await self._persist_channel(config)
        return True

    def remove_channel(
        self, channel_type: NotificationChannel, workspace_id: str | None = None
    ) -> bool:
        """Remove a notification channel."""
        removed_configs = [
            c
            for c in self._channels
            if c.channel_type == channel_type and c.workspace_id == workspace_id
        ]

        initial_count = len(self._channels)
        self._channels = [
            c
            for c in self._channels
            if not (c.channel_type == channel_type and c.workspace_id == workspace_id)
        ]

        # Delete from persistence asynchronously
        if self._redis:
            for config in removed_configs:
                if config.config_id is not None:
                    asyncio.create_task(self._delete_persisted_channel(config.config_id))

        return len(self._channels) < initial_count

    async def remove_channel_async(
        self, channel_type: NotificationChannel, workspace_id: str | None = None
    ) -> bool:
        """Remove a notification channel (async with persistence)."""
        removed_configs = [
            c
            for c in self._channels
            if c.channel_type == channel_type and c.workspace_id == workspace_id
        ]

        initial_count = len(self._channels)
        self._channels = [
            c
            for c in self._channels
            if not (c.channel_type == channel_type and c.workspace_id == workspace_id)
        ]

        # Delete from persistence
        if self._redis:
            for config in removed_configs:
                if config.config_id is not None:
                    await self._delete_persisted_channel(config.config_id)

        return len(self._channels) < initial_count

    def get_channels(self, workspace_id: str | None = None) -> list[ChannelConfig]:
        """Get configured channels, optionally filtered by workspace."""
        if workspace_id:
            return [
                c
                for c in self._channels
                if c.workspace_id == workspace_id or c.workspace_id is None
            ]
        return list(self._channels)

    async def notify(
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
        Send a notification to all applicable channels.

        Args:
            event_type: Type of event triggering notification
            title: Notification title
            body: Notification body text
            priority: Notification priority
            metadata: Additional metadata
            workspace_id: Workspace for filtering channels
            link_url: Optional URL for action button
            link_text: Text for action button

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
        applicable_channels = self._filter_channels(message)

        if not applicable_channels:
            logger.debug("No channels configured for event %s", event_type.value)
            return []

        # Send to all applicable channels in parallel
        tasks = [self._send_to_channel(message, config) for config in applicable_channels]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        notification_results: list[NotificationResult] = []
        for result in results:
            if isinstance(result, NotificationResult):
                notification_results.append(result)
                self._add_to_history(result)
            elif isinstance(result, Exception):
                logger.warning("Notification delivery failed: %s", result)
                error_result = NotificationResult(
                    success=False,
                    channel=NotificationChannel.WEBHOOK,  # Generic
                    error="Notification delivery failed",
                )
                notification_results.append(error_result)
                self._add_to_history(error_result)

        return notification_results

    def _filter_channels(self, message: NotificationMessage) -> list[ChannelConfig]:
        """Filter channels based on message properties."""
        applicable = []

        for config in self._channels:
            # Check if enabled
            if not config.enabled:
                continue

            # Check workspace filter
            if config.workspace_id and message.workspace_id != config.workspace_id:
                continue

            # Check event type filter
            if config.event_types and message.event_type not in config.event_types:
                continue

            # Check priority filter
            priority_order = list(NotificationPriority)
            if priority_order.index(message.priority) < priority_order.index(config.min_priority):
                continue

            applicable.append(config)

        return applicable

    async def _send_to_channel(
        self, message: NotificationMessage, config: ChannelConfig
    ) -> NotificationResult:
        """Send message to a specific channel."""
        provider = self._providers.get(config.channel_type)

        if not provider:
            return NotificationResult(
                success=False,
                channel=config.channel_type,
                error=f"No provider for channel type: {config.channel_type.value}",
            )

        try:
            result = await provider.send(message, config)
            if result.success:
                logger.info(
                    "Notification sent to %s",
                    config.channel_type.value,
                    extra={"event_type": message.event_type.value},
                )
            else:
                logger.warning(
                    "Failed to send notification to %s: %s",
                    config.channel_type.value,
                    result.error,
                )
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
            logger.error("Error sending notification to %s: %s", config.channel_type.value, e)
            return NotificationResult(
                success=False,
                channel=config.channel_type,
                error="Notification delivery failed",
            )

    def _add_to_history(self, result: NotificationResult) -> None:
        """Add result to history with size limit."""
        self._notification_history.append(result)
        if len(self._notification_history) > self._max_history:
            self._notification_history = self._notification_history[-self._max_history :]

    def get_stats(self) -> dict[str, Any]:
        """Get notification statistics."""
        total = len(self._notification_history)
        successful = sum(1 for r in self._notification_history if r.success)
        by_channel: dict[str, int] = {}

        for result in self._notification_history:
            channel = result.channel.value
            by_channel[channel] = by_channel.get(channel, 0) + 1

        return {
            "total_sent": total,
            "successful": successful,
            "failed": total - successful,
            "success_rate": successful / total if total > 0 else 0,
            "by_channel": by_channel,
            "channels_configured": len(self._channels),
        }


# =============================================================================
# Helper Functions
# =============================================================================


def create_task_completed_notification(
    task_id: str,
    task_type: str,
    agent_id: str,
    duration_seconds: float,
    ui_base_url: str = "https://app.aragora.ai",
) -> NotificationMessage:
    """Create a notification for task completion."""
    return NotificationMessage(
        event_type=NotificationEventType.TASK_COMPLETED,
        title=f"Task Completed: {task_type}",
        body=f"Task `{task_id[:8]}...` completed by agent `{agent_id}` in {duration_seconds:.1f}s",
        priority=NotificationPriority.NORMAL,
        metadata={"task_id": task_id, "task_type": task_type, "agent_id": agent_id},
        link_url=f"{ui_base_url}/control-plane?task={task_id}",
        link_text="View Task",
    )


def create_deliberation_consensus_notification(
    task_id: str,
    question: str,
    answer: str,
    confidence: float,
    ui_base_url: str = "https://app.aragora.ai",
) -> NotificationMessage:
    """Create a notification for vetted decisionmaking consensus."""
    return NotificationMessage(
        event_type=NotificationEventType.DELIBERATION_CONSENSUS,
        title="Vetted Decisionmaking Consensus Reached",
        body=f"**Question:** {question[:100]}...\n\n**Answer:** {answer[:200]}...\n\n**Confidence:** {confidence:.0%}",
        priority=NotificationPriority.NORMAL,
        metadata={"task_id": task_id, "confidence": confidence},
        link_url=f"{ui_base_url}/deliberations/{task_id}",
        link_text="View Vetted Decisionmaking",
    )


def create_sla_violation_notification(
    task_id: str,
    task_type: str,
    elapsed_seconds: float,
    timeout_seconds: float,
) -> NotificationMessage:
    """Create a notification for SLA violation."""
    return NotificationMessage(
        event_type=NotificationEventType.SLA_VIOLATION,
        title=f"SLA Violation: {task_type}",
        body=f"Task `{task_id[:8]}...` exceeded SLA timeout.\n\n**Elapsed:** {elapsed_seconds:.0f}s\n**Timeout:** {timeout_seconds:.0f}s",
        priority=NotificationPriority.HIGH,
        metadata={"task_id": task_id, "elapsed_seconds": elapsed_seconds},
    )


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Enums
    "NotificationChannel",
    "DeliveryStatus",
    "NotificationPriority",
    "NotificationEventType",
    # Data Classes
    "NotificationMessage",
    "ChannelConfig",
    "NotificationResult",
    # Providers
    "ChannelProvider",
    "SlackProvider",
    "TeamsProvider",
    "WebhookProvider",
    # Manager
    "NotificationManager",
    # Helpers
    "create_task_completed_notification",
    "create_deliberation_consensus_notification",
    "create_sla_violation_notification",
]
