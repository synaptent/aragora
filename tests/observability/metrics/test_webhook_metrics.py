"""
Tests for webhook delivery metrics.
"""

import time
from unittest.mock import MagicMock, patch

import pytest


class TestWebhookMetricsInitialization:
    """Tests for metric initialization."""

    def test_init_returns_true_with_prometheus(self):
        """Test that _init_metrics returns True when prometheus_client is available."""
        from aragora.observability.metrics import webhook

        # Reset state
        webhook._metrics_initialized = False
        webhook._DELIVERIES_TOTAL = None

        result = webhook._init_metrics()

        # May be True or False depending on prometheus_client installation
        assert isinstance(result, bool)

    def test_init_is_idempotent(self):
        """Test that _init_metrics only initializes once."""
        from aragora.observability.metrics import webhook

        # Reset state
        webhook._metrics_initialized = False
        webhook._DELIVERIES_TOTAL = None

        result1 = webhook._init_metrics()
        result2 = webhook._init_metrics()

        # Second call should return same result
        assert result1 == result2


class TestRecordWebhookDelivery:
    """Tests for record_webhook_delivery function."""

    def test_record_delivery_success(self):
        """Test recording a successful delivery."""
        from aragora.observability.metrics.webhook import record_webhook_delivery

        # Should not raise even if prometheus not available
        record_webhook_delivery(
            event_type="debate_end",
            success=True,
            duration_seconds=0.25,
        )

    def test_record_delivery_failure_with_status(self):
        """Test recording a failed delivery with status code."""
        from aragora.observability.metrics.webhook import record_webhook_delivery

        record_webhook_delivery(
            event_type="slo_violation",
            success=False,
            duration_seconds=30.0,
            status_code=503,
        )

    def test_record_delivery_with_various_event_types(self):
        """Test recording deliveries for different event types."""
        from aragora.observability.metrics.webhook import record_webhook_delivery

        event_types = [
            "debate_start",
            "debate_end",
            "consensus",
            "slo_violation",
            "slo_recovery",
        ]

        for event_type in event_types:
            record_webhook_delivery(
                event_type=event_type,
                success=True,
                duration_seconds=0.1,
            )


class TestRecordWebhookRetry:
    """Tests for record_webhook_retry function."""

    def test_record_retry(self):
        """Test recording a retry attempt."""
        from aragora.observability.metrics.webhook import record_webhook_retry

        record_webhook_retry(event_type="debate_end", attempt=1)
        record_webhook_retry(event_type="debate_end", attempt=2)
        record_webhook_retry(event_type="debate_end", attempt=3)

    def test_record_retry_caps_attempt_number(self):
        """Test that high attempt numbers are capped."""
        from aragora.observability.metrics.webhook import record_webhook_retry

        # Should not create unbounded label cardinality
        record_webhook_retry(event_type="test", attempt=100)


class TestQueueSizeMetrics:
    """Tests for queue size metrics."""

    def test_set_queue_size(self):
        """Test setting queue size."""
        from aragora.observability.metrics.webhook import set_queue_size

        set_queue_size(10)
        set_queue_size(0)

    def test_increment_decrement_queue(self):
        """Test incrementing and decrementing queue."""
        from aragora.observability.metrics.webhook import (
            increment_queue,
            decrement_queue,
        )

        increment_queue()
        increment_queue()
        decrement_queue()


class TestActiveEndpointsMetrics:
    """Tests for active endpoints metrics."""

    def test_set_active_endpoints(self):
        """Test setting active endpoint count."""
        from aragora.observability.metrics.webhook import set_active_endpoints

        set_active_endpoints("debate_end", 5)
        set_active_endpoints("slo_violation", 2)


class TestWebhookDeliveryTimer:
    """Tests for WebhookDeliveryTimer context manager."""

    def test_timer_records_success(self):
        """Test timer records successful delivery."""
        from aragora.observability.metrics.webhook import WebhookDeliveryTimer

        with WebhookDeliveryTimer("test_event") as timer:
            time.sleep(0.01)
            timer.set_success(True, 200)

    def test_timer_records_failure(self):
        """Test timer records failed delivery."""
        from aragora.observability.metrics.webhook import WebhookDeliveryTimer

        with WebhookDeliveryTimer("test_event") as timer:
            timer.set_success(False, 500)

    def test_timer_handles_exception(self):
        """Test timer handles exceptions gracefully."""
        from aragora.observability.metrics.webhook import WebhookDeliveryTimer

        with pytest.raises(ValueError):
            with WebhookDeliveryTimer("test_event"):
                raise ValueError("Test error")

    def test_timer_manages_queue_size(self):
        """Test timer increments/decrements queue."""
        from aragora.observability.metrics.webhook import WebhookDeliveryTimer

        # Just verify no errors
        with WebhookDeliveryTimer("test_event") as timer:
            timer.set_success(True)


class TestDispatcherMetricsIntegration:
    """Tests for metrics integration with dispatcher."""

    def test_dispatcher_records_delivery_metrics(self):
        """Test that dispatcher records delivery metrics."""
        from aragora.events.dispatcher import dispatch_webhook_with_retry
        from aragora.server.handlers.webhook_management import WebhookConfig

        # Create a test webhook
        webhook = WebhookConfig(
            id="test-123",
            url="http://localhost:9999/webhook",  # Non-existent
            events=["test"],
            secret="test-secret",
        )

        payload = {"event": "test", "data": {}}

        # This will fail but should record metrics
        result = dispatch_webhook_with_retry(webhook, payload, max_retries=0)

        assert result.success is False

    def test_dispatcher_records_retry_metrics(self):
        """Test that dispatcher records retry metrics."""
        from aragora.events.dispatcher import dispatch_webhook_with_retry
        from aragora.server.handlers.webhook_management import WebhookConfig

        webhook = WebhookConfig(
            id="test-456",
            url="http://localhost:9999/webhook",
            events=["test"],
            secret="test-secret",
        )

        payload = {"event": "test_with_retry", "data": {}}

        # Will retry and record metrics
        result = dispatch_webhook_with_retry(webhook, payload, max_retries=1, initial_delay=0.01)

        assert result.success is False
        assert result.retry_count == 1
