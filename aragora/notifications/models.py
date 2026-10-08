"""
Notification data models.

Contains enums, dataclasses, and configuration objects used across the
notification system.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

__all__ = [
    "NotificationChannel",
    "NotificationPriority",
    "Notification",
    "NotificationResult",
    "SlackConfig",
    "EmailConfig",
    "WebhookEndpoint",
]


class NotificationChannel(str, Enum):
    """Available notification channels."""

    SLACK = "slack"
    EMAIL = "email"
    WEBHOOK = "webhook"
    IN_APP = "in_app"


class NotificationPriority(str, Enum):
    """Notification priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class Notification:
    """A notification to be sent."""

    title: str
    message: str
    severity: str = "info"  # info, warning, error, critical
    priority: NotificationPriority = NotificationPriority.NORMAL

    # Context
    resource_type: str | None = None  # finding, document, session
    resource_id: str | None = None
    workspace_id: str | None = None
    # Tenant whose record this notification is about; None for system notices.
    org_id: str | None = None

    # Metadata
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    # Links
    action_url: str | None = None
    action_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "priority": self.priority.value,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "workspace_id": self.workspace_id,
            "org_id": self.org_id,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
            "action_url": self.action_url,
            "action_label": self.action_label,
        }


@dataclass
class NotificationResult:
    """Result of sending a notification."""

    success: bool
    channel: NotificationChannel
    recipient: str
    notification_id: str
    error: str | None = None
    external_id: str | None = None  # Message ID from external service

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "channel": self.channel.value,
            "recipient": self.recipient,
            "notification_id": self.notification_id,
            "error": self.error,
            "external_id": self.external_id,
        }


@dataclass
class SlackConfig:
    """Slack integration configuration."""

    webhook_url: str | None = None
    bot_token: str | None = None
    default_channel: str = "#notifications"
    username: str = "Aragora"
    icon_emoji: str = ":robot_face:"

    @classmethod
    def from_env(cls) -> SlackConfig:
        """Create from environment variables."""
        return cls(
            webhook_url=os.environ.get("SLACK_WEBHOOK_URL"),
            bot_token=os.environ.get("SLACK_BOT_TOKEN"),
            default_channel=os.environ.get("SLACK_DEFAULT_CHANNEL", "#notifications"),
        )


@dataclass
class EmailConfig:
    """Email (SMTP) configuration."""

    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    use_tls: bool = True
    from_address: str = "notifications@aragora.local"
    from_name: str = "Aragora Notifications"

    @classmethod
    def from_env(cls) -> EmailConfig:
        """Create from environment variables."""
        return cls(
            smtp_host=os.environ.get("SMTP_HOST", "localhost"),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_user=os.environ.get("SMTP_USER"),
            smtp_password=os.environ.get("SMTP_PASSWORD"),
            use_tls=os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
            from_address=os.environ.get("SMTP_FROM", "notifications@aragora.local"),
            from_name=os.environ.get("SMTP_FROM_NAME", "Aragora Notifications"),
        )


@dataclass
class WebhookEndpoint:
    """A configured webhook endpoint."""

    id: str
    url: str
    secret: str | None = None
    events: list[str] = field(default_factory=list)  # Empty = all events
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    workspace_id: str | None = None
    # Owning tenant. None marks a server-operator endpoint, which receives
    # every notification; an owned endpoint receives only its own org's.
    org_id: str | None = None

    def matches_event(self, event_type: str) -> bool:
        """Check if this endpoint should receive the event."""
        if not self.events:
            return True  # All events
        return event_type in self.events

    def receives_org(self, org_id: str | None) -> bool:
        """Whether a notification about ``org_id``'s records may reach this endpoint."""
        owner = (self.org_id or "").strip()
        if not owner:
            return True
        return owner == (org_id or "").strip()
