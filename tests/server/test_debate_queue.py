"""
Tests for Debate Queue management.

Tests cover:
- BatchItem dataclass and validation
- BatchRequest dataclass and status tracking
- DebateQueue initialization and configuration
- Batch submission and processing
- Priority ordering
- Concurrency limits
- Batch status tracking and monitoring
- Batch cancellation
- Webhook URL validation and SSRF prevention
- Webhook header sanitization
- Webhook delivery on completion
- Cleanup of old batches
- Global queue instance management
"""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.debate_queue import (
    BatchItem,
    BatchRequest,
    BatchStatus,
    DebateQueue,
    ItemStatus,
    get_debate_queue,
    get_debate_queue_sync,
    sanitize_webhook_headers,
    validate_webhook_url,
)


# =============================================================================
# BatchItem Tests
# =============================================================================


class TestBatchItem:
    """Tests for BatchItem dataclass."""

    def test_default_creation(self):
        """BatchItem creates with sensible defaults."""
        item = BatchItem(question="What is the capital of France?")

        assert item.question == "What is the capital of France?"
        assert item.agents == "anthropic-api,openai-api,gemini"
        assert item.rounds > 0
        assert item.consensus == "majority"
        assert item.priority == 0
        assert item.metadata == {}
        assert item.status == ItemStatus.QUEUED
        assert item.item_id.startswith("item_")
        assert item.debate_id is None
        assert item.result is None
        assert item.error is None
        assert item.started_at is None
        assert item.completed_at is None

    def test_custom_creation(self):
        """BatchItem accepts custom values."""
        item = BatchItem(
            question="Test question",
            agents="claude,gpt4",
            rounds=5,
            consensus="unanimous",
            priority=10,
            metadata={"key": "value"},
        )

        assert item.question == "Test question"
        assert item.agents == "claude,gpt4"
        assert item.rounds == 5
        assert item.consensus == "unanimous"
        assert item.priority == 10
        assert item.metadata == {"key": "value"}

    def test_to_dict_serialization(self):
        """to_dict returns JSON-serializable dict."""
        item = BatchItem(
            question="Test question",
            priority=5,
        )
        item.status = ItemStatus.COMPLETED
        item.started_at = 1000.0
        item.completed_at = 1010.0
        item.debate_id = "debate-123"
        item.result = {"answer": "Paris"}

        data = item.to_dict()

        assert data["question"] == "Test question"
        assert data["priority"] == 5
        assert data["status"] == "completed"
        assert data["started_at"] == 1000.0
        assert data["completed_at"] == 1010.0
        assert data["debate_id"] == "debate-123"
        assert data["result"] == {"answer": "Paris"}
        assert data["duration_seconds"] == 10.0

    def test_to_dict_without_times(self):
        """to_dict handles missing times."""
        item = BatchItem(question="Test")

        data = item.to_dict()

        assert data["started_at"] is None
        assert data["completed_at"] is None
        assert data["duration_seconds"] is None


class TestBatchItemFromDict:
    """Tests for BatchItem.from_dict factory method."""

    def test_minimal_dict(self):
        """from_dict creates item with minimal data."""
        data = {"question": "What is 2+2?"}
        item = BatchItem.from_dict(data)

        assert item.question == "What is 2+2?"
        assert item.agents  # Has default
        assert item.rounds > 0

    def test_full_dict(self):
        """from_dict creates item with all fields."""
        data = {
            "question": "Test question",
            "agents": "anthropic-api,openai-api",
            "rounds": 3,
            "consensus": "unanimous",
            "priority": 10,
            "metadata": {"user": "test"},
        }
        item = BatchItem.from_dict(data)

        assert item.question == "Test question"
        assert item.agents == "anthropic-api,openai-api"
        assert item.rounds == 3
        assert item.consensus == "unanimous"
        assert item.priority == 10
        assert item.metadata == {"user": "test"}

    def test_agents_as_list(self):
        """from_dict handles agents as list."""
        data = {"question": "Test", "agents": ["claude", "gpt4", "gemini"]}
        item = BatchItem.from_dict(data)

        assert item.agents == "claude,gpt4,gemini"

    def test_agents_as_structured_object(self):
        """from_dict serializes a structured agent spec into pipe format."""
        data = {
            "question": "Test",
            "agents": {"provider": "anthropic-api", "model": "claude-opus-4-7"},
        }
        item = BatchItem.from_dict(data)

        assert item.agents == "anthropic-api|claude-opus-4-7||"

    def test_agents_as_mixed_list(self):
        """from_dict preserves legacy strings and serializes structured specs."""
        data = {
            "question": "Test",
            "agents": [
                "claude",
                {"provider": "openai-api", "model": "gpt-4.1", "role": "critic"},
            ],
        }
        item = BatchItem.from_dict(data)

        assert item.agents == "claude,openai-api|gpt-4.1||critic"

    def test_agents_object_missing_provider_raises(self):
        """Structured agent specs without a provider-like field are rejected."""
        with pytest.raises(ValueError, match="provider"):
            BatchItem.from_dict({"question": "Test", "agents": {"model": "claude-opus-4-7"}})

    def test_missing_question_raises(self):
        """from_dict raises ValueError for missing question."""
        with pytest.raises(ValueError, match="question is required"):
            BatchItem.from_dict({})

    def test_empty_question_raises(self):
        """from_dict raises ValueError for empty question."""
        with pytest.raises(ValueError, match="question is required"):
            BatchItem.from_dict({"question": "   "})

    def test_long_question_raises(self):
        """from_dict raises ValueError for oversized question."""
        with pytest.raises(ValueError, match="exceeds 10,000 characters"):
            BatchItem.from_dict({"question": "x" * 10001})

    def test_invalid_consensus_raises(self):
        """from_dict raises ValueError for invalid consensus."""
        with pytest.raises(ValueError, match="consensus must be one of"):
            BatchItem.from_dict({"question": "Test", "consensus": "invalid"})

    def test_invalid_metadata_raises(self):
        """from_dict raises ValueError for non-dict metadata."""
        with pytest.raises(ValueError, match="metadata must be an object"):
            BatchItem.from_dict({"question": "Test", "metadata": "not a dict"})

    def test_rounds_clamped_to_valid_range(self):
        """from_dict clamps rounds to valid range."""
        item_low = BatchItem.from_dict({"question": "Test", "rounds": 0})
        item_high = BatchItem.from_dict({"question": "Test", "rounds": 1000})

        assert item_low.rounds >= 1
        assert item_high.rounds <= 20  # MAX_ROUNDS from config

    def test_invalid_rounds_uses_default(self):
        """from_dict uses default for invalid rounds."""
        item = BatchItem.from_dict({"question": "Test", "rounds": "invalid"})

        assert item.rounds > 0

    def test_invalid_priority_uses_zero(self):
        """from_dict uses zero for invalid priority."""
        item = BatchItem.from_dict({"question": "Test", "priority": "high"})

        assert item.priority == 0

    def test_none_metadata_becomes_empty_dict(self):
        """from_dict converts None metadata to empty dict."""
        item = BatchItem.from_dict({"question": "Test", "metadata": None})

        assert item.metadata == {}


# =============================================================================
# BatchRequest Tests
# =============================================================================


class TestBatchRequest:
    """Tests for BatchRequest dataclass."""

    def test_default_creation(self):
        """BatchRequest creates with defaults."""
        items = [BatchItem(question="Q1"), BatchItem(question="Q2")]
        batch = BatchRequest(items=items)

        assert len(batch.items) == 2
        assert batch.webhook_url is None
        assert batch.webhook_headers == {}
        assert batch.max_parallel is None
        assert batch.status == BatchStatus.PENDING
        assert batch.batch_id.startswith("batch_")
        assert batch.created_at > 0
        assert batch.started_at is None
        assert batch.completed_at is None

    def test_with_webhook(self):
        """BatchRequest accepts webhook configuration."""
        batch = BatchRequest(
            items=[BatchItem(question="Q1")],
            webhook_url="https://example.com/callback",
            webhook_headers={"Authorization": "Bearer token"},
        )

        assert batch.webhook_url == "https://example.com/callback"
        assert batch.webhook_headers == {"Authorization": "Bearer token"}

    def test_to_dict_serialization(self):
        """to_dict returns JSON-serializable dict."""
        items = [
            BatchItem(question="Q1"),
            BatchItem(question="Q2"),
        ]
        items[0].status = ItemStatus.COMPLETED
        items[1].status = ItemStatus.RUNNING

        batch = BatchRequest(items=items)
        batch.started_at = 1000.0
        batch.completed_at = 1020.0

        data = batch.to_dict()

        assert data["batch_id"].startswith("batch_")
        assert data["status"] == "pending"
        assert data["total_items"] == 2
        assert data["completed"] == 1
        assert data["running"] == 1
        assert data["queued"] == 0
        assert data["failed"] == 0
        assert data["progress_percent"] == 50.0
        assert data["duration_seconds"] == 20.0
        assert len(data["items"]) == 2

    def test_summary_excludes_items(self):
        """summary returns dict without items."""
        batch = BatchRequest(items=[BatchItem(question="Q1")])

        summary = batch.summary()

        assert "items" not in summary
        assert "batch_id" in summary
        assert "status" in summary

    def test_progress_percent_empty_batch(self):
        """to_dict handles empty batch."""
        batch = BatchRequest(items=[])

        data = batch.to_dict()

        assert data["progress_percent"] == 0


# =============================================================================
# Webhook Validation Tests
# =============================================================================


class TestValidateWebhookUrl:
    """Tests for validate_webhook_url function."""

    def test_valid_https_url(self):
        """Accepts valid HTTPS URLs."""
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
            is_valid, error = validate_webhook_url("https://example.com/webhook")

        assert is_valid is True
        assert error == ""

    def test_valid_http_url(self):
        """Accepts valid HTTP URLs."""
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]):
            is_valid, error = validate_webhook_url("http://example.com/webhook")

        assert is_valid is True
        assert error == ""

    def test_empty_url(self):
        """Rejects empty URL."""
        is_valid, error = validate_webhook_url("")

        assert is_valid is False
        assert "non-empty string" in error

    def test_none_url(self):
        """Rejects None URL."""
        is_valid, error = validate_webhook_url(None)

        assert is_valid is False
        assert "non-empty string" in error

    def test_too_long_url(self):
        """Rejects URL exceeding max length."""
        long_url = "https://example.com/" + "x" * 3000

        is_valid, error = validate_webhook_url(long_url)

        assert is_valid is False
        assert "too long" in error

    def test_invalid_scheme(self):
        """Rejects non-HTTP schemes."""
        is_valid, error = validate_webhook_url("ftp://example.com/webhook")

        assert is_valid is False
        assert "http or https" in error

    def test_missing_hostname(self):
        """Rejects URL without hostname."""
        is_valid, error = validate_webhook_url("https:///path")

        assert is_valid is False
        assert "hostname" in error

    def test_blocked_metadata_endpoint(self):
        """Rejects cloud metadata endpoints."""
        is_valid, error = validate_webhook_url("http://169.254.169.254/latest/meta-data/")

        assert is_valid is False
        assert "blocked metadata" in error

    def test_internal_hostname_suffix(self):
        """Rejects internal hostname suffixes."""
        is_valid, error = validate_webhook_url("https://service.internal/webhook")

        assert is_valid is False
        assert "internal hostname" in error

    def test_localhost_blocked_by_default(self):
        """Rejects localhost by default."""
        with patch.dict(os.environ, {"ARAGORA_WEBHOOK_ALLOW_LOCALHOST": ""}):
            is_valid, error = validate_webhook_url("http://localhost/webhook")

        assert is_valid is False

    def test_localhost_allowed_with_env_var(self):
        """Allows localhost when env var is set."""
        with patch.dict(os.environ, {"ARAGORA_WEBHOOK_ALLOW_LOCALHOST": "true"}):
            is_valid, error = validate_webhook_url("http://localhost/webhook")

        assert is_valid is True

    def test_private_ip_rejected(self):
        """Rejects private IP addresses."""
        is_valid, error = validate_webhook_url("http://192.168.1.1/webhook")

        assert is_valid is False
        assert "private or local" in error

    def test_loopback_ip_rejected(self):
        """Rejects loopback IP addresses."""
        is_valid, error = validate_webhook_url("http://127.0.0.1/webhook")

        assert is_valid is False

    def test_link_local_ip_rejected(self):
        """Rejects link-local IP addresses."""
        is_valid, error = validate_webhook_url("http://169.254.1.1/webhook")

        assert is_valid is False

    @patch("socket.getaddrinfo")
    def test_hostname_resolving_to_private_ip(self, mock_getaddrinfo):
        """Rejects hostname that resolves to private IP."""
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("10.0.0.1", 80)),
        ]

        is_valid, error = validate_webhook_url("https://internal.company.com/webhook")

        assert is_valid is False
        assert "private or local" in error

    @patch("socket.getaddrinfo")
    def test_unresolvable_hostname(self, mock_getaddrinfo):
        """Rejects hostname that cannot be resolved."""
        import socket

        mock_getaddrinfo.side_effect = socket.gaierror("Name resolution failed")

        is_valid, error = validate_webhook_url("https://nonexistent.invalid/webhook")

        assert is_valid is False
        assert "could not be resolved" in error


class TestSanitizeWebhookHeaders:
    """Tests for sanitize_webhook_headers function."""

    def test_none_headers(self):
        """Returns empty dict for None headers."""
        sanitized, error = sanitize_webhook_headers(None)

        assert sanitized == {}
        assert error is None

    def test_valid_headers(self):
        """Accepts valid headers."""
        headers = {"X-Custom-Header": "value", "Authorization": "Bearer token"}

        sanitized, error = sanitize_webhook_headers(headers)

        assert sanitized == headers
        assert error is None

    def test_non_dict_headers(self):
        """Rejects non-dict headers."""
        sanitized, error = sanitize_webhook_headers("not a dict")

        assert sanitized == {}
        assert "must be an object" in error

    def test_too_many_headers(self):
        """Rejects headers exceeding max count."""
        headers = {f"X-Header-{i}": f"value{i}" for i in range(25)}

        sanitized, error = sanitize_webhook_headers(headers)

        assert sanitized == {}
        assert "maximum header count" in error

    def test_non_string_key(self):
        """Rejects non-string key."""
        sanitized, error = sanitize_webhook_headers({123: "value"})

        assert sanitized == {}
        assert "must be strings" in error

    def test_non_string_value(self):
        """Rejects non-string value."""
        sanitized, error = sanitize_webhook_headers({"key": 123})

        assert sanitized == {}
        assert "must be strings" in error

    def test_newline_in_key(self):
        """Rejects header key with newline."""
        sanitized, error = sanitize_webhook_headers({"key\n": "value"})

        assert sanitized == {}
        assert "invalid characters" in error

    def test_carriage_return_in_value(self):
        """Rejects header value with carriage return."""
        sanitized, error = sanitize_webhook_headers({"key": "value\r"})

        assert sanitized == {}
        assert "invalid characters" in error

    def test_oversized_key(self):
        """Rejects oversized header key."""
        sanitized, error = sanitize_webhook_headers({"x" * 300: "value"})

        assert sanitized == {}
        assert "oversized values" in error

    def test_oversized_value(self):
        """Rejects oversized header value."""
        sanitized, error = sanitize_webhook_headers({"key": "x" * 2000})

        assert sanitized == {}
        assert "oversized values" in error


# =============================================================================
# DebateQueue Tests
# =============================================================================


class TestDebateQueueInit:
    """Tests for DebateQueue initialization."""

    def test_default_initialization(self):
        """DebateQueue initializes with defaults."""
        queue = DebateQueue()

        assert queue.max_concurrent == 3
        assert queue.debate_executor is None
        assert queue._batches == {}
        assert queue._active_count == 0
        assert queue._shutdown is False

    def test_custom_initialization(self):
        """DebateQueue accepts custom values."""
        executor = AsyncMock()
        queue = DebateQueue(max_concurrent=5, debate_executor=executor)

        assert queue.max_concurrent == 5
        assert queue.debate_executor is executor


class TestDebateQueueSubmitBatch:
    """Tests for batch submission."""

    @pytest.mark.asyncio
    async def test_submit_empty_batch_raises(self):
        """submit_batch raises for empty batch."""
        queue = DebateQueue()
        batch = BatchRequest(items=[])

        with pytest.raises(ValueError, match="at least one item"):
            await queue.submit_batch(batch)

    @pytest.mark.asyncio
    async def test_submit_oversized_batch_raises(self):
        """submit_batch raises for batch exceeding 1000 items."""
        queue = DebateQueue()
        items = [BatchItem(question=f"Q{i}") for i in range(1001)]
        batch = BatchRequest(items=items)

        with pytest.raises(ValueError, match="cannot exceed 1000 items"):
            await queue.submit_batch(batch)

    @pytest.mark.asyncio
    async def test_submit_batch_returns_id(self):
        """submit_batch returns batch_id."""
        queue = DebateQueue()
        batch = BatchRequest(items=[BatchItem(question="Q1")])

        batch_id = await queue.submit_batch(batch)
        await queue.shutdown()

        assert batch_id == batch.batch_id
        assert batch_id in queue._batches

    @pytest.mark.asyncio
    async def test_submit_batch_sorts_by_priority(self):
        """submit_batch sorts items by priority (highest first)."""
        queue = DebateQueue()
        items = [
            BatchItem(question="Low", priority=1),
            BatchItem(question="High", priority=10),
            BatchItem(question="Medium", priority=5),
        ]
        batch = BatchRequest(items=items)

        await queue.submit_batch(batch)
        await queue.shutdown()

        assert batch.items[0].priority == 10
        assert batch.items[1].priority == 5
        assert batch.items[2].priority == 1

    @pytest.mark.asyncio
    async def test_submit_starts_processor(self):
        """submit_batch starts background processor."""
        queue = DebateQueue()
        batch = BatchRequest(items=[BatchItem(question="Q1")])

        await queue.submit_batch(batch)

        assert queue._processor_task is not None
        await queue.shutdown()


class TestDebateQueueStatus:
    """Tests for batch status methods."""

    @pytest.mark.asyncio
    async def test_get_batch_status(self):
        """get_batch_status returns batch data."""
        queue = DebateQueue()
        batch = BatchRequest(items=[BatchItem(question="Q1")])
        await queue.submit_batch(batch)
        await queue.shutdown()

        status = queue.get_batch_status(batch.batch_id)

        assert status is not None
        assert status["batch_id"] == batch.batch_id
        assert "items" in status

    def test_get_batch_status_not_found(self):
        """get_batch_status returns None for unknown batch."""
        queue = DebateQueue()

        status = queue.get_batch_status("unknown-batch")

        assert status is None

    @pytest.mark.asyncio
    async def test_get_batch_summary(self):
        """get_batch_summary returns summary without items."""
        queue = DebateQueue()
        batch = BatchRequest(items=[BatchItem(question="Q1")])
        await queue.submit_batch(batch)
        await queue.shutdown()

        summary = queue.get_batch_summary(batch.batch_id)

        assert summary is not None
        assert "items" not in summary

    def test_get_batch_summary_not_found(self):
        """get_batch_summary returns None for unknown batch."""
        queue = DebateQueue()

        summary = queue.get_batch_summary("unknown-batch")

        assert summary is None


class TestDebateQueueListBatches:
    """Tests for listing batches."""

    @pytest.mark.asyncio
    async def test_list_batches_all(self):
        """list_batches returns all batches."""
        queue = DebateQueue()
        batch1 = BatchRequest(items=[BatchItem(question="Q1")])
        batch2 = BatchRequest(items=[BatchItem(question="Q2")])
        await queue.submit_batch(batch1)
        await queue.submit_batch(batch2)
        await queue.shutdown()

        batches = queue.list_batches()

        assert len(batches) == 2

    @pytest.mark.asyncio
    async def test_list_batches_by_status(self):
        """list_batches filters by status."""
        queue = DebateQueue()
        batch1 = BatchRequest(items=[BatchItem(question="Q1")])
        batch2 = BatchRequest(items=[BatchItem(question="Q2")])
        await queue.submit_batch(batch1)
        await queue.submit_batch(batch2)

        batch1.status = BatchStatus.COMPLETED
        await queue.shutdown()

        pending = queue.list_batches(status=BatchStatus.PENDING)
        completed = queue.list_batches(status=BatchStatus.COMPLETED)

        # After submission, status changes to PROCESSING
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_list_batches_limit(self):
        """list_batches respects limit."""
        queue = DebateQueue()
        for i in range(10):
            batch = BatchRequest(items=[BatchItem(question=f"Q{i}")])
            await queue.submit_batch(batch)
        await queue.shutdown()

        batches = queue.list_batches(limit=5)

        assert len(batches) == 5

    @pytest.mark.asyncio
    async def test_list_batches_sorted_by_creation(self):
        """list_batches returns newest first."""
        queue = DebateQueue()
        batch1 = BatchRequest(items=[BatchItem(question="Q1")])
        batch1.created_at = 1000.0
        batch2 = BatchRequest(items=[BatchItem(question="Q2")])
        batch2.created_at = 2000.0
        await queue.submit_batch(batch1)
        await queue.submit_batch(batch2)
        await queue.shutdown()

        batches = queue.list_batches()

        assert batches[0]["created_at"] > batches[1]["created_at"]


class TestDebateQueueCancelBatch:
    """Tests for batch cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_pending_batch(self):
        """cancel_batch cancels pending batch."""
        queue = DebateQueue()
        batch = BatchRequest(items=[BatchItem(question="Q1")])
        batch.status = BatchStatus.PENDING
        queue._batches[batch.batch_id] = batch

        result = await queue.cancel_batch(batch.batch_id)

        assert result is True
        assert batch.status == BatchStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_processing_batch(self):
        """cancel_batch cancels processing batch."""
        queue = DebateQueue()
        batch = BatchRequest(items=[BatchItem(question="Q1"), BatchItem(question="Q2")])
        batch.status = BatchStatus.PROCESSING
        batch.items[0].status = ItemStatus.RUNNING
        batch.items[1].status = ItemStatus.QUEUED
        queue._batches[batch.batch_id] = batch

        result = await queue.cancel_batch(batch.batch_id)

        assert result is True
        assert batch.status == BatchStatus.CANCELLED
        # Running items stay running, queued items get cancelled
        assert batch.items[0].status == ItemStatus.RUNNING
        assert batch.items[1].status == ItemStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_completed_batch_fails(self):
        """cancel_batch returns False for completed batch."""
        queue = DebateQueue()
        batch = BatchRequest(items=[BatchItem(question="Q1")])
        batch.status = BatchStatus.COMPLETED
        queue._batches[batch.batch_id] = batch

        result = await queue.cancel_batch(batch.batch_id)

        assert result is False
        assert batch.status == BatchStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_cancel_unknown_batch_fails(self):
        """cancel_batch returns False for unknown batch."""
        queue = DebateQueue()

        result = await queue.cancel_batch("unknown-batch")

        assert result is False


class TestDebateQueueProcessing:
    """Tests for batch processing."""

    @pytest.mark.asyncio
    async def test_process_with_executor(self):
        """Items are processed using debate_executor."""
        executed_items = []

        async def mock_executor(item):
            executed_items.append(item.question)
            return {"debate_id": "test-debate", "answer": "42"}

        queue = DebateQueue(max_concurrent=1, debate_executor=mock_executor)
        batch = BatchRequest(items=[BatchItem(question="Q1")])

        await queue.submit_batch(batch)

        # Give processor time to run
        await asyncio.sleep(0.2)
        await queue.shutdown()

        assert len(executed_items) == 1
        assert "Q1" in executed_items
        assert batch.items[0].status == ItemStatus.COMPLETED
        assert batch.items[0].debate_id == "test-debate"

    @pytest.mark.asyncio
    async def test_process_without_executor(self):
        """Items fail when no executor configured."""
        queue = DebateQueue(max_concurrent=1)
        batch = BatchRequest(items=[BatchItem(question="Q1")])

        await queue.submit_batch(batch)
        await asyncio.sleep(0.2)
        await queue.shutdown()

        assert batch.items[0].status == ItemStatus.FAILED
        assert "No debate executor configured" in batch.items[0].error

    @pytest.mark.asyncio
    async def test_process_executor_error(self):
        """Items marked failed on executor error."""

        async def failing_executor(item):
            raise ValueError("Execution failed")

        queue = DebateQueue(max_concurrent=1, debate_executor=failing_executor)
        batch = BatchRequest(items=[BatchItem(question="Q1")])

        await queue.submit_batch(batch)
        await asyncio.sleep(0.2)
        await queue.shutdown()

        assert batch.items[0].status == ItemStatus.FAILED
        assert "failed" in batch.items[0].error.lower()

    @pytest.mark.asyncio
    async def test_respects_max_concurrent(self):
        """Processing respects max_concurrent limit."""
        running_count = 0
        max_observed = 0

        async def tracking_executor(item):
            nonlocal running_count, max_observed
            running_count += 1
            max_observed = max(max_observed, running_count)
            await asyncio.sleep(0.1)
            running_count -= 1
            return {"debate_id": "test"}

        queue = DebateQueue(max_concurrent=2, debate_executor=tracking_executor)
        items = [BatchItem(question=f"Q{i}") for i in range(5)]
        batch = BatchRequest(items=items)

        await queue.submit_batch(batch)
        await asyncio.sleep(1)
        await queue.shutdown()

        assert max_observed <= 2

    @pytest.mark.asyncio
    async def test_respects_batch_max_parallel(self):
        """Processing respects batch-level max_parallel."""
        running_count = 0
        max_observed = 0

        async def tracking_executor(item):
            nonlocal running_count, max_observed
            running_count += 1
            max_observed = max(max_observed, running_count)
            await asyncio.sleep(0.1)
            running_count -= 1
            return {"debate_id": "test"}

        queue = DebateQueue(max_concurrent=5, debate_executor=tracking_executor)
        items = [BatchItem(question=f"Q{i}") for i in range(5)]
        batch = BatchRequest(items=items, max_parallel=1)

        await queue.submit_batch(batch)
        await asyncio.sleep(1)
        await queue.shutdown()

        assert max_observed <= 1


class TestDebateQueueCompletion:
    """Tests for batch completion detection."""

    @pytest.mark.asyncio
    async def test_batch_completed_all_success(self):
        """Batch marked COMPLETED when all items succeed."""

        async def success_executor(item):
            return {"debate_id": "test"}

        queue = DebateQueue(max_concurrent=3, debate_executor=success_executor)
        items = [BatchItem(question=f"Q{i}") for i in range(3)]
        batch = BatchRequest(items=items)

        await queue.submit_batch(batch)
        await asyncio.sleep(0.5)
        await queue.shutdown()

        assert batch.status == BatchStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_batch_partial_on_failures(self):
        """Batch marked PARTIAL when some items fail."""
        call_count = 0

        async def partial_executor(item):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("Failed")
            return {"debate_id": "test"}

        queue = DebateQueue(max_concurrent=1, debate_executor=partial_executor)
        items = [BatchItem(question=f"Q{i}") for i in range(3)]
        batch = BatchRequest(items=items)

        await queue.submit_batch(batch)
        await asyncio.sleep(0.5)
        await queue.shutdown()

        assert batch.status == BatchStatus.PARTIAL

    @pytest.mark.asyncio
    async def test_batch_failed_all_failures(self):
        """Batch marked FAILED when all items fail."""

        async def failing_executor(item):
            raise ValueError("All fail")

        queue = DebateQueue(max_concurrent=3, debate_executor=failing_executor)
        items = [BatchItem(question=f"Q{i}") for i in range(3)]
        batch = BatchRequest(items=items)

        await queue.submit_batch(batch)
        await asyncio.sleep(0.5)
        await queue.shutdown()

        assert batch.status == BatchStatus.FAILED


class TestDebateQueueWebhook:
    """Tests for webhook delivery."""

    @pytest.mark.asyncio
    async def test_webhook_sent_on_completion(self):
        """Webhook is sent when batch completes."""

        async def success_executor(item):
            return {"debate_id": "test"}

        queue = DebateQueue(max_concurrent=1, debate_executor=success_executor)
        batch = BatchRequest(
            items=[BatchItem(question="Q1")],
            webhook_url="https://example.com/webhook",
        )

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock()
        mock_pool.get_session.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_pool.get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "aragora.observability.http_client_pool.get_http_pool",
                return_value=mock_pool,
            ),
            patch(
                "aragora.server.debate_queue.validate_webhook_url",
                return_value=(True, ""),
            ),
        ):
            await queue.submit_batch(batch)
            await asyncio.sleep(0.5)
            await queue.shutdown()

            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_skipped_invalid_url(self):
        """Webhook skipped for invalid URL."""

        async def success_executor(item):
            return {"debate_id": "test"}

        queue = DebateQueue(max_concurrent=1, debate_executor=success_executor)
        batch = BatchRequest(
            items=[BatchItem(question="Q1")],
            webhook_url="http://169.254.169.254/metadata",  # Blocked
        )

        mock_pool = MagicMock()

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            await queue.submit_batch(batch)
            await asyncio.sleep(0.5)
            await queue.shutdown()

            mock_pool.get_session.assert_not_called()


class TestDebateQueueCleanup:
    """Tests for batch cleanup."""

    def test_cleanup_old_batches(self):
        """cleanup_old_batches removes old completed batches."""
        queue = DebateQueue()

        # Create old completed batch
        old_batch = BatchRequest(items=[BatchItem(question="Q1")])
        old_batch.status = BatchStatus.COMPLETED
        old_batch.created_at = time.time() - 25 * 3600  # 25 hours ago

        # Create recent completed batch
        recent_batch = BatchRequest(items=[BatchItem(question="Q2")])
        recent_batch.status = BatchStatus.COMPLETED
        recent_batch.created_at = time.time() - 1 * 3600  # 1 hour ago

        # Create old pending batch (should not be removed)
        pending_batch = BatchRequest(items=[BatchItem(question="Q3")])
        pending_batch.status = BatchStatus.PENDING
        pending_batch.created_at = time.time() - 25 * 3600

        queue._batches[old_batch.batch_id] = old_batch
        queue._batches[recent_batch.batch_id] = recent_batch
        queue._batches[pending_batch.batch_id] = pending_batch

        removed = queue.cleanup_old_batches(max_age_hours=24)

        assert removed == 1
        assert old_batch.batch_id not in queue._batches
        assert recent_batch.batch_id in queue._batches
        assert pending_batch.batch_id in queue._batches


class TestDebateQueueShutdown:
    """Tests for queue shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_stops_processor(self):
        """shutdown stops the background processor."""
        queue = DebateQueue()
        batch = BatchRequest(items=[BatchItem(question="Q1")])
        await queue.submit_batch(batch)

        await queue.shutdown()

        assert queue._shutdown is True
        assert queue._processor_task is None or (
            queue._processor_task.cancelled() or queue._processor_task.done()
        )


# =============================================================================
# Global Instance Tests
# =============================================================================


class TestGlobalDebateQueue:
    """Tests for global queue instance."""

    @pytest.mark.asyncio
    async def test_get_debate_queue_singleton(self):
        """get_debate_queue returns singleton instance."""
        # Reset global state
        import aragora.server.debate_queue as module

        module._queue = None

        queue1 = await get_debate_queue()
        queue2 = await get_debate_queue()

        assert queue1 is queue2

        # Cleanup
        await queue1.shutdown()
        module._queue = None

    def test_get_debate_queue_sync_returns_none_initially(self):
        """get_debate_queue_sync returns None before initialization."""
        import aragora.server.debate_queue as module

        module._queue = None

        result = get_debate_queue_sync()

        assert result is None

    @pytest.mark.asyncio
    async def test_get_debate_queue_sync_after_init(self):
        """get_debate_queue_sync returns instance after initialization."""
        import aragora.server.debate_queue as module

        module._queue = None

        queue = await get_debate_queue()
        sync_result = get_debate_queue_sync()

        assert sync_result is queue

        # Cleanup
        await queue.shutdown()
        module._queue = None


# =============================================================================
# Status Enum Tests
# =============================================================================


class TestStatusEnums:
    """Tests for status enum values."""

    def test_batch_status_values(self):
        """BatchStatus has expected values."""
        assert BatchStatus.PENDING.value == "pending"
        assert BatchStatus.PROCESSING.value == "processing"
        assert BatchStatus.COMPLETED.value == "completed"
        assert BatchStatus.PARTIAL.value == "partial"
        assert BatchStatus.FAILED.value == "failed"
        assert BatchStatus.CANCELLED.value == "cancelled"

    def test_item_status_values(self):
        """ItemStatus has expected values."""
        assert ItemStatus.QUEUED.value == "queued"
        assert ItemStatus.RUNNING.value == "running"
        assert ItemStatus.COMPLETED.value == "completed"
        assert ItemStatus.FAILED.value == "failed"
        assert ItemStatus.CANCELLED.value == "cancelled"
