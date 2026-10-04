"""
Tests for Webhook Delivery Manager.

Tests delivery tracking, retry logic, dead-letter queue, and circuit breaker.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from aragora.server.webhook_delivery import (
    DeliveryStatus,
    WebhookDelivery,
    DeliveryMetrics,
    WebhookDeliveryManager,
    get_delivery_manager,
    deliver_webhook,
    reset_delivery_manager,
)


@pytest.fixture(autouse=True)
def _reset_tracing_and_delivery():
    """Reset tracing context and delivery manager to prevent cross-test pollution."""
    # Reset tracing ContextVars
    try:
        from aragora.observability.middleware.tracing import _trace_id, _span_id

        token_trace = _trace_id.set(None)
        token_span = _span_id.set(None)
    except ImportError:
        token_trace = token_span = None

    # Reset global delivery manager singleton
    reset_delivery_manager()
    yield
    reset_delivery_manager()

    # Restore tracing context
    if token_trace is not None:
        from aragora.observability.middleware.tracing import _trace_id, _span_id

        _trace_id.reset(token_trace)
        _span_id.reset(token_span)


class TestWebhookDelivery:
    """Tests for WebhookDelivery dataclass."""

    def test_to_dict(self):
        """Should serialize to dictionary."""
        delivery = WebhookDelivery(
            delivery_id="test-123",
            webhook_id="webhook-456",
            event_type="debate_end",
            payload={"debate_id": "d-789"},
        )

        data = delivery.to_dict()

        assert data["delivery_id"] == "test-123"
        assert data["webhook_id"] == "webhook-456"
        assert data["event_type"] == "debate_end"
        assert data["status"] == "pending"


class TestDeliveryMetrics:
    """Tests for DeliveryMetrics."""

    def test_success_rate(self):
        """Should calculate success rate correctly."""
        metrics = DeliveryMetrics()
        metrics.total_deliveries = 100
        metrics.successful_deliveries = 95

        assert metrics.success_rate == 95.0

    def test_avg_latency(self):
        """Should calculate average latency."""
        metrics = DeliveryMetrics()
        metrics.successful_deliveries = 10
        metrics.total_latency_ms = 500.0

        assert metrics.avg_latency_ms == 50.0


class TestWebhookDeliveryManager:
    """Tests for WebhookDeliveryManager."""

    @pytest.fixture
    def manager(self):
        """Create a fresh manager."""
        return WebhookDeliveryManager(max_retries=3, base_delay_seconds=0.1)

    @pytest.mark.asyncio
    async def test_successful_delivery(self, manager):
        """Should deliver successfully on 2xx response."""

        # Mock successful sender
        async def mock_sender(url, payload, headers):
            return 200, {"ok": True}

        manager.set_sender(mock_sender)

        delivery = await manager.deliver(
            webhook_id="wh-123",
            event_type="debate_end",
            payload={"debate_id": "d-456"},
            url="https://example.com/webhook",
        )

        assert delivery.status == DeliveryStatus.DELIVERED
        assert delivery.delivered_at is not None
        assert delivery.attempts == 1
        assert manager._metrics.successful_deliveries == 1

    @pytest.mark.asyncio
    async def test_failed_delivery_enters_retry(self, manager):
        """Should schedule retry on failure."""

        # Mock failing sender
        async def mock_sender(url, payload, headers):
            return 500, {"error": "Internal server error"}

        manager.set_sender(mock_sender)

        delivery = await manager.deliver(
            webhook_id="wh-123",
            event_type="debate_end",
            payload={"debate_id": "d-456"},
            url="https://example.com/webhook",
        )

        assert delivery.status == DeliveryStatus.RETRYING
        assert delivery.next_retry_at is not None
        assert delivery.attempts == 1
        assert len(manager._retry_queue) == 1

    @pytest.mark.asyncio
    async def test_max_retries_moves_to_dead_letter(self, manager):
        """Should move to dead-letter queue after max retries."""

        # Mock always-failing sender
        async def mock_sender(url, payload, headers):
            return 500, {"error": "Always fails"}

        manager.set_sender(mock_sender)
        manager._max_retries = 1  # Only 1 attempt

        delivery = await manager.deliver(
            webhook_id="wh-123",
            event_type="debate_end",
            payload={"debate_id": "d-456"},
            url="https://example.com/webhook",
        )

        assert delivery.status == DeliveryStatus.DEAD_LETTERED
        assert delivery.dead_lettered_at is not None
        assert len(manager._dead_letter_queue) == 1
        assert manager._metrics.dead_lettered == 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self, manager):
        """Should open circuit breaker after threshold failures."""
        manager._circuit_threshold = 3

        async def mock_sender(url, payload, headers):
            return 503, {"error": "Service unavailable"}

        manager.set_sender(mock_sender)

        url = "https://example.com/webhook"

        # Trigger multiple failures
        for _ in range(3):
            await manager.deliver(
                webhook_id="wh-123",
                event_type="test",
                payload={},
                url=url,
            )

        # Circuit should be open
        assert manager._is_circuit_open(url) is True
        assert url in manager._circuit_open_until

    @pytest.mark.asyncio
    async def test_circuit_breaker_resets_on_success(self, manager):
        """Should reset circuit breaker on successful delivery."""
        url = "https://example.com/webhook"

        # Simulate some failures
        manager._circuit_failures[url] = 2

        # Mock successful sender
        async def mock_sender(url, payload, headers):
            return 200, {"ok": True}

        manager.set_sender(mock_sender)

        await manager.deliver(
            webhook_id="wh-123",
            event_type="test",
            payload={},
            url=url,
        )

        # Circuit should be reset
        assert manager._circuit_failures[url] == 0

    @pytest.mark.asyncio
    async def test_get_delivery(self, manager):
        """Should retrieve delivery by ID."""

        async def mock_sender(url, payload, headers):
            return 200, {"ok": True}

        manager.set_sender(mock_sender)

        delivery = await manager.deliver(
            webhook_id="wh-123",
            event_type="test",
            payload={},
            url="https://example.com/webhook",
        )

        retrieved = await manager.get_delivery(delivery.delivery_id)
        assert retrieved is not None
        assert retrieved.delivery_id == delivery.delivery_id

    @pytest.mark.asyncio
    async def test_retry_dead_letter(self, manager):
        """Should move dead-lettered delivery back to retry queue."""
        # Create a dead-lettered delivery
        delivery = WebhookDelivery(
            delivery_id="test-123",
            webhook_id="wh-456",
            event_type="test",
            payload={},
            status=DeliveryStatus.DEAD_LETTERED,
            attempts=5,
            metadata={"retry_url": "https://example.com/webhook"},
        )
        manager._dead_letter_queue[delivery.delivery_id] = delivery

        # Retry it
        result = await manager.retry_dead_letter(delivery.delivery_id)

        assert result is True
        assert delivery.delivery_id in manager._retry_queue
        assert delivery.delivery_id not in manager._dead_letter_queue
        assert delivery.attempts == 0

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, manager):
        """Should track metrics correctly."""

        async def mock_sender(url, payload, headers):
            await asyncio.sleep(0.01)  # Simulate latency
            return 200, {"ok": True}

        manager.set_sender(mock_sender)

        # Make several deliveries
        for i in range(5):
            await manager.deliver(
                webhook_id=f"wh-{i}",
                event_type="test",
                payload={},
                url="https://example.com/webhook",
            )

        metrics = await manager.get_metrics()

        assert metrics["total_deliveries"] == 5
        assert metrics["successful_deliveries"] == 5
        assert metrics["success_rate"] == 100.0
        assert metrics["avg_latency_ms"] > 0

    @pytest.mark.asyncio
    async def test_timeout_handling(self, manager):
        """Should handle timeout errors."""

        async def mock_sender(url, payload, headers):
            raise asyncio.TimeoutError()

        manager.set_sender(mock_sender)

        delivery = await manager.deliver(
            webhook_id="wh-123",
            event_type="test",
            payload={},
            url="https://example.com/webhook",
        )

        assert delivery.last_error == "Timeout"
        assert delivery.status == DeliveryStatus.RETRYING


class TestGlobalDeliveryFunctions:
    """Tests for global delivery functions."""

    def setup_method(self):
        """Reset manager before each test."""
        reset_delivery_manager()

    @pytest.mark.asyncio
    async def test_get_delivery_manager_singleton(self):
        """Should return singleton manager."""
        manager1 = await get_delivery_manager()
        manager2 = await get_delivery_manager()
        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_deliver_webhook_function(self):
        """Should deliver via global function."""
        manager = await get_delivery_manager()

        async def mock_sender(url, payload, headers):
            return 200, {"ok": True}

        manager.set_sender(mock_sender)

        delivery = await deliver_webhook(
            webhook_id="wh-123",
            event_type="debate_end",
            payload={"debate_id": "d-456"},
            url="https://example.com/webhook",
        )

        assert delivery.status == DeliveryStatus.DELIVERED


class TestRetryProcessing:
    """Tests for background retry processing."""

    @pytest.mark.asyncio
    async def test_retry_queue_processing(self):
        """Should process retry queue in background."""
        manager = WebhookDeliveryManager(max_retries=3, base_delay_seconds=0.05)

        call_count = 0

        async def mock_sender(url, payload, headers):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return 500, {"error": "Temporary failure"}
            return 200, {"ok": True}

        manager.set_sender(mock_sender)

        # Start retry processor
        await manager.start()

        try:
            # First delivery fails
            delivery = await manager.deliver(
                webhook_id="wh-123",
                event_type="test",
                payload={},
                url="https://example.com/webhook",
            )

            assert delivery.status == DeliveryStatus.RETRYING

            # Wait for retry to be processed (retry check runs every 1s, plus processing time)
            for _ in range(30):  # Wait up to 3 seconds
                await asyncio.sleep(0.1)
                updated = await manager.get_delivery(delivery.delivery_id)
                if updated and updated.status == DeliveryStatus.DELIVERED:
                    break

            # Check delivery was eventually successful
            updated = await manager.get_delivery(delivery.delivery_id)
            assert updated.status == DeliveryStatus.DELIVERED
        finally:
            await manager.stop()


class TestSignatureGeneration:
    """Tests for HMAC signature generation."""

    @pytest.mark.asyncio
    async def test_signature_included_with_secret(self):
        """Should include signature header when secret provided."""
        captured_headers = {}

        async def capture_sender(url, payload, headers):
            captured_headers.update(headers)
            return 200, {"ok": True}

        manager = WebhookDeliveryManager()
        manager.set_sender(capture_sender)

        await manager.deliver(
            webhook_id="wh-123",
            event_type="test",
            payload={"data": "test"},
            url="https://example.com/webhook",
            secret="my-secret-key",
        )

        assert "X-Webhook-Signature" in captured_headers
        assert captured_headers["X-Webhook-Signature"].startswith("sha256=")

    @pytest.mark.asyncio
    async def test_no_signature_without_secret(self):
        """Should not include signature when no secret provided."""
        captured_headers = {}

        async def capture_sender(url, payload, headers):
            captured_headers.update(headers)
            return 200, {"ok": True}

        manager = WebhookDeliveryManager()
        manager.set_sender(capture_sender)

        await manager.deliver(
            webhook_id="wh-123",
            event_type="test",
            payload={"data": "test"},
            url="https://example.com/webhook",
        )

        assert "X-Webhook-Signature" not in captured_headers


class TestDeliveryPersistence:
    """Tests for webhook delivery persistence."""

    @pytest.fixture
    def temp_db_path(self, tmp_path):
        """Create a temporary database path."""
        return str(tmp_path / "test_webhook_delivery.db")

    @pytest.mark.asyncio
    async def test_persistence_saves_retry(self, temp_db_path):
        """Should persist retrying deliveries to database."""
        manager = WebhookDeliveryManager(
            max_retries=3,
            base_delay_seconds=0.1,
            db_path=temp_db_path,
            enable_persistence=True,
        )

        async def mock_sender(url, payload, headers):
            return 500, {"error": "Server error"}

        manager.set_sender(mock_sender)

        delivery = await manager.deliver(
            webhook_id="wh-persist-1",
            event_type="test",
            payload={"data": "test"},
            url="https://example.com/webhook",
        )

        assert delivery.status == DeliveryStatus.RETRYING

        # Check database has the record
        import sqlite3

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.execute(
            "SELECT status, webhook_id FROM webhook_deliveries WHERE delivery_id = ?",
            (delivery.delivery_id,),
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "retrying"
        assert row[1] == "wh-persist-1"

    @pytest.mark.asyncio
    async def test_persistence_removes_on_success(self, temp_db_path):
        """Should remove record from database on successful delivery."""
        manager = WebhookDeliveryManager(
            db_path=temp_db_path,
            enable_persistence=True,
        )

        async def mock_sender(url, payload, headers):
            return 200, {"ok": True}

        manager.set_sender(mock_sender)

        delivery = await manager.deliver(
            webhook_id="wh-success-1",
            event_type="test",
            payload={"data": "test"},
            url="https://example.com/webhook",
        )

        assert delivery.status == DeliveryStatus.DELIVERED

        # Check database has NO record (removed on success)
        import sqlite3

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.execute(
            "SELECT COUNT(*) FROM webhook_deliveries WHERE delivery_id = ?", (delivery.delivery_id,)
        )
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 0

    @pytest.mark.asyncio
    async def test_persistence_dead_letter(self, temp_db_path):
        """Should persist dead-lettered deliveries."""
        manager = WebhookDeliveryManager(
            max_retries=1,
            db_path=temp_db_path,
            enable_persistence=True,
        )

        async def mock_sender(url, payload, headers):
            return 500, {"error": "Always fails"}

        manager.set_sender(mock_sender)

        delivery = await manager.deliver(
            webhook_id="wh-dead-1",
            event_type="test",
            payload={"data": "test"},
            url="https://example.com/webhook",
        )

        assert delivery.status == DeliveryStatus.DEAD_LETTERED

        # Check database has dead-lettered record
        import sqlite3

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.execute(
            "SELECT status FROM webhook_deliveries WHERE delivery_id = ?", (delivery.delivery_id,)
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "dead_lettered"

    @pytest.mark.asyncio
    async def test_recovery_on_startup(self, temp_db_path):
        """Should recover pending deliveries on startup."""
        # First, create a manager and add a retrying delivery
        manager1 = WebhookDeliveryManager(
            max_retries=5,
            base_delay_seconds=1.0,
            db_path=temp_db_path,
            enable_persistence=True,
        )

        async def mock_sender(url, payload, headers):
            return 500, {"error": "Temporary failure"}

        manager1.set_sender(mock_sender)

        delivery = await manager1.deliver(
            webhook_id="wh-recover-1",
            event_type="test",
            payload={"important": "data"},
            url="https://example.com/webhook",
        )

        assert delivery.status == DeliveryStatus.RETRYING
        delivery_id = delivery.delivery_id

        # Simulate server restart - create new manager
        manager2 = WebhookDeliveryManager(
            max_retries=5,
            base_delay_seconds=0.05,
            db_path=temp_db_path,
            enable_persistence=True,
        )

        # Start should recover pending deliveries
        await manager2.start()

        try:
            # Check retry queue has the recovered delivery
            assert delivery_id in manager2._retry_queue

            recovered = manager2._retry_queue[delivery_id]
            assert recovered.webhook_id == "wh-recover-1"
            assert recovered.payload == {"important": "data"}
        finally:
            await manager2.stop()

    @pytest.mark.asyncio
    async def test_disabled_persistence(self):
        """Should work without persistence when disabled."""
        manager = WebhookDeliveryManager(enable_persistence=False)

        async def mock_sender(url, payload, headers):
            return 500, {"error": "Fails"}

        manager.set_sender(mock_sender)

        delivery = await manager.deliver(
            webhook_id="wh-no-persist",
            event_type="test",
            payload={"data": "test"},
            url="https://example.com/webhook",
        )

        # Should still work, just not persist
        assert delivery.status == DeliveryStatus.RETRYING
        assert manager._persistence is None


class TestTracePropagation:
    """Tests for distributed tracing header propagation."""

    @pytest.mark.asyncio
    async def test_trace_headers_included_with_context(self):
        """Should include trace headers when trace context is set."""
        from aragora.observability.middleware.tracing import set_trace_id, set_span_id

        captured_headers = {}

        async def capture_sender(url, payload, headers):
            captured_headers.update(headers)
            return 200, {"ok": True}

        manager = WebhookDeliveryManager(enable_persistence=False)
        manager.set_sender(capture_sender)

        # Set trace context
        set_trace_id("abc123def456789012345678901234ab")
        set_span_id("span12345678abcd")

        try:
            await manager.deliver(
                webhook_id="wh-trace-1",
                event_type="test",
                payload={"data": "test"},
                url="https://example.com/webhook",
            )
        finally:
            # Reset context
            set_trace_id(None)
            set_span_id(None)

        # Check custom trace headers
        assert "X-Trace-ID" in captured_headers
        assert captured_headers["X-Trace-ID"] == "abc123def456789012345678901234ab"
        assert "X-Span-ID" in captured_headers
        assert captured_headers["X-Span-ID"] == "span12345678abcd"

        # Check W3C traceparent header
        assert "traceparent" in captured_headers
        traceparent = captured_headers["traceparent"]
        assert traceparent.startswith("00-")  # Version 00
        assert "-01" in traceparent  # Sampled flag

    @pytest.mark.asyncio
    async def test_no_trace_headers_without_context(self):
        """Should not include trace headers when no context is set."""
        from aragora.observability.middleware.tracing import set_trace_id, set_span_id

        captured_headers = {}

        async def capture_sender(url, payload, headers):
            captured_headers.update(headers)
            return 200, {"ok": True}

        manager = WebhookDeliveryManager(enable_persistence=False)
        manager.set_sender(capture_sender)

        # Ensure no trace context
        set_trace_id(None)
        set_span_id(None)

        await manager.deliver(
            webhook_id="wh-no-trace",
            event_type="test",
            payload={"data": "test"},
            url="https://example.com/webhook",
        )

        # Trace headers should not be present
        assert "X-Trace-ID" not in captured_headers
        assert "traceparent" not in captured_headers

    @pytest.mark.asyncio
    async def test_trace_id_stored_in_metadata(self):
        """Should store trace ID in delivery metadata."""
        from aragora.observability.middleware.tracing import set_trace_id, set_span_id

        async def mock_sender(url, payload, headers):
            return 200, {"ok": True}

        manager = WebhookDeliveryManager(enable_persistence=False)
        manager.set_sender(mock_sender)

        # Set trace context
        set_trace_id("trace-for-metadata-test-12345678")
        set_span_id("span-metadata-12")

        try:
            delivery = await manager.deliver(
                webhook_id="wh-metadata-1",
                event_type="test",
                payload={"data": "test"},
                url="https://example.com/webhook",
            )
        finally:
            set_trace_id(None)
            set_span_id(None)

        # Check metadata contains trace info
        assert delivery.metadata.get("trace_id") == "trace-for-metadata-test-12345678"
        assert delivery.metadata.get("span_id") == "span-metadata-12"

    @pytest.mark.asyncio
    async def test_traceparent_format(self):
        """Should generate valid W3C traceparent header."""
        from aragora.observability.middleware.tracing import set_trace_id, set_span_id

        captured_headers = {}

        async def capture_sender(url, payload, headers):
            captured_headers.update(headers)
            return 200, {"ok": True}

        manager = WebhookDeliveryManager(enable_persistence=False)
        manager.set_sender(capture_sender)

        # Set trace context
        set_trace_id("a" * 32)  # 32-char trace ID
        set_span_id("b" * 16)  # 16-char span ID

        try:
            await manager.deliver(
                webhook_id="wh-format-1",
                event_type="test",
                payload={},
                url="https://example.com/webhook",
            )
        finally:
            set_trace_id(None)
            set_span_id(None)

        traceparent = captured_headers.get("traceparent", "")
        parts = traceparent.split("-")

        # W3C format: version-trace_id-parent_id-flags
        assert len(parts) == 4
        assert parts[0] == "00"  # Version
        assert len(parts[1]) == 32  # Trace ID (32 hex chars)
        assert len(parts[2]) == 16  # Parent ID (16 hex chars)
        assert parts[3] == "01"  # Sampled flag
