"""
Tests for batch debate operations handler.

Tests the BatchOperationsMixin for batch submission, status tracking,
and queue management.
"""

import types

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json


def _make_batch_mixin():
    """Create a BatchOperationsMixin with all decorators bypassed.

    The _submit_batch method is decorated with @require_permission (and
    other wrappers like @with_timeout_sync, @rate_limit) which need an
    AuthorizationContext or signal setup. For unit tests that exercise
    validation logic we fully unwrap the decorator chain so tests can
    call the underlying method directly.
    """
    from aragora.server.handlers.debates.batch import BatchOperationsMixin

    mixin = BatchOperationsMixin()
    for attr_name in dir(mixin):
        attr = getattr(mixin, attr_name, None)
        if callable(attr) and hasattr(attr, "__wrapped__"):
            # Walk to the innermost function through all decorator layers
            func = attr
            while hasattr(func, "__wrapped__"):
                func = func.__wrapped__
            setattr(mixin, attr_name, types.MethodType(func, mixin))
    return mixin


class TestBatchSubmission:
    """Tests for batch debate submission."""

    @pytest.fixture(autouse=True)
    def org_user(self, monkeypatch):
        """Batch submission requires an authenticated user with an org."""
        from aragora.billing.auth.context import UserAuthContext

        user = UserAuthContext(authenticated=True, user_id="user-1", org_id="org-1")
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: user,
        )

    def test_submit_batch_empty_items_returns_error(self):
        """Should return error when items array is empty."""
        mixin = _make_batch_mixin()
        mixin.read_json_body = MagicMock(return_value={"items": []})

        result = mixin._submit_batch(MagicMock())

        assert result.status_code == 400
        response = json.loads(result.body.decode())
        assert "items" in response.get("error", "").lower()

    def test_submit_batch_missing_body_returns_error(self):
        """Should return error when JSON body is missing."""
        mixin = _make_batch_mixin()
        mixin.read_json_body = MagicMock(return_value=None)

        result = mixin._submit_batch(MagicMock())

        assert result.status_code == 400
        response = json.loads(result.body.decode())
        assert "Invalid or missing JSON body" in response.get("error", "")

    def test_submit_batch_exceeds_max_items(self):
        """Should return error when batch exceeds 1000 items."""
        mixin = _make_batch_mixin()
        items = [{"question": f"Question {i}"} for i in range(1001)]
        mixin.read_json_body = MagicMock(return_value={"items": items})

        result = mixin._submit_batch(MagicMock())

        assert result.status_code == 400
        response = json.loads(result.body.decode())
        assert "1000" in response.get("error", "")

    def test_submit_batch_validates_questions(self):
        """Should validate that each item has a question."""
        mixin = _make_batch_mixin()
        items = [
            {"question": "Valid question"},
            {"agents": "anthropic-api"},  # Missing question
        ]
        mixin.read_json_body = MagicMock(return_value={"items": items})

        result = mixin._submit_batch(MagicMock())

        assert result.status_code == 400
        response = json.loads(result.body.decode())
        assert "question is required" in response.get("error", "")

    def test_submit_batch_validates_question_length(self):
        """Should reject questions over 10,000 characters."""
        mixin = _make_batch_mixin()
        items = [{"question": "x" * 10001}]
        mixin.read_json_body = MagicMock(return_value={"items": items})

        result = mixin._submit_batch(MagicMock())

        assert result.status_code == 400
        response = json.loads(result.body.decode())
        assert "exceeds 10,000 characters" in response.get("error", "")


class TestBatchStatus:
    """Tests for batch status retrieval."""

    def test_get_batch_status_invalid_id_format(self):
        """Should reject invalid batch ID format."""
        from aragora.server.handlers.debates.batch import BatchOperationsMixin

        mixin = BatchOperationsMixin()

        # Invalid ID with path traversal
        result = mixin._get_batch_status("batch/../../../etc/passwd")

        assert result.status_code == 400

    def test_get_batch_status_not_found_or_no_queue(self):
        """Should return 404 or 503 when batch not found or queue not available."""
        from aragora.server.handlers.debates.batch import BatchOperationsMixin

        mixin = BatchOperationsMixin()

        # Use a valid-looking ID - will return 503 if queue not initialized
        result = mixin._get_batch_status("batch_abc123xyz")

        # Should either be 404 (not found) or 503 (queue not init)
        assert result.status_code in (404, 503)

    def test_get_batch_status_queue_not_initialized(self):
        """Should return 503 when queue not initialized."""
        from aragora.server.handlers.debates.batch import BatchOperationsMixin

        mixin = BatchOperationsMixin()

        # With no queue, should return 503
        with patch("aragora.server.debate_queue.get_debate_queue_sync", return_value=None):
            result = mixin._get_batch_status("batch_valid123")

            assert result.status_code == 503


class TestListBatches:
    """Tests for batch listing."""

    def test_list_batches_returns_empty_when_queue_not_initialized(self):
        """Should return empty list when queue not initialized."""
        from aragora.server.handlers.debates.batch import BatchOperationsMixin

        mixin = BatchOperationsMixin()

        with patch("aragora.server.debate_queue.get_debate_queue_sync", return_value=None):
            result = mixin._list_batches(limit=10)

            assert result.status_code == 200
            response = json.loads(result.body.decode())
            assert response["batches"] == []
            assert response["count"] == 0

    def test_list_batches_invalid_status_filter(self):
        """Should return error for invalid status filter."""
        from aragora.server.handlers.debates.batch import BatchOperationsMixin

        mixin = BatchOperationsMixin()

        with patch("aragora.server.debate_queue.get_debate_queue_sync", return_value=MagicMock()):
            result = mixin._list_batches(limit=10, status_filter="invalid_status")

            assert result.status_code == 400


class TestQueueStatus:
    """Tests for queue status retrieval."""

    def test_get_queue_status_not_initialized(self):
        """Should indicate when queue is not initialized."""
        from aragora.server.handlers.debates.batch import BatchOperationsMixin

        mixin = BatchOperationsMixin()

        with patch("aragora.server.debate_queue.get_debate_queue_sync", return_value=None):
            result = mixin._get_queue_status()

            assert result.status_code == 200
            response = json.loads(result.body.decode())
            assert response["active"] is False


class TestDebateExecutor:
    """Tests for debate executor creation."""

    def test_create_debate_executor_returns_callable(self):
        """Should return a callable executor."""
        from aragora.server.handlers.debates.batch import BatchOperationsMixin

        mixin = BatchOperationsMixin()
        executor = mixin._create_debate_executor()

        assert callable(executor)


class TestMixinIntegration:
    """Tests for mixin integration with DebatesHandler."""

    def test_batch_methods_available_on_handler(self):
        """Should make batch methods available on handler."""
        from aragora.server.handlers.debates import DebatesHandler

        handler = DebatesHandler({})

        # Check batch methods
        assert hasattr(handler, "_submit_batch")
        assert hasattr(handler, "_get_batch_status")
        assert hasattr(handler, "_list_batches")
        assert hasattr(handler, "_get_queue_status")
        assert hasattr(handler, "_create_debate_executor")
