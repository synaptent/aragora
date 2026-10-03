"""Tests for the control-plane SLO alert adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from aragora.control_plane.channels import NotificationEventType, NotificationPriority
from aragora.control_plane import slo_alert_sink as adapter
from aragora.observability import slo as slo_module
from aragora.observability import slo_alert_bridge
from aragora.observability.slo import SLOBreach, create_notification_callback
from aragora.observability.slo_alert_bridge import SLOAlertConfig


def _breach(*, severity: str = "critical") -> SLOBreach:
    return SLOBreach(
        slo_name="API Availability",
        severity=severity,
        current_value=0.975,
        target_value=0.999,
        error_budget_remaining=12.3,
        burn_rate=4.56,
        message="Availability below target",
        timestamp=datetime(2026, 7, 13, 12, 30, tzinfo=timezone.utc),
    )


@pytest.fixture(autouse=True)
def _reset_sinks():
    slo_alert_bridge.register_channel_alert_sink(None)
    register = getattr(slo_module, "register_slo_notification_sink_provider", None)
    if register is not None:
        register(None)
    yield
    slo_alert_bridge.register_channel_alert_sink(None)
    if register is not None:
        register(None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("severity", "priority"),
    [
        ("critical", NotificationPriority.CRITICAL),
        ("major", NotificationPriority.HIGH),
    ],
)
async def test_direct_notification_preserves_payload_and_priority(
    monkeypatch: pytest.MonkeyPatch,
    severity: str,
    priority: NotificationPriority,
) -> None:
    dispatcher = AsyncMock()
    monkeypatch.setattr(adapter, "get_default_notification_dispatcher", lambda: dispatcher)
    breach = _breach(severity=severity)

    await adapter.ControlPlaneSLONotificationSink().notify(breach)

    dispatcher.dispatch.assert_awaited_once_with(
        event_type=NotificationEventType.SYSTEM_ALERT,
        title="SLO Alert: API Availability",
        body=(
            "Availability below target\n\n"
            "Current: 0.9750\n"
            "Target: 0.9990\n"
            "Error Budget: 12.3%\n"
            "Burn Rate: 4.56x"
        ),
        priority=priority,
        metadata=breach.to_dict(),
    )


@pytest.mark.asyncio
async def test_direct_notification_resolves_replaced_dispatcher_each_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_dispatcher = AsyncMock()
    second_dispatcher = AsyncMock()
    dispatchers = iter((first_dispatcher, second_dispatcher))
    monkeypatch.setattr(
        adapter,
        "get_default_notification_dispatcher",
        lambda: next(dispatchers),
    )
    sink = adapter.ControlPlaneSLONotificationSink()
    breach = _breach()

    await sink.notify(breach)
    await sink.notify(breach)

    first_dispatcher.dispatch.assert_awaited_once()
    second_dispatcher.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_dispatcher_is_fail_soft(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(adapter, "get_default_notification_dispatcher", lambda: None)

    await adapter.ControlPlaneSLONotificationSink().notify(_breach())

    assert "Notification dispatcher not configured" in caplog.text


@pytest.mark.asyncio
async def test_registered_provider_tracks_dispatcher_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_dispatcher = AsyncMock()
    second_dispatcher = AsyncMock()
    current_dispatcher = [first_dispatcher]
    monkeypatch.setattr(
        adapter,
        "get_default_notification_dispatcher",
        lambda: current_dispatcher[0],
    )
    adapter.register_slo_alert_sink()
    callback = create_notification_callback()
    breach = _breach()

    await callback(breach)
    current_dispatcher[0] = second_dispatcher
    await callback(breach)

    first_dispatcher.dispatch.assert_awaited_once()
    second_dispatcher.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_channel_bridge_contract_remains_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = AsyncMock()
    sink = adapter.ControlPlaneSLOAlertSink(SLOAlertConfig())
    monkeypatch.setattr(sink, "_get_manager", lambda: manager)

    await sink.notify(
        event_type="system_alert",
        title="SLO Alert",
        body="Threshold exceeded",
        priority="critical",
        metadata={"slo_name": "availability"},
    )

    manager.notify.assert_awaited_once_with(
        event_type=NotificationEventType.SYSTEM_ALERT,
        title="SLO Alert",
        body="Threshold exceeded",
        priority=NotificationPriority.CRITICAL,
        metadata={"slo_name": "availability"},
    )


def test_registration_keeps_bridge_and_adds_direct_provider() -> None:
    assert adapter.register_slo_alert_sink() is True

    assert slo_alert_bridge._channel_alert_sink_factory is adapter.ControlPlaneSLOAlertSink
    assert slo_module._slo_notification_sink_provider is not None
