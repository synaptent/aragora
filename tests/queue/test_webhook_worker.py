"""
Tests for webhook delivery worker module.

Tests cover:
- DeliveryResult dataclass properties
- EndpointHealth dataclass and success rate calculation
- WebhookDeliveryWorker lifecycle (start, stop)
- Worker properties (worker_id, is_running, get_stats)
- Queue job processing (_process_loop, _process_delivery)
- Exponential backoff retry logic (_schedule_retry)
- Circuit breaker per-endpoint isolation (_get_circuit_breaker)
- HMAC-SHA256 signature generation (_generate_signature)
- Concurrent delivery handling (semaphore management)
- Endpoint health tracking (_update_endpoint_health)
- Metrics tracking (_update_metrics)
- Error handling scenarios (timeout, connection error, HTTP errors)
- enqueue_webhook_delivery helper function
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.queue.base import Job, JobQueue, JobStatus
from aragora.queue.config import QueueConfig, reset_queue_config, set_queue_config
from aragora.queue.webhook_worker import (
    DeliveryResult,
    EndpointHealth,
    WebhookDeliveryWorker,
    enqueue_webhook_delivery,
)


@pytest.fixture(autouse=True)
def _reset_config():
    set_queue_config(QueueConfig())
    yield
    reset_queue_config()


def _make_worker(
    max_concurrent: int = 10,
    request_timeout: float = 10.0,
) -> tuple[WebhookDeliveryWorker, AsyncMock]:
    """Create a WebhookDeliveryWorker with mock queue."""
    mock_queue = AsyncMock(spec=JobQueue)
    worker = WebhookDeliveryWorker(
        queue=mock_queue,
        worker_id="test-webhook-worker-1",
        max_concurrent=max_concurrent,
        request_timeout=request_timeout,
    )
    return worker, mock_queue


class TestDeliveryResult:
    """Tests for DeliveryResult dataclass."""

    def test_successful_delivery(self):
        result = DeliveryResult(
            webhook_id="wh-123",
            url="https://example.com/webhook",
            success=True,
            status_code=200,
            response_time_ms=150.0,
            attempt=1,
        )
        assert result.success is True
        assert result.status_code == 200
        assert result.error is None
        assert result.response_time_ms == 150.0

    def test_failed_delivery(self):
        result = DeliveryResult(
            webhook_id="wh-456",
            url="https://example.com/webhook",
            success=False,
            status_code=500,
            error="HTTP 500",
            attempt=2,
        )
        assert result.success is False
        assert result.status_code == 500
        assert result.error == "HTTP 500"
        assert result.attempt == 2

    def test_default_values(self):
        result = DeliveryResult(
            webhook_id="wh-789",
            url="https://example.com/webhook",
            success=True,
        )
        assert result.status_code is None
        assert result.error is None
        assert result.response_time_ms == 0.0
        assert result.attempt == 1
        assert result.delivered_at > 0


class TestEndpointHealth:
    """Tests for EndpointHealth dataclass."""

    def test_default_values(self):
        health = EndpointHealth(url="https://example.com/webhook")
        assert health.total_deliveries == 0
        assert health.successful_deliveries == 0
        assert health.failed_deliveries == 0
        assert health.last_success_at is None
        assert health.last_failure_at is None
        assert health.avg_response_time_ms == 0.0
        assert health.circuit_state == "closed"

    def test_success_rate_no_deliveries(self):
        health = EndpointHealth(url="https://example.com")
        assert health.success_rate == 100.0

    def test_success_rate_all_successful(self):
        health = EndpointHealth(
            url="https://example.com",
            total_deliveries=10,
            successful_deliveries=10,
            failed_deliveries=0,
        )
        assert health.success_rate == 100.0

    def test_success_rate_partial(self):
        health = EndpointHealth(
            url="https://example.com",
            total_deliveries=10,
            successful_deliveries=7,
            failed_deliveries=3,
        )
        assert health.success_rate == 70.0

    def test_success_rate_all_failed(self):
        health = EndpointHealth(
            url="https://example.com",
            total_deliveries=5,
            successful_deliveries=0,
            failed_deliveries=5,
        )
        assert health.success_rate == 0.0


class TestWorkerConstruction:
    """Tests for WebhookDeliveryWorker construction and properties."""

    def test_worker_id(self):
        worker, _ = _make_worker()
        assert worker.worker_id == "test-webhook-worker-1"

    def test_is_running_initially_false(self):
        worker, _ = _make_worker()
        assert worker.is_running is False

    def test_queue_name_constant(self):
        assert WebhookDeliveryWorker.QUEUE_NAME == "webhook_delivery"

    def test_retry_configuration(self):
        assert WebhookDeliveryWorker.MAX_RETRIES == 5
        assert WebhookDeliveryWorker.INITIAL_BACKOFF_SECONDS == 1.0
        assert WebhookDeliveryWorker.MAX_BACKOFF_SECONDS == 60.0
        assert WebhookDeliveryWorker.BACKOFF_MULTIPLIER == 2.0

    def test_circuit_breaker_configuration(self):
        assert WebhookDeliveryWorker.CIRCUIT_FAILURE_THRESHOLD == 5
        assert WebhookDeliveryWorker.CIRCUIT_RESET_TIMEOUT == 60.0


class TestWorkerStats:
    """Tests for get_stats."""

    def test_stats_not_running(self):
        worker, _ = _make_worker()
        stats = worker.get_stats()

        assert stats["worker_id"] == "test-webhook-worker-1"
        assert stats["is_running"] is False
        assert stats["uptime_seconds"] == 0
        assert stats["deliveries_total"] == 0
        assert stats["deliveries_succeeded"] == 0
        assert stats["deliveries_failed"] == 0
        assert stats["active_deliveries"] == 0
        assert stats["endpoints_tracked"] == 0
        assert stats["queue_name"] == "webhook_delivery"

    def test_stats_with_activity(self):
        worker, _ = _make_worker(max_concurrent=10)
        worker._running = True
        worker._start_time = time.time() - 100
        worker._deliveries_total = 50
        worker._deliveries_succeeded = 45
        worker._deliveries_failed = 5
        worker._endpoint_health["https://a.com"] = EndpointHealth(url="https://a.com")
        worker._endpoint_health["https://b.com"] = EndpointHealth(url="https://b.com")

        stats = worker.get_stats()

        assert stats["is_running"] is True
        assert stats["deliveries_total"] == 50
        assert stats["deliveries_succeeded"] == 45
        assert stats["deliveries_failed"] == 5
        assert stats["uptime_seconds"] >= 99
        assert stats["endpoints_tracked"] == 2


class TestEndpointHealthTracking:
    """Tests for endpoint health retrieval."""

    def test_get_endpoint_health_exists(self):
        worker, _ = _make_worker()
        health = EndpointHealth(
            url="https://example.com",
            total_deliveries=5,
            successful_deliveries=4,
        )
        worker._endpoint_health["https://example.com"] = health

        result = worker.get_endpoint_health("https://example.com")
        assert result is not None
        assert result.total_deliveries == 5
        assert result.successful_deliveries == 4

    def test_get_endpoint_health_not_exists(self):
        worker, _ = _make_worker()
        result = worker.get_endpoint_health("https://nonexistent.com")
        assert result is None

    def test_get_all_endpoint_health(self):
        worker, _ = _make_worker()
        worker._endpoint_health["https://a.com"] = EndpointHealth(url="https://a.com")
        worker._endpoint_health["https://b.com"] = EndpointHealth(url="https://b.com")

        result = worker.get_all_endpoint_health()
        assert len(result) == 2
        urls = [h.url for h in result]
        assert "https://a.com" in urls
        assert "https://b.com" in urls


class TestWorkerLifecycle:
    """Tests for start and stop."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        worker, _ = _make_worker()
        await worker.start()

        assert worker.is_running is True
        assert worker._start_time is not None
        assert not worker._shutdown_event.is_set()

        # Clean up
        await worker.stop(timeout=0.1)

    @pytest.mark.asyncio
    async def test_start_already_running(self):
        worker, _ = _make_worker()
        worker._running = True

        await worker.start()  # Should log warning and return early
        assert worker._start_time is None  # Not re-initialized

    @pytest.mark.asyncio
    async def test_stop_not_running(self):
        worker, _ = _make_worker()
        await worker.stop()  # Should return early without error

    @pytest.mark.asyncio
    async def test_stop_running_no_tasks(self):
        worker, _ = _make_worker()
        worker._running = True

        await worker.stop(timeout=1.0)

        assert worker._running is False
        assert worker._shutdown_event.is_set()


class TestSignatureGeneration:
    """Tests for HMAC-SHA256 signature generation."""

    def test_generate_signature_basic(self):
        worker, _ = _make_worker()
        payload = b'{"event": "test"}'
        secret = "my-secret-key"

        signature = worker._generate_signature(payload, secret)

        expected = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        assert signature == f"sha256={expected}"

    def test_generate_signature_empty_payload(self):
        worker, _ = _make_worker()
        payload = b""
        secret = "secret"

        signature = worker._generate_signature(payload, secret)
        assert signature.startswith("sha256=")

    def test_generate_signature_unicode_secret(self):
        worker, _ = _make_worker()
        payload = b'{"data": "test"}'
        secret = "secret-with-unicode-\u00e9"

        signature = worker._generate_signature(payload, secret)
        assert signature.startswith("sha256=")
        assert len(signature) == 71  # "sha256=" + 64 hex chars


class TestCircuitBreaker:
    """Tests for per-endpoint circuit breaker isolation."""

    def test_get_circuit_breaker_creates_new(self):
        worker, _ = _make_worker()
        url = "https://example.com/webhook"

        circuit = worker._get_circuit_breaker(url)

        assert circuit is not None
        assert circuit.failure_threshold == WebhookDeliveryWorker.CIRCUIT_FAILURE_THRESHOLD
        assert circuit.cooldown_seconds == WebhookDeliveryWorker.CIRCUIT_RESET_TIMEOUT

    def test_get_circuit_breaker_reuses_existing(self):
        worker, _ = _make_worker()
        url = "https://example.com/webhook"

        circuit1 = worker._get_circuit_breaker(url)
        circuit2 = worker._get_circuit_breaker(url)

        assert circuit1 is circuit2

    def test_circuit_breakers_isolated_per_endpoint(self):
        worker, _ = _make_worker()
        url1 = "https://a.com/webhook"
        url2 = "https://b.com/webhook"

        circuit1 = worker._get_circuit_breaker(url1)
        circuit2 = worker._get_circuit_breaker(url2)

        assert circuit1 is not circuit2

        # Failures on one don't affect the other
        for _ in range(5):
            circuit1.record_failure()

        assert circuit1.state == "open"
        assert circuit2.state == "closed"


class TestExponentialBackoff:
    """Tests for exponential backoff retry logic."""

    @pytest.mark.asyncio
    async def test_schedule_retry_calculates_backoff(self):
        worker, mock_queue = _make_worker()
        job = Job(
            id="j-retry-1",
            payload={"url": "https://example.com"},
            attempts=0,
        )

        await worker._schedule_retry(job, "test error")

        mock_queue.enqueue.assert_called_once()
        call_args = mock_queue.enqueue.call_args
        assert call_args.kwargs["queue_name"] == "webhook_delivery"
        # First retry: 1.0 * (2.0 ** 1) = 2.0 seconds
        assert call_args.kwargs["delay_seconds"] == 2.0

    @pytest.mark.asyncio
    async def test_schedule_retry_increases_backoff(self):
        worker, mock_queue = _make_worker()

        # Test increasing backoff
        delays = []
        for attempt in range(5):
            job = Job(
                id=f"j-retry-{attempt}",
                payload={"url": "https://example.com"},
                attempts=attempt,
            )
            mock_queue.reset_mock()
            await worker._schedule_retry(job, "test error")
            call_args = mock_queue.enqueue.call_args
            delays.append(call_args.kwargs["delay_seconds"])

        # 1*2^1=2, 1*2^2=4, 1*2^3=8, 1*2^4=16, 1*2^5=32
        assert delays == [2.0, 4.0, 8.0, 16.0, 32.0]

    @pytest.mark.asyncio
    async def test_schedule_retry_caps_at_max(self):
        worker, mock_queue = _make_worker()

        # High attempt count should cap at MAX_BACKOFF_SECONDS
        job = Job(
            id="j-retry-max",
            payload={"url": "https://example.com"},
            attempts=10,  # Would be 1*2^11 = 2048 without cap
        )

        await worker._schedule_retry(job, "test error")

        call_args = mock_queue.enqueue.call_args
        assert call_args.kwargs["delay_seconds"] == 60.0  # MAX_BACKOFF_SECONDS


class TestMetricsUpdate:
    """Tests for metrics tracking."""

    def test_update_metrics_success(self):
        worker, _ = _make_worker()
        result = DeliveryResult(
            webhook_id="wh-1",
            url="https://example.com",
            success=True,
        )

        worker._update_metrics(result)

        assert worker._deliveries_total == 1
        assert worker._deliveries_succeeded == 1
        assert worker._deliveries_failed == 0

    def test_update_metrics_failure(self):
        worker, _ = _make_worker()
        result = DeliveryResult(
            webhook_id="wh-1",
            url="https://example.com",
            success=False,
            error="HTTP 500",
        )

        worker._update_metrics(result)

        assert worker._deliveries_total == 1
        assert worker._deliveries_succeeded == 0
        assert worker._deliveries_failed == 1


class TestEndpointHealthUpdate:
    """Tests for endpoint health update."""

    def test_update_endpoint_health_new_endpoint(self):
        worker, _ = _make_worker()
        result = DeliveryResult(
            webhook_id="wh-1",
            url="https://new.example.com",
            success=True,
            response_time_ms=100.0,
        )

        worker._update_endpoint_health(result)

        health = worker._endpoint_health["https://new.example.com"]
        assert health.total_deliveries == 1
        assert health.successful_deliveries == 1
        assert health.failed_deliveries == 0
        assert health.avg_response_time_ms == 100.0
        assert health.last_success_at is not None

    def test_update_endpoint_health_failure(self):
        worker, _ = _make_worker()
        result = DeliveryResult(
            webhook_id="wh-1",
            url="https://fail.example.com",
            success=False,
            error="Connection refused",
            response_time_ms=50.0,
        )

        worker._update_endpoint_health(result)

        health = worker._endpoint_health["https://fail.example.com"]
        assert health.total_deliveries == 1
        assert health.successful_deliveries == 0
        assert health.failed_deliveries == 1
        assert health.last_failure_at is not None
        assert health.last_success_at is None

    def test_update_endpoint_health_avg_response_time(self):
        worker, _ = _make_worker()
        url = "https://example.com"

        # First delivery: 100ms
        result1 = DeliveryResult(
            webhook_id="wh-1",
            url=url,
            success=True,
            response_time_ms=100.0,
        )
        worker._update_endpoint_health(result1)
        assert worker._endpoint_health[url].avg_response_time_ms == 100.0

        # Second delivery: 200ms -> avg = (100 + 200) / 2 = 150
        result2 = DeliveryResult(
            webhook_id="wh-2",
            url=url,
            success=True,
            response_time_ms=200.0,
        )
        worker._update_endpoint_health(result2)
        assert worker._endpoint_health[url].avg_response_time_ms == 150.0

    def test_update_endpoint_health_circuit_state(self):
        worker, _ = _make_worker()
        url = "https://example.com"

        # Create circuit breaker and open it
        circuit = worker._get_circuit_breaker(url)
        for _ in range(5):
            circuit.record_failure()

        result = DeliveryResult(
            webhook_id="wh-1",
            url=url,
            success=False,
            response_time_ms=50.0,
        )
        worker._update_endpoint_health(result)

        health = worker._endpoint_health[url]
        assert health.circuit_state == "open"


class TestProcessDelivery:
    """Tests for _process_delivery."""

    @pytest.mark.asyncio
    async def test_process_delivery_success(self):
        worker, mock_queue = _make_worker()
        job = Job(
            id="j-success",
            payload={
                "webhook_id": "wh-123",
                "url": "https://example.com/webhook",
                "secret": "test-secret",
                "event_data": {"type": "test"},
            },
            attempts=0,
        )

        # Mock HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_pool.return_value.get_session.return_value.__aenter__.return_value = mock_client

            await worker._process_delivery(job)

        mock_queue.complete.assert_called_once()
        assert worker._deliveries_succeeded == 1

    @pytest.mark.asyncio
    async def test_process_delivery_http_error(self):
        worker, mock_queue = _make_worker()
        job = Job(
            id="j-http-err",
            payload={
                "webhook_id": "wh-123",
                "url": "https://example.com/webhook",
                "secret": "",
                "event_data": {},
            },
            attempts=0,
        )

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_pool.return_value.get_session.return_value.__aenter__.return_value = mock_client

            await worker._process_delivery(job)

        # Should schedule retry (not max attempts yet)
        mock_queue.enqueue.assert_called_once()
        assert worker._deliveries_failed == 1

    @pytest.mark.asyncio
    async def test_process_delivery_timeout(self):
        worker, mock_queue = _make_worker()
        job = Job(
            id="j-timeout",
            payload={
                "webhook_id": "wh-123",
                "url": "https://slow.example.com/webhook",
                "secret": "",
                "event_data": {},
            },
            attempts=0,
        )

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_client = AsyncMock()
            mock_client.post.side_effect = asyncio.TimeoutError()
            mock_pool.return_value.get_session.return_value.__aenter__.return_value = mock_client

            await worker._process_delivery(job)

        mock_queue.enqueue.assert_called_once()  # Scheduled for retry
        assert worker._deliveries_failed == 1

    @pytest.mark.asyncio
    async def test_process_delivery_connection_error(self):
        worker, mock_queue = _make_worker()
        job = Job(
            id="j-conn-err",
            payload={
                "webhook_id": "wh-123",
                "url": "https://unreachable.example.com/webhook",
                "secret": "",
                "event_data": {},
            },
            attempts=0,
        )

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_client = AsyncMock()
            mock_client.post.side_effect = ConnectionError("Connection refused")
            mock_pool.return_value.get_session.return_value.__aenter__.return_value = mock_client

            await worker._process_delivery(job)

        mock_queue.enqueue.assert_called_once()
        assert worker._deliveries_failed == 1

    @pytest.mark.asyncio
    async def test_process_delivery_circuit_open(self):
        worker, mock_queue = _make_worker()
        url = "https://failing.example.com/webhook"

        # Open circuit breaker for this endpoint
        circuit = worker._get_circuit_breaker(url)
        for _ in range(5):
            circuit.record_failure()

        job = Job(
            id="j-circuit-open",
            payload={
                "webhook_id": "wh-123",
                "url": url,
                "secret": "",
                "event_data": {},
            },
            attempts=0,
        )

        await worker._process_delivery(job)

        # Should schedule retry without attempting delivery
        mock_queue.enqueue.assert_called_once()
        # Metrics should NOT be updated (delivery was skipped)
        assert worker._deliveries_total == 0

    @pytest.mark.asyncio
    async def test_process_delivery_max_retries_exceeded(self):
        worker, mock_queue = _make_worker()
        job = Job(
            id="j-max-retry",
            payload={
                "webhook_id": "wh-123",
                "url": "https://example.com/webhook",
                "secret": "",
                "event_data": {},
            },
            attempts=4,  # Will be attempt 5 (MAX_RETRIES)
        )

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_pool.return_value.get_session.return_value.__aenter__.return_value = mock_client

            await worker._process_delivery(job)

        # Should mark as failed, not retry
        mock_queue.fail.assert_called_once()
        mock_queue.enqueue.assert_not_called()


class TestDeliverWebhook:
    """Tests for _deliver_webhook HTTP delivery."""

    @pytest.mark.asyncio
    async def test_deliver_webhook_success_result(self):
        worker, _ = _make_worker()

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_pool.return_value.get_session.return_value.__aenter__.return_value = mock_client

            result = await worker._deliver_webhook(
                webhook_id="wh-123",
                url="https://example.com/webhook",
                secret="test-secret",
                event_data={"type": "test"},
                attempt=1,
            )

        assert result.success is True
        assert result.status_code == 200
        assert result.error is None
        assert result.webhook_id == "wh-123"
        assert result.url == "https://example.com/webhook"
        assert result.attempt == 1

    @pytest.mark.asyncio
    async def test_deliver_webhook_includes_headers(self):
        worker, _ = _make_worker()

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_pool.return_value.get_session.return_value.__aenter__.return_value = mock_client

            await worker._deliver_webhook(
                webhook_id="wh-123",
                url="https://example.com/webhook",
                secret="my-secret",
                event_data={"key": "value"},
                attempt=2,
            )

            call_args = mock_client.post.call_args
            headers = call_args.kwargs["headers"]

            assert headers["Content-Type"] == "application/json"
            assert headers["User-Agent"] == "Aragora-Webhooks/1.0"
            assert headers["X-Webhook-ID"] == "wh-123"
            assert headers["X-Delivery-Attempt"] == "2"
            assert "X-Signature-SHA256" in headers

    @pytest.mark.asyncio
    async def test_deliver_webhook_no_signature_without_secret(self):
        worker, _ = _make_worker()

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("aragora.observability.http_client_pool.get_http_pool") as mock_pool:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_pool.return_value.get_session.return_value.__aenter__.return_value = mock_client

            await worker._deliver_webhook(
                webhook_id="wh-123",
                url="https://example.com/webhook",
                secret="",  # Empty secret
                event_data={"key": "value"},
                attempt=1,
            )

            call_args = mock_client.post.call_args
            headers = call_args.kwargs["headers"]

            assert "X-Signature-SHA256" not in headers


class TestEnqueueWebhookDelivery:
    """Tests for enqueue_webhook_delivery helper function."""

    @pytest.mark.asyncio
    async def test_enqueue_creates_job(self):
        mock_queue = AsyncMock(spec=JobQueue)

        job = await enqueue_webhook_delivery(
            queue=mock_queue,
            webhook_id="wh-123",
            url="https://example.com/webhook",
            secret="test-secret",
            event_type="debate.completed",
            event_data={"debate_id": "d-456"},
            priority=5,
        )

        assert job.payload["webhook_id"] == "wh-123"
        assert job.payload["url"] == "https://example.com/webhook"
        assert job.payload["secret"] == "test-secret"
        assert job.payload["event_type"] == "debate.completed"
        assert job.payload["event_data"] == {"debate_id": "d-456"}
        assert job.priority == 5
        assert job.metadata["type"] == "webhook_delivery"
        assert job.metadata["event_type"] == "debate.completed"

    @pytest.mark.asyncio
    async def test_enqueue_calls_queue(self):
        mock_queue = AsyncMock(spec=JobQueue)

        await enqueue_webhook_delivery(
            queue=mock_queue,
            webhook_id="wh-123",
            url="https://example.com/webhook",
            secret="secret",
            event_type="test",
            event_data={},
        )

        mock_queue.enqueue.assert_called_once()
        call_args = mock_queue.enqueue.call_args
        assert call_args.kwargs["queue_name"] == "webhook_delivery"


class TestTaskManagement:
    """Tests for task done callback and semaphore management."""

    def test_on_task_done_removes_task_and_releases_semaphore(self):
        worker, _ = _make_worker(max_concurrent=2)

        # Simulate task completion
        mock_task = MagicMock()
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = None

        worker._tasks.add(mock_task)
        worker._semaphore._value = 1  # One slot taken

        worker._on_task_done(mock_task)

        assert mock_task not in worker._tasks
        assert worker._semaphore._value == 2  # Released

    def test_on_task_done_logs_exception(self):
        worker, _ = _make_worker()

        mock_task = MagicMock()
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = RuntimeError("Task failed")

        worker._tasks.add(mock_task)

        # Should not raise, just log
        worker._on_task_done(mock_task)

        assert mock_task not in worker._tasks


class TestConcurrentDelivery:
    """Tests for concurrent delivery handling."""

    def test_semaphore_initialized_correctly(self):
        worker, _ = _make_worker(max_concurrent=5)
        assert worker._semaphore._value == 5

    def test_active_deliveries_calculation(self):
        worker, _ = _make_worker(max_concurrent=10)
        # Simulate 3 active deliveries
        worker._semaphore._value = 7

        stats = worker.get_stats()
        assert stats["active_deliveries"] == 3
