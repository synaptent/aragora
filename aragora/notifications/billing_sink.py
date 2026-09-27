"""Notification-service adapter for billing-owned sink contracts."""

from __future__ import annotations

from aragora.billing.notification_sink import (
    register_billing_notification_sink as register_sink,
)


class NotificationServiceBillingSink:
    """Translate billing notification requests to the notification service."""

    async def notify_budget_runway(
        self,
        *,
        title: str,
        message: str,
        severity: str,
        workspace_id: str,
    ) -> None:
        from aragora.notifications.models import Notification
        from aragora.notifications.service import get_notification_service

        notification = Notification(
            title=title,
            message=message,
            severity=severity,
            resource_type="budget_runway_alert",
            workspace_id=workspace_id,
        )
        await get_notification_service().notify(notification)

    async def notify_cost_anomaly(
        self,
        *,
        anomaly_type: str,
        severity: str,
        amount: float,
        expected: float,
        workspace_id: str,
        details: str | None,
    ) -> None:
        from aragora.notifications.service import notify_cost_anomaly

        await notify_cost_anomaly(
            anomaly_type=anomaly_type,
            severity=severity,
            amount=amount,
            expected=expected,
            workspace_id=workspace_id,
            details=details,
        )


def register_billing_notification_sink() -> None:
    """Register the notification-service adapter with billing."""
    register_sink(NotificationServiceBillingSink())


__all__ = [
    "NotificationServiceBillingSink",
    "register_billing_notification_sink",
]
