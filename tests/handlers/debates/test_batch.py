"""Tests for batch debate operations handler (batch.py).

Tests the BatchOperationsMixin covering:
- POST /api/v1/debates/batch (_submit_batch)
- GET /api/v1/debates/batch/{batch_id}/status (_get_batch_status)
- GET /api/v1/debates/batch (_list_batches)
- GET /api/v1/debates/queue/status (_get_queue_status)

Covers: success paths, error handling, edge cases, validation,
quota checks, spam filtering, webhook validation, and queue operations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def bypass_rate_limiters(monkeypatch):
    """Bypass all rate limiter decorators to avoid 429s in unit tests."""
    try:
        from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

        reset_rate_limiters()
    except ImportError:
        pass

    # Patch user rate limiter to always allow
    try:
        from aragora.server.middleware.rate_limit.limiter import RateLimitResult
        from aragora.server.middleware.rate_limit import decorators as rl_decorators

        def _always_allowed(*args, **kwargs):
            return RateLimitResult(allowed=True, remaining=99, limit=100, key="test")

        monkeypatch.setattr(rl_decorators, "check_user_rate_limit", _always_allowed)
    except (ImportError, AttributeError):
        pass

    yield

    try:
        from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

        reset_rate_limiters()
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def org_user(monkeypatch):
    """Batch submission requires an authenticated user with an org."""
    monkeypatch.setattr(
        "aragora.billing.jwt_auth.extract_user_from_request",
        lambda handler, user_store=None: _MockUserCtx(),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict[str, Any]:
    """Extract JSON body from a HandlerResult."""
    if result is None:
        return {}
    raw = result.body
    if isinstance(raw, bytes):
        return json.loads(raw.decode())
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _status(result) -> int:
    """Extract status code from a HandlerResult."""
    if result is None:
        return 0
    return result.status_code


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


@dataclass
class _MockValidationResult:
    """Mock ValidationResult for schema validation."""

    is_valid: bool
    error: str | None = None
    data: dict | None = None


@dataclass
class _MockBatchItem:
    """Mock BatchItem for testing."""

    question: str
    agents: str = "anthropic-api,openai-api,gemini"
    rounds: int = 3
    consensus: str = "majority"
    priority: int = 0
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> _MockBatchItem:
        question = data.get("question", "").strip()
        if not question:
            raise ValueError("question is required")
        return cls(question=question)


@dataclass
class _MockUserCtx:
    """Mock user context for quota checking."""

    is_authenticated: bool = True
    user_id: str = "test-user-001"
    org_id: str | None = "test-org-001"
    email: str = "test@example.com"


@dataclass
class _MockOrg:
    """Mock organization for quota checking."""

    is_at_limit: bool = False
    debates_used_this_month: int = 5
    tier: Any = None
    limits: Any = None

    def __post_init__(self):
        if self.tier is None:
            self.tier = MagicMock(value="pro")
        if self.limits is None:
            self.limits = MagicMock(debates_per_month=100)


def _make_handler(
    ctx_extra: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
):
    """Build a minimal handler instance with BatchOperationsMixin."""
    from aragora.server.handlers.base import BaseHandler
    from aragora.server.handlers.debates.batch import BatchOperationsMixin

    ctx: dict[str, Any] = {}
    if ctx_extra:
        ctx.update(ctx_extra)

    class _Handler(BatchOperationsMixin, BaseHandler):
        def __init__(self):
            self.ctx = ctx
            self._json_body = json_body

        def read_json_body(self, handler, max_size=None):
            return self._json_body

        def _create_debate_executor(self):
            return MagicMock()

    return _Handler()


def _mock_http_handler(command="POST"):
    """Create a mock HTTP handler object."""
    h = MagicMock()
    h.command = command
    h.user_store = None
    h.headers = {"Content-Length": "2"}
    h.rfile = MagicMock()
    h.rfile.read.return_value = b"{}"
    return h


# ---------------------------------------------------------------------------
# _submit_batch tests
# ---------------------------------------------------------------------------


class TestSubmitBatch:
    """Tests for POST /api/v1/debates/batch (_submit_batch)."""

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.handlers.debates.batch.rate_limit", lambda **kw: lambda fn: fn)
    def test_submit_batch_missing_body(self, mock_validate):
        """Null body returns 400."""
        h = _make_handler(json_body=None)
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        assert "Invalid or missing JSON body" in _body(result).get("error", "")

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    def test_submit_batch_schema_validation_failure(self, mock_validate):
        """Schema validation failure returns 400."""
        mock_validate.return_value = _MockValidationResult(
            is_valid=False, error="items is required"
        )
        h = _make_handler(json_body={"wrong_field": "value"})
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        assert "items is required" in _body(result).get("error", "")

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    def test_submit_batch_empty_items(self, mock_validate):
        """Empty items array returns 400."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        h = _make_handler(json_body={"items": []})
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        assert "cannot be empty" in _body(result).get("error", "")

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    def test_submit_batch_exceeds_max_items(self, mock_validate):
        """More than 1000 items returns 400."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        items = [{"question": f"q{i}"} for i in range(1001)]
        h = _make_handler(json_body={"items": items})
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        assert "1000" in _body(result).get("error", "")

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    def test_submit_batch_item_not_dict(self, mock_validate):
        """Non-dict items produce validation errors."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        h = _make_handler(json_body={"items": ["not a dict"]})
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        assert "must be an object" in _body(result).get("error", "")

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    def test_submit_batch_item_missing_question(self, mock_validate):
        """Items missing question produce validation errors."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        h = _make_handler(json_body={"items": [{"agents": "openai-api"}]})
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        assert "question is required" in _body(result).get("error", "")

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    def test_submit_batch_question_too_long(self, mock_validate):
        """Question exceeding 10,000 chars returns error."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        h = _make_handler(json_body={"items": [{"question": "x" * 10001}]})
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        assert "10,000" in _body(result).get("error", "")

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    def test_submit_batch_multiple_validation_errors(self, mock_validate):
        """Multiple invalid items are reported (up to 5)."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        items = [
            {"agents": "openai"},  # missing question
            {"question": ""},  # empty question
            "not_a_dict",  # not a dict
            {"question": "x" * 10001},  # too long
            {"agents": "test"},  # missing question
            {"question": ""},  # 6th error
        ]
        h = _make_handler(json_body={"items": items})
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        body = _body(result)
        # Should report first 5 errors and indicate more
        assert "and 1 more" in body.get("error", "")

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    def test_submit_batch_exactly_5_errors(self, mock_validate):
        """Exactly 5 errors shows all without 'and X more'."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        items = [
            {"agents": "openai"},
            {"question": ""},
            "not_a_dict",
            {"question": "x" * 10001},
            {"agents": "test"},
        ]
        h = _make_handler(json_body={"items": items})
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        body = _body(result)
        assert (
            "and" not in body.get("error", "").split("more")[0]
            if "more" in body.get("error", "")
            else True
        )

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    @patch("aragora.server.debate_queue.get_debate_queue")
    @patch("aragora.server.http_utils.run_async")
    def test_submit_batch_success(
        self, mock_run_async, mock_get_queue, mock_extract_user, mock_from_dict, mock_validate
    ):
        """Successful batch submission returns batch_id and items_queued."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_item = MagicMock()
        mock_from_dict.return_value = mock_item
        mock_extract_user.return_value = _MockUserCtx()
        mock_run_async.return_value = "batch_abc123"

        h = _make_handler(
            json_body={
                "items": [
                    {"question": "What is AI?"},
                    {"question": "What is ML?"},
                ]
            }
        )
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["batch_id"] == "batch_abc123"
        assert body["items_queued"] == 2
        assert "status_url" in body

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    @patch("aragora.server.debate_queue.get_debate_queue")
    @patch("aragora.server.http_utils.run_async")
    def test_submit_batch_status_url_format(
        self, mock_run_async, mock_get_queue, mock_extract_user, mock_from_dict, mock_validate
    ):
        """Status URL follows expected format."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()
        mock_extract_user.return_value = _MockUserCtx()
        mock_run_async.return_value = "batch_xyz789"

        h = _make_handler(json_body={"items": [{"question": "Test?"}]})
        result = h._submit_batch(_mock_http_handler())
        body = _body(result)
        assert body["status_url"] == "/api/v1/debates/batch/batch_xyz789/status"

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    def test_submit_batch_queue_error(self, mock_extract_user, mock_from_dict, mock_validate):
        """Queue submission failure returns 500."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()
        mock_extract_user.return_value = _MockUserCtx()

        with patch(
            "aragora.server.http_utils.run_async",
            side_effect=RuntimeError("Queue unavailable"),
        ):
            h = _make_handler(json_body={"items": [{"question": "Test?"}]})
            result = h._submit_batch(_mock_http_handler())
            assert _status(result) == 500

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    def test_submit_batch_batch_item_from_dict_error(
        self, mock_extract_user, mock_from_dict, mock_validate
    ):
        """BatchItem.from_dict raising ValueError adds validation error."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.side_effect = ValueError("bad consensus")
        mock_extract_user.return_value = _MockUserCtx()

        h = _make_handler(json_body={"items": [{"question": "Test question?"}]})
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        assert "validation failed" in _body(result).get("error", "")

    # -----------------------------------------------------------------------
    # Webhook validation
    # -----------------------------------------------------------------------

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    @patch("aragora.server.debate_queue.validate_webhook_url")
    def test_submit_batch_invalid_webhook_url(
        self, mock_validate_url, mock_extract_user, mock_from_dict, mock_validate
    ):
        """Invalid webhook URL returns 400."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()
        mock_extract_user.return_value = _MockUserCtx()
        mock_validate_url.return_value = (False, "webhook_url must use http or https")

        h = _make_handler(
            json_body={
                "items": [{"question": "Test?"}],
                "webhook_url": "ftp://bad.url",
            }
        )
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        assert "webhook_url" in _body(result).get("error", "")

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    @patch("aragora.server.debate_queue.validate_webhook_url")
    @patch("aragora.server.debate_queue.sanitize_webhook_headers")
    def test_submit_batch_invalid_webhook_headers(
        self,
        mock_sanitize_headers,
        mock_validate_url,
        mock_extract_user,
        mock_from_dict,
        mock_validate,
    ):
        """Invalid webhook headers return 400."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()
        mock_extract_user.return_value = _MockUserCtx()
        mock_validate_url.return_value = (True, "")
        mock_sanitize_headers.return_value = ({}, "webhook_headers contains invalid characters")

        h = _make_handler(
            json_body={
                "items": [{"question": "Test?"}],
                "webhook_url": "https://example.com/hook",
                "webhook_headers": {"X-Bad": "val\r\n"},
            }
        )
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        assert "webhook_headers" in _body(result).get("error", "")

    # -----------------------------------------------------------------------
    # max_parallel validation
    # -----------------------------------------------------------------------

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    def test_submit_batch_invalid_max_parallel(
        self, mock_extract_user, mock_from_dict, mock_validate
    ):
        """Non-integer max_parallel returns 400."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()
        mock_extract_user.return_value = _MockUserCtx()

        h = _make_handler(
            json_body={
                "items": [{"question": "Test?"}],
                "max_parallel": "not_a_number",
            }
        )
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 400
        assert "max_parallel" in _body(result).get("error", "")

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    @patch("aragora.server.debate_queue.get_debate_queue")
    @patch("aragora.server.http_utils.run_async")
    def test_submit_batch_max_parallel_clamped(
        self, mock_run_async, mock_get_queue, mock_extract_user, mock_from_dict, mock_validate
    ):
        """max_parallel is clamped to [1, MAX_CONCURRENT_DEBATES]."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()
        mock_extract_user.return_value = _MockUserCtx()
        mock_run_async.return_value = "batch_123"

        h = _make_handler(
            json_body={
                "items": [{"question": "Test?"}],
                "max_parallel": 0,  # Should be clamped to 1
            }
        )
        result = h._submit_batch(_mock_http_handler())
        # Should succeed (clamped, not rejected)
        assert _status(result) == 200

    # -----------------------------------------------------------------------
    # Quota checks
    # -----------------------------------------------------------------------

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    def test_submit_batch_quota_exceeded(self, mock_extract_user, mock_from_dict, mock_validate):
        """Org at debate limit returns 402."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()

        mock_user = _MockUserCtx(is_authenticated=True, org_id="org-1")
        mock_extract_user.return_value = mock_user

        mock_org = _MockOrg(is_at_limit=True)

        mock_handler = _mock_http_handler()
        mock_user_store = MagicMock()
        mock_user_store.get_organization_by_id.return_value = mock_org
        mock_handler.user_store = mock_user_store

        h = _make_handler(json_body={"items": [{"question": "Test?"}]})
        result = h._submit_batch(mock_handler)
        assert _status(result) == 402
        body = _body(result)
        assert body["error"] == "quota_exceeded"
        assert body["code"] == "QUOTA_EXCEEDED"
        assert "upgrade_url" in body

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    def test_submit_batch_quota_insufficient(
        self, mock_extract_user, mock_from_dict, mock_validate
    ):
        """Batch exceeding remaining quota returns 402."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()

        mock_user = _MockUserCtx(is_authenticated=True, org_id="org-1")
        mock_extract_user.return_value = mock_user

        mock_org = _MockOrg(is_at_limit=False, debates_used_this_month=98)
        mock_org.limits.debates_per_month = 100

        mock_handler = _mock_http_handler()
        mock_user_store = MagicMock()
        mock_user_store.get_organization_by_id.return_value = mock_org
        mock_handler.user_store = mock_user_store

        # 3 items but only 2 remaining
        h = _make_handler(
            json_body={
                "items": [
                    {"question": "Q1?"},
                    {"question": "Q2?"},
                    {"question": "Q3?"},
                ]
            }
        )
        result = h._submit_batch(mock_handler)
        assert _status(result) == 402
        body = _body(result)
        assert body["error"] == "quota_insufficient"
        assert body["code"] == "QUOTA_INSUFFICIENT"
        assert body["remaining"] == 2
        assert body["requested"] == 3

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    @patch("aragora.server.debate_queue.get_debate_queue")
    @patch("aragora.server.http_utils.run_async")
    def test_submit_batch_no_user_store_skips_quota(
        self, mock_run_async, mock_get_queue, mock_extract_user, mock_from_dict, mock_validate
    ):
        """Without user_store, quota check is skipped."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()
        mock_extract_user.return_value = _MockUserCtx(is_authenticated=True, org_id="org-1")
        mock_run_async.return_value = "batch_abc"

        # Mock handler without user_store attribute
        mock_handler = _mock_http_handler()
        del mock_handler.user_store

        h = _make_handler(json_body={"items": [{"question": "Test?"}]})
        result = h._submit_batch(mock_handler)
        assert _status(result) == 200

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    @patch("aragora.server.debate_queue.get_debate_queue")
    @patch("aragora.server.http_utils.run_async")
    def test_submit_batch_unauthenticated_user_is_rejected(
        self, mock_run_async, mock_get_queue, mock_extract_user, mock_from_dict, mock_validate
    ):
        """Unauthenticated user gets 401 and nothing is queued."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()
        mock_extract_user.return_value = _MockUserCtx(is_authenticated=False, org_id=None)
        mock_run_async.return_value = "batch_abc"

        h = _make_handler(json_body={"items": [{"question": "Test?"}]})
        result = h._submit_batch(_mock_http_handler())
        assert _status(result) == 401
        mock_run_async.assert_not_called()

    # -----------------------------------------------------------------------
    # Usage increment
    # -----------------------------------------------------------------------

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    @patch("aragora.server.debate_queue.get_debate_queue")
    @patch("aragora.server.http_utils.run_async")
    def test_submit_batch_increments_usage(
        self, mock_run_async, mock_get_queue, mock_extract_user, mock_from_dict, mock_validate
    ):
        """Successful submission increments usage for the org."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()

        mock_user = _MockUserCtx(is_authenticated=True, org_id="org-1")
        mock_extract_user.return_value = mock_user

        mock_org = _MockOrg(is_at_limit=False, debates_used_this_month=5)
        mock_org.limits.debates_per_month = 100

        mock_handler = _mock_http_handler()
        mock_user_store = MagicMock()
        mock_user_store.get_organization_by_id.return_value = mock_org
        mock_handler.user_store = mock_user_store
        mock_run_async.return_value = "batch_inc123"

        h = _make_handler(json_body={"items": [{"question": "Q1?"}, {"question": "Q2?"}]})
        result = h._submit_batch(mock_handler)
        assert _status(result) == 200
        mock_user_store.increment_usage.assert_called_once_with("org-1", 2)

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    @patch("aragora.server.debate_queue.BatchItem.from_dict")
    @patch("aragora.billing.jwt_auth.extract_user_from_request")
    @patch("aragora.server.debate_queue.get_debate_queue")
    @patch("aragora.server.http_utils.run_async")
    def test_submit_batch_usage_increment_failure_does_not_block(
        self, mock_run_async, mock_get_queue, mock_extract_user, mock_from_dict, mock_validate
    ):
        """Usage increment failure logs warning but does not fail the request."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)
        mock_from_dict.return_value = MagicMock()

        mock_user = _MockUserCtx(is_authenticated=True, org_id="org-1")
        mock_extract_user.return_value = mock_user

        mock_org = _MockOrg(is_at_limit=False, debates_used_this_month=5)
        mock_org.limits.debates_per_month = 100

        mock_handler = _mock_http_handler()
        mock_user_store = MagicMock()
        mock_user_store.get_organization_by_id.return_value = mock_org
        mock_user_store.increment_usage.side_effect = RuntimeError("DB error")
        mock_handler.user_store = mock_user_store
        mock_run_async.return_value = "batch_ok"

        h = _make_handler(json_body={"items": [{"question": "Q?"}]})
        result = h._submit_batch(mock_handler)
        # Should still succeed despite increment failure
        assert _status(result) == 200

    # -----------------------------------------------------------------------
    # Spam filtering
    # -----------------------------------------------------------------------

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    def test_submit_batch_spam_blocked(self, mock_validate):
        """Items blocked by spam filter are reported as errors."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)

        mock_spam_result = MagicMock()
        mock_spam_result.should_block = True
        mock_spam_result.confidence = 0.95

        mock_spam_mod = MagicMock()
        mock_spam_mod._initialized = True
        mock_spam_mod.enabled = True
        mock_spam_mod.check_debate_input = AsyncMock(return_value=mock_spam_result)

        with (
            patch("aragora.moderation.get_spam_moderation", return_value=mock_spam_mod),
            patch("aragora.server.http_utils.run_async", side_effect=lambda coro: mock_spam_result),
        ):
            h = _make_handler(json_body={"items": [{"question": "Buy cheap stuff!"}]})
            result = h._submit_batch(_mock_http_handler())
            assert _status(result) == 400
            assert "spam filter" in _body(result).get("error", "")

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    def test_submit_batch_spam_check_error_fails_open(self, mock_validate):
        """Spam check exception allows item to proceed (fail-open)."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)

        mock_spam_mod = MagicMock()
        mock_spam_mod._initialized = True
        mock_spam_mod.enabled = True
        # check_debate_input returns a coroutine that raises when awaited
        mock_spam_mod.check_debate_input = AsyncMock(side_effect=RuntimeError("Spam service down"))

        call_count = 0

        def smart_run_async(coro):
            """First call (spam check) raises, second (submit) returns batch_id.

            Note: spam_moderation._initialized=True so init run_async is skipped.
            """
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # spam check run_async - raise to trigger fail-open
                raise RuntimeError("Spam service down")
            else:
                # queue submit run_async
                return "batch_ok"

        with (
            patch("aragora.moderation.get_spam_moderation", return_value=mock_spam_mod),
            patch("aragora.server.debate_queue.BatchItem.from_dict", return_value=MagicMock()),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=_MockUserCtx(),
            ),
            patch("aragora.server.http_utils.run_async", side_effect=smart_run_async),
        ):
            h = _make_handler(json_body={"items": [{"question": "Valid question?"}]})
            result = h._submit_batch(_mock_http_handler())
            # The spam error is caught, item proceeds, batch submits
            assert _status(result) == 200

    @patch("aragora.server.handlers.debates.batch.validate_against_schema")
    def test_submit_batch_spam_not_available(self, mock_validate):
        """Spam moderation import failure is handled gracefully."""
        mock_validate.return_value = _MockValidationResult(is_valid=True)

        with (
            patch("aragora.server.debate_queue.BatchItem.from_dict", return_value=MagicMock()),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=_MockUserCtx(),
            ),
            patch("aragora.server.http_utils.run_async", return_value="batch_ok"),
        ):
            h = _make_handler(json_body={"items": [{"question": "Good question?"}]})
            # Spam moderation import fails silently inside the method
            result = h._submit_batch(_mock_http_handler())
            assert _status(result) == 200


# ---------------------------------------------------------------------------
# _get_batch_status tests
# ---------------------------------------------------------------------------


class TestGetBatchStatus:
    """Tests for GET /api/v1/debates/batch/{batch_id}/status (_get_batch_status)."""

    def test_get_batch_status_success(self):
        """Valid batch_id returns full batch status."""
        mock_queue = MagicMock()
        mock_queue.get_batch_status.return_value = {
            "batch_id": "batch_abc123",
            "status": "processing",
            "total_items": 5,
            "completed": 2,
            "failed": 0,
        }

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = _make_handler()
            result = h._get_batch_status("batch_abc123")
            assert _status(result) == 200
            body = _body(result)
            assert body["batch_id"] == "batch_abc123"
            assert body["status"] == "processing"

    def test_get_batch_status_not_found(self):
        """Unknown batch_id returns 404."""
        mock_queue = MagicMock()
        mock_queue.get_batch_status.return_value = None

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = _make_handler()
            result = h._get_batch_status("batch_unknown")
            assert _status(result) == 404
            assert "not found" in _body(result).get("error", "").lower()

    def test_get_batch_status_queue_not_initialized(self):
        """Queue not initialized returns 503."""
        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=None,
        ):
            h = _make_handler()
            result = h._get_batch_status("batch_abc123")
            assert _status(result) == 503
            assert "not initialized" in _body(result).get("error", "").lower()

    def test_get_batch_status_invalid_batch_id(self):
        """Invalid batch ID format returns 400."""
        h = _make_handler()
        # Path traversal attempt
        result = h._get_batch_status("../../../etc/passwd")
        assert _status(result) == 400

    def test_get_batch_status_empty_batch_id(self):
        """Empty batch ID returns 400."""
        h = _make_handler()
        result = h._get_batch_status("")
        assert _status(result) == 400

    def test_get_batch_status_special_characters(self):
        """Batch ID with special chars returns 400."""
        h = _make_handler()
        result = h._get_batch_status("batch<script>alert(1)</script>")
        assert _status(result) == 400


# ---------------------------------------------------------------------------
# _list_batches tests
# ---------------------------------------------------------------------------


class TestListBatches:
    """Tests for GET /api/v1/debates/batch (_list_batches)."""

    def test_list_batches_success(self):
        """Returns list of batch summaries."""
        mock_queue = MagicMock()
        mock_queue.list_batches.return_value = [
            {"batch_id": "batch_1", "status": "completed", "total_items": 3},
            {"batch_id": "batch_2", "status": "processing", "total_items": 5},
        ]

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = _make_handler()
            result = h._list_batches(limit=50)
            assert _status(result) == 200
            body = _body(result)
            assert body["count"] == 2
            assert len(body["batches"]) == 2

    def test_list_batches_empty(self):
        """No batches returns empty list."""
        mock_queue = MagicMock()
        mock_queue.list_batches.return_value = []

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = _make_handler()
            result = h._list_batches(limit=50)
            assert _status(result) == 200
            body = _body(result)
            assert body["count"] == 0
            assert body["batches"] == []

    def test_list_batches_queue_not_initialized(self):
        """Queue not initialized returns empty list (not error)."""
        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=None,
        ):
            h = _make_handler()
            result = h._list_batches(limit=50)
            assert _status(result) == 200
            body = _body(result)
            assert body["count"] == 0
            assert body["batches"] == []

    def test_list_batches_with_status_filter(self):
        """Status filter is passed through to queue."""
        mock_queue = MagicMock()
        mock_queue.list_batches.return_value = [
            {"batch_id": "batch_1", "status": "completed"},
        ]

        with (
            patch(
                "aragora.server.debate_queue.get_debate_queue_sync",
                return_value=mock_queue,
            ),
            patch("aragora.server.debate_queue.BatchStatus") as mock_status_cls,
        ):
            mock_status_cls.return_value = "completed"
            mock_status_cls.__iter__ = MagicMock(return_value=iter([]))

            h = _make_handler()
            result = h._list_batches(limit=50, status_filter="completed")
            assert _status(result) == 200

    def test_list_batches_invalid_status_filter(self):
        """Invalid status filter returns 400."""
        mock_queue = MagicMock()

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = _make_handler()
            result = h._list_batches(limit=50, status_filter="invalid_status")
            assert _status(result) == 400
            assert "Invalid status" in _body(result).get("error", "")

    def test_list_batches_with_limit(self):
        """Limit parameter is passed through to queue."""
        mock_queue = MagicMock()
        mock_queue.list_batches.return_value = []

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = _make_handler()
            h._list_batches(limit=10)
            mock_queue.list_batches.assert_called_once_with(status=None, limit=10)

    def test_list_batches_no_status_filter(self):
        """No status filter passes None to queue."""
        mock_queue = MagicMock()
        mock_queue.list_batches.return_value = []

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = _make_handler()
            h._list_batches(limit=50, status_filter=None)
            mock_queue.list_batches.assert_called_once_with(status=None, limit=50)


# ---------------------------------------------------------------------------
# _get_queue_status tests
# ---------------------------------------------------------------------------


class TestGetQueueStatus:
    """Tests for GET /api/v1/debates/queue/status (_get_queue_status)."""

    def test_get_queue_status_active(self):
        """Active queue returns status with counts."""
        mock_queue = MagicMock()
        mock_queue.max_concurrent = 5
        mock_queue._active_count = 2
        mock_queue.list_batches.return_value = [
            {"status": "processing"},
            {"status": "processing"},
            {"status": "completed"},
            {"status": "completed"},
            {"status": "pending"},
        ]

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = _make_handler()
            result = h._get_queue_status()
            assert _status(result) == 200
            body = _body(result)
            assert body["active"] is True
            assert body["max_concurrent"] == 5
            assert body["active_count"] == 2
            assert body["total_batches"] == 5
            assert body["status_counts"]["processing"] == 2
            assert body["status_counts"]["completed"] == 2
            assert body["status_counts"]["pending"] == 1

    def test_get_queue_status_not_initialized(self):
        """Queue not initialized returns inactive status."""
        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=None,
        ):
            h = _make_handler()
            result = h._get_queue_status()
            assert _status(result) == 200
            body = _body(result)
            assert body["active"] is False
            assert "not initialized" in body.get("message", "").lower()

    def test_get_queue_status_empty_queue(self):
        """Empty queue returns zero counts."""
        mock_queue = MagicMock()
        mock_queue.max_concurrent = 3
        mock_queue._active_count = 0
        mock_queue.list_batches.return_value = []

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = _make_handler()
            result = h._get_queue_status()
            assert _status(result) == 200
            body = _body(result)
            assert body["active"] is True
            assert body["total_batches"] == 0
            assert body["status_counts"] == {}

    def test_get_queue_status_unknown_status_counted(self):
        """Batches with unexpected status values are still counted."""
        mock_queue = MagicMock()
        mock_queue.max_concurrent = 3
        mock_queue._active_count = 0
        mock_queue.list_batches.return_value = [
            {"status": "unknown_status"},
            {},  # No status key defaults to "unknown"
        ]

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = _make_handler()
            result = h._get_queue_status()
            assert _status(result) == 200
            body = _body(result)
            assert body["total_batches"] == 2


# ---------------------------------------------------------------------------
# Routing integration tests (via DebatesHandler.handle and handle_post)
# ---------------------------------------------------------------------------


class TestBatchRouting:
    """Tests for batch endpoint routing through DebatesHandler."""

    def _make_debates_handler(self, json_body=None):
        """Build a DebatesHandler with minimal dependencies."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        class _TestHandler(DebatesHandler):
            def __init__(self):
                self.ctx = {}
                self._json_body = json_body

            def read_json_body(self, handler, max_size=None):
                return self._json_body

            def get_current_user(self, handler):
                mock_user = MagicMock()
                mock_user.org_id = None
                return mock_user

            def get_storage(self):
                return None

        return _TestHandler()

    def test_get_queue_status_route(self):
        """GET /api/v1/debates/queue/status routes correctly."""
        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=None,
        ):
            h = self._make_debates_handler()
            result = h.handle("/api/v1/debates/queue/status", {}, _mock_http_handler("GET"))
            assert _status(result) == 200
            body = _body(result)
            assert body["active"] is False

    def test_get_batch_status_route(self):
        """GET /api/v1/debates/batch/{id}/status routes correctly."""
        mock_queue = MagicMock()
        mock_queue.get_batch_status.return_value = {
            "batch_id": "batch_abc",
            "status": "completed",
        }

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = self._make_debates_handler()
            result = h.handle(
                "/api/v1/debates/batch/batch_abc/status", {}, _mock_http_handler("GET")
            )
            assert _status(result) == 200
            body = _body(result)
            assert body["batch_id"] == "batch_abc"

    def test_list_batches_route(self):
        """GET /api/v1/debates/batch routes correctly."""
        mock_queue = MagicMock()
        mock_queue.list_batches.return_value = []

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = self._make_debates_handler()
            result = h.handle("/api/v1/debates/batch", {}, _mock_http_handler("GET"))
            assert _status(result) == 200
            body = _body(result)
            assert body["count"] == 0

    def test_list_batches_route_with_trailing_slash(self):
        """GET /api/v1/debates/batch/ routes correctly."""
        mock_queue = MagicMock()
        mock_queue.list_batches.return_value = []

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = self._make_debates_handler()
            result = h.handle("/api/v1/debates/batch/", {}, _mock_http_handler("GET"))
            assert _status(result) == 200

    def test_list_batches_with_status_param(self):
        """GET /api/v1/debates/batch?status=completed routes with filter."""
        mock_queue = MagicMock()
        mock_queue.list_batches.return_value = []

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = self._make_debates_handler()
            result = h.handle(
                "/api/v1/debates/batch",
                {"status": "completed"},
                _mock_http_handler("GET"),
            )
            assert _status(result) == 200

    def test_list_batches_with_limit_param(self):
        """GET /api/v1/debates/batch?limit=10 respects limit."""
        mock_queue = MagicMock()
        mock_queue.list_batches.return_value = []

        with patch(
            "aragora.server.debate_queue.get_debate_queue_sync",
            return_value=mock_queue,
        ):
            h = self._make_debates_handler()
            h.handle(
                "/api/v1/debates/batch",
                {"limit": "10"},
                _mock_http_handler("GET"),
            )
            mock_queue.list_batches.assert_called_once()

    def test_post_batch_route(self):
        """POST /api/v1/debates/batch routes to _submit_batch."""
        h = self._make_debates_handler(json_body=None)
        mock_handler = _mock_http_handler("POST")

        # _submit_batch should be called and return error (no body)
        result = h.handle_post("/api/v1/debates/batch", {}, mock_handler)
        assert _status(result) == 400

    def test_post_batch_route_trailing_slash(self):
        """POST /api/v1/debates/batch/ routes to _submit_batch."""
        h = self._make_debates_handler(json_body=None)
        mock_handler = _mock_http_handler("POST")
        result = h.handle_post("/api/v1/debates/batch/", {}, mock_handler)
        assert _status(result) == 400

    def test_post_batch_route_unversioned(self):
        """POST /api/debates/batch routes to _submit_batch."""
        h = self._make_debates_handler(json_body=None)
        mock_handler = _mock_http_handler("POST")
        result = h.handle_post("/api/debates/batch", {}, mock_handler)
        assert _status(result) == 400


# ---------------------------------------------------------------------------
# _create_debate_executor tests
# ---------------------------------------------------------------------------


class TestCreateDebateExecutor:
    """Tests for _create_debate_executor method."""

    def _make_real_handler(self):
        """Build a handler with the REAL _create_debate_executor (not mocked)."""
        from aragora.server.handlers.base import BaseHandler
        from aragora.server.handlers.debates.batch import BatchOperationsMixin

        class _Handler(BatchOperationsMixin, BaseHandler):
            def __init__(self):
                self.ctx = {}

            def read_json_body(self, handler, max_size=None):
                return None

        return _Handler()

    def test_returns_callable(self):
        """_create_debate_executor returns a callable."""
        h = self._make_real_handler()
        executor = h._create_debate_executor()
        assert callable(executor)

    @patch("aragora.server.debate_controller.DebateController")
    @patch("aragora.server.debate_controller.DebateRequest")
    @patch("aragora.server.debate_factory.DebateFactory")
    @patch("aragora.server.stream.SyncEventEmitter")
    def test_executor_success(
        self, mock_emitter_cls, mock_factory_cls, mock_request_cls, mock_controller_cls
    ):
        """Executor returns success dict when debate starts."""
        import asyncio

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.debate_id = "debate_123"
        mock_controller = MagicMock()
        mock_controller.start_debate.return_value = mock_response
        mock_controller_cls.return_value = mock_controller

        h = self._make_real_handler()
        executor = h._create_debate_executor()

        mock_item = MagicMock()
        mock_item.question = "Test question?"
        mock_item.agents = "anthropic-api"
        mock_item.rounds = 3
        mock_item.consensus = "majority"

        result = asyncio.run(executor(mock_item))
        assert result["success"] is True
        assert result["debate_id"] == "debate_123"

    @patch("aragora.server.debate_controller.DebateController")
    @patch("aragora.server.debate_controller.DebateRequest")
    @patch("aragora.server.debate_factory.DebateFactory")
    @patch("aragora.server.stream.SyncEventEmitter")
    def test_executor_failure_raises(
        self, mock_emitter_cls, mock_factory_cls, mock_request_cls, mock_controller_cls
    ):
        """Executor raises DebateStartError when debate fails."""
        import asyncio

        from aragora.exceptions import DebateStartError

        mock_response = MagicMock()
        mock_response.success = False
        mock_response.debate_id = "debate_fail"
        mock_response.error = "Agent timeout"
        mock_controller = MagicMock()
        mock_controller.start_debate.return_value = mock_response
        mock_controller_cls.return_value = mock_controller

        h = self._make_real_handler()
        executor = h._create_debate_executor()

        mock_item = MagicMock()
        mock_item.question = "Test?"
        mock_item.agents = "openai-api"
        mock_item.rounds = 3
        mock_item.consensus = "majority"

        with pytest.raises(DebateStartError):
            asyncio.run(executor(mock_item))
