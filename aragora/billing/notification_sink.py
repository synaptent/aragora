"""Billing-owned contract for best-effort external notifications."""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class BillingNotificationSink(Protocol):
    """Higher-layer notification capability consumed by billing."""

    async def notify_budget_runway(
        self,
        *,
        title: str,
        message: str,
        severity: str,
        workspace_id: str,
    ) -> None: ...

    async def notify_cost_anomaly(
        self,
        *,
        anomaly_type: str,
        severity: str,
        amount: float,
        expected: float,
        workspace_id: str,
        details: str | None,
    ) -> None: ...


_notification_sink: BillingNotificationSink | None = None


def register_billing_notification_sink(sink: BillingNotificationSink) -> None:
    """Register the process-wide notification capability."""
    global _notification_sink
    _notification_sink = sink


def clear_billing_notification_sink() -> None:
    """Clear the registered capability, primarily for isolated tests."""
    global _notification_sink
    _notification_sink = None


async def notify_budget_runway(
    *,
    title: str,
    message: str,
    severity: str,
    workspace_id: str,
) -> bool:
    """Send a budget runway notification when a sink is available."""
    if _notification_sink is None:
        logger.debug("Billing notification sink is not registered")
        return False
    await _notification_sink.notify_budget_runway(
        title=title,
        message=message,
        severity=severity,
        workspace_id=workspace_id,
    )
    return True


async def notify_cost_anomaly(
    *,
    anomaly_type: str,
    severity: str,
    amount: float,
    expected: float,
    workspace_id: str,
    details: str | None,
) -> bool:
    """Send a cost anomaly notification when a sink is available."""
    if _notification_sink is None:
        logger.debug("Billing notification sink is not registered")
        return False
    await _notification_sink.notify_cost_anomaly(
        anomaly_type=anomaly_type,
        severity=severity,
        amount=amount,
        expected=expected,
        workspace_id=workspace_id,
        details=details,
    )
    return True


__all__ = [
    "BillingNotificationSink",
    "clear_billing_notification_sink",
    "notify_budget_runway",
    "notify_cost_anomaly",
    "register_billing_notification_sink",
]
