"""Control-plane channel adapter for observability SLO alerts."""

from __future__ import annotations

import logging
from typing import Any

from aragora.control_plane.channels import (
    NotificationEventType,
    NotificationPriority,
)
from aragora.control_plane.notifications import get_default_notification_dispatcher
from aragora.observability.slo import (
    SLOBreach,
    SLONotificationSink,
    register_slo_notification_sink_provider,
)
from aragora.observability.slo_alert_bridge import (
    SLOAlertConfig,
    register_channel_alert_sink,
)

logger = logging.getLogger(__name__)


class ControlPlaneSLOAlertSink:
    """Translate primitive alert fields to control-plane notifications."""

    def __init__(self, config: SLOAlertConfig) -> None:
        self._config = config
        self._manager: Any | None = None

    def _get_manager(self) -> Any:
        if self._manager is None:
            from aragora.control_plane.channels import (
                ChannelConfig,
                NotificationChannel,
                NotificationManager,
            )

            manager = NotificationManager()
            manager.add_channel(
                ChannelConfig(
                    channel_type=NotificationChannel.SLACK,
                    slack_webhook_url=self._config.slack_webhook_url,
                    slack_channel=self._config.slack_channel,
                )
            )
            self._manager = manager
        return self._manager

    async def notify(
        self,
        *,
        event_type: str,
        title: str,
        body: str,
        priority: str,
        metadata: dict[str, Any],
    ) -> Any:
        """Deliver an observability alert through the channel manager."""
        from aragora.control_plane.channels import (
            NotificationEventType,
            NotificationPriority,
        )

        return await self._get_manager().notify(
            event_type=NotificationEventType(event_type),
            title=title,
            body=body,
            priority=NotificationPriority(priority),
            metadata=metadata,
        )


class ControlPlaneSLONotificationSink:
    """Deliver direct SLO notifications through the current dispatcher."""

    async def notify(self, breach: SLOBreach) -> None:
        """Dispatch one SLO breach without caching the dispatcher."""
        dispatcher = get_default_notification_dispatcher()
        if dispatcher is None:
            logger.warning("Notification dispatcher not configured")
            return

        priority = (
            NotificationPriority.CRITICAL
            if breach.severity == "critical"
            else NotificationPriority.HIGH
        )

        await dispatcher.dispatch(
            event_type=NotificationEventType.SYSTEM_ALERT,
            title=f"SLO Alert: {breach.slo_name}",
            body=(
                f"{breach.message}\n\n"
                f"Current: {breach.current_value:.4f}\n"
                f"Target: {breach.target_value:.4f}\n"
                f"Error Budget: {breach.error_budget_remaining:.1f}%\n"
                f"Burn Rate: {breach.burn_rate:.2f}x"
            ),
            priority=priority,
            metadata=breach.to_dict(),
        )


_direct_notification_sink = ControlPlaneSLONotificationSink()


def get_slo_notification_sink() -> SLONotificationSink | None:
    """Resolve the direct sink only while a dispatcher is configured."""
    if get_default_notification_dispatcher() is None:
        return None
    return _direct_notification_sink


def register_slo_alert_sink() -> bool:
    """Register both control-plane adapters with observability contracts."""
    register_channel_alert_sink(ControlPlaneSLOAlertSink)
    register_slo_notification_sink_provider(get_slo_notification_sink)
    return True


__all__ = [
    "ControlPlaneSLOAlertSink",
    "ControlPlaneSLONotificationSink",
    "get_slo_notification_sink",
    "register_slo_alert_sink",
]
