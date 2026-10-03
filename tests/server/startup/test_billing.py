"""Tests for server-side billing adapter composition."""

from unittest.mock import patch

import pytest

from aragora.server.startup.billing import init_billing_edge_adapters


def test_init_billing_edge_adapters_registers_all_capabilities():
    with (
        patch("aragora.audit.billing_sink.register_billing_audit_sink") as audit,
        patch("aragora.connectors.chat.budget_alert_sink.register_budget_alert_sinks") as channels,
        patch(
            "aragora.knowledge.mound.cost_adapter_registration.register_billing_cost_adapter"
        ) as cost,
        patch(
            "aragora.notifications.billing_sink.register_billing_notification_sink"
        ) as notifications,
    ):
        assert init_billing_edge_adapters() is True

    audit.assert_called_once_with()
    channels.assert_called_once_with()
    cost.assert_called_once_with()
    notifications.assert_called_once_with()


def test_init_billing_edge_adapters_degrades_on_registration_failure():
    with (
        patch(
            "aragora.audit.billing_sink.register_billing_audit_sink",
            side_effect=ImportError("audit unavailable"),
        ),
        patch("aragora.connectors.chat.budget_alert_sink.register_budget_alert_sinks") as channels,
        patch(
            "aragora.knowledge.mound.cost_adapter_registration.register_billing_cost_adapter"
        ) as cost,
        patch(
            "aragora.notifications.billing_sink.register_billing_notification_sink"
        ) as notifications,
    ):
        assert init_billing_edge_adapters() is False

    channels.assert_called_once_with()
    cost.assert_called_once_with()
    notifications.assert_called_once_with()


def test_init_billing_edge_adapters_fails_strictly():
    with (
        patch(
            "aragora.audit.billing_sink.register_billing_audit_sink",
            side_effect=ImportError("audit unavailable"),
        ),
        pytest.raises(RuntimeError, match="Billing edge adapter registration failed"),
    ):
        init_billing_edge_adapters(strict=True)
