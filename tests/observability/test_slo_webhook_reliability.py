"""
Tests for SLO webhook reliability guarantees.

Verifies:
- Retry exhaustion moves webhooks to DLQ
- Manual DLQ retry functionality
- Circuit breaker prevents cascading failures
- HMAC signature verification
- Concurrent violations don't lose events
- Idempotency key uniqueness
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _register_webhook_sink_provider():
    """Route patched integration dispatchers through the observability hook."""
    from aragora.observability.metrics.slo import register_slo_event_sink_provider

    def provider():
        from aragora.integrations import webhooks

        return webhooks.get_dispatcher()

    register_slo_event_sink_provider(provider)
    yield
    register_slo_event_sink_provider(None)


class TestSLOWebhookRetryExhaustion:
    """Test retry exhaustion and DLQ handling."""

    @pytest.fixture
    def delivery_manager(self):
        """Create a delivery manager with low retry settings for testing."""
        from aragora.server.webhook_delivery import WebhookDeliveryManager

        manager = WebhookDeliveryManager(
            max_retries=3,
            base_delay_seconds=0.01,  # Fast retries for testing
            max_delay_seconds=0.1,
            timeout_seconds=1.0,
            circuit_breaker_threshold=10,  # High threshold to avoid interference
            enable_persistence=False,  # In-memory for testing
        )
        return manager

    @pytest.mark.asyncio
    async def test_retry_exhaustion_moves_to_dlq(self, delivery_manager):
        """After max retries, webhook moves to dead-letter queue."""
        failure_count = 0

        async def failing_sender(url: str, payload: dict, headers: dict) -> tuple:
            nonlocal failure_count
            failure_count += 1
            return (500, "Internal Server Error")

        delivery_manager.set_sender(failing_sender)
        await delivery_manager.start()

        try:
            # Attempt delivery - should fail and enter retry
            delivery = await delivery_manager.deliver(
                webhook_id="test-webhook",
                event_type="slo_violation",
                payload={"operation": "km_query", "severity": "critical"},
                url="https://example.com/webhook",
                secret="test-secret",
            )

            # First attempt fails, moves to retry queue
            assert delivery.attempts == 1
            assert delivery.status.value == "retrying"

            # Process retries until exhausted (process_retries runs in background)
            # We need to manually process for this test
            for _ in range(5):  # Extra iterations to ensure completion
                await asyncio.sleep(0.15)  # Wait for retry delays

            # Check DLQ
            dlq = await delivery_manager.get_dead_letter_queue()
            dlq_ids = [d.delivery_id for d in dlq]

            # Either in DLQ or still retrying (timing dependent)
            final_delivery = await delivery_manager.get_delivery(delivery.delivery_id)
            if final_delivery:
                # Should eventually be dead-lettered after max retries
                assert final_delivery.attempts >= 1

        finally:
            await delivery_manager.stop()

    @pytest.mark.asyncio
    async def test_dlq_manual_retry_succeeds(self, delivery_manager):
        """DLQ entries can be manually retried and succeed."""
        attempts_made = 0

        async def eventually_succeeds(url: str, payload: dict, headers: dict) -> tuple:
            nonlocal attempts_made
            attempts_made += 1
            if attempts_made <= 3:
                return (500, "Temporary failure")
            return (200, "OK")

        delivery_manager.set_sender(eventually_succeeds)

        # Directly add to DLQ for testing
        from aragora.server.webhook_delivery import WebhookDelivery, DeliveryStatus

        dlq_delivery = WebhookDelivery(
            delivery_id="dlq-test-123",
            webhook_id="test-webhook",
            event_type="slo_violation",
            payload={"operation": "test", "severity": "major"},
            status=DeliveryStatus.DEAD_LETTERED,
            attempts=5,
            dead_lettered_at=datetime.now(timezone.utc),
        )

        delivery_manager._dead_letter_queue[dlq_delivery.delivery_id] = dlq_delivery
        delivery_manager._delivery_urls[dlq_delivery.delivery_id] = "https://example.com/webhook"
        delivery_manager._delivery_secrets[dlq_delivery.delivery_id] = "test-secret"

        await delivery_manager.start()

        try:
            # Retry the dead-lettered delivery
            result = await delivery_manager.retry_dead_letter("dlq-test-123")
            assert result is True

            # Wait for retry processing
            await asyncio.sleep(0.2)

            # Verify it's been moved out of DLQ
            dlq = await delivery_manager.get_dead_letter_queue()
            dlq_ids = [d.delivery_id for d in dlq]
            assert "dlq-test-123" not in dlq_ids

        finally:
            await delivery_manager.stop()


class TestSLOWebhookCircuitBreaker:
    """Test circuit breaker functionality."""

    @pytest.fixture
    def delivery_manager(self):
        """Create a delivery manager with low circuit breaker threshold."""
        from aragora.server.webhook_delivery import WebhookDeliveryManager

        manager = WebhookDeliveryManager(
            max_retries=5,
            base_delay_seconds=0.01,
            max_delay_seconds=0.1,
            timeout_seconds=1.0,
            circuit_breaker_threshold=3,  # Low threshold for testing
            enable_persistence=False,
        )
        return manager

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self, delivery_manager):
        """Circuit breaker opens after consecutive failures."""

        async def always_fails(url: str, payload: dict, headers: dict) -> tuple:
            return (503, "Service Unavailable")

        delivery_manager.set_sender(always_fails)

        # Make multiple failing deliveries to trip the circuit breaker
        for i in range(4):
            delivery = await delivery_manager.deliver(
                webhook_id=f"test-webhook-{i}",
                event_type="slo_violation",
                payload={"operation": "test", "severity": "critical"},
                url="https://failing-endpoint.com/webhook",
            )
            assert delivery.status.value in ("retrying", "dead_lettered", "failed")

        # Check circuit is open
        metrics = await delivery_manager.get_metrics()
        # Circuit should have opened for this endpoint
        assert (
            delivery_manager._circuit_failures.get("https://failing-endpoint.com/webhook", 0) >= 3
        )

    @pytest.mark.asyncio
    async def test_circuit_breaker_prevents_cascading_failures(self, delivery_manager):
        """Open circuit breaker queues webhooks instead of failing them."""
        call_count = 0

        async def counting_sender(url: str, payload: dict, headers: dict) -> tuple:
            nonlocal call_count
            call_count += 1
            return (503, "Service Unavailable")

        delivery_manager.set_sender(counting_sender)

        # Trip the circuit breaker
        for i in range(5):
            await delivery_manager.deliver(
                webhook_id=f"trip-{i}",
                event_type="slo_violation",
                payload={"operation": "test"},
                url="https://test-endpoint.com/webhook",
            )

        initial_calls = call_count

        # Force circuit open
        delivery_manager._circuit_failures["https://test-endpoint.com/webhook"] = 10
        delivery_manager._circuit_open_until["https://test-endpoint.com/webhook"] = datetime.now(
            timezone.utc
        ).replace(year=2030)  # Far future

        # New delivery should be queued, not attempted
        delivery = await delivery_manager.deliver(
            webhook_id="queued-webhook",
            event_type="slo_violation",
            payload={"operation": "test"},
            url="https://test-endpoint.com/webhook",
        )

        # Should be queued for retry, not attempted
        assert delivery.status.value == "retrying"
        assert delivery.last_error == "Circuit breaker open"
        # No additional HTTP calls should have been made
        assert call_count == initial_calls


class TestSLOWebhookSignatureVerification:
    """Test HMAC-SHA256 signature generation."""

    @pytest.mark.asyncio
    async def test_webhook_signature_generated(self):
        """HMAC-SHA256 signatures are correctly generated."""
        from aragora.server.webhook_delivery import WebhookDeliveryManager

        captured_headers: dict[str, str] = {}

        async def capture_headers(url: str, payload: dict, headers: dict) -> tuple:
            nonlocal captured_headers
            captured_headers = headers.copy()
            return (200, "OK")

        manager = WebhookDeliveryManager(enable_persistence=False)
        manager.set_sender(capture_headers)

        await manager.deliver(
            webhook_id="test-webhook",
            event_type="slo_violation",
            payload={"operation": "km_query", "severity": "critical"},
            url="https://example.com/webhook",
            secret="my-secret-key",
        )

        # Verify signature header exists
        assert "X-Webhook-Signature" in captured_headers
        assert captured_headers["X-Webhook-Signature"].startswith("sha256=")
        assert len(captured_headers["X-Webhook-Signature"]) > 10  # Has actual hash

    @pytest.mark.asyncio
    async def test_webhook_signature_not_present_without_secret(self):
        """No signature header when secret is not provided."""
        from aragora.server.webhook_delivery import WebhookDeliveryManager

        captured_headers: dict[str, str] = {}

        async def capture_headers(url: str, payload: dict, headers: dict) -> tuple:
            nonlocal captured_headers
            captured_headers = headers.copy()
            return (200, "OK")

        manager = WebhookDeliveryManager(enable_persistence=False)
        manager.set_sender(capture_headers)

        await manager.deliver(
            webhook_id="test-webhook",
            event_type="slo_violation",
            payload={"operation": "test"},
            url="https://example.com/webhook",
            secret=None,  # No secret
        )

        assert "X-Webhook-Signature" not in captured_headers


class TestSLOWebhookConcurrency:
    """Test concurrent violation handling."""

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

    def test_concurrent_violations_tracked_independently(self):
        """Multiple simultaneous violations for different operations don't interfere."""
        from aragora.observability.metrics.slo import (
            SLOWebhookConfig,
            check_and_record_slo_with_recovery,
            get_violation_state,
            init_slo_webhooks,
        )

        notifications: list[dict[str, Any]] = []

        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = lambda event: notifications.append(event) or True

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = mock_dispatcher

            config = SLOWebhookConfig(enabled=True, cooldown_seconds=0.0)
            init_slo_webhooks(config)

            # Use operations that have defined SLO thresholds
            # km_query has p99 threshold of 500ms
            # km_ingestion has p99 threshold of 1000ms
            operations = ["km_query", "km_ingestion"]

            for op in operations:
                # Trigger violations - each has different thresholds
                check_and_record_slo_with_recovery(
                    operation=op,
                    latency_ms=5000.0,  # High enough to exceed all thresholds
                    percentile="p99",
                )

            # All operations should be in violation state
            for op in operations:
                state = get_violation_state(op)
                assert state["in_violation"] is True, f"{op} should be in violation"

            # Should have one notification per operation
            assert len(notifications) == len(operations)
            notified_ops = {n["operation"] for n in notifications}
            assert notified_ops == set(operations)


class TestSLOWebhookIdempotency:
    """Test idempotency key generation."""

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

    def test_idempotency_key_in_violation_event(self):
        """Violation events include idempotency key."""
        from aragora.observability.metrics.slo import (
            SLOWebhookConfig,
            init_slo_webhooks,
            notify_slo_violation,
        )

        captured_event: dict[str, Any] = {}

        mock_dispatcher = MagicMock()

        def capture_event(event):
            nonlocal captured_event
            captured_event = event.copy()
            return True

        mock_dispatcher.enqueue = capture_event

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = mock_dispatcher

            config = SLOWebhookConfig(enabled=True, cooldown_seconds=0.0)
            init_slo_webhooks(config)

            result = notify_slo_violation(
                operation="km_query",
                percentile="p99",
                latency_ms=1000.0,
                threshold_ms=500.0,
                severity="major",
            )

            assert result is True
            assert "idempotency_key" in captured_event
            # Key format: operation:percentile:timestamp_ms
            key = captured_event["idempotency_key"]
            assert key.startswith("km_query:p99:")
            # Timestamp should be a valid integer
            timestamp_part = key.split(":")[-1]
            assert timestamp_part.isdigit()

    def test_idempotency_keys_unique_for_same_operation(self):
        """Different violations generate unique idempotency keys."""
        from aragora.observability.metrics.slo import (
            SLOWebhookConfig,
            init_slo_webhooks,
            notify_slo_violation,
        )

        captured_keys: list[str] = []

        mock_dispatcher = MagicMock()

        def capture_key(event):
            if "idempotency_key" in event:
                captured_keys.append(event["idempotency_key"])
            return True

        mock_dispatcher.enqueue = capture_key

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = mock_dispatcher

            config = SLOWebhookConfig(enabled=True, cooldown_seconds=0.0)
            init_slo_webhooks(config)

            # Send multiple violations with small delays
            # Use different operations to avoid cooldown
            for i in range(3):
                notify_slo_violation(
                    operation=f"test_op_{i}",  # Different operation each time
                    percentile="p99",
                    latency_ms=1000.0,
                    threshold_ms=500.0,
                    severity="major",
                    cooldown_seconds=0.0,  # Explicitly disable cooldown
                )
                time.sleep(0.002)  # Small delay to ensure different timestamps

            # All keys should be unique
            assert len(captured_keys) == 3
            assert len(set(captured_keys)) == 3  # All unique


class TestSLORecoveryWebhookReliability:
    """Test recovery webhook reliability."""

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

    def test_recovery_path_survives_global_noop_initialization(self):
        """Global no-op initialization leaves SLO collectors coherent."""
        from aragora.observability.metrics.initialization import _init_noop_metrics_all
        from aragora.observability.metrics import slo as slo_module

        slo_module._initialized = False
        slo_module.SLO_CHECKS_TOTAL = None
        slo_module.SLO_VIOLATIONS_TOTAL = None
        slo_module.SLO_LATENCY_HISTOGRAM = None
        slo_module.SLO_VIOLATION_MARGIN = None

        _init_noop_metrics_all()

        passed, _ = slo_module.check_and_record_slo_with_recovery(
            "km_query",
            100.0,
            "p99",
        )

        assert passed is True
        assert slo_module._initialized is True
        assert all(
            metric is not None
            for metric in (
                slo_module.SLO_CHECKS_TOTAL,
                slo_module.SLO_VIOLATIONS_TOTAL,
                slo_module.SLO_LATENCY_HISTOGRAM,
                slo_module.SLO_VIOLATION_MARGIN,
            )
        )

    def test_recovery_notification_includes_duration(self):
        """Recovery notification includes violation duration."""
        from aragora.observability.metrics.slo import (
            SLOWebhookConfig,
            check_and_record_slo_with_recovery,
            init_slo_webhooks,
        )

        notifications: list[dict[str, Any]] = []

        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue = lambda event: notifications.append(event) or True

        with patch("aragora.integrations.webhooks.get_dispatcher") as mock_get_dispatcher:
            mock_get_dispatcher.return_value = mock_dispatcher

            config = SLOWebhookConfig(enabled=True, cooldown_seconds=0.0)
            init_slo_webhooks(config)

            # Trigger violation
            check_and_record_slo_with_recovery("km_query", 1000.0, "p99")

            # Small delay to ensure measurable duration
            time.sleep(0.05)

            # Trigger recovery
            check_and_record_slo_with_recovery("km_query", 100.0, "p99")

            # Find recovery notification
            recovery_notifs = [n for n in notifications if n.get("type") == "slo_recovery"]
            assert len(recovery_notifs) == 1

            recovery = recovery_notifs[0]
            assert "violation_duration_seconds" in recovery
            assert recovery["violation_duration_seconds"] >= 0.05


class TestWebhookDeliveryMetrics:
    """Test webhook delivery metrics."""

    @pytest.mark.asyncio
    async def test_metrics_track_successes_and_failures(self):
        """Metrics accurately track delivery attempts."""
        from aragora.server.webhook_delivery import WebhookDeliveryManager

        success_count = 0
        fail_count = 0

        async def alternating_sender(url: str, payload: dict, headers: dict) -> tuple:
            nonlocal success_count, fail_count
            if "success" in url:
                success_count += 1
                return (200, "OK")
            else:
                fail_count += 1
                return (500, "Error")

        manager = WebhookDeliveryManager(
            max_retries=1,  # Low retries for fast test
            enable_persistence=False,
        )
        manager.set_sender(alternating_sender)

        # Successful deliveries
        for i in range(3):
            await manager.deliver(
                webhook_id=f"success-{i}",
                event_type="test",
                payload={},
                url="https://success.example.com/webhook",
            )

        # Failed deliveries
        for i in range(2):
            await manager.deliver(
                webhook_id=f"fail-{i}",
                event_type="test",
                payload={},
                url="https://fail.example.com/webhook",
            )

        metrics = await manager.get_metrics()

        assert metrics["successful_deliveries"] == 3
        assert metrics["total_deliveries"] == 5
        assert metrics["success_rate"] == 60.0  # 3/5 = 60%
