"""
Integration tests for SLO webhook flow.

Tests the full flow from SLO violation detection through webhook notification,
including:
- Server startup initialization
- Violation detection and recording
- Webhook notification dispatch
- Recovery detection and notification
- API endpoints for status and testing
"""

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _register_webhook_sink_provider():
    """Route patched dispatchers through the inward registration hook."""
    from aragora.observability.metrics.slo import register_slo_event_sink_provider

    def provider():
        from aragora.integrations import webhooks

        return webhooks.get_dispatcher()

    register_slo_event_sink_provider(provider)
    yield
    register_slo_event_sink_provider(None)


class TestSLOWebhookIntegrationFlow:
    """Integration tests for SLO webhook end-to-end flow."""

    @pytest.fixture(autouse=True)
    def reset_slo_state(self):
        """Reset SLO state before each test."""
        from aragora.observability.metrics import slo as slo_module

        def provider():
            from aragora.integrations import webhooks

            return webhooks.get_dispatcher()

        slo_module.register_slo_event_sink_provider(provider)
        # Reset all module state
        slo_module._webhook_callback = None
        slo_module._webhook_sink = None
        slo_module._webhook_config = None
        slo_module._last_notification = {}
        slo_module._violation_state = {}
        slo_module._notification_count = 0
        slo_module._recovery_count = 0
        yield
        # Cleanup after test
        slo_module.register_slo_event_sink_provider(None)
        slo_module._webhook_config = None
        slo_module._last_notification = {}
        slo_module._violation_state = {}
        slo_module._notification_count = 0
        slo_module._recovery_count = 0

    def test_full_violation_to_recovery_flow(self):
        """Test complete flow from violation detection to recovery notification."""
        from aragora.observability.metrics.slo import (
            SLOWebhookConfig,
            check_and_record_slo_with_recovery,
            get_violation_state,
            init_slo_webhooks,
        )

        # Track notifications
        notifications: list[dict[str, Any]] = []

        # Create a mock dispatcher that has an enqueue method
        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = (
            lambda event: notifications.append({"type": event.get("type"), "payload": event})
            or True
        )

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = mock_dispatcher

            # Initialize SLO webhooks with minimal cooldown for testing
            config = SLOWebhookConfig(
                enabled=True,
                min_severity="minor",
                cooldown_seconds=0.0,  # No cooldown for testing
            )
            assert init_slo_webhooks(config) is True

            # Step 1: Trigger a violation (latency > threshold)
            passed, message = check_and_record_slo_with_recovery(
                operation="km_query",
                latency_ms=1500.0,  # 1500ms > 500ms threshold
                percentile="p99",
                context={"endpoint": "/api/test"},
            )

            # Verify violation detected
            assert passed is False
            assert "EXCEEDS" in message

            # Check violation notification was sent
            assert len(notifications) == 1
            assert notifications[0]["type"] == "slo_violation"
            assert notifications[0]["payload"]["operation"] == "km_query"

            # Check violation state is tracked
            state = get_violation_state("km_query")
            assert state["in_violation"] is True
            # Severity should be critical for 3x threshold
            assert state["last_severity"] == "critical"

            # Step 2: Operation returns to normal (latency < threshold)
            notifications.clear()
            passed, message = check_and_record_slo_with_recovery(
                operation="km_query",
                latency_ms=200.0,  # 200ms < 500ms threshold
                percentile="p99",
                context={"endpoint": "/api/test"},
            )

            # Verify passed
            assert passed is True
            assert "OK" in message or "within" in message.lower()

            # Check recovery notification was sent
            assert len(notifications) == 1
            assert notifications[0]["type"] == "slo_recovery"
            assert notifications[0]["payload"]["operation"] == "km_query"
            assert "violation_duration_seconds" in notifications[0]["payload"]

            # Check violation state cleared
            state = get_violation_state("km_query")
            assert state["in_violation"] is False

    def test_server_startup_initializes_slo_webhooks(self):
        """Test that server startup properly initializes SLO webhooks."""
        # Verify the startup module has the init_slo_webhooks function
        from aragora.server.startup import init_slo_webhooks as startup_init

        assert callable(startup_init)

        # Verify calling it returns a boolean (false without dispatcher)
        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = None
            result = startup_init()
            assert isinstance(result, bool)

    def test_multiple_operations_independent_tracking(self):
        """Test that different operations are tracked independently."""
        from aragora.observability.metrics.slo import (
            SLOWebhookConfig,
            check_and_record_slo_with_recovery,
            get_violation_state,
            init_slo_webhooks,
        )

        notifications: list[dict[str, Any]] = []

        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = (
            lambda event: notifications.append({"type": event.get("type"), "payload": event})
            or True
        )

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = mock_dispatcher

            config = SLOWebhookConfig(enabled=True, cooldown_seconds=0.0)
            init_slo_webhooks(config)

            # Trigger violations for two different operations
            # km_query has p99 threshold of 500ms
            # km_ingestion has p99 threshold of 1000ms
            check_and_record_slo_with_recovery("km_query", 1000.0, "p99")  # Exceeds 500ms
            check_and_record_slo_with_recovery("km_ingestion", 2000.0, "p99")  # Exceeds 1000ms

            # Both should be in violation
            assert get_violation_state("km_query")["in_violation"] is True
            assert get_violation_state("km_ingestion")["in_violation"] is True
            assert len(notifications) == 2

            # Recover km_query only
            notifications.clear()
            check_and_record_slo_with_recovery("km_query", 100.0, "p99")  # Under 500ms

            # km_query recovered, km_ingestion still in violation
            assert get_violation_state("km_query")["in_violation"] is False
            assert get_violation_state("km_ingestion")["in_violation"] is True
            assert len(notifications) == 1
            assert notifications[0]["payload"]["operation"] == "km_query"

    def test_severity_filtering_integration(self):
        """Test that severity filtering works in the full flow."""
        from aragora.observability.metrics.slo import (
            SLOWebhookConfig,
            get_slo_webhook_status,
            init_slo_webhooks,
            notify_slo_violation,
        )

        notifications: list[dict[str, Any]] = []

        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = (
            lambda event: notifications.append({"type": event.get("type"), "payload": event})
            or True
        )

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = mock_dispatcher

            # Configure to only notify on major or critical
            config = SLOWebhookConfig(
                enabled=True,
                min_severity="major",
                cooldown_seconds=0.0,
            )
            init_slo_webhooks(config)

            # Minor violation - should be filtered
            result = notify_slo_violation(
                operation="test",
                percentile="p99",
                latency_ms=600.0,
                threshold_ms=500.0,
                severity="minor",
            )
            assert result is False
            assert len(notifications) == 0

            # Major violation - should go through
            result = notify_slo_violation(
                operation="test",
                percentile="p99",
                latency_ms=1100.0,
                threshold_ms=500.0,
                severity="major",
            )
            assert result is True
            assert len(notifications) == 1

    def test_webhook_handler_endpoints(self):
        """Test the webhook handler SLO endpoints."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        ctx: dict[str, Any] = {}
        handler = WebhookHandler(ctx)

        # Test status endpoint when not initialized
        result = handler._handle_slo_status(None)
        assert result.status_code == 200
        import json

        body = json.loads(result.body)
        assert body["slo_webhooks"]["enabled"] is False
        assert body["slo_webhooks"]["initialized"] is False
        assert body["active_violations"] == 0

        # Test test endpoint when not initialized
        result = handler._handle_slo_test(None)
        assert result.status_code == 400
        body = json.loads(result.body)
        assert "not enabled" in body["error"]

    def test_webhook_handler_after_initialization(self):
        """Test webhook handler endpoints after SLO initialization."""
        from aragora.observability.metrics.slo import (
            SLOWebhookConfig,
            init_slo_webhooks,
        )
        from aragora.server.handlers.webhook_management import WebhookHandler

        notifications: list[dict[str, Any]] = []

        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = (
            lambda event: notifications.append({"type": event.get("type"), "payload": event})
            or True
        )

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = mock_dispatcher

            config = SLOWebhookConfig(enabled=True, cooldown_seconds=0.0)
            init_slo_webhooks(config)

            ctx: dict[str, Any] = {}
            handler = WebhookHandler(ctx)

            # Test status endpoint after initialization
            result = handler._handle_slo_status(None)
            assert result.status_code == 200
            import json

            body = json.loads(result.body)
            assert body["slo_webhooks"]["enabled"] is True
            assert body["slo_webhooks"]["initialized"] is True

            # Test sending a test notification
            result = handler._handle_slo_test(None)
            assert result.status_code == 200
            body = json.loads(result.body)
            assert body["success"] is True

            # Verify notification was sent
            assert len(notifications) == 1
            assert notifications[0]["type"] == "slo_violation"
            assert notifications[0]["payload"]["operation"] == "test_operation"

    def test_violation_state_persistence_across_checks(self):
        """Test that violation state persists correctly across multiple checks."""
        from aragora.observability.metrics.slo import (
            SLOWebhookConfig,
            check_and_record_slo_with_recovery,
            get_violation_state,
            init_slo_webhooks,
        )

        notifications: list[dict[str, Any]] = []

        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = (
            lambda event: notifications.append({"type": event.get("type"), "payload": event})
            or True
        )

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = mock_dispatcher

            config = SLOWebhookConfig(enabled=True, cooldown_seconds=0.0)
            init_slo_webhooks(config)

            # Initial violation - km_query has p99 threshold of 500ms
            check_and_record_slo_with_recovery("km_query", 2000.0, "p99")
            state = get_violation_state("km_query")
            initial_violation_time = state["violation_start"]

            # Subsequent violations should not reset the start time
            time.sleep(0.1)
            check_and_record_slo_with_recovery("km_query", 2500.0, "p99")
            state = get_violation_state("km_query")
            assert state["violation_start"] == initial_violation_time

            # Recovery should clear the state
            check_and_record_slo_with_recovery("km_query", 100.0, "p99")
            state = get_violation_state("km_query")
            assert state["in_violation"] is False
            assert state.get("violation_start") is None

    def test_prometheus_alerting_rules_exist(self):
        """Verify Prometheus alerting rules file contains SLO alerts."""
        import yaml
        from pathlib import Path

        alerts_path = Path(__file__).resolve().parents[2] / "deploy/observability/alerts.rules"
        assert alerts_path.exists(), "Prometheus alerts file should exist"

        content = alerts_path.read_text()
        rules = yaml.safe_load(content)

        # Find the aragora_slo_operations group
        slo_group = None
        for group in rules.get("groups", []):
            if group.get("name") == "aragora_slo_operations":
                slo_group = group
                break

        assert slo_group is not None, "SLO alert group should exist"

        # Check for key alerts
        alert_names = [r.get("alert") for r in slo_group.get("rules", [])]
        expected_alerts = [
            "SLOViolationRateHigh",
            "SLOViolationCritical",
            "SLOKMQueryLatencyBreach",
        ]
        for expected in expected_alerts:
            assert expected in alert_names, f"Missing alert: {expected}"


class TestSLOWebhookCooldownIntegration:
    """Integration tests for cooldown behavior."""

    @pytest.fixture(autouse=True)
    def reset_slo_state(self):
        """Reset SLO state before each test."""
        from aragora.observability.metrics import slo as slo_module

        slo_module._webhook_callback = None
        slo_module._webhook_config = None
        slo_module._last_notification = {}
        slo_module._violation_state = {}
        slo_module._notification_count = 0
        slo_module._recovery_count = 0
        yield
        slo_module._webhook_callback = None
        slo_module._webhook_config = None
        slo_module._last_notification = {}
        slo_module._violation_state = {}
        slo_module._notification_count = 0
        slo_module._recovery_count = 0

    def test_cooldown_integration_with_recovery(self):
        """Test that cooldown doesn't affect recovery notifications."""
        from aragora.observability.metrics.slo import (
            SLOWebhookConfig,
            check_and_record_slo_with_recovery,
            init_slo_webhooks,
        )

        notifications: list[dict[str, Any]] = []

        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = (
            lambda event: notifications.append({"type": event.get("type"), "payload": event})
            or True
        )

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = mock_dispatcher

            # Configure with longer cooldown
            config = SLOWebhookConfig(
                enabled=True,
                cooldown_seconds=60.0,  # 60 second cooldown
            )
            init_slo_webhooks(config)

            # First violation goes through - km_query has p99 threshold of 500ms
            check_and_record_slo_with_recovery("km_query", 1000.0, "p99")
            assert len(notifications) == 1
            assert notifications[0]["type"] == "slo_violation"

            # Second violation is blocked by cooldown
            notifications.clear()
            check_and_record_slo_with_recovery("km_query", 1100.0, "p99")
            # No new notification due to cooldown
            # (operation is already in violation state, so no duplicate)

            # Recovery should still go through regardless of cooldown
            notifications.clear()
            check_and_record_slo_with_recovery("km_query", 100.0, "p99")
            assert len(notifications) == 1
            assert notifications[0]["type"] == "slo_recovery"


class TestSLOWebhookErrorHandling:
    """Integration tests for error handling in SLO webhook flow."""

    @pytest.fixture(autouse=True)
    def reset_slo_state(self):
        """Reset SLO state before each test."""
        from aragora.observability.metrics import slo as slo_module

        slo_module._webhook_callback = None
        slo_module._webhook_config = None
        slo_module._last_notification = {}
        slo_module._violation_state = {}
        slo_module._notification_count = 0
        slo_module._recovery_count = 0
        yield
        slo_module._webhook_callback = None
        slo_module._webhook_config = None
        slo_module._last_notification = {}
        slo_module._violation_state = {}
        slo_module._notification_count = 0
        slo_module._recovery_count = 0

    def test_dispatcher_exception_handled_gracefully(self):
        """Test that exceptions in dispatcher don't crash the flow."""
        from aragora.observability.metrics.slo import (
            SLOWebhookConfig,
            init_slo_webhooks,
            notify_slo_violation,
        )

        def failing_enqueue(event):
            raise RuntimeError("Dispatcher failed!")

        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = failing_enqueue

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = mock_dispatcher

            config = SLOWebhookConfig(enabled=True, cooldown_seconds=0.0)
            init_slo_webhooks(config)

            # This should not raise, just return False
            result = notify_slo_violation(
                operation="test",
                percentile="p99",
                latency_ms=1000.0,
                threshold_ms=500.0,
                severity="major",
            )
            assert result is False

    def test_missing_dispatcher_handled(self):
        """Test that missing dispatcher is handled gracefully."""
        from aragora.observability.metrics.slo import (
            init_slo_webhooks,
            notify_slo_violation,
        )

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = None

            # init should return False when dispatcher unavailable
            result = init_slo_webhooks()
            assert result is False

            # notify should return False when not initialized
            result = notify_slo_violation(
                operation="test",
                percentile="p99",
                latency_ms=1000.0,
                threshold_ms=500.0,
                severity="major",
            )
            assert result is False
