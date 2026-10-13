"""
Tests for aragora.server.debate_queue module.

Covers:
- Validation functions (SSRF protection, header sanitization)
- BatchItem and BatchRequest dataclasses
- DebateQueue operations (submit, cancel, status, cleanup)
- Priority ordering and concurrency limits
- Webhook notifications
"""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.config import DEFAULT_AGENTS, DEFAULT_CONSENSUS, DEFAULT_ROUNDS, MAX_ROUNDS
from aragora.server.debate_queue import (
    BatchItem,
    BatchRequest,
    BatchStatus,
    DebateQueue,
    ItemStatus,
    MAX_WEBHOOK_HEADER_COUNT,
    MAX_WEBHOOK_HEADER_SIZE,
    MAX_WEBHOOK_URL_LENGTH,
    sanitize_webhook_headers,
    validate_webhook_url,
)


class TestValidateWebhookUrl:
    """Tests for validate_webhook_url function."""

    def test_valid_https_url(self):
        """Valid HTTPS URL should pass."""
        with patch("socket.getaddrinfo") as mock_getaddr:
            # Return a non-private IP
            mock_getaddr.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
            valid, error = validate_webhook_url("https://example.com/webhook")
            assert valid is True
            assert error == ""

    def test_valid_http_url(self):
        """Valid HTTP URL should pass."""
        with patch("socket.getaddrinfo") as mock_getaddr:
            mock_getaddr.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
            valid, error = validate_webhook_url("http://example.com/webhook")
            assert valid is True
            assert error == ""

    def test_empty_url_rejected(self):
        """Empty URL should be rejected."""
        valid, error = validate_webhook_url("")
        assert valid is False
        assert "non-empty" in error

    def test_none_url_rejected(self):
        """None URL should be rejected."""
        valid, error = validate_webhook_url(None)
        assert valid is False
        assert "non-empty" in error

    def test_url_too_long(self):
        """URL exceeding max length should be rejected."""
        long_url = "https://example.com/" + "a" * MAX_WEBHOOK_URL_LENGTH
        valid, error = validate_webhook_url(long_url)
        assert valid is False
        assert "too long" in error

    def test_invalid_scheme_ftp(self):
        """FTP scheme should be rejected."""
        valid, error = validate_webhook_url("ftp://example.com/file")
        assert valid is False
        assert "http or https" in error

    def test_invalid_scheme_file(self):
        """File scheme should be rejected."""
        valid, error = validate_webhook_url("file:///etc/passwd")
        assert valid is False
        assert "http or https" in error

    def test_missing_hostname(self):
        """URL without hostname should be rejected."""
        valid, error = validate_webhook_url("https:///path")
        assert valid is False
        assert "hostname" in error

    def test_metadata_endpoint_blocked(self):
        """Cloud metadata endpoints should be blocked."""
        for hostname in ["169.254.169.254", "metadata.google.internal"]:
            valid, error = validate_webhook_url(f"http://{hostname}/")
            assert valid is False
            assert "blocked" in error.lower()

    def test_internal_hostname_blocked(self):
        """Internal hostnames should be blocked."""
        for suffix in [".internal", ".local", ".localhost", ".lan"]:
            valid, error = validate_webhook_url(f"https://service{suffix}/")
            assert valid is False
            assert "internal hostname" in error

    def test_private_ip_blocked(self):
        """Private IPs should be blocked."""
        for ip in ["10.0.0.1", "172.16.0.1", "192.168.1.1"]:
            valid, error = validate_webhook_url(f"http://{ip}/webhook")
            assert valid is False
            assert "private" in error.lower()

    def test_loopback_blocked_by_default(self):
        """Loopback addresses should be blocked by default."""
        valid, error = validate_webhook_url("http://127.0.0.1/webhook")
        assert valid is False
        assert "private" in error.lower() or "loopback" in error.lower() or "local" in error.lower()

    def test_localhost_allowed_with_env_var(self):
        """Localhost should be allowed when env var is set."""
        with patch.dict(os.environ, {"ARAGORA_WEBHOOK_ALLOW_LOCALHOST": "true"}):
            valid, error = validate_webhook_url("http://localhost/webhook")
            assert valid is True
            assert error == ""

    def test_dns_resolution_failure(self):
        """Unresolvable hostname should be rejected."""
        import socket

        with patch("socket.getaddrinfo", side_effect=socket.gaierror):
            valid, error = validate_webhook_url("https://nonexistent.invalid/")
            assert valid is False
            assert "could not be resolved" in error

    def test_dns_resolves_to_private_ip(self):
        """Hostname resolving to private IP should be blocked."""
        with patch("socket.getaddrinfo") as mock_getaddr:
            mock_getaddr.return_value = [(2, 1, 6, "", ("192.168.1.1", 443))]
            valid, error = validate_webhook_url("https://malicious.example.com/")
            assert valid is False
            assert "private" in error.lower() or "local" in error.lower()


class TestSanitizeWebhookHeaders:
    """Tests for sanitize_webhook_headers function."""

    def test_none_headers(self):
        """None headers should return empty dict."""
        headers, error = sanitize_webhook_headers(None)
        assert headers == {}
        assert error is None

    def test_empty_dict(self):
        """Empty dict should pass."""
        headers, error = sanitize_webhook_headers({})
        assert headers == {}
        assert error is None

    def test_valid_headers(self):
        """Valid headers should pass."""
        input_headers = {"Authorization": "Bearer token", "X-Custom": "value"}
        headers, error = sanitize_webhook_headers(input_headers)
        assert headers == input_headers
        assert error is None

    def test_non_dict_rejected(self):
        """Non-dict input should be rejected."""
        headers, error = sanitize_webhook_headers(["header"])
        assert headers == {}
        assert "must be an object" in error

    def test_too_many_headers(self):
        """Exceeding max header count should be rejected."""
        input_headers = {f"X-Header-{i}": f"value{i}" for i in range(MAX_WEBHOOK_HEADER_COUNT + 1)}
        headers, error = sanitize_webhook_headers(input_headers)
        assert headers == {}
        assert "maximum header count" in error

    def test_non_string_key_rejected(self):
        """Non-string key should be rejected."""
        headers, error = sanitize_webhook_headers({123: "value"})
        assert headers == {}
        assert "must be strings" in error

    def test_non_string_value_rejected(self):
        """Non-string value should be rejected."""
        headers, error = sanitize_webhook_headers({"key": 123})
        assert headers == {}
        assert "must be strings" in error

    def test_newline_in_key_rejected(self):
        """Newline in header key should be rejected."""
        headers, error = sanitize_webhook_headers({"X-Bad\nHeader": "value"})
        assert headers == {}
        assert "invalid characters" in error

    def test_newline_in_value_rejected(self):
        """Newline in header value should be rejected."""
        headers, error = sanitize_webhook_headers({"X-Header": "bad\nvalue"})
        assert headers == {}
        assert "invalid characters" in error

    def test_carriage_return_rejected(self):
        """Carriage return in headers should be rejected."""
        headers, error = sanitize_webhook_headers({"X-Header": "bad\rvalue"})
        assert headers == {}
        assert "invalid characters" in error

    def test_oversized_key_rejected(self):
        """Oversized header key should be rejected."""
        long_key = "X-" + "a" * 200
        headers, error = sanitize_webhook_headers({long_key: "value"})
        assert headers == {}
        assert "oversized" in error

    def test_oversized_value_rejected(self):
        """Oversized header value should be rejected."""
        long_value = "a" * (MAX_WEBHOOK_HEADER_SIZE + 1)
        headers, error = sanitize_webhook_headers({"X-Header": long_value})
        assert headers == {}
        assert "oversized" in error


class TestBatchItem:
    """Tests for BatchItem dataclass."""

    def test_default_values(self):
        """Default values should be set correctly."""
        item = BatchItem(question="Test question?")
        assert item.question == "Test question?"
        assert item.agents == "anthropic-api,openai-api,gemini"
        assert item.rounds == DEFAULT_ROUNDS
        assert item.consensus == "majority"
        assert item.priority == 0
        assert item.metadata == {}
        assert item.status == ItemStatus.QUEUED
        assert item.item_id.startswith("item_")

    def test_custom_values(self):
        """Custom values should be set correctly."""
        item = BatchItem(
            question="Custom question",
            agents="custom-agent",
            rounds=5,
            consensus="unanimous",
            priority=10,
            metadata={"key": "value"},
        )
        assert item.question == "Custom question"
        assert item.agents == "custom-agent"
        assert item.rounds == 5
        assert item.consensus == "unanimous"
        assert item.priority == 10
        assert item.metadata == {"key": "value"}

    def test_to_dict(self):
        """to_dict should serialize all fields."""
        item = BatchItem(question="Test?")
        item.status = ItemStatus.COMPLETED
        item.started_at = 1000.0
        item.completed_at = 1010.0

        d = item.to_dict()
        assert d["question"] == "Test?"
        assert d["status"] == "completed"
        assert d["duration_seconds"] == 10.0

    def test_to_dict_no_duration_without_times(self):
        """Duration should be None if times not set."""
        item = BatchItem(question="Test?")
        d = item.to_dict()
        assert d["duration_seconds"] is None

    def test_from_dict_minimal(self):
        """from_dict with minimal data should work."""
        item = BatchItem.from_dict({"question": "Minimal test"})
        assert item.question == "Minimal test"
        assert item.agents == DEFAULT_AGENTS

    def test_from_dict_full(self):
        """from_dict with full data should work."""
        item = BatchItem.from_dict(
            {
                "question": "Full test",
                "agents": "agent1,agent2",
                "rounds": 5,
                "consensus": "unanimous",
                "priority": 100,
                "metadata": {"foo": "bar"},
            }
        )
        assert item.question == "Full test"
        assert item.agents == "agent1,agent2"
        assert item.rounds == 5
        assert item.consensus == "unanimous"
        assert item.priority == 100
        assert item.metadata == {"foo": "bar"}

    def test_from_dict_agents_as_list(self):
        """from_dict should accept agents as list."""
        item = BatchItem.from_dict(
            {
                "question": "Test",
                "agents": ["agent1", "agent2", "agent3"],
            }
        )
        assert item.agents == "agent1,agent2,agent3"

    def test_from_dict_missing_question(self):
        """from_dict should raise on missing question."""
        with pytest.raises(ValueError, match="question is required"):
            BatchItem.from_dict({})

    def test_from_dict_empty_question(self):
        """from_dict should raise on empty question."""
        with pytest.raises(ValueError, match="question is required"):
            BatchItem.from_dict({"question": "   "})

    def test_from_dict_question_too_long(self):
        """from_dict should raise on question > 10000 chars."""
        with pytest.raises(ValueError, match="exceeds 10,000"):
            BatchItem.from_dict({"question": "a" * 10001})

    def test_from_dict_invalid_consensus(self):
        """from_dict should raise on invalid consensus value."""
        with pytest.raises(ValueError, match="consensus must be one of"):
            BatchItem.from_dict({"question": "Test", "consensus": "invalid"})

    def test_from_dict_invalid_metadata(self):
        """from_dict should raise on non-dict metadata."""
        with pytest.raises(ValueError, match="metadata must be an object"):
            BatchItem.from_dict({"question": "Test", "metadata": "not-a-dict"})

    def test_from_dict_rounds_clamped(self):
        """from_dict should clamp rounds to 1-MAX_ROUNDS."""
        item = BatchItem.from_dict({"question": "Test", "rounds": 0})
        assert item.rounds == 1

        item = BatchItem.from_dict({"question": "Test", "rounds": 100})
        assert item.rounds == MAX_ROUNDS


class TestBatchRequest:
    """Tests for BatchRequest dataclass."""

    def test_default_values(self):
        """Default values should be set correctly."""
        items = [BatchItem(question="Q1")]
        batch = BatchRequest(items=items)

        assert batch.items == items
        assert batch.webhook_url is None
        assert batch.webhook_headers == {}
        assert batch.max_parallel is None
        assert batch.status == BatchStatus.PENDING
        assert batch.batch_id.startswith("batch_")
        assert batch.created_at > 0

    def test_to_dict_counts(self):
        """to_dict should include correct counts."""
        items = [
            BatchItem(question="Q1"),
            BatchItem(question="Q2"),
            BatchItem(question="Q3"),
        ]
        items[0].status = ItemStatus.COMPLETED
        items[1].status = ItemStatus.FAILED
        items[2].status = ItemStatus.QUEUED

        batch = BatchRequest(items=items)
        d = batch.to_dict()

        assert d["total_items"] == 3
        assert d["completed"] == 1
        assert d["failed"] == 1
        assert d["queued"] == 1
        assert d["running"] == 0
        assert d["progress_percent"] == pytest.approx(66.7, rel=0.1)

    def test_summary_excludes_items(self):
        """summary should not include individual items."""
        items = [BatchItem(question="Q1")]
        batch = BatchRequest(items=items)
        summary = batch.summary()

        assert "items" not in summary
        assert "batch_id" in summary
        assert "status" in summary


class TestDebateQueue:
    """Tests for DebateQueue class."""

    @pytest.fixture
    def queue(self):
        """Create a fresh DebateQueue for each test."""
        return DebateQueue(max_concurrent=2)

    @pytest.fixture
    def mock_executor(self):
        """Create a mock debate executor."""

        async def executor(item):
            await asyncio.sleep(0.01)  # Simulate work
            return {"debate_id": f"debate_{item.item_id}", "result": "success"}

        return executor

    @pytest.mark.asyncio
    async def test_submit_batch_empty_rejected(self, queue):
        """Empty batch should be rejected."""
        batch = BatchRequest(items=[])
        with pytest.raises(ValueError, match="at least one item"):
            await queue.submit_batch(batch)

    @pytest.mark.asyncio
    async def test_submit_batch_too_large_rejected(self, queue):
        """Batch with > 1000 items should be rejected."""
        items = [BatchItem(question=f"Q{i}") for i in range(1001)]
        batch = BatchRequest(items=items)
        with pytest.raises(ValueError, match="cannot exceed 1000"):
            await queue.submit_batch(batch)

    @pytest.mark.asyncio
    async def test_submit_batch_returns_batch_id(self, queue):
        """submit_batch should return batch_id."""
        batch = BatchRequest(items=[BatchItem(question="Test")])
        batch_id = await queue.submit_batch(batch)
        assert batch_id == batch.batch_id

    @pytest.mark.asyncio
    async def test_submit_batch_sorts_by_priority(self, queue):
        """Items should be sorted by priority (highest first)."""
        items = [
            BatchItem(question="Low", priority=1),
            BatchItem(question="High", priority=10),
            BatchItem(question="Medium", priority=5),
        ]
        batch = BatchRequest(items=items)
        await queue.submit_batch(batch)

        # Items should now be sorted high -> medium -> low
        assert batch.items[0].question == "High"
        assert batch.items[1].question == "Medium"
        assert batch.items[2].question == "Low"

    @pytest.mark.asyncio
    async def test_get_batch_status(self, queue):
        """get_batch_status should return batch dict."""
        batch = BatchRequest(items=[BatchItem(question="Test")])
        await queue.submit_batch(batch)

        status = queue.get_batch_status(batch.batch_id)
        assert status is not None
        assert status["batch_id"] == batch.batch_id
        assert status["total_items"] == 1

    def test_get_batch_status_not_found(self, queue):
        """get_batch_status should return None for unknown batch."""
        status = queue.get_batch_status("nonexistent")
        assert status is None

    @pytest.mark.asyncio
    async def test_get_batch_summary(self, queue):
        """get_batch_summary should return summary without items."""
        batch = BatchRequest(items=[BatchItem(question="Test")])
        await queue.submit_batch(batch)

        summary = queue.get_batch_summary(batch.batch_id)
        assert summary is not None
        assert "items" not in summary

    @pytest.mark.asyncio
    async def test_list_batches(self, queue):
        """list_batches should return list of batch summaries."""
        batch1 = BatchRequest(items=[BatchItem(question="Q1")])
        batch2 = BatchRequest(items=[BatchItem(question="Q2")])

        await queue.submit_batch(batch1)
        await queue.submit_batch(batch2)

        batches = queue.list_batches()
        assert len(batches) == 2

    @pytest.mark.asyncio
    async def test_list_batches_filter_by_status(self, queue):
        """list_batches should filter by status."""
        batch1 = BatchRequest(items=[BatchItem(question="Q1")])
        batch2 = BatchRequest(items=[BatchItem(question="Q2")])
        batch2.status = BatchStatus.COMPLETED

        await queue.submit_batch(batch1)
        queue._batches[batch2.batch_id] = batch2

        pending = queue.list_batches(status=BatchStatus.PENDING)
        assert len(pending) == 1

        completed = queue.list_batches(status=BatchStatus.COMPLETED)
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_list_batches_limit(self, queue):
        """list_batches should respect limit."""
        for i in range(10):
            batch = BatchRequest(items=[BatchItem(question=f"Q{i}")])
            await queue.submit_batch(batch)

        batches = queue.list_batches(limit=3)
        assert len(batches) == 3

    @pytest.mark.asyncio
    async def test_cancel_batch_pending(self, queue):
        """cancel_batch should cancel pending batch."""
        batch = BatchRequest(items=[BatchItem(question="Test")])
        await queue.submit_batch(batch)

        result = await queue.cancel_batch(batch.batch_id)
        assert result is True
        assert batch.status == BatchStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_batch_cancels_queued_items(self, queue):
        """cancel_batch should cancel queued items."""
        items = [BatchItem(question=f"Q{i}") for i in range(3)]
        batch = BatchRequest(items=items)
        await queue.submit_batch(batch)

        await queue.cancel_batch(batch.batch_id)

        for item in batch.items:
            assert item.status == ItemStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_batch_not_found(self, queue):
        """cancel_batch should return False for unknown batch."""
        result = await queue.cancel_batch("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_batch_already_completed(self, queue):
        """cancel_batch should return False for completed batch."""
        batch = BatchRequest(items=[BatchItem(question="Test")])
        batch.status = BatchStatus.COMPLETED
        queue._batches[batch.batch_id] = batch

        result = await queue.cancel_batch(batch.batch_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_old_batches(self, queue):
        """cleanup_old_batches should remove old terminal batches."""
        # Create an old completed batch
        old_batch = BatchRequest(items=[BatchItem(question="Old")])
        old_batch.status = BatchStatus.COMPLETED
        old_batch.created_at = time.time() - (25 * 3600)  # 25 hours ago
        queue._batches[old_batch.batch_id] = old_batch

        # Create a recent completed batch
        new_batch = BatchRequest(items=[BatchItem(question="New")])
        new_batch.status = BatchStatus.COMPLETED
        queue._batches[new_batch.batch_id] = new_batch

        removed = queue.cleanup_old_batches(max_age_hours=24)
        assert removed == 1
        assert old_batch.batch_id not in queue._batches
        assert new_batch.batch_id in queue._batches

    @pytest.mark.asyncio
    async def test_cleanup_keeps_processing_batches(self, queue):
        """cleanup_old_batches should not remove processing batches."""
        old_batch = BatchRequest(items=[BatchItem(question="Old")])
        old_batch.status = BatchStatus.PROCESSING
        old_batch.created_at = time.time() - (25 * 3600)
        queue._batches[old_batch.batch_id] = old_batch

        removed = queue.cleanup_old_batches(max_age_hours=24)
        assert removed == 0
        assert old_batch.batch_id in queue._batches

    @pytest.mark.asyncio
    async def test_process_item_with_executor(self, queue, mock_executor):
        """_process_item should use executor and update item."""
        queue.debate_executor = mock_executor

        batch = BatchRequest(items=[BatchItem(question="Test")])
        item = batch.items[0]
        item.status = ItemStatus.RUNNING
        item.started_at = time.time()
        queue._batches[batch.batch_id] = batch

        await queue._process_item(batch, item)

        assert item.status == ItemStatus.COMPLETED
        assert item.result is not None
        assert item.debate_id is not None
        assert item.completed_at is not None

    @pytest.mark.asyncio
    async def test_process_item_without_executor(self, queue):
        """_process_item without executor should fail item."""
        batch = BatchRequest(items=[BatchItem(question="Test")])
        item = batch.items[0]
        item.status = ItemStatus.RUNNING
        queue._batches[batch.batch_id] = batch

        await queue._process_item(batch, item)

        assert item.status == ItemStatus.FAILED
        assert "No debate executor" in item.error

    @pytest.mark.asyncio
    async def test_process_item_exception(self, queue):
        """_process_item should handle executor exceptions."""

        async def failing_executor(item):
            raise RuntimeError("Executor failed")

        queue.debate_executor = failing_executor

        batch = BatchRequest(items=[BatchItem(question="Test")])
        item = batch.items[0]
        item.status = ItemStatus.RUNNING
        queue._batches[batch.batch_id] = batch

        await queue._process_item(batch, item)

        assert item.status == ItemStatus.FAILED
        assert "Executor failed" in item.error

    @pytest.mark.asyncio
    async def test_batch_completion_all_success(self, queue, mock_executor):
        """Batch should be COMPLETED when all items succeed."""
        queue.debate_executor = mock_executor

        items = [BatchItem(question=f"Q{i}") for i in range(3)]
        for item in items:
            item.status = ItemStatus.COMPLETED

        batch = BatchRequest(items=items)
        batch.status = BatchStatus.PROCESSING
        queue._batches[batch.batch_id] = batch

        await queue._check_batch_completion(batch)

        assert batch.status == BatchStatus.COMPLETED
        assert batch.completed_at is not None

    @pytest.mark.asyncio
    async def test_batch_completion_all_failed(self, queue):
        """Batch should be FAILED when all items fail."""
        items = [BatchItem(question=f"Q{i}") for i in range(3)]
        for item in items:
            item.status = ItemStatus.FAILED

        batch = BatchRequest(items=items)
        batch.status = BatchStatus.PROCESSING
        queue._batches[batch.batch_id] = batch

        await queue._check_batch_completion(batch)

        assert batch.status == BatchStatus.FAILED

    @pytest.mark.asyncio
    async def test_batch_completion_partial(self, queue):
        """Batch should be PARTIAL when some items fail."""
        items = [BatchItem(question=f"Q{i}") for i in range(3)]
        items[0].status = ItemStatus.COMPLETED
        items[1].status = ItemStatus.FAILED
        items[2].status = ItemStatus.COMPLETED

        batch = BatchRequest(items=items)
        batch.status = BatchStatus.PROCESSING
        queue._batches[batch.batch_id] = batch

        await queue._check_batch_completion(batch)

        assert batch.status == BatchStatus.PARTIAL

    @pytest.mark.asyncio
    async def test_batch_completion_all_cancelled(self, queue):
        """Batch should be CANCELLED when all items cancelled."""
        items = [BatchItem(question=f"Q{i}") for i in range(3)]
        for item in items:
            item.status = ItemStatus.CANCELLED

        batch = BatchRequest(items=items)
        batch.status = BatchStatus.PROCESSING
        queue._batches[batch.batch_id] = batch

        await queue._check_batch_completion(batch)

        assert batch.status == BatchStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, queue, mock_executor):
        """Queue should respect max_concurrent limit."""
        queue.debate_executor = mock_executor

        # Track concurrent executions
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def tracking_executor(item):
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                max_concurrent = max(max_concurrent, current_concurrent)

            await asyncio.sleep(0.05)  # Simulate work

            async with lock:
                current_concurrent -= 1

            return {"debate_id": f"debate_{item.item_id}"}

        queue.debate_executor = tracking_executor
        queue.max_concurrent = 2

        items = [BatchItem(question=f"Q{i}") for i in range(5)]
        batch = BatchRequest(items=items)
        await queue.submit_batch(batch)

        # Wait for processing
        await asyncio.sleep(0.5)
        await queue.shutdown()

        assert max_concurrent <= 2

    @pytest.mark.asyncio
    async def test_processor_stops_when_queue_drains(self, queue, mock_executor):
        """Processor task should exit once all queued work completes."""
        queue.debate_executor = mock_executor

        batch = BatchRequest(items=[BatchItem(question="Test")])
        await queue.submit_batch(batch)

        await asyncio.sleep(0.2)

        assert batch.status == BatchStatus.COMPLETED
        assert queue._processor_task is None or queue._processor_task.done()

    @pytest.mark.asyncio
    async def test_shutdown(self, queue):
        """shutdown should stop processor task."""
        batch = BatchRequest(items=[BatchItem(question="Test")])
        await queue.submit_batch(batch)

        await queue.shutdown()

        assert queue._shutdown is True
        assert queue._processor_task is None or queue._processor_task.done()


class TestWebhookSending:
    """Tests for webhook notification."""

    @pytest.fixture
    def queue(self):
        return DebateQueue(max_concurrent=1)

    @pytest.mark.asyncio
    async def test_send_webhook_success(self, queue):
        """Webhook should be sent on batch completion."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_pool = MagicMock()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_get_session(provider):
            yield mock_client

        mock_pool.get_session = _mock_get_session

        items = [BatchItem(question="Test")]
        items[0].status = ItemStatus.COMPLETED

        batch = BatchRequest(
            items=items,
            webhook_url="https://example.com/webhook",
        )
        queue._batches[batch.batch_id] = batch

        with patch("aragora.observability.http_client_pool.get_http_pool", return_value=mock_pool):
            with patch("socket.getaddrinfo") as mock_getaddr:
                mock_getaddr.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
                await queue._send_webhook(batch)
                mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_webhook_skipped_invalid_url(self, queue):
        """Webhook should be skipped for invalid URL."""
        items = [BatchItem(question="Test")]
        items[0].status = ItemStatus.COMPLETED

        batch = BatchRequest(
            items=items,
            webhook_url="http://169.254.169.254/",  # Blocked metadata endpoint
        )
        queue._batches[batch.batch_id] = batch

        # Should not raise, just log warning
        await queue._send_webhook(batch)


class TestBatchItemStatus:
    """Tests for ItemStatus enum."""

    def test_item_status_values(self):
        """ItemStatus should have expected values."""
        assert ItemStatus.QUEUED.value == "queued"
        assert ItemStatus.RUNNING.value == "running"
        assert ItemStatus.COMPLETED.value == "completed"
        assert ItemStatus.FAILED.value == "failed"
        assert ItemStatus.CANCELLED.value == "cancelled"


class TestBatchStatus:
    """Tests for BatchStatus enum."""

    def test_batch_status_values(self):
        """BatchStatus should have expected values."""
        assert BatchStatus.PENDING.value == "pending"
        assert BatchStatus.PROCESSING.value == "processing"
        assert BatchStatus.COMPLETED.value == "completed"
        assert BatchStatus.PARTIAL.value == "partial"
        assert BatchStatus.FAILED.value == "failed"
        assert BatchStatus.CANCELLED.value == "cancelled"


class TestGlobalQueueFunctions:
    """Tests for global queue singleton functions."""

    @pytest.fixture(autouse=True)
    def _reset_queue_singleton(self):
        """Reset debate queue singleton before/after each test."""
        import aragora.server.debate_queue as dq

        dq._queue = None
        yield
        dq._queue = None

    @pytest.mark.asyncio
    async def test_get_debate_queue(self):
        """get_debate_queue should return a DebateQueue instance."""
        import aragora.server.debate_queue as dq

        with patch("aragora.config.MAX_CONCURRENT_DEBATES", 5):
            queue = await dq.get_debate_queue()
            assert isinstance(queue, DebateQueue)

            # Second call should return same instance
            queue2 = await dq.get_debate_queue()
            assert queue is queue2

    def test_get_debate_queue_sync_none(self):
        """get_debate_queue_sync should return None if not initialized."""
        import aragora.server.debate_queue as dq

        result = dq.get_debate_queue_sync()
        assert result is None

    def test_get_debate_queue_sync_returns_instance(self):
        """get_debate_queue_sync should return instance if initialized."""
        import aragora.server.debate_queue as dq

        test_queue = DebateQueue()
        dq._queue = test_queue

        result = dq.get_debate_queue_sync()
        assert result is test_queue
