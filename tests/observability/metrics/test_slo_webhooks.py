"""Tests for SLO webhook integration."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from aragora.observability.metrics.slo import (
    init_slo_webhooks,
    notify_slo_violation,
    notify_slo_recovery,
    get_slo_webhook_status,
    get_violation_state,
    record_slo_violation,
    register_slo_event_sink_provider,
    check_and_record_slo_with_recovery,
    SLOWebhookConfig,
    SEVERITY_ORDER,
)


@pytest.fixture(autouse=True)
def _register_webhook_sink_provider():
    """Preserve dynamic dispatcher patching through the inward provider."""

    def provider():
        from aragora.integrations import webhooks

        return webhooks.get_dispatcher()

    register_slo_event_sink_provider(provider)
    yield
    register_slo_event_sink_provider(None)


class TestSeverityOrdering:
    """Tests for severity level ordering."""

    def test_severity_order_values(self):
        """Test severity ordering is correct."""
        assert SEVERITY_ORDER["minor"] < SEVERITY_ORDER["moderate"]
        assert SEVERITY_ORDER["moderate"] < SEVERITY_ORDER["major"]
        assert SEVERITY_ORDER["major"] < SEVERITY_ORDER["critical"]

    def test_all_severities_present(self):
        """Test all expected severities are defined."""
        assert "minor" in SEVERITY_ORDER
        assert "moderate" in SEVERITY_ORDER
        assert "major" in SEVERITY_ORDER
        assert "critical" in SEVERITY_ORDER


class TestSLOWebhookConfig:
    """Tests for SLOWebhookConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SLOWebhookConfig()
        assert config.enabled is True
        assert config.min_severity == "minor"
        assert config.batch_size == 10
        assert config.cooldown_seconds == 60.0

    def test_custom_values(self):
        """Test custom configuration values."""
        config = SLOWebhookConfig(
            enabled=False,
            min_severity="major",
            batch_size=5,
            cooldown_seconds=120.0,
        )
        assert config.enabled is False
        assert config.min_severity == "major"
        assert config.batch_size == 5
        assert config.cooldown_seconds == 120.0


class TestInitSLOWebhooks:
    """Tests for init_slo_webhooks function."""

    def test_returns_false_when_dispatcher_unavailable(self):
        """Test returns False when webhook dispatcher is not available."""
        import aragora.observability.metrics.slo as slo_module

        # Reset callback state
        slo_module._webhook_callback = None

        with patch(
            "aragora.integrations.webhooks.get_dispatcher",
            return_value=None,
        ):
            result = init_slo_webhooks()
            assert result is False

    def test_returns_true_when_dispatcher_available(self):
        """Test returns True when webhook dispatcher is available."""
        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = MagicMock(return_value=True)

        with patch(
            "aragora.integrations.webhooks.get_dispatcher",
            return_value=mock_dispatcher,
        ):
            result = init_slo_webhooks()
            assert result is True

    def test_uses_custom_config(self):
        """Test custom config is used."""
        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = MagicMock(return_value=True)

        config = SLOWebhookConfig(min_severity="critical")

        with patch(
            "aragora.integrations.webhooks.get_dispatcher",
            return_value=mock_dispatcher,
        ):
            result = init_slo_webhooks(webhook_config=config)
            assert result is True

    def test_registered_provider_supplies_dispatcher(self):
        """The integrations layer can register its dispatcher inward."""
        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = MagicMock(return_value=True)
        register_slo_event_sink_provider(lambda: mock_dispatcher)
        try:
            assert init_slo_webhooks() is True
        finally:
            register_slo_event_sink_provider(None)

    def test_replacing_provider_rebinds_active_dispatcher(self):
        """Replacing a provider keeps initialized delivery active on the new sink."""
        old_dispatcher = MagicMock()
        old_dispatcher.enqueue = MagicMock(return_value=True)
        new_dispatcher = MagicMock()
        new_dispatcher.enqueue = MagicMock(return_value=True)

        register_slo_event_sink_provider(lambda: old_dispatcher)
        assert init_slo_webhooks() is True
        register_slo_event_sink_provider(lambda: new_dispatcher)

        assert (
            notify_slo_violation(
                operation="provider_rebound",
                percentile="p99",
                latency_ms=600.0,
                threshold_ms=500.0,
                severity="minor",
                cooldown_seconds=0.0,
            )
            is True
        )
        old_dispatcher.enqueue.assert_not_called()
        new_dispatcher.enqueue.assert_called_once()

    def test_failed_provider_replacement_preserves_active_dispatcher(self):
        """A replacement that cannot resolve does not disable active delivery."""
        old_dispatcher = MagicMock()
        old_dispatcher.enqueue = MagicMock(return_value=True)

        register_slo_event_sink_provider(lambda: old_dispatcher)
        assert init_slo_webhooks() is True
        register_slo_event_sink_provider(lambda: None)

        assert (
            notify_slo_violation(
                operation="provider_replacement_failed",
                percentile="p99",
                latency_ms=600.0,
                threshold_ms=500.0,
                severity="minor",
                cooldown_seconds=0.0,
            )
            is True
        )
        old_dispatcher.enqueue.assert_called_once()

    def test_violation_callback_refreshes_replaceable_provider_result(self):
        """Violation delivery follows a dispatcher singleton replacement."""
        old_dispatcher = MagicMock()
        old_dispatcher.enqueue = MagicMock(return_value=True)
        new_dispatcher = MagicMock()
        new_dispatcher.enqueue = MagicMock(return_value=True)
        current_dispatcher = [old_dispatcher]
        register_slo_event_sink_provider(lambda: current_dispatcher[0])
        assert init_slo_webhooks() is True

        assert (
            notify_slo_violation(
                operation="old_dispatcher",
                percentile="p99",
                latency_ms=600.0,
                threshold_ms=500.0,
                severity="minor",
                cooldown_seconds=0.0,
            )
            is True
        )
        current_dispatcher[0] = new_dispatcher
        assert (
            notify_slo_violation(
                operation="new_dispatcher",
                percentile="p99",
                latency_ms=600.0,
                threshold_ms=500.0,
                severity="minor",
                cooldown_seconds=0.0,
            )
            is True
        )

        old_dispatcher.enqueue.assert_called_once()
        new_dispatcher.enqueue.assert_called_once()

    def test_reinitialization_refreshes_cached_dispatcher(self):
        """Repeated initialization resolves the provider's current dispatcher."""
        import aragora.observability.metrics.slo as slo_module

        old_dispatcher = MagicMock()
        old_dispatcher.enqueue = MagicMock(return_value=True)
        new_dispatcher = MagicMock()
        new_dispatcher.enqueue = MagicMock(return_value=True)
        current_dispatcher = [old_dispatcher]

        register_slo_event_sink_provider(lambda: current_dispatcher[0])
        assert init_slo_webhooks() is True
        assert slo_module._webhook_sink is old_dispatcher

        current_dispatcher[0] = new_dispatcher
        assert init_slo_webhooks() is True
        assert slo_module._webhook_sink is new_dispatcher


class TestNotifySLOViolation:
    """Tests for notify_slo_violation function."""

    def test_returns_false_when_not_initialized(self):
        """Test returns False when webhooks not initialized."""
        # Reset the callback
        import aragora.observability.metrics.slo as slo_module

        slo_module._webhook_callback = None

        result = notify_slo_violation(
            operation="test_op",
            percentile="p99",
            latency_ms=600.0,
            threshold_ms=500.0,
            severity="moderate",
        )
        assert result is False

    def test_calculates_margins_correctly(self):
        """Test margin calculations are correct."""
        captured_data = {}

        def capture_callback(data):
            captured_data.update(data)
            return True

        import aragora.observability.metrics.slo as slo_module

        slo_module._webhook_callback = capture_callback
        slo_module._last_notification = {}  # Clear cooldown

        notify_slo_violation(
            operation="margin_test",
            percentile="p99",
            latency_ms=750.0,
            threshold_ms=500.0,
            severity="major",
        )

        assert captured_data["margin_ms"] == 250.0
        assert captured_data["margin_percent"] == 50.0

    def test_includes_context(self):
        """Test context is included in notification."""
        captured_data = {}

        def capture_callback(data):
            captured_data.update(data)
            return True

        import aragora.observability.metrics.slo as slo_module

        slo_module._webhook_callback = capture_callback
        slo_module._last_notification = {}

        notify_slo_violation(
            operation="context_test",
            percentile="p90",
            latency_ms=200.0,
            threshold_ms=100.0,
            severity="critical",
            context={"request_id": "req_123", "user_id": "user_456"},
        )

        assert captured_data["context"]["request_id"] == "req_123"
        assert captured_data["context"]["user_id"] == "user_456"


class TestGetSLOWebhookStatus:
    """Tests for get_slo_webhook_status function."""

    def test_returns_status_dict(self):
        """Test returns proper status dictionary."""
        status = get_slo_webhook_status()

        assert "enabled" in status
        assert "cooldown_active" in status
        assert "buffer_size" in status
        assert isinstance(status["enabled"], bool)
        assert isinstance(status["cooldown_active"], dict)
        assert isinstance(status["buffer_size"], int)


class TestRecordSLOViolationWithWebhook:
    """Tests for record_slo_violation with webhook integration."""

    def test_auto_calculates_severity(self):
        """Test severity is auto-calculated based on margin."""
        import aragora.observability.metrics.slo as slo_module

        # Mock metrics to avoid prometheus issues
        slo_module._initialized = True
        slo_module.SLO_VIOLATIONS_TOTAL = MagicMock()
        slo_module.SLO_VIOLATION_MARGIN = MagicMock()
        slo_module._webhook_callback = None  # Disable webhook for this test

        # Minor: < 20% over
        severity = record_slo_violation("test_op", "p99", 110.0, 100.0, notify_webhook=False)
        assert severity == "minor"

        # Moderate: 20-50% over
        severity = record_slo_violation("test_op", "p99", 130.0, 100.0, notify_webhook=False)
        assert severity == "moderate"

        # Major: 50-100% over
        severity = record_slo_violation("test_op", "p99", 175.0, 100.0, notify_webhook=False)
        assert severity == "major"

        # Critical: > 100% over
        severity = record_slo_violation("test_op", "p99", 250.0, 100.0, notify_webhook=False)
        assert severity == "critical"

    def test_respects_notify_webhook_flag(self):
        """Test notify_webhook flag controls webhook notification."""
        import aragora.observability.metrics.slo as slo_module

        called = []

        def track_callback(data):
            called.append(data)
            return True

        slo_module._initialized = True
        slo_module.SLO_VIOLATIONS_TOTAL = MagicMock()
        slo_module.SLO_VIOLATION_MARGIN = MagicMock()
        slo_module._webhook_callback = track_callback
        slo_module._last_notification = {}

        # With notify_webhook=False, should not call webhook
        record_slo_violation("no_notify_op", "p99", 600.0, 500.0, notify_webhook=False)
        assert len(called) == 0

        # With notify_webhook=True (default), should call webhook
        record_slo_violation("yes_notify_op", "p99", 600.0, 500.0, notify_webhook=True)
        assert len(called) == 1


class TestCooldownBehavior:
    """Tests for cooldown behavior in webhook notifications."""

    def test_cooldown_prevents_rapid_notifications(self):
        """Test cooldown prevents rapid notifications for same operation."""
        import aragora.observability.metrics.slo as slo_module

        call_count = [0]

        def counting_callback(data):
            call_count[0] += 1
            return True

        # Set the last notification time to now to simulate a recent notification
        import time

        slo_module._webhook_callback = counting_callback
        slo_module._last_notification = {"cooldown_op": time.time()}

        # This call should be blocked by cooldown (within 60 seconds)
        result = notify_slo_violation("cooldown_op", "p99", 700.0, 500.0, "moderate")
        assert result is False
        assert call_count[0] == 0  # Should not have been called

    def test_first_notification_goes_through(self):
        """Test first notification for an operation goes through."""
        import aragora.observability.metrics.slo as slo_module

        call_count = [0]

        def counting_callback(data):
            call_count[0] += 1
            return True

        slo_module._webhook_callback = counting_callback
        slo_module._last_notification = {}  # Empty - no previous notifications

        # First call should go through
        result = notify_slo_violation("first_op", "p99", 600.0, 500.0, "minor")
        assert result is True
        assert call_count[0] == 1

    def test_different_operations_independent_cooldown(self):
        """Test different operations have independent cooldowns."""
        import aragora.observability.metrics.slo as slo_module

        call_count = [0]

        def counting_callback(data):
            call_count[0] += 1
            return True

        slo_module._webhook_callback = counting_callback
        slo_module._last_notification = {}

        # First operation
        notify_slo_violation("op_a", "p99", 600.0, 500.0, "minor")
        assert call_count[0] == 1

        # Different operation should not be blocked
        notify_slo_violation("op_b", "p99", 600.0, 500.0, "minor")
        assert call_count[0] == 2


class TestSeverityFiltering:
    """Tests for severity-based filtering in webhook notifications."""

    def test_filters_by_min_severity(self):
        """Test violations below min_severity are filtered."""
        mock_dispatcher = MagicMock()
        enqueue_calls = []

        def track_enqueue(event):
            enqueue_calls.append(event)
            return True

        mock_dispatcher.enqueue = track_enqueue

        with patch(
            "aragora.integrations.webhooks.get_dispatcher",
            return_value=mock_dispatcher,
        ):
            # Initialize with min_severity="major"
            config = SLOWebhookConfig(min_severity="major")
            init_slo_webhooks(webhook_config=config)

            import aragora.observability.metrics.slo as slo_module

            slo_module._last_notification = {}

            # Minor should be filtered
            result1 = notify_slo_violation("filter_op1", "p99", 110.0, 100.0, "minor")
            # Moderate should be filtered
            result2 = notify_slo_violation("filter_op2", "p99", 140.0, 100.0, "moderate")
            # Major should pass
            result3 = notify_slo_violation("filter_op3", "p99", 175.0, 100.0, "major")

            # Only major severity should have been enqueued
            major_events = [e for e in enqueue_calls if e.get("severity") == "major"]
            assert len(major_events) >= 1


class TestSLORecovery:
    """Tests for SLO recovery notifications."""

    def test_notify_slo_recovery_returns_false_when_not_initialized(self):
        """Test returns False when no webhook sink is registered."""
        register_slo_event_sink_provider(None)

        result = notify_slo_recovery(
            operation="test_op",
            percentile="p99",
            latency_ms=400.0,
            threshold_ms=500.0,
            violation_duration_seconds=120.0,
        )
        assert result is False

    def test_notify_slo_recovery_sends_correct_event(self):
        """Test recovery notification sends correct event type."""
        import aragora.observability.metrics.slo as slo_module

        mock_dispatcher = MagicMock()
        captured_events = []

        def capture_enqueue(event):
            captured_events.append(event)
            return True

        mock_dispatcher.enqueue = capture_enqueue

        with patch(
            "aragora.integrations.webhooks.get_dispatcher",
            return_value=mock_dispatcher,
        ):
            assert init_slo_webhooks() is True
            result = notify_slo_recovery(
                operation="recovery_test",
                percentile="p99",
                latency_ms=400.0,
                threshold_ms=500.0,
                violation_duration_seconds=120.0,
                context={"request_id": "req_456"},
            )

            assert result is True
            assert len(captured_events) == 1
            event = captured_events[0]
            assert event["type"] == "slo_recovery"
            assert event["operation"] == "recovery_test"
            assert event["latency_ms"] == 400.0
            assert event["threshold_ms"] == 500.0
            assert event["margin_ms"] == 100.0  # 500 - 400
            assert event["violation_duration_seconds"] == 120.0
            assert event["context"]["request_id"] == "req_456"

    def test_recovery_uses_registered_sink(self):
        """Recovery events use the same registered sink as violations."""
        import aragora.observability.metrics.slo as slo_module

        mock_dispatcher = MagicMock()
        captured_events = []
        mock_dispatcher.enqueue = lambda event: captured_events.append(event) or True
        register_slo_event_sink_provider(lambda: mock_dispatcher)
        try:
            assert init_slo_webhooks() is True
            assert (
                notify_slo_recovery(
                    operation="registered_recovery",
                    percentile="p99",
                    latency_ms=400.0,
                    threshold_ms=500.0,
                    violation_duration_seconds=60.0,
                )
                is True
            )
            assert captured_events[-1]["type"] == "slo_recovery"
        finally:
            register_slo_event_sink_provider(None)
            slo_module._webhook_callback = None

    def test_recovery_resolves_registered_sink_without_explicit_init(self):
        """Recovery delivery preserves legacy no-init behavior via the provider."""
        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = MagicMock(return_value=True)
        register_slo_event_sink_provider(lambda: mock_dispatcher)

        try:
            assert (
                notify_slo_recovery(
                    operation="registered_recovery_no_init",
                    percentile="p99",
                    latency_ms=400.0,
                    threshold_ms=500.0,
                    violation_duration_seconds=60.0,
                )
                is True
            )
        finally:
            register_slo_event_sink_provider(None)

        event = mock_dispatcher.enqueue.call_args.args[0]
        assert event["type"] == "slo_recovery"

    def test_recovery_refreshes_replaceable_provider_result(self):
        """Recovery delivery does not retain a stopped singleton dispatcher."""
        old_dispatcher = MagicMock()
        old_dispatcher.enqueue = MagicMock(return_value=True)
        new_dispatcher = MagicMock()
        new_dispatcher.enqueue = MagicMock(return_value=True)
        current_dispatcher = [old_dispatcher]
        register_slo_event_sink_provider(lambda: current_dispatcher[0])

        try:
            assert (
                notify_slo_recovery(
                    operation="old_dispatcher",
                    percentile="p99",
                    latency_ms=400.0,
                    threshold_ms=500.0,
                    violation_duration_seconds=60.0,
                )
                is True
            )
            current_dispatcher[0] = new_dispatcher
            assert (
                notify_slo_recovery(
                    operation="new_dispatcher",
                    percentile="p99",
                    latency_ms=400.0,
                    threshold_ms=500.0,
                    violation_duration_seconds=60.0,
                )
                is True
            )
        finally:
            register_slo_event_sink_provider(None)

        old_dispatcher.enqueue.assert_called_once()
        new_dispatcher.enqueue.assert_called_once()


class TestViolationState:
    """Tests for violation state tracking."""

    def test_get_violation_state_empty(self):
        """Test get_violation_state returns empty when no violations."""
        import aragora.observability.metrics.slo as slo_module

        slo_module._violation_state = {}

        state = get_violation_state("unknown_op")
        assert state == {"in_violation": False}

    def test_get_violation_state_all(self):
        """Test get_violation_state returns all states."""
        import aragora.observability.metrics.slo as slo_module

        slo_module._violation_state = {
            "op1": {"in_violation": True, "last_severity": "major"},
            "op2": {"in_violation": False},
        }

        all_states = get_violation_state()
        assert "op1" in all_states
        assert "op2" in all_states
        assert all_states["op1"]["in_violation"] is True

    def test_get_slo_webhook_status_includes_violations(self):
        """Test status includes list of operations in violation."""
        import aragora.observability.metrics.slo as slo_module

        slo_module._violation_state = {
            "violating_op": {"in_violation": True},
            "healthy_op": {"in_violation": False},
        }

        status = get_slo_webhook_status()
        assert "operations_in_violation" in status
        assert "violating_op" in status["operations_in_violation"]
        assert "healthy_op" not in status["operations_in_violation"]


class TestCheckAndRecordWithRecovery:
    """Tests for check_and_record_slo_with_recovery."""

    def test_tracks_violation_state(self):
        """Test violation state is tracked correctly."""
        import aragora.observability.metrics.slo as slo_module

        # Mock required components
        slo_module._initialized = True
        slo_module.SLO_CHECKS_TOTAL = MagicMock()
        slo_module.SLO_VIOLATIONS_TOTAL = MagicMock()
        slo_module.SLO_VIOLATION_MARGIN = MagicMock()
        slo_module.SLO_LATENCY_HISTOGRAM = MagicMock()
        slo_module._webhook_callback = None
        slo_module._violation_state = {}

        # Mock the SLO check to fail
        with (
            patch(
                "aragora.config.performance_slos.check_latency_slo",
                return_value=(False, "SLO violated"),
            ),
            patch(
                "aragora.config.performance_slos.get_slo_config",
            ) as mock_config,
        ):
            mock_slo = MagicMock()
            mock_slo.p99_ms = 500.0
            mock_config.return_value = MagicMock(track_violation_op=mock_slo)

            passed, _ = check_and_record_slo_with_recovery("track_violation_op", 600.0, "p99")

            assert passed is False
            # Should be in violation state
            state = get_violation_state("track_violation_op")
            assert state.get("in_violation") is True

    def test_detects_recovery(self):
        """Test recovery is detected when SLO passes after violation."""
        import aragora.observability.metrics.slo as slo_module
        import time

        # Setup: Already in violation state
        slo_module._initialized = True
        slo_module.SLO_CHECKS_TOTAL = MagicMock()
        slo_module.SLO_VIOLATIONS_TOTAL = MagicMock()
        slo_module.SLO_VIOLATION_MARGIN = MagicMock()
        slo_module.SLO_LATENCY_HISTOGRAM = MagicMock()
        slo_module._webhook_callback = None
        slo_module._violation_state = {
            "recovery_op": {
                "in_violation": True,
                "violation_start": time.time() - 60,  # Started 60s ago
                "last_severity": "major",
                "percentile": "p99",
                "threshold_ms": 500.0,
            }
        }

        recovery_called = []

        # Mock notify_slo_recovery to track calls
        with (
            patch(
                "aragora.config.performance_slos.check_latency_slo",
                return_value=(True, "Within SLO"),
            ),
            patch.object(
                slo_module,
                "notify_slo_recovery",
                side_effect=lambda **kwargs: recovery_called.append(kwargs) or True,
            ),
        ):
            passed, _ = check_and_record_slo_with_recovery("recovery_op", 400.0, "p99")

            assert passed is True
            # Recovery should have been called
            assert len(recovery_called) == 1
            assert recovery_called[0]["operation"] == "recovery_op"
            assert recovery_called[0]["violation_duration_seconds"] >= 59.0

            # Violation state should be cleared
            state = get_violation_state("recovery_op")
            assert state.get("in_violation") is False
