"""
Sharing Notifications for Knowledge Mound.

Handles notifications when knowledge items are shared:
- In-app notifications (stored for UI display)
- Email notifications via existing SMTP infrastructure
- Webhook notifications for external integrations

This module integrates with:
- BillingNotifier for email/webhook sending
- NotificationsHandler for email/telegram

Usage:
    from aragora.knowledge.mound.notifications import (
        SharingNotifier,
        notify_item_shared,
        get_notifications_for_user,
    )

    # Notify when sharing
    await notify_item_shared(
        item_id="km_123",
        item_title="Important Knowledge",
        from_user_id="user_alice",
        to_user_id="user_bob",
        workspace_id="ws_456",
    )

    # Get notifications for display
    notifications = await get_notifications_for_user("user_bob", limit=20)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    """Type of sharing notification."""

    ITEM_SHARED = "item_shared"
    ITEM_UNSHARED = "item_unshared"
    PERMISSION_CHANGED = "permission_changed"
    SHARE_EXPIRING = "share_expiring"
    SHARE_EXPIRED = "share_expired"
    FEDERATION_SYNC = "federation_sync"


class NotificationChannel(str, Enum):
    """Notification delivery channel."""

    IN_APP = "in_app"
    EMAIL = "email"
    WEBHOOK = "webhook"
    TELEGRAM = "telegram"


class NotificationStatus(str, Enum):
    """Status of an in-app notification."""

    UNREAD = "unread"
    READ = "read"
    DISMISSED = "dismissed"


@dataclass
class SharingNotification:
    """A notification about a sharing event."""

    id: str
    user_id: str  # Recipient user ID
    notification_type: NotificationType
    title: str
    message: str
    item_id: str | None = None
    item_title: str | None = None
    from_user_id: str | None = None
    from_user_name: str | None = None
    workspace_id: str | None = None
    status: NotificationStatus = NotificationStatus.UNREAD
    created_at: datetime = field(default_factory=datetime.now)
    read_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "notification_type": self.notification_type.value,
            "title": self.title,
            "message": self.message,
            "item_id": self.item_id,
            "item_title": self.item_title,
            "from_user_id": self.from_user_id,
            "from_user_name": self.from_user_name,
            "workspace_id": self.workspace_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SharingNotification:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            notification_type=NotificationType(data["notification_type"]),
            title=data["title"],
            message=data["message"],
            item_id=data.get("item_id"),
            item_title=data.get("item_title"),
            from_user_id=data.get("from_user_id"),
            from_user_name=data.get("from_user_name"),
            workspace_id=data.get("workspace_id"),
            status=NotificationStatus(data.get("status", "unread")),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if data.get("created_at")
                else datetime.now()
            ),
            read_at=datetime.fromisoformat(data["read_at"]) if data.get("read_at") else None,
            metadata=data.get("metadata", {}),
        )


@dataclass
class NotificationPreferences:
    """User preferences for sharing notifications."""

    user_id: str
    email_on_share: bool = True
    email_on_unshare: bool = False
    email_on_permission_change: bool = True
    in_app_enabled: bool = True
    telegram_enabled: bool = False
    webhook_url: str | None = None
    quiet_hours_start: int | None = None  # Hour (0-23)
    quiet_hours_end: int | None = None


class InAppNotificationStore:
    """
    In-memory store for in-app notifications.

    In production, this would be backed by a database.
    """

    def __init__(self):
        self._notifications: dict[str, list[SharingNotification]] = {}
        self._preferences: dict[str, NotificationPreferences] = {}

    def add_notification(self, notification: SharingNotification) -> None:
        """Add a notification for a user."""
        if notification.user_id not in self._notifications:
            self._notifications[notification.user_id] = []
        self._notifications[notification.user_id].insert(0, notification)

        # Keep only last 100 notifications per user
        if len(self._notifications[notification.user_id]) > 100:
            self._notifications[notification.user_id] = self._notifications[notification.user_id][
                :100
            ]

    def get_notifications(
        self,
        user_id: str,
        status: NotificationStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[SharingNotification]:
        """Get notifications for a user."""
        notifications = self._notifications.get(user_id, [])

        if status:
            notifications = [n for n in notifications if n.status == status]

        return notifications[offset : offset + limit]

    def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications."""
        notifications = self._notifications.get(user_id, [])
        return sum(1 for n in notifications if n.status == NotificationStatus.UNREAD)

    def mark_as_read(self, notification_id: str, user_id: str) -> bool:
        """Mark a notification as read."""
        notifications = self._notifications.get(user_id, [])
        for n in notifications:
            if n.id == notification_id:
                n.status = NotificationStatus.READ
                n.read_at = datetime.now()
                return True
        return False

    def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        notifications = self._notifications.get(user_id, [])
        count = 0
        now = datetime.now()
        for n in notifications:
            if n.status == NotificationStatus.UNREAD:
                n.status = NotificationStatus.READ
                n.read_at = now
                count += 1
        return count

    def dismiss_notification(self, notification_id: str, user_id: str) -> bool:
        """Dismiss a notification."""
        notifications = self._notifications.get(user_id, [])
        for n in notifications:
            if n.id == notification_id:
                n.status = NotificationStatus.DISMISSED
                return True
        return False

    def get_preferences(self, user_id: str) -> NotificationPreferences:
        """Get notification preferences for a user."""
        if user_id not in self._preferences:
            self._preferences[user_id] = NotificationPreferences(user_id=user_id)
        return self._preferences[user_id]

    def set_preferences(self, preferences: NotificationPreferences) -> None:
        """Set notification preferences for a user."""
        self._preferences[preferences.user_id] = preferences


# Global store instance
_notification_store: InAppNotificationStore | None = None


def get_notification_store() -> InAppNotificationStore:
    """Get the global notification store instance."""
    global _notification_store
    if _notification_store is None:
        _notification_store = InAppNotificationStore()
    return _notification_store


class SharingNotifier:
    """
    Handles sending notifications for knowledge sharing events.

    Supports multiple channels:
    - In-app notifications (stored for UI display)
    - Email via SMTP
    - Webhook for external systems
    - Telegram via bot
    """

    def __init__(
        self,
        store: InAppNotificationStore | None = None,
    ):
        self.store = store or get_notification_store()

    async def notify_item_shared(
        self,
        item_id: str,
        item_title: str,
        from_user_id: str,
        from_user_name: str,
        to_user_id: str,
        to_user_email: str | None = None,
        workspace_id: str | None = None,
        permissions: list[str] | None = None,
    ) -> dict[str, bool]:
        """
        Notify a user that an item was shared with them.

        Args:
            item_id: ID of the shared item
            item_title: Title/name of the item
            from_user_id: ID of the user who shared
            from_user_name: Display name of the user who shared
            to_user_id: ID of the user receiving the share
            to_user_email: Optional email for email notifications
            workspace_id: Optional workspace context
            permissions: Granted permissions

        Returns:
            Dict with success status for each channel
        """
        results = {}
        prefs = self.store.get_preferences(to_user_id)

        # Create in-app notification
        if prefs.in_app_enabled:
            notification = SharingNotification(
                id=f"notif_{uuid4().hex[:12]}",
                user_id=to_user_id,
                notification_type=NotificationType.ITEM_SHARED,
                title="Knowledge Shared With You",
                message=f'{from_user_name} shared "{item_title}" with you',
                item_id=item_id,
                item_title=item_title,
                from_user_id=from_user_id,
                from_user_name=from_user_name,
                workspace_id=workspace_id,
                metadata={"permissions": permissions or ["read"]},
            )
            self.store.add_notification(notification)
            results["in_app"] = True
            logger.info("Created in-app notification for %s: item shared", to_user_id)

        # Send email notification
        if prefs.email_on_share and to_user_email:
            email_sent = await self._send_email_notification(
                to_email=to_user_email,
                subject=f"{from_user_name} shared knowledge with you",
                item_title=item_title,
                from_user_name=from_user_name,
                notification_type="shared",
            )
            results["email"] = email_sent

        # Send webhook notification
        if prefs.webhook_url:
            webhook_sent = await self._send_webhook_notification(
                webhook_url=prefs.webhook_url,
                event="item_shared",
                payload={
                    "item_id": item_id,
                    "item_title": item_title,
                    "from_user_id": from_user_id,
                    "from_user_name": from_user_name,
                    "to_user_id": to_user_id,
                    "permissions": permissions,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            results["webhook"] = webhook_sent

        return results

    async def notify_share_revoked(
        self,
        item_id: str,
        item_title: str,
        from_user_id: str,
        from_user_name: str,
        to_user_id: str,
        to_user_email: str | None = None,
    ) -> dict[str, bool]:
        """Notify a user that an item share was revoked."""
        results = {}
        prefs = self.store.get_preferences(to_user_id)

        # Create in-app notification
        if prefs.in_app_enabled:
            notification = SharingNotification(
                id=f"notif_{uuid4().hex[:12]}",
                user_id=to_user_id,
                notification_type=NotificationType.ITEM_UNSHARED,
                title="Knowledge Share Revoked",
                message=f'Access to "{item_title}" has been revoked',
                item_id=item_id,
                item_title=item_title,
                from_user_id=from_user_id,
                from_user_name=from_user_name,
            )
            self.store.add_notification(notification)
            results["in_app"] = True

        # Send email if enabled
        if prefs.email_on_unshare and to_user_email:
            email_sent = await self._send_email_notification(
                to_email=to_user_email,
                subject=f"Knowledge share revoked: {item_title}",
                item_title=item_title,
                from_user_name=from_user_name,
                notification_type="revoked",
            )
            results["email"] = email_sent

        return results

    async def notify_permission_changed(
        self,
        item_id: str,
        item_title: str,
        from_user_id: str,
        from_user_name: str,
        to_user_id: str,
        to_user_email: str | None = None,
        old_permissions: list[str] | None = None,
        new_permissions: list[str] | None = None,
    ) -> dict[str, bool]:
        """Notify a user that their permissions on a shared item changed."""
        results = {}
        prefs = self.store.get_preferences(to_user_id)

        # Create in-app notification
        if prefs.in_app_enabled:
            notification = SharingNotification(
                id=f"notif_{uuid4().hex[:12]}",
                user_id=to_user_id,
                notification_type=NotificationType.PERMISSION_CHANGED,
                title="Share Permissions Updated",
                message=f'Your permissions on "{item_title}" have been updated',
                item_id=item_id,
                item_title=item_title,
                from_user_id=from_user_id,
                from_user_name=from_user_name,
                metadata={
                    "old_permissions": old_permissions,
                    "new_permissions": new_permissions,
                },
            )
            self.store.add_notification(notification)
            results["in_app"] = True

        # Send email if enabled
        if prefs.email_on_permission_change and to_user_email:
            email_sent = await self._send_email_notification(
                to_email=to_user_email,
                subject=f"Share permissions updated: {item_title}",
                item_title=item_title,
                from_user_name=from_user_name,
                notification_type="permission_changed",
            )
            results["email"] = email_sent

        return results

    async def notify_share_expiring(
        self,
        item_id: str,
        item_title: str,
        to_user_id: str,
        to_user_email: str | None = None,
        expires_at: datetime | None = None,
        days_remaining: int = 3,
    ) -> dict[str, bool]:
        """Notify a user that their share access is expiring soon."""
        results = {}
        prefs = self.store.get_preferences(to_user_id)

        if prefs.in_app_enabled:
            notification = SharingNotification(
                id=f"notif_{uuid4().hex[:12]}",
                user_id=to_user_id,
                notification_type=NotificationType.SHARE_EXPIRING,
                title="Share Access Expiring",
                message=f'Your access to "{item_title}" expires in {days_remaining} day{"s" if days_remaining != 1 else ""}',
                item_id=item_id,
                item_title=item_title,
                metadata={
                    "expires_at": expires_at.isoformat() if expires_at else None,
                    "days_remaining": days_remaining,
                },
            )
            self.store.add_notification(notification)
            results["in_app"] = True

        return results

    async def _send_email_notification(
        self,
        to_email: str,
        subject: str,
        item_title: str,
        from_user_name: str,
        notification_type: str,
    ) -> bool:
        """Send email notification using existing infrastructure."""
        try:
            from aragora.server.handlers.social.notifications import get_email_integration

            email = get_email_integration()
            if not email:
                logger.debug("Email integration not configured, skipping email notification")
                return False

            # Build email content
            html_body = self._build_email_html(
                subject=subject,
                item_title=item_title,
                from_user_name=from_user_name,
                notification_type=notification_type,
            )
            text_body = self._build_email_text(
                subject=subject,
                item_title=item_title,
                from_user_name=from_user_name,
                notification_type=notification_type,
            )

            from aragora.integrations.email import EmailRecipient

            recipient = EmailRecipient(email=to_email)
            success = await email._send_email(recipient, subject, html_body, text_body)
            return success

        except ImportError:
            logger.debug("Email integration not available")
            return False
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to send email notification: %s", e)
            return False

    async def _send_webhook_notification(
        self,
        webhook_url: str,
        event: str,
        payload: dict[str, Any],
    ) -> bool:
        """Send webhook notification."""
        import json
        from urllib.error import URLError
        from urllib.request import Request, urlopen

        try:
            data = json.dumps({"event": event, **payload}).encode("utf-8")
            req = Request(  # config webhook URL
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10) as response:  # config webhook URL
                response.read()
            return True
        except (URLError, TimeoutError) as e:
            logger.error("Failed to send webhook notification: %s", e)
            return False

    def _build_email_html(
        self,
        subject: str,
        item_title: str,
        from_user_name: str,
        notification_type: str,
    ) -> str:
        """Build HTML email body."""
        if notification_type == "shared":
            action = "shared knowledge with you"
            color = "#00ff00"
        elif notification_type == "revoked":
            action = "revoked your access to"
            color = "#ff6600"
        else:
            action = "updated your permissions on"
            color = "#00ffff"

        return f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Monaco', 'Menlo', monospace; background: #0a0a0a; color: #00ff00; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; border: 1px solid {color}; padding: 20px; }}
        .header {{ font-size: 18px; margin-bottom: 20px; color: {color}; }}
        .item-title {{ color: {color}; font-weight: bold; }}
        .message {{ margin: 20px 0; line-height: 1.6; }}
        .button {{ display: inline-block; padding: 10px 20px; background: {color}; color: #0a0a0a; text-decoration: none; margin-top: 20px; }}
        .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">[KNOWLEDGE MOUND]</div>
        <div class="message">
            <p><strong>{from_user_name}</strong> {action} <span class="item-title">{item_title}</span></p>
            <p><a href="https://aragora.ai/knowledge" class="button">VIEW IN ARAGORA</a></p>
        </div>
        <div class="footer">
            <p>You can manage notification preferences in your Aragora settings.</p>
            <p>- Aragora Knowledge Mound</p>
        </div>
    </div>
</body>
</html>
"""

    def _build_email_text(
        self,
        subject: str,
        item_title: str,
        from_user_name: str,
        notification_type: str,
    ) -> str:
        """Build plain text email body."""
        if notification_type == "shared":
            action = "shared knowledge with you"
        elif notification_type == "revoked":
            action = "revoked your access to"
        else:
            action = "updated your permissions on"

        return f"""
[KNOWLEDGE MOUND]

{from_user_name} {action}: {item_title}

View in Aragora: https://aragora.ai/knowledge

You can manage notification preferences in your Aragora settings.

- Aragora Knowledge Mound
"""


# Convenience functions


async def notify_item_shared(
    item_id: str,
    item_title: str,
    from_user_id: str,
    from_user_name: str,
    to_user_id: str,
    to_user_email: str | None = None,
    workspace_id: str | None = None,
    permissions: list[str] | None = None,
) -> dict[str, bool]:
    """Convenience function to notify about item sharing."""
    notifier = SharingNotifier()
    return await notifier.notify_item_shared(
        item_id=item_id,
        item_title=item_title,
        from_user_id=from_user_id,
        from_user_name=from_user_name,
        to_user_id=to_user_id,
        to_user_email=to_user_email,
        workspace_id=workspace_id,
        permissions=permissions,
    )


async def notify_share_revoked(
    item_id: str,
    item_title: str,
    from_user_id: str,
    from_user_name: str,
    to_user_id: str,
    to_user_email: str | None = None,
) -> dict[str, bool]:
    """Convenience function to notify about share revocation."""
    notifier = SharingNotifier()
    return await notifier.notify_share_revoked(
        item_id=item_id,
        item_title=item_title,
        from_user_id=from_user_id,
        from_user_name=from_user_name,
        to_user_id=to_user_id,
        to_user_email=to_user_email,
    )


def get_notifications_for_user(
    user_id: str,
    status: NotificationStatus | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[SharingNotification]:
    """Get notifications for a user."""
    store = get_notification_store()
    return store.get_notifications(user_id, status=status, limit=limit, offset=offset)


def get_unread_count(user_id: str) -> int:
    """Get count of unread notifications for a user."""
    store = get_notification_store()
    return store.get_unread_count(user_id)


def mark_notification_read(notification_id: str, user_id: str) -> bool:
    """Mark a notification as read."""
    store = get_notification_store()
    return store.mark_as_read(notification_id, user_id)


def mark_all_notifications_read(user_id: str) -> int:
    """Mark all notifications as read for a user."""
    store = get_notification_store()
    return store.mark_all_as_read(user_id)


def get_notification_preferences(user_id: str) -> NotificationPreferences:
    """Get notification preferences for a user."""
    store = get_notification_store()
    return store.get_preferences(user_id)


def set_notification_preferences(preferences: NotificationPreferences) -> None:
    """Set notification preferences for a user."""
    store = get_notification_store()
    store.set_preferences(preferences)


__all__ = [
    "NotificationType",
    "NotificationChannel",
    "NotificationStatus",
    "SharingNotification",
    "NotificationPreferences",
    "InAppNotificationStore",
    "SharingNotifier",
    "get_notification_store",
    "notify_item_shared",
    "notify_share_revoked",
    "get_notifications_for_user",
    "get_unread_count",
    "mark_notification_read",
    "mark_all_notifications_read",
    "get_notification_preferences",
    "set_notification_preferences",
]
