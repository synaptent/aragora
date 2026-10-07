"""
Tests for Batch Operations Handler Mixin.

Tests cover:
- Batch submission with validation
- Batch status retrieval
- Batch listing with filters
- Queue status endpoint
- Error handling for invalid inputs
- Quota checking
"""

import json
import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock

from aragora.server.handlers.debates.batch import BatchOperationsMixin


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_handler():
    """Create a mock HTTP handler with required attributes."""
    handler = Mock()
    handler.command = "POST"
    handler.user_store = None
    return handler


@pytest.fixture
def mock_server_context():
    """Create a mock server context."""
    ctx = Mock()
    ctx.config = {}
    return ctx


@pytest.fixture
def mock_batch_item():
    """Create a mock BatchItem class."""
    with patch("aragora.server.debate_queue.BatchItem") as mock_class:
        mock_item = Mock()
        mock_item.question = "Test question"
        mock_item.agents = "anthropic-api,openai-api"
        mock_item.rounds = 3
        mock_item.consensus = "majority"
        mock_class.from_dict.return_value = mock_item
        yield mock_class


@pytest.fixture
def mock_debate_queue():
    """Create a mock debate queue."""
    queue = Mock()
    queue.submit_batch = AsyncMock(return_value="batch_123")
    queue.get_batch_status = Mock(
        return_value={
            "batch_id": "batch_123",
            "status": "processing",
            "total_items": 5,
            "completed_items": 2,
            "failed_items": 0,
        }
    )
    queue.list_batches = Mock(
        return_value=[
            {"batch_id": "batch_1", "status": "completed"},
            {"batch_id": "batch_2", "status": "processing"},
        ]
    )
    queue.max_concurrent = 5
    queue._active_count = 2
    queue.debate_executor = None
    return queue


@pytest.fixture
def batch_mixin(mock_server_context):
    """Create BatchOperationsMixin instance with mocked dependencies."""

    class TestHandler(BatchOperationsMixin):
        def __init__(self):
            self.ctx = mock_server_context
            self._json_body = None

        def read_json_body(self, handler, max_size=None):
            return self._json_body

        def _create_debate_executor(self):
            return AsyncMock()

    return TestHandler()


@pytest.fixture(autouse=True)
def mock_permission_check():
    """Mock the permission checker to always allow access."""
    with patch("aragora.rbac.decorators.get_permission_checker") as mock_get:
        mock_checker = Mock()
        mock_checker.check_permission.return_value = Mock(
            allowed=True,
            permission="debates:create",
            reason="test allowed",
        )
        mock_get.return_value = mock_checker
        yield mock_checker


@pytest.fixture(autouse=True)
def mock_rate_limiters():
    """Mock rate limiters to always allow."""
    with patch("aragora.server.handlers.utils.rate_limit.rate_limit") as mock_rl:
        mock_rl.return_value = lambda f: f
        with patch("aragora.server.handlers.utils.rate_limit.user_rate_limit") as mock_url:
            mock_url.return_value = lambda f: f
            yield


@pytest.fixture(autouse=True)
def mock_timeout_decorator():
    """Mock timeout decorator."""
    with patch("aragora.resilience_patterns.with_timeout_sync") as mock_timeout:
        mock_timeout.return_value = lambda f: f
        yield


# ============================================================================
# Submit Batch Tests
# ============================================================================


class TestSubmitBatch:
    """Tests for batch submission endpoint."""

    def test_submit_batch_missing_body(self, batch_mixin, mock_handler):
        """Test 400 response when body is missing."""
        batch_mixin._json_body = None

        result = batch_mixin._submit_batch(mock_handler)

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "json" in data.get("error", "").lower() or "body" in data.get("error", "").lower()

    def test_submit_batch_empty_items(self, batch_mixin, mock_handler):
        """Test 400 response when items array is empty."""
        batch_mixin._json_body = {"items": []}

        with patch(
            "aragora.server.handlers.debates.batch.validate_against_schema"
        ) as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = batch_mixin._submit_batch(mock_handler)

            assert result.status_code == 400
            data = json.loads(result.body)
            assert "empty" in data.get("error", "").lower()

    def test_submit_batch_missing_items(self, batch_mixin, mock_handler):
        """Test 400 response when items key is missing."""
        batch_mixin._json_body = {}

        with patch(
            "aragora.server.handlers.debates.batch.validate_against_schema"
        ) as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = batch_mixin._submit_batch(mock_handler)

            assert result.status_code == 400
            data = json.loads(result.body)
            assert (
                "items" in data.get("error", "").lower() or "empty" in data.get("error", "").lower()
            )

    def test_submit_batch_too_many_items(self, batch_mixin, mock_handler):
        """Test 400 response when batch exceeds 1000 items."""
        batch_mixin._json_body = {"items": [{"question": f"Q{i}"} for i in range(1001)]}

        with patch(
            "aragora.server.handlers.debates.batch.validate_against_schema"
        ) as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = batch_mixin._submit_batch(mock_handler)

            assert result.status_code == 400
            data = json.loads(result.body)
            assert "1000" in data.get("error", "")

    def test_submit_batch_item_missing_question(self, batch_mixin, mock_handler):
        """Test 400 when item lacks question."""
        batch_mixin._json_body = {"items": [{"agents": "anthropic-api"}]}

        with patch(
            "aragora.server.handlers.debates.batch.validate_against_schema"
        ) as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = batch_mixin._submit_batch(mock_handler)

            assert result.status_code == 400
            data = json.loads(result.body)
            assert "question" in data.get("error", "").lower()

    def test_submit_batch_item_question_too_long(self, batch_mixin, mock_handler):
        """Test 400 when question exceeds 10000 chars."""
        batch_mixin._json_body = {"items": [{"question": "x" * 10001}]}

        with patch(
            "aragora.server.handlers.debates.batch.validate_against_schema"
        ) as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = batch_mixin._submit_batch(mock_handler)

            assert result.status_code == 400
            data = json.loads(result.body)
            assert "10,000" in data.get("error", "") or "10000" in data.get("error", "")

    def test_submit_batch_invalid_max_parallel(self, batch_mixin, mock_handler):
        """Test 400 when max_parallel is not an integer."""
        batch_mixin._json_body = {
            "items": [{"question": "Test question"}],
            "max_parallel": "not_a_number",
        }

        with patch(
            "aragora.server.handlers.debates.batch.validate_against_schema"
        ) as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)
            with patch("aragora.server.debate_queue.BatchItem") as mock_batch_item:
                mock_batch_item.from_dict.return_value = Mock(
                    question="Test question",
                    agents="anthropic-api",
                    rounds=3,
                    consensus="majority",
                )

                result = batch_mixin._submit_batch(mock_handler)

                assert result.status_code == 400
                data = json.loads(result.body)
                assert "max_parallel" in data.get("error", "").lower()

    def test_submit_batch_success(self, batch_mixin, mock_handler, mock_debate_queue):
        """Test successful batch submission."""
        batch_mixin._json_body = {
            "items": [
                {"question": "What is AI?"},
                {"question": "How does ML work?"},
            ]
        }

        with patch(
            "aragora.server.handlers.debates.batch.validate_against_schema"
        ) as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)
            with patch("aragora.server.debate_queue.BatchItem") as mock_batch_item:
                mock_batch_item.from_dict.return_value = Mock(
                    question="Test",
                    agents="anthropic-api",
                    rounds=3,
                    consensus="majority",
                )
                with patch("aragora.server.debate_queue.get_debate_queue") as mock_get_queue:
                    mock_get_queue.return_value = mock_debate_queue
                    with patch("aragora.server.http_utils.run_async") as mock_run_async:
                        mock_run_async.return_value = "batch_abc123"

                        result = batch_mixin._submit_batch(mock_handler)

                        assert result.status_code == 200
                        data = json.loads(result.body)
                        assert data["success"] is True
                        assert "batch_id" in data
                        assert data["items_queued"] == 2


# ============================================================================
# Get Batch Status Tests
# ============================================================================


class TestGetBatchStatus:
    """Tests for batch status endpoint."""

    def test_get_status_invalid_batch_id(self, batch_mixin, mock_handler):
        """Test 400 for invalid batch ID format."""
        with patch("aragora.server.handlers.debates.batch.validate_path_segment") as mock_validate:
            mock_validate.return_value = (False, "Invalid batch ID format")

            result = batch_mixin._get_batch_status("invalid<>id", "org-1")

            assert result.status_code == 400

    def test_get_status_queue_not_initialized(self, batch_mixin, mock_handler):
        """Test 503 when queue is not initialized."""
        with patch("aragora.server.handlers.debates.batch.validate_path_segment") as mock_validate:
            mock_validate.return_value = (True, None)
            with patch("aragora.server.debate_queue.get_debate_queue_sync") as mock_get:
                mock_get.return_value = None

                result = batch_mixin._get_batch_status("batch_123", "org-1")

                assert result.status_code == 503
                data = json.loads(result.body)
                assert "not initialized" in data.get("error", "").lower()

    def test_get_status_batch_not_found(self, batch_mixin, mock_handler, mock_debate_queue):
        """Test 404 when batch doesn't exist."""
        mock_debate_queue.get_batch_status.return_value = None

        with patch("aragora.server.handlers.debates.batch.validate_path_segment") as mock_validate:
            mock_validate.return_value = (True, None)
            with patch("aragora.server.debate_queue.get_debate_queue_sync") as mock_get:
                mock_get.return_value = mock_debate_queue

                result = batch_mixin._get_batch_status("nonexistent_batch", "org-1")

                assert result.status_code == 404
                data = json.loads(result.body)
                assert data == {"error": "Batch not found", "code": "not_found"}
                mock_debate_queue.get_batch_status.assert_called_once_with(
                    "nonexistent_batch", org_id="org-1"
                )

    def test_get_status_success(self, batch_mixin, mock_handler, mock_debate_queue):
        """Test successful status retrieval."""
        with patch("aragora.server.handlers.debates.batch.validate_path_segment") as mock_validate:
            mock_validate.return_value = (True, None)
            with patch("aragora.server.debate_queue.get_debate_queue_sync") as mock_get:
                mock_get.return_value = mock_debate_queue

                result = batch_mixin._get_batch_status("batch_123", "org-1")

                assert result.status_code == 200
                data = json.loads(result.body)
                assert data["batch_id"] == "batch_123"
                assert data["status"] == "processing"
                assert data["total_items"] == 5


# ============================================================================
# List Batches Tests
# ============================================================================


class TestListBatches:
    """Tests for batch listing endpoint."""

    def test_list_batches_queue_not_initialized(self, batch_mixin, mock_handler):
        """Test empty list when queue is not initialized."""
        with patch("aragora.server.debate_queue.get_debate_queue_sync") as mock_get:
            mock_get.return_value = None

            result = batch_mixin._list_batches(limit=50, org_id="org-1")

            assert result.status_code == 200
            data = json.loads(result.body)
            assert data["batches"] == []
            assert data["count"] == 0

    def test_list_batches_invalid_status(self, batch_mixin, mock_handler, mock_debate_queue):
        """Test 400 for invalid status filter."""
        with patch("aragora.server.debate_queue.get_debate_queue_sync") as mock_get:
            mock_get.return_value = mock_debate_queue
            with patch("aragora.server.debate_queue.BatchStatus") as mock_status:
                mock_status.side_effect = ValueError("Invalid status")

                result = batch_mixin._list_batches(
                    limit=50, status_filter="invalid_status", org_id="org-1"
                )

                assert result.status_code == 400
                data = json.loads(result.body)
                assert "invalid" in data.get("error", "").lower()

    def test_list_batches_success(self, batch_mixin, mock_handler, mock_debate_queue):
        """Test successful batch listing."""
        with patch("aragora.server.debate_queue.get_debate_queue_sync") as mock_get:
            mock_get.return_value = mock_debate_queue

            result = batch_mixin._list_batches(limit=50, org_id="org-1")

            assert result.status_code == 200
            data = json.loads(result.body)
            assert len(data["batches"]) == 2
            assert data["count"] == 2
            mock_debate_queue.list_batches.assert_called_once_with(
                status=None, limit=50, org_id="org-1"
            )

    def test_list_batches_with_status_filter(self, batch_mixin, mock_handler, mock_debate_queue):
        """Test listing with status filter."""
        mock_debate_queue.list_batches.return_value = [
            {"batch_id": "batch_1", "status": "completed"}
        ]

        with patch("aragora.server.debate_queue.get_debate_queue_sync") as mock_get:
            mock_get.return_value = mock_debate_queue
            with patch("aragora.server.debate_queue.BatchStatus") as mock_status:
                mock_status.return_value = "completed"

                result = batch_mixin._list_batches(
                    limit=50, status_filter="completed", org_id="org-1"
                )

                assert result.status_code == 200
                data = json.loads(result.body)
                assert len(data["batches"]) == 1


# ============================================================================
# Queue Status Tests
# ============================================================================


class TestQueueStatus:
    """Tests for queue status endpoint."""

    def test_queue_status_not_initialized(self, batch_mixin, mock_handler):
        """Test queue status when not initialized."""
        with patch("aragora.server.debate_queue.get_debate_queue_sync") as mock_get:
            mock_get.return_value = None

            result = batch_mixin._get_queue_status()

            assert result.status_code == 200
            data = json.loads(result.body)
            assert data["active"] is False
            assert "not initialized" in data.get("message", "").lower()

    def test_queue_status_success(self, batch_mixin, mock_handler, mock_debate_queue):
        """Test successful queue status retrieval."""
        with patch("aragora.server.debate_queue.get_debate_queue_sync") as mock_get:
            mock_get.return_value = mock_debate_queue

            result = batch_mixin._get_queue_status()

            assert result.status_code == 200
            data = json.loads(result.body)
            assert data["active"] is True
            assert data["max_concurrent"] == 5
            assert data["active_count"] == 2
            assert data["total_batches"] == 2
            assert "status_counts" in data


# ============================================================================
# Schema Validation Tests
# ============================================================================


class TestSchemaValidation:
    """Tests for input schema validation."""

    def test_schema_validation_failure(self, batch_mixin, mock_handler):
        """Test 400 when schema validation fails."""
        batch_mixin._json_body = {"invalid": "structure"}

        with patch(
            "aragora.server.handlers.debates.batch.validate_against_schema"
        ) as mock_validate:
            mock_validate.return_value = Mock(is_valid=False, error="Schema validation failed")

            result = batch_mixin._submit_batch(mock_handler)

            assert result.status_code == 400
            data = json.loads(result.body)
            assert (
                "schema" in data.get("error", "").lower()
                or "validation" in data.get("error", "").lower()
            )


# ============================================================================
# Webhook Validation Tests
# ============================================================================


class TestWebhookValidation:
    """Tests for webhook URL validation."""

    def test_invalid_webhook_url(self, batch_mixin, mock_handler):
        """Test 400 for invalid webhook URL."""
        batch_mixin._json_body = {
            "items": [{"question": "Test question"}],
            "webhook_url": "not_a_valid_url",
        }

        with patch(
            "aragora.server.handlers.debates.batch.validate_against_schema"
        ) as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)
            with patch("aragora.server.debate_queue.BatchItem") as mock_batch_item:
                mock_batch_item.from_dict.return_value = Mock(
                    question="Test",
                    agents="anthropic-api",
                    rounds=3,
                    consensus="majority",
                )
                with patch("aragora.server.debate_queue.validate_webhook_url") as mock_webhook:
                    mock_webhook.return_value = (False, "Invalid webhook URL")

                    result = batch_mixin._submit_batch(mock_handler)

                    assert result.status_code == 400
                    data = json.loads(result.body)
                    assert "webhook" in data.get("error", "").lower()

    def test_invalid_webhook_headers(self, batch_mixin, mock_handler):
        """Test 400 for invalid webhook headers."""
        batch_mixin._json_body = {
            "items": [{"question": "Test question"}],
            "webhook_url": "https://example.com/webhook",
            "webhook_headers": {"Invalid-Header": ["not", "a", "string"]},
        }

        with patch(
            "aragora.server.handlers.debates.batch.validate_against_schema"
        ) as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)
            with patch("aragora.server.debate_queue.BatchItem") as mock_batch_item:
                mock_batch_item.from_dict.return_value = Mock(
                    question="Test",
                    agents="anthropic-api",
                    rounds=3,
                    consensus="majority",
                )
                with patch("aragora.server.debate_queue.validate_webhook_url") as mock_webhook_url:
                    mock_webhook_url.return_value = (True, None)
                    with patch(
                        "aragora.server.debate_queue.sanitize_webhook_headers"
                    ) as mock_headers:
                        mock_headers.return_value = (None, "Invalid header format")

                        result = batch_mixin._submit_batch(mock_handler)

                        assert result.status_code == 400
                        data = json.loads(result.body)
                        assert "header" in data.get("error", "").lower()
