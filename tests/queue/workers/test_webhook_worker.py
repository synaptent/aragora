"""
Comprehensive Tests for Webhook Delivery Worker.

Tests the background worker for reliable webhook delivery including:
- Job processing lifecycle (start, process, complete, fail)
- Error handling and retry logic
- Circuit breaker functionality
- Task validation and metrics
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.queue.webhook_worker import (
    DeliveryResult,
    EndpointHealth,
    WebhookDeliveryWorker,
    enqueue_webhook_delivery,
)
from aragora.queue.base import Job, JobStatus


# =============================================================================
# DeliveryResult Tests
# =============================================================================


class TestDeliveryResult:
    """Tests for DeliveryResult dataclass."""

    def test_delivery_result_creation_success(self):
        """Test creating a successful delivery result."""
        result = DeliveryResult(
            webhook_id="wh_123",
            url="https://example.com/webhook",
            success=True,
            status_code=200,
            response_time_ms=150.5,
        )

        assert result.webhook_id == "wh_123"
        assert result.url == "https://example.com/webhook"
        assert result.success is True
        assert result.status_code == 200
        assert result.response_time_ms == 150.5
        assert result.error is None
        assert result.attempt == 1

    def test_delivery_result_creation_failure(self):
        """Test creating a failed delivery result."""
        result = DeliveryResult(
            webhook_id="wh_456",
            url="https://example.com/webhook",
            success=False,
            error="Connection refused",
            attempt=3,
        )

        assert result.success is False
        assert result.error == "Connection refused"
        assert result.attempt == 3
        assert result.status_code is None

    def test_delivery_result_default_timestamp(self):
        """Test delivery result has default timestamp."""
        before = time.time()
        result = DeliveryResult(
            webhook_id="wh_789",
            url="https://example.com",
            success=True,
        )
        after = time.time()

        assert before <= result.delivered_at <= after

    def test_delivery_result_with_http_error(self):
        """Test delivery result with HTTP error status."""
        result = DeliveryResult(
            webhook_id="wh_error",
            url="https://example.com",
            success=False,
            status_code=500,
            error="HTTP 500",
            response_time_ms=50.0,
        )

        assert result.success is False
        assert result.status_code == 500
        assert result.error == "HTTP 500"

    def test_delivery_result_timeout(self):
        """Test delivery result for timeout."""
        result = DeliveryResult(
            webhook_id="wh_timeout",
            url="https://slow.example.com",
            success=False,
            error="Request timeout",
            response_time_ms=10000.0,
        )

        assert result.success is False
        assert result.error == "Request timeout"


# =============================================================================
# EndpointHealth Tests
# =============================================================================


class TestEndpointHealth:
    """Tests for EndpointHealth dataclass."""

    def test_endpoint_health_creation(self):
        """Test creating endpoint health."""
        health = EndpointHealth(url="https://example.com/webhook")

        assert health.url == "https://example.com/webhook"
        assert health.total_deliveries == 0
        assert health.successful_deliveries == 0
        assert health.failed_deliveries == 0
        assert health.last_success_at is None
        assert health.last_failure_at is None
        assert health.avg_response_time_ms == 0.0
        assert health.circuit_state == "closed"

    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        health = EndpointHealth(
            url="https://example.com",
            total_deliveries=100,
            successful_deliveries=95,
            failed_deliveries=5,
        )

        assert health.success_rate == 95.0

    def test_success_rate_no_deliveries(self):
        """Test success rate with no deliveries defaults to 100%."""
        health = EndpointHealth(url="https://example.com")
        assert health.success_rate == 100.0

    def test_success_rate_all_failures(self):
        """Test success rate when all deliveries fail."""
        health = EndpointHealth(
            url="https://example.com",
            total_deliveries=10,
            successful_deliveries=0,
            failed_deliveries=10,
        )

        assert health.success_rate == 0.0

    def test_success_rate_partial_success(self):
        """Test success rate with partial success."""
        health = EndpointHealth(
            url="https://example.com",
            total_deliveries=200,
            successful_deliveries=150,
            failed_deliveries=50,
        )

        assert health.success_rate == 75.0

    def test_endpoint_health_with_timestamps(self):
        """Test endpoint health with timestamps."""
        now = time.time()
        health = EndpointHealth(
            url="https://example.com",
            last_success_at=now - 60,
            last_failure_at=now - 120,
        )

        assert health.last_success_at == now - 60
        assert health.last_failure_at == now - 120

    def test_endpoint_health_circuit_states(self):
        """Test endpoint health with different circuit states."""
        for state in ["closed", "open", "half_open"]:
            health = EndpointHealth(
                url="https://example.com",
                circuit_state=state,
            )
            assert health.circuit_state == state


# =============================================================================
# WebhookDeliveryWorker Initialization Tests
# =============================================================================


class TestWebhookDeliveryWorkerInit:
    """Tests for WebhookDeliveryWorker initialization."""

    def test_worker_initialization_defaults(self):
        """Test worker initialization with defaults."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="webhook-worker-1",
        )

        assert worker.worker_id == "webhook-worker-1"
        assert worker._max_concurrent == 10
        assert worker._request_timeout == 10.0
        assert worker.is_running is False

    def test_worker_initialization_custom(self):
        """Test worker initialization with custom values."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="custom-worker",
            max_concurrent=20,
            request_timeout=15.0,
        )

        assert worker._max_concurrent == 20
        assert worker._request_timeout == 15.0

    def test_worker_initial_metrics(self):
        """Test worker has correct initial metrics."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="test-worker",
        )

        assert worker._deliveries_total == 0
        assert worker._deliveries_succeeded == 0
        assert worker._deliveries_failed == 0

    def test_worker_initial_collections(self):
        """Test worker has empty initial collections."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="test-worker",
        )

        assert len(worker._circuit_breakers) == 0
        assert len(worker._endpoint_health) == 0
        assert len(worker._tasks) == 0


# =============================================================================
# WebhookDeliveryWorker Properties Tests
# =============================================================================


class TestWebhookDeliveryWorkerProperties:
    """Tests for WebhookDeliveryWorker properties."""

    def test_worker_id_property(self):
        """Test worker_id property."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="property-test-worker",
        )

        assert worker.worker_id == "property-test-worker"

    def test_is_running_property_false(self):
        """Test is_running property when not running."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="test-worker",
        )

        assert worker.is_running is False

    def test_is_running_property_true(self):
        """Test is_running property when running."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="test-worker",
        )
        worker._running = True

        assert worker.is_running is True


# =============================================================================
# WebhookDeliveryWorker Stats Tests
# =============================================================================


class TestWebhookDeliveryWorkerStats:
    """Tests for WebhookDeliveryWorker stats."""

    def test_get_stats(self):
        """Test get_stats method."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="stats-worker",
        )

        # Simulate some activity
        worker._deliveries_total = 100
        worker._deliveries_succeeded = 95
        worker._deliveries_failed = 5
        worker._start_time = time.time() - 3600

        stats = worker.get_stats()

        assert stats["worker_id"] == "stats-worker"
        assert stats["deliveries_total"] == 100
        assert stats["deliveries_succeeded"] == 95
        assert stats["deliveries_failed"] == 5
        assert stats["uptime_seconds"] >= 3599
        assert "active_deliveries" in stats
        assert "endpoints_tracked" in stats
        assert stats["queue_name"] == "webhook_delivery"

    def test_get_stats_initial(self):
        """Test get_stats with initial state."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="initial-worker",
        )

        stats = worker.get_stats()

        assert stats["deliveries_total"] == 0
        assert stats["deliveries_succeeded"] == 0
        assert stats["deliveries_failed"] == 0
        assert stats["uptime_seconds"] == 0
        assert stats["is_running"] is False


# =============================================================================
# WebhookDeliveryWorker Signature Tests
# =============================================================================


class TestWebhookDeliveryWorkerSignature:
    """Tests for HMAC signature generation."""

    def test_generate_signature(self):
        """Test HMAC signature generation."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="sig-worker",
        )

        payload = b'{"event": "test"}'
        secret = "my_secret_key"

        signature = worker._generate_signature(payload, secret)

        assert signature.startswith("sha256=")
        assert len(signature) == 71  # "sha256=" + 64 hex chars

    def test_generate_signature_consistency(self):
        """Test signature is consistent for same input."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="sig-worker",
        )

        payload = b'{"data": "consistent"}'
        secret = "test_secret"

        sig1 = worker._generate_signature(payload, secret)
        sig2 = worker._generate_signature(payload, secret)

        assert sig1 == sig2

    def test_generate_signature_different_payloads(self):
        """Test different payloads produce different signatures."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="sig-worker",
        )

        secret = "test_secret"
        sig1 = worker._generate_signature(b'{"a": 1}', secret)
        sig2 = worker._generate_signature(b'{"a": 2}', secret)

        assert sig1 != sig2

    def test_generate_signature_different_secrets(self):
        """Test different secrets produce different signatures."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="sig-worker",
        )

        payload = b'{"data": "test"}'
        sig1 = worker._generate_signature(payload, "secret1")
        sig2 = worker._generate_signature(payload, "secret2")

        assert sig1 != sig2

    def test_generate_signature_verifiable(self):
        """Test generated signature can be verified."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="sig-worker",
        )

        payload = b'{"event": "test", "data": "value"}'
        secret = "webhook_secret"

        signature = worker._generate_signature(payload, secret)

        # Verify manually
        expected = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        assert signature == f"sha256={expected}"


# =============================================================================
# WebhookDeliveryWorker Endpoint Health Tests
# =============================================================================


class TestWebhookDeliveryWorkerEndpointHealth:
    """Tests for endpoint health management."""

    def test_get_endpoint_health_none(self):
        """Test getting health for unknown endpoint."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="health-worker",
        )

        health = worker.get_endpoint_health("https://unknown.example.com")
        assert health is None

    def test_get_endpoint_health_exists(self):
        """Test getting health for known endpoint."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="health-worker",
        )

        worker._endpoint_health["https://known.example.com"] = EndpointHealth(
            url="https://known.example.com",
            total_deliveries=50,
            successful_deliveries=45,
        )

        health = worker.get_endpoint_health("https://known.example.com")
        assert health is not None
        assert health.total_deliveries == 50
        assert health.successful_deliveries == 45

    def test_get_all_endpoint_health_empty(self):
        """Test getting all health when empty."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="health-worker",
        )

        all_health = worker.get_all_endpoint_health()
        assert len(all_health) == 0

    def test_get_all_endpoint_health_multiple(self):
        """Test getting all health with multiple endpoints."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="health-worker",
        )

        worker._endpoint_health["https://a.example.com"] = EndpointHealth(
            url="https://a.example.com"
        )
        worker._endpoint_health["https://b.example.com"] = EndpointHealth(
            url="https://b.example.com"
        )
        worker._endpoint_health["https://c.example.com"] = EndpointHealth(
            url="https://c.example.com"
        )

        all_health = worker.get_all_endpoint_health()
        assert len(all_health) == 3


# =============================================================================
# WebhookDeliveryWorker Metrics Update Tests
# =============================================================================


class TestWebhookDeliveryWorkerMetricsUpdate:
    """Tests for metrics update."""

    def test_update_metrics_success(self):
        """Test updating metrics for successful delivery."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="metrics-worker",
        )

        result = DeliveryResult(
            webhook_id="wh_1",
            url="https://example.com",
            success=True,
            status_code=200,
        )
        worker._update_metrics(result)

        assert worker._deliveries_total == 1
        assert worker._deliveries_succeeded == 1
        assert worker._deliveries_failed == 0

    def test_update_metrics_failure(self):
        """Test updating metrics for failed delivery."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="metrics-worker",
        )

        result = DeliveryResult(
            webhook_id="wh_1",
            url="https://example.com",
            success=False,
            error="Connection failed",
        )
        worker._update_metrics(result)

        assert worker._deliveries_total == 1
        assert worker._deliveries_succeeded == 0
        assert worker._deliveries_failed == 1

    def test_update_metrics_multiple(self):
        """Test updating metrics with multiple deliveries."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="metrics-worker",
        )

        # Success
        for i in range(5):
            result = DeliveryResult(
                webhook_id=f"wh_{i}",
                url="https://example.com",
                success=True,
            )
            worker._update_metrics(result)

        # Failures
        for i in range(3):
            result = DeliveryResult(
                webhook_id=f"wh_fail_{i}",
                url="https://example.com",
                success=False,
            )
            worker._update_metrics(result)

        assert worker._deliveries_total == 8
        assert worker._deliveries_succeeded == 5
        assert worker._deliveries_failed == 3


# =============================================================================
# WebhookDeliveryWorker Endpoint Health Update Tests
# =============================================================================


class TestWebhookDeliveryWorkerEndpointHealthUpdate:
    """Tests for endpoint health update."""

    def test_update_endpoint_health_new_endpoint(self):
        """Test updating health for new endpoint."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="health-worker",
        )

        result = DeliveryResult(
            webhook_id="wh_1",
            url="https://new.example.com",
            success=True,
            response_time_ms=100.0,
        )
        worker._update_endpoint_health(result)

        health = worker._endpoint_health.get("https://new.example.com")
        assert health is not None
        assert health.total_deliveries == 1
        assert health.successful_deliveries == 1
        assert health.avg_response_time_ms == 100.0

    def test_update_endpoint_health_success(self):
        """Test updating health on success."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="health-worker",
        )

        # Initialize health
        worker._endpoint_health["https://example.com"] = EndpointHealth(
            url="https://example.com",
            total_deliveries=10,
            successful_deliveries=9,
            failed_deliveries=1,
        )

        result = DeliveryResult(
            webhook_id="wh_1",
            url="https://example.com",
            success=True,
            response_time_ms=50.0,
        )
        worker._update_endpoint_health(result)

        health = worker._endpoint_health["https://example.com"]
        assert health.total_deliveries == 11
        assert health.successful_deliveries == 10
        assert health.last_success_at is not None

    def test_update_endpoint_health_failure(self):
        """Test updating health on failure."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="health-worker",
        )

        # Initialize health
        worker._endpoint_health["https://example.com"] = EndpointHealth(
            url="https://example.com",
            total_deliveries=10,
            successful_deliveries=9,
            failed_deliveries=1,
        )

        result = DeliveryResult(
            webhook_id="wh_1",
            url="https://example.com",
            success=False,
            response_time_ms=5000.0,
        )
        worker._update_endpoint_health(result)

        health = worker._endpoint_health["https://example.com"]
        assert health.total_deliveries == 11
        assert health.failed_deliveries == 2
        assert health.last_failure_at is not None


# =============================================================================
# WebhookDeliveryWorker Circuit Breaker Tests
# =============================================================================


class TestWebhookDeliveryWorkerCircuitBreaker:
    """Tests for circuit breaker management."""

    def test_get_circuit_breaker_creates_new(self):
        """Test getting circuit breaker creates new one if not exists."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="circuit-worker",
        )

        circuit = worker._get_circuit_breaker("https://new.example.com")
        assert circuit is not None

    def test_get_circuit_breaker_returns_same(self):
        """Test getting circuit breaker returns same instance."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="circuit-worker",
        )

        circuit1 = worker._get_circuit_breaker("https://example.com")
        circuit2 = worker._get_circuit_breaker("https://example.com")

        assert circuit1 is circuit2

    def test_get_circuit_breaker_different_urls(self):
        """Test different URLs get different circuit breakers."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="circuit-worker",
        )

        circuit1 = worker._get_circuit_breaker("https://a.example.com")
        circuit2 = worker._get_circuit_breaker("https://b.example.com")

        assert circuit1 is not circuit2


# =============================================================================
# WebhookDeliveryWorker Start/Stop Tests
# =============================================================================


class TestWebhookDeliveryWorkerLifecycle:
    """Tests for worker lifecycle."""

    @pytest.mark.asyncio
    async def test_worker_start(self):
        """Test worker start."""
        mock_queue = AsyncMock()
        mock_queue.dequeue.return_value = None

        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="lifecycle-worker",
        )

        await worker.start()
        assert worker.is_running is True
        assert worker._start_time is not None

        await worker.stop(timeout=1.0)

    @pytest.mark.asyncio
    async def test_worker_stop(self):
        """Test worker stop."""
        mock_queue = AsyncMock()
        mock_queue.dequeue.return_value = None

        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="lifecycle-worker",
        )

        await worker.start()
        await worker.stop(timeout=1.0)

        assert worker.is_running is False

    @pytest.mark.asyncio
    async def test_worker_start_already_running(self):
        """Test starting already running worker."""
        mock_queue = AsyncMock()
        mock_queue.dequeue.return_value = None

        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="lifecycle-worker",
        )

        await worker.start()
        # Start again should not fail
        await worker.start()

        assert worker.is_running is True

        await worker.stop(timeout=1.0)

    @pytest.mark.asyncio
    async def test_worker_stop_not_running(self):
        """Test stopping worker that's not running."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="lifecycle-worker",
        )

        # Should not fail
        await worker.stop(timeout=1.0)


# =============================================================================
# WebhookDeliveryWorker Retry Tests
# =============================================================================


class TestWebhookDeliveryWorkerRetry:
    """Tests for retry scheduling."""

    @pytest.mark.asyncio
    async def test_schedule_retry_calculates_backoff(self):
        """Test retry schedules with exponential backoff."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="retry-worker",
        )

        job = Job(
            payload={"url": "https://example.com"},
            attempts=1,
        )

        await worker._schedule_retry(job, "Test error")

        # Verify enqueue was called with delay
        mock_queue.enqueue.assert_called_once()
        call_kwargs = mock_queue.enqueue.call_args
        assert call_kwargs.kwargs.get("delay_seconds", 0) > 0

    @pytest.mark.asyncio
    async def test_schedule_retry_updates_job(self):
        """Test retry updates job state."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="retry-worker",
        )

        job = Job(
            payload={"url": "https://example.com"},
            attempts=0,
        )

        await worker._schedule_retry(job, "Connection failed")

        assert job.attempts == 1
        assert job.error == "Connection failed"
        assert job.status == JobStatus.RETRYING

    @pytest.mark.asyncio
    async def test_schedule_retry_caps_backoff(self):
        """Test retry caps backoff at max."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="retry-worker",
        )

        # High attempt number
        job = Job(
            payload={"url": "https://example.com"},
            attempts=10,
        )

        await worker._schedule_retry(job, "Test error")

        call_kwargs = mock_queue.enqueue.call_args
        delay = call_kwargs.kwargs.get("delay_seconds", 0)
        assert delay <= worker.MAX_BACKOFF_SECONDS


# =============================================================================
# WebhookDeliveryWorker Delivery Tests
# =============================================================================


class TestWebhookDeliveryWorkerDelivery:
    """Tests for webhook delivery."""

    @pytest.mark.asyncio
    async def test_deliver_webhook_success(self):
        """Test successful webhook delivery."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="delivery-worker",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            result = await worker._deliver_webhook(
                webhook_id="wh_test",
                url="https://example.com/webhook",
                secret="secret123",
                event_data={"event": "test"},
                attempt=1,
            )

        assert result.success is True
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_deliver_webhook_http_error(self):
        """Test webhook delivery with HTTP error."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="delivery-worker",
        )

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            result = await worker._deliver_webhook(
                webhook_id="wh_test",
                url="https://example.com/webhook",
                secret="",
                event_data={"event": "test"},
                attempt=1,
            )

        assert result.success is False
        assert result.status_code == 500
        assert "HTTP 500" in result.error

    @pytest.mark.asyncio
    async def test_deliver_webhook_timeout(self):
        """Test webhook delivery timeout."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="delivery-worker",
        )

        mock_client = AsyncMock()
        mock_client.post.side_effect = asyncio.TimeoutError()

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            result = await worker._deliver_webhook(
                webhook_id="wh_test",
                url="https://slow.example.com",
                secret="",
                event_data={"event": "test"},
                attempt=1,
            )

        assert result.success is False
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_deliver_webhook_connection_error(self):
        """Test webhook delivery connection error."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="delivery-worker",
        )

        mock_client = AsyncMock()
        mock_client.post.side_effect = ConnectionError("Connection refused")

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            result = await worker._deliver_webhook(
                webhook_id="wh_test",
                url="https://down.example.com",
                secret="",
                event_data={"event": "test"},
                attempt=1,
            )

        assert result.success is False
        assert "Connection refused" in result.error


# =============================================================================
# WebhookDeliveryWorker Job Processing Tests
# =============================================================================


class TestWebhookDeliveryWorkerJobProcessing:
    """Tests for job processing."""

    @pytest.mark.asyncio
    async def test_process_delivery_success(self):
        """Test successful job processing."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="process-worker",
        )

        job = Job(
            payload={
                "webhook_id": "wh_123",
                "url": "https://example.com/webhook",
                "secret": "secret123",
                "event_data": {"event": "test"},
            },
            attempts=0,
        )

        # Mock successful delivery
        with patch.object(
            worker,
            "_deliver_webhook",
            return_value=DeliveryResult(
                webhook_id="wh_123",
                url="https://example.com/webhook",
                success=True,
                status_code=200,
            ),
        ):
            # Mock circuit breaker
            mock_circuit = MagicMock()
            mock_circuit.state = "closed"
            worker._circuit_breakers["https://example.com/webhook"] = mock_circuit

            await worker._process_delivery(job)

        # Verify job completed
        mock_queue.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_delivery_circuit_open(self):
        """Test job processing when circuit breaker is open."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="process-worker",
        )

        job = Job(
            payload={
                "webhook_id": "wh_123",
                "url": "https://unhealthy.example.com",
                "secret": "",
                "event_data": {},
            },
            attempts=0,
        )

        # Mock circuit breaker as open
        mock_circuit = MagicMock()
        mock_circuit.state = "open"
        worker._circuit_breakers["https://unhealthy.example.com"] = mock_circuit

        await worker._process_delivery(job)

        # Should schedule retry, not complete
        mock_queue.complete.assert_not_called()


# =============================================================================
# Enqueue Function Tests
# =============================================================================


class TestEnqueueWebhookDelivery:
    """Tests for enqueue_webhook_delivery function."""

    @pytest.mark.asyncio
    async def test_enqueue_webhook_delivery(self):
        """Test enqueueing a webhook delivery job."""
        mock_queue = AsyncMock()

        job = await enqueue_webhook_delivery(
            queue=mock_queue,
            webhook_id="wh_123",
            url="https://example.com/webhook",
            secret="secret_key",
            event_type="debate.completed",
            event_data={"debate_id": "d_456"},
            priority=5,
        )

        assert job is not None
        assert job.payload["webhook_id"] == "wh_123"
        assert job.payload["url"] == "https://example.com/webhook"
        assert job.payload["secret"] == "secret_key"
        assert job.payload["event_type"] == "debate.completed"
        assert job.payload["event_data"] == {"debate_id": "d_456"}
        assert job.priority == 5

        mock_queue.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_enqueue_webhook_delivery_defaults(self):
        """Test enqueueing with default priority."""
        mock_queue = AsyncMock()

        job = await enqueue_webhook_delivery(
            queue=mock_queue,
            webhook_id="wh_default",
            url="https://example.com",
            secret="",
            event_type="test",
            event_data={},
        )

        assert job.priority == 0

    @pytest.mark.asyncio
    async def test_enqueue_webhook_delivery_metadata(self):
        """Test enqueueing sets correct metadata."""
        mock_queue = AsyncMock()

        job = await enqueue_webhook_delivery(
            queue=mock_queue,
            webhook_id="wh_meta",
            url="https://example.com",
            secret="",
            event_type="custom.event",
            event_data={"key": "value"},
        )

        assert job.metadata["type"] == "webhook_delivery"
        assert job.metadata["event_type"] == "custom.event"


# =============================================================================
# Integration Tests
# =============================================================================


class TestWebhookWorkerIntegration:
    """Integration tests for webhook worker."""

    @pytest.mark.asyncio
    async def test_full_delivery_cycle_success(self):
        """Test full delivery cycle for successful webhook."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="integration-worker",
        )

        # Create and enqueue job
        job = await enqueue_webhook_delivery(
            queue=mock_queue,
            webhook_id="wh_integration",
            url="https://example.com/webhook",
            secret="test_secret",
            event_type="test.event",
            event_data={"test": "data"},
        )

        # Mock successful delivery
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            # Process the job
            await worker._process_delivery(job)

        # Verify completed
        mock_queue.complete.assert_called()
        assert worker._deliveries_total == 1
        assert worker._deliveries_succeeded == 1

    @pytest.mark.asyncio
    async def test_full_delivery_cycle_with_retry(self):
        """Test full delivery cycle with retry."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="integration-worker",
        )

        job = Job(
            payload={
                "webhook_id": "wh_retry",
                "url": "https://flaky.example.com",
                "secret": "",
                "event_data": {"event": "retry_test"},
            },
            attempts=0,
            max_attempts=3,
        )

        # Mock failed delivery
        mock_client = AsyncMock()
        mock_client.post.side_effect = ConnectionError("Connection failed")

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            await worker._process_delivery(job)

        # Should schedule retry
        mock_queue.enqueue.assert_called()
        assert job.status == JobStatus.RETRYING

    @pytest.mark.asyncio
    async def test_worker_processes_queue(self):
        """Test worker processes jobs from queue."""
        mock_queue = AsyncMock()
        mock_queue.dequeue.return_value = None

        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="queue-worker",
        )

        # Start worker
        await worker.start()

        # Let it poll
        await asyncio.sleep(0.2)

        # Stop worker
        await worker.stop(timeout=1.0)

        # Verify dequeue was called
        assert mock_queue.dequeue.call_count >= 1


# =============================================================================
# WebhookDeliveryWorker Constants Tests
# =============================================================================


class TestWebhookDeliveryWorkerConstants:
    """Tests for worker class constants."""

    def test_queue_name_constant(self):
        """Test QUEUE_NAME is set correctly."""
        assert WebhookDeliveryWorker.QUEUE_NAME == "webhook_delivery"

    def test_retry_constants(self):
        """Test retry configuration constants."""
        assert WebhookDeliveryWorker.MAX_RETRIES == 5
        assert WebhookDeliveryWorker.INITIAL_BACKOFF_SECONDS == 1.0
        assert WebhookDeliveryWorker.MAX_BACKOFF_SECONDS == 60.0
        assert WebhookDeliveryWorker.BACKOFF_MULTIPLIER == 2.0

    def test_circuit_breaker_constants(self):
        """Test circuit breaker configuration constants."""
        assert WebhookDeliveryWorker.CIRCUIT_FAILURE_THRESHOLD == 5
        assert WebhookDeliveryWorker.CIRCUIT_RESET_TIMEOUT == 60.0


# =============================================================================
# WebhookDeliveryWorker _on_task_done Tests
# =============================================================================


class TestWebhookDeliveryWorkerOnTaskDone:
    """Tests for _on_task_done callback."""

    def test_on_task_done_removes_task(self):
        """Test _on_task_done removes the task from the task set."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="task-done-worker",
        )

        # Create a mock task
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = None
        worker._tasks.add(mock_task)

        # Acquire semaphore to simulate it being held
        worker._semaphore._value -= 1

        worker._on_task_done(mock_task)

        assert mock_task not in worker._tasks

    def test_on_task_done_releases_semaphore(self):
        """Test _on_task_done releases the semaphore."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="task-done-worker",
            max_concurrent=5,
        )

        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = None

        # Simulate semaphore being acquired
        initial_value = worker._semaphore._value
        worker._semaphore._value -= 1

        worker._on_task_done(mock_task)

        assert worker._semaphore._value == initial_value

    def test_on_task_done_logs_exception(self):
        """Test _on_task_done logs exception from failed task."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="task-done-worker",
        )

        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = RuntimeError("Delivery failed")

        # Acquire semaphore to simulate it being held
        worker._semaphore._value -= 1

        # Should not raise
        worker._on_task_done(mock_task)

        assert mock_task not in worker._tasks

    def test_on_task_done_cancelled_task(self):
        """Test _on_task_done handles cancelled task."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="task-done-worker",
        )

        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.cancelled.return_value = True

        # Acquire semaphore to simulate it being held
        worker._semaphore._value -= 1

        # Should not raise even for cancelled task
        worker._on_task_done(mock_task)

        assert mock_task not in worker._tasks


# =============================================================================
# WebhookDeliveryWorker Process Delivery Extended Tests
# =============================================================================


class TestWebhookDeliveryWorkerProcessDeliveryExtended:
    """Extended tests for _process_delivery covering retry and max retries paths."""

    @pytest.mark.asyncio
    async def test_process_delivery_failure_schedules_retry(self):
        """Test failed delivery schedules retry when under max retries."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="process-worker",
        )

        job = Job(
            payload={
                "webhook_id": "wh_retry",
                "url": "https://failing.example.com",
                "secret": "",
                "event_data": {"test": True},
            },
            attempts=0,
            max_attempts=5,
        )

        # Mock failed delivery
        with patch.object(
            worker,
            "_deliver_webhook",
            return_value=DeliveryResult(
                webhook_id="wh_retry",
                url="https://failing.example.com",
                success=False,
                status_code=503,
                error="HTTP 503",
            ),
        ):
            # Set up circuit breaker in closed state
            mock_circuit = MagicMock()
            mock_circuit.state = "closed"
            worker._circuit_breakers["https://failing.example.com"] = mock_circuit

            await worker._process_delivery(job)

        # Should schedule retry, not complete
        mock_queue.complete.assert_not_called()
        # Should re-enqueue for retry
        mock_queue.enqueue.assert_called_once()
        assert job.status == JobStatus.RETRYING
        mock_circuit.record_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_delivery_max_retries_exceeded(self):
        """Test delivery fails permanently when max retries exceeded."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="process-worker",
        )

        job = Job(
            payload={
                "webhook_id": "wh_maxretry",
                "url": "https://dead.example.com",
                "secret": "",
                "event_data": {"test": True},
            },
            # attempts = MAX_RETRIES - 1, so attempt will be MAX_RETRIES
            attempts=WebhookDeliveryWorker.MAX_RETRIES - 1,
        )

        # Mock failed delivery
        with patch.object(
            worker,
            "_deliver_webhook",
            return_value=DeliveryResult(
                webhook_id="wh_maxretry",
                url="https://dead.example.com",
                success=False,
                error="Connection refused",
            ),
        ):
            mock_circuit = MagicMock()
            mock_circuit.state = "closed"
            worker._circuit_breakers["https://dead.example.com"] = mock_circuit

            await worker._process_delivery(job)

        # Should call fail, not retry
        mock_queue.fail.assert_called_once()
        fail_kwargs = mock_queue.fail.call_args.kwargs
        assert "Max retries exceeded" in fail_kwargs["error"]
        mock_queue.enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_delivery_updates_metrics_on_success(self):
        """Test _process_delivery updates metrics on successful delivery."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="metrics-delivery-worker",
        )

        job = Job(
            payload={
                "webhook_id": "wh_metrics",
                "url": "https://example.com",
                "secret": "secret",
                "event_data": {"event": "test"},
            },
            attempts=0,
        )

        with patch.object(
            worker,
            "_deliver_webhook",
            return_value=DeliveryResult(
                webhook_id="wh_metrics",
                url="https://example.com",
                success=True,
                status_code=200,
                response_time_ms=55.0,
            ),
        ):
            mock_circuit = MagicMock()
            mock_circuit.state = "closed"
            worker._circuit_breakers["https://example.com"] = mock_circuit

            await worker._process_delivery(job)

        assert worker._deliveries_total == 1
        assert worker._deliveries_succeeded == 1
        assert worker._deliveries_failed == 0
        mock_circuit.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_delivery_updates_metrics_on_failure(self):
        """Test _process_delivery updates metrics on failed delivery."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="metrics-delivery-worker",
        )

        job = Job(
            payload={
                "webhook_id": "wh_failmetrics",
                "url": "https://fail.example.com",
                "secret": "",
                "event_data": {},
            },
            attempts=0,
        )

        with patch.object(
            worker,
            "_deliver_webhook",
            return_value=DeliveryResult(
                webhook_id="wh_failmetrics",
                url="https://fail.example.com",
                success=False,
                error="HTTP 500",
            ),
        ):
            mock_circuit = MagicMock()
            mock_circuit.state = "closed"
            worker._circuit_breakers["https://fail.example.com"] = mock_circuit

            await worker._process_delivery(job)

        assert worker._deliveries_total == 1
        assert worker._deliveries_succeeded == 0
        assert worker._deliveries_failed == 1

    @pytest.mark.asyncio
    async def test_process_delivery_missing_payload_fields(self):
        """Test _process_delivery handles missing payload fields gracefully."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="process-worker",
        )

        # Minimal/empty payload
        job = Job(
            payload={},
            attempts=0,
        )

        with patch.object(
            worker,
            "_deliver_webhook",
            return_value=DeliveryResult(
                webhook_id="unknown",
                url="",
                success=False,
                error="Invalid URL",
            ),
        ):
            mock_circuit = MagicMock()
            mock_circuit.state = "closed"
            worker._circuit_breakers[""] = mock_circuit

            await worker._process_delivery(job)

        # Should still process without error
        assert worker._deliveries_total == 1


# =============================================================================
# WebhookDeliveryWorker Deliver Webhook Extended Tests
# =============================================================================


class TestWebhookDeliveryWorkerDeliverExtended:
    """Extended tests for _deliver_webhook."""

    @pytest.mark.asyncio
    async def test_deliver_webhook_unexpected_error(self):
        """Test webhook delivery with unexpected error."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="deliver-worker",
        )

        mock_client = AsyncMock()
        mock_client.post.side_effect = ValueError("Unexpected serialization error")

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            result = await worker._deliver_webhook(
                webhook_id="wh_unexpected",
                url="https://example.com/webhook",
                secret="",
                event_data={"event": "test"},
                attempt=1,
            )

        assert result.success is False
        assert "Unexpected error" in result.error

    @pytest.mark.asyncio
    async def test_deliver_webhook_os_error(self):
        """Test webhook delivery with OSError."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="deliver-worker",
        )

        mock_client = AsyncMock()
        mock_client.post.side_effect = OSError("Network unreachable")

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            result = await worker._deliver_webhook(
                webhook_id="wh_os_err",
                url="https://unreachable.example.com",
                secret="",
                event_data={},
                attempt=1,
            )

        assert result.success is False
        assert "Network unreachable" in result.error

    @pytest.mark.asyncio
    async def test_deliver_webhook_with_signature_headers(self):
        """Test webhook delivery includes signature header when secret provided."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="deliver-worker",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            result = await worker._deliver_webhook(
                webhook_id="wh_sig",
                url="https://example.com/webhook",
                secret="my_secret",
                event_data={"event": "signed_test"},
                attempt=1,
            )

        assert result.success is True

        # Verify headers included signature
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert "X-Signature-SHA256" in headers
        assert headers["X-Signature-SHA256"].startswith("sha256=")

    @pytest.mark.asyncio
    async def test_deliver_webhook_without_signature_headers(self):
        """Test webhook delivery excludes signature header when no secret."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="deliver-worker",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            result = await worker._deliver_webhook(
                webhook_id="wh_nosig",
                url="https://example.com/webhook",
                secret="",
                event_data={"event": "unsigned_test"},
                attempt=1,
            )

        assert result.success is True

        # Verify headers do NOT include signature
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert "X-Signature-SHA256" not in headers

    @pytest.mark.asyncio
    async def test_deliver_webhook_standard_headers(self):
        """Test webhook delivery includes standard headers."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="deliver-worker",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            await worker._deliver_webhook(
                webhook_id="wh_headers",
                url="https://example.com/webhook",
                secret="",
                event_data={"event": "test"},
                attempt=3,
            )

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers["Content-Type"] == "application/json"
        assert headers["User-Agent"] == "Aragora-Webhooks/1.0"
        assert headers["X-Webhook-ID"] == "wh_headers"
        assert headers["X-Delivery-Attempt"] == "3"

    @pytest.mark.asyncio
    async def test_deliver_webhook_2xx_success_range(self):
        """Test 2xx status codes are treated as success."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="deliver-worker",
        )

        for status_code in [200, 201, 202, 204]:
            mock_response = MagicMock()
            mock_response.status_code = status_code

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response

            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_client

            with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
                mock_pool.return_value.get_session.return_value = mock_session

                result = await worker._deliver_webhook(
                    webhook_id=f"wh_{status_code}",
                    url="https://example.com/webhook",
                    secret="",
                    event_data={},
                    attempt=1,
                )

            assert result.success is True, f"Status {status_code} should be success"
            assert result.status_code == status_code

    @pytest.mark.asyncio
    async def test_deliver_webhook_non_2xx_failure(self):
        """Test non-2xx status codes are treated as failure."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="deliver-worker",
        )

        for status_code in [301, 400, 401, 403, 404, 429, 500, 502, 503]:
            mock_response = MagicMock()
            mock_response.status_code = status_code

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response

            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_client

            with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
                mock_pool.return_value.get_session.return_value = mock_session

                result = await worker._deliver_webhook(
                    webhook_id=f"wh_{status_code}",
                    url="https://example.com/webhook",
                    secret="",
                    event_data={},
                    attempt=1,
                )

            assert result.success is False, f"Status {status_code} should be failure"
            assert f"HTTP {status_code}" in result.error

    @pytest.mark.asyncio
    async def test_deliver_webhook_response_time(self):
        """Test delivery records response time."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="deliver-worker",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_client

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_pool.return_value.get_session.return_value = mock_session

            result = await worker._deliver_webhook(
                webhook_id="wh_time",
                url="https://example.com/webhook",
                secret="",
                event_data={},
                attempt=1,
            )

        assert result.response_time_ms >= 0


# =============================================================================
# WebhookDeliveryWorker Endpoint Health Update Extended Tests
# =============================================================================


class TestWebhookDeliveryWorkerEndpointHealthUpdateExtended:
    """Extended tests for _update_endpoint_health."""

    def test_update_endpoint_health_avg_response_time(self):
        """Test average response time calculation."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="health-worker",
        )

        # First delivery: 100ms
        result1 = DeliveryResult(
            webhook_id="wh_1",
            url="https://example.com",
            success=True,
            response_time_ms=100.0,
        )
        worker._update_endpoint_health(result1)

        health = worker._endpoint_health["https://example.com"]
        assert health.avg_response_time_ms == 100.0

        # Second delivery: 200ms -> avg should be 150ms
        result2 = DeliveryResult(
            webhook_id="wh_2",
            url="https://example.com",
            success=True,
            response_time_ms=200.0,
        )
        worker._update_endpoint_health(result2)

        assert health.avg_response_time_ms == pytest.approx(150.0)
        assert health.total_deliveries == 2

    def test_update_endpoint_health_circuit_state_update(self):
        """Test circuit state gets updated in endpoint health."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="health-worker",
        )

        # Set up circuit breaker
        mock_circuit = MagicMock()
        mock_circuit.state = "half_open"
        worker._circuit_breakers["https://example.com"] = mock_circuit

        result = DeliveryResult(
            webhook_id="wh_circuit",
            url="https://example.com",
            success=True,
            response_time_ms=50.0,
        )
        worker._update_endpoint_health(result)

        health = worker._endpoint_health["https://example.com"]
        assert health.circuit_state == "half_open"

    def test_update_endpoint_health_no_circuit_breaker(self):
        """Test endpoint health update when no circuit breaker exists."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="health-worker",
        )

        result = DeliveryResult(
            webhook_id="wh_no_circuit",
            url="https://new.example.com",
            success=True,
            response_time_ms=75.0,
        )
        worker._update_endpoint_health(result)

        health = worker._endpoint_health["https://new.example.com"]
        # Should keep default circuit state
        assert health.circuit_state == "closed"

    def test_update_endpoint_health_multiple_endpoints(self):
        """Test health tracking across multiple endpoints."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="health-worker",
        )

        urls = [
            "https://a.example.com",
            "https://b.example.com",
            "https://c.example.com",
        ]

        for i, url in enumerate(urls):
            result = DeliveryResult(
                webhook_id=f"wh_{i}",
                url=url,
                success=True,
                response_time_ms=float((i + 1) * 50),
            )
            worker._update_endpoint_health(result)

        assert len(worker._endpoint_health) == 3
        assert worker._endpoint_health["https://a.example.com"].avg_response_time_ms == 50.0
        assert worker._endpoint_health["https://b.example.com"].avg_response_time_ms == 100.0
        assert worker._endpoint_health["https://c.example.com"].avg_response_time_ms == 150.0


# =============================================================================
# WebhookDeliveryWorker Process Loop Tests
# =============================================================================


class TestWebhookDeliveryWorkerProcessLoop:
    """Tests for _process_loop behavior."""

    @pytest.mark.asyncio
    async def test_process_loop_dequeues_jobs(self):
        """Test process loop dequeues from queue."""
        mock_queue = AsyncMock()
        mock_queue.dequeue.return_value = None

        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="loop-worker",
        )

        await worker.start()
        await asyncio.sleep(0.2)
        await worker.stop(timeout=1.0)

        # Should have tried to dequeue at least once
        mock_queue.dequeue.assert_called()
        call_kwargs = mock_queue.dequeue.call_args.kwargs
        assert call_kwargs["queue_name"] == "webhook_delivery"
        assert call_kwargs["worker_id"] == "loop-worker"

    @pytest.mark.asyncio
    async def test_process_loop_handles_errors(self):
        """Test process loop handles dequeue errors gracefully."""
        mock_queue = AsyncMock()
        mock_queue.dequeue.side_effect = RuntimeError("DB connection lost")

        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="error-loop-worker",
        )

        await worker.start()
        await asyncio.sleep(0.2)
        await worker.stop(timeout=1.0)

        # Worker should still be in stopped state (not crashed)
        assert worker.is_running is False


# =============================================================================
# WebhookDeliveryWorker Stop with Pending Tasks Tests
# =============================================================================


class TestWebhookDeliveryWorkerStopWithPendingTasks:
    """Tests for stop behavior with pending tasks."""

    @pytest.mark.asyncio
    async def test_stop_cancels_pending_tasks(self):
        """Test stop cancels tasks that don't finish in time."""
        mock_queue = AsyncMock()
        mock_queue.dequeue.return_value = None

        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="stop-worker",
        )

        # Create a long-running mock task
        async def long_running():
            await asyncio.sleep(100)

        task = asyncio.create_task(long_running())
        worker._tasks.add(task)
        worker._running = True

        # Stop with very short timeout to force cancellation
        await worker.stop(timeout=0.1)

        assert worker.is_running is False

    @pytest.mark.asyncio
    async def test_stop_no_tasks_graceful(self):
        """Test stop with no active tasks is graceful."""
        mock_queue = MagicMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="stop-worker",
        )
        worker._running = True

        await worker.stop(timeout=1.0)

        assert worker.is_running is False


# =============================================================================
# WebhookDeliveryWorker Retry Backoff Calculation Tests
# =============================================================================


class TestWebhookDeliveryWorkerBackoffCalculation:
    """Tests for backoff calculation details."""

    @pytest.mark.asyncio
    async def test_backoff_exponential_growth(self):
        """Test backoff grows exponentially."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="backoff-worker",
        )

        delays = []
        for attempt in range(5):
            job = Job(
                payload={"url": "https://example.com"},
                attempts=attempt,
            )

            await worker._schedule_retry(job, "Test error")

            call_kwargs = mock_queue.enqueue.call_args.kwargs
            delays.append(call_kwargs.get("delay_seconds", 0))
            mock_queue.enqueue.reset_mock()

        # Each delay should be larger than the previous
        for i in range(1, len(delays)):
            assert delays[i] > delays[i - 1], f"Delay {i} should be > delay {i - 1}"

    @pytest.mark.asyncio
    async def test_first_retry_backoff(self):
        """Test first retry has initial backoff."""
        mock_queue = AsyncMock()
        worker = WebhookDeliveryWorker(
            queue=mock_queue,
            worker_id="backoff-worker",
        )

        job = Job(
            payload={"url": "https://example.com"},
            attempts=0,
        )

        await worker._schedule_retry(job, "Error")

        call_kwargs = mock_queue.enqueue.call_args.kwargs
        delay = call_kwargs.get("delay_seconds", 0)
        # First retry: INITIAL_BACKOFF * MULTIPLIER^1 = 1.0 * 2.0 = 2.0
        assert delay == pytest.approx(worker.INITIAL_BACKOFF_SECONDS * worker.BACKOFF_MULTIPLIER)


# =============================================================================
# Enqueue Function Extended Tests
# =============================================================================


class TestEnqueueWebhookDeliveryExtended:
    """Extended tests for enqueue_webhook_delivery function."""

    @pytest.mark.asyncio
    async def test_enqueue_sets_queue_name(self):
        """Test enqueue uses correct queue name."""
        mock_queue = AsyncMock()

        await enqueue_webhook_delivery(
            queue=mock_queue,
            webhook_id="wh_qname",
            url="https://example.com",
            secret="",
            event_type="test",
            event_data={},
        )

        call_kwargs = mock_queue.enqueue.call_args.kwargs
        assert call_kwargs["queue_name"] == "webhook_delivery"

    @pytest.mark.asyncio
    async def test_enqueue_with_complex_event_data(self):
        """Test enqueue with complex nested event data."""
        mock_queue = AsyncMock()

        event_data = {
            "debate": {
                "id": "d_123",
                "topic": "Rate limiter design",
                "result": {
                    "consensus": True,
                    "confidence": 0.95,
                    "participants": ["claude", "gpt4", "gemini"],
                },
            },
            "metadata": {
                "workspace_id": "ws_456",
                "triggered_at": 1700000000.0,
            },
        }

        job = await enqueue_webhook_delivery(
            queue=mock_queue,
            webhook_id="wh_complex",
            url="https://example.com/webhook",
            secret="secret",
            event_type="debate.completed",
            event_data=event_data,
            priority=10,
        )

        assert job.payload["event_data"] == event_data
        assert job.priority == 10

    @pytest.mark.asyncio
    async def test_enqueue_returns_job(self):
        """Test enqueue returns a Job instance."""
        mock_queue = AsyncMock()

        job = await enqueue_webhook_delivery(
            queue=mock_queue,
            webhook_id="wh_return",
            url="https://example.com",
            secret="",
            event_type="test",
            event_data={},
        )

        assert isinstance(job, Job)
        assert job.payload is not None
