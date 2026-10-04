"""Tests for debate creation and lifecycle operations handler (create.py).

Tests the CreateOperationsMixin covering:
- POST /api/v1/debates (_create_debate)
- POST /api/v1/debates/{id}/cancel (_cancel_debate)
- POST /api/v1/debate-this (_debate_this)
- Spam content checking (_check_spam_content)
- Direct debate creation (_create_debate_direct)

Covers: success paths, error handling, edge cases, rate limiting,
schema validation, spam filtering, cancellation states, and spectate URLs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.auth.context import UserAuthContext
from aragora.tenancy.record_scope import OrgScope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def bypass_rate_limiters(monkeypatch):
    """Bypass all rate limiter decorators to avoid 429s in unit tests.

    Patches both the registry-based limiters and the user rate limiter
    so that decorated methods execute without being throttled.
    """
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


_ORG_SCOPE = OrgScope(org_id="test-org-001", user_id="test-user-001", role="admin")


@pytest.fixture(autouse=True)
def org_user(monkeypatch):
    """Debate creation requires an authenticated user with an org."""
    user = UserAuthContext(authenticated=True, user_id="test-user-001", org_id="test-org-001")
    monkeypatch.setattr(
        "aragora.billing.jwt_auth.extract_user_from_request",
        lambda handler, user_store=None: user,
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


def _mock_http_handler(command="POST"):
    """Create a mock HTTP handler object."""
    h = MagicMock()
    h.command = command
    h.headers = {"Content-Length": "2"}
    h.rfile = MagicMock()
    h.rfile.read.return_value = b"{}"
    h.stream_emitter = MagicMock()
    return h


@dataclass
class _MockDebateResponse:
    """Mock DebateResponse from debate_controller."""

    success: bool
    debate_id: str | None = None
    status: str | None = None
    task: str | None = None
    error: str | None = None
    status_code: int = 200

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"success": self.success}
        if self.debate_id:
            result["debate_id"] = self.debate_id
        if self.status:
            result["status"] = self.status
        if self.task:
            result["task"] = self.task
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class _MockValidationResult:
    """Mock ValidationResult for schema validation."""

    is_valid: bool
    error: str | None = None


def _make_handler(
    storage=None,
    ctx_extra: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    user=None,
    spam_result=None,
):
    """Build a minimal handler instance with CreateOperationsMixin.

    Args:
        storage: Mock debate storage
        ctx_extra: Extra context entries
        json_body: JSON body returned by read_json_body
        user: Mock user context
        spam_result: Value to return from _check_spam_content (None = pass)
    """
    from aragora.server.handlers.base import BaseHandler
    from aragora.server.handlers.debates.create import CreateOperationsMixin
    from aragora.server.debate_controller_mixin import DebateControllerMixin

    ctx: dict[str, Any] = {}
    if storage is not None:
        ctx["storage"] = storage
    if ctx_extra:
        ctx.update(ctx_extra)

    mock_user = user
    if mock_user is None:
        mock_user = MagicMock()
        mock_user.user_id = "test-user-001"
        mock_user.org_id = "test-org-001"
        mock_user.role = "admin"
        mock_user.plan = "pro"

    _spam_result = spam_result

    class _Handler(CreateOperationsMixin, DebateControllerMixin, BaseHandler):
        def __init__(self):
            self.ctx = ctx
            self._json_body = json_body
            self._mock_user = mock_user
            self._spam_result = _spam_result

        def get_storage(self):
            return ctx.get("storage")

        def read_json_body(self, handler, max_size=None):
            return self._json_body

        def get_current_user(self, handler):
            return self._mock_user

        def _check_spam_content(self, body):
            return self._spam_result

    return _Handler()


def _make_spam_handler():
    """Build a handler that uses the REAL _check_spam_content (not overridden)."""
    from aragora.server.handlers.base import BaseHandler
    from aragora.server.handlers.debates.create import CreateOperationsMixin

    class _H(CreateOperationsMixin, BaseHandler):
        def __init__(self):
            self.ctx = {}

        def get_storage(self):
            return None

        def read_json_body(self, handler, max_size=None):
            return None

        def get_current_user(self, handler):
            return None

    return _H()


# ---------------------------------------------------------------------------
# _create_debate tests
# ---------------------------------------------------------------------------


class TestCreateDebate:
    """Tests for POST /api/v1/debates (_create_debate)."""

    @patch("aragora.server.handlers.debates.create.emit_handler_event")
    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_success(self, mock_import, mock_get_schema, mock_emit):
        """Successful debate creation returns 200 with debate_id."""
        mock_get_schema.return_value = lambda body, schema: _MockValidationResult(is_valid=True)

        body = {"question": "Should we use microservices?", "rounds": 3}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        mock_response = _MockDebateResponse(
            success=True,
            debate_id="debate-123",
            status="starting",
            task="Should we use microservices?",
        )

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps(mock_response.to_dict()).encode(),
            )
            result = h._create_debate(handler)

        assert _status(result) == 200
        assert _body(result)["success"] is True
        assert _body(result)["debate_id"] == "debate-123"

    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_no_body(self, mock_import, mock_get_schema):
        """Missing JSON body returns 400."""
        h = _make_handler(json_body=None)
        handler = _mock_http_handler()
        result = h._create_debate(handler)
        assert _status(result) == 400
        assert "json body" in _body(result).get("error", "").lower()

    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_empty_body(self, mock_import, mock_get_schema):
        """Empty JSON body returns 400."""
        h = _make_handler(json_body={})
        handler = _mock_http_handler()
        result = h._create_debate(handler)
        assert _status(result) == 400
        assert "no content" in _body(result).get("error", "").lower()

    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_schema_validation_failure(self, mock_import, mock_get_schema):
        """Invalid request returns validation error."""
        mock_get_schema.return_value = lambda body, schema: _MockValidationResult(
            is_valid=False, error="question field is required"
        )

        body = {"invalid_field": "value"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()
        result = h._create_debate(handler)
        assert _status(result) == 422
        error_text = _body(result).get("error", "").lower()
        assert "question" in error_text or "invalid" in error_text

    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_spam_blocked(self, mock_import, mock_get_schema):
        """Spam content returns spam filter error."""
        mock_get_schema.return_value = lambda body, schema: _MockValidationResult(is_valid=True)

        from aragora.server.handlers.utils.responses import error_response

        spam_error = error_response("Content blocked by spam filter", 400)

        body = {"question": "Buy cheap drugs now!!!"}
        h = _make_handler(json_body=body, spam_result=spam_error)
        handler = _mock_http_handler()
        result = h._create_debate(handler)
        assert _status(result) == 400
        assert "spam" in _body(result).get("error", "").lower()

    @patch(
        "aragora.server.handlers.debates.create.importlib.import_module",
        side_effect=ImportError("no module"),
    )
    def test_create_debate_orchestrator_not_available(self, mock_import):
        """Missing debate orchestrator returns 500."""
        body = {"question": "Test question"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()
        result = h._create_debate(handler)
        assert _status(result) == 500
        assert "orchestrator" in _body(result).get("error", "").lower()

    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_no_stream_emitter(self, mock_import, mock_get_schema):
        """Missing stream_emitter returns 500."""
        body = {"question": "Test question"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()
        handler.stream_emitter = None
        result = h._create_debate(handler)
        assert _status(result) == 500
        assert "streaming" in _body(result).get("error", "").lower()

    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_rate_limit_exceeded(self, mock_import, mock_get_schema):
        """Rate limit check failure returns 429."""
        body = {"question": "Test question"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()
        handler._check_rate_limit = MagicMock(return_value=False)
        result = h._create_debate(handler)
        assert _status(result) == 429
        assert "rate limit" in _body(result).get("error", "").lower()

    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_rate_limit_error(self, mock_import, mock_get_schema):
        """Rate limit check exception returns 500."""
        body = {"question": "Test question"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()
        handler._check_rate_limit = MagicMock(side_effect=RuntimeError("rate limit broken"))
        result = h._create_debate(handler)
        assert _status(result) == 500

    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_tier_rate_limit_exceeded(self, mock_import, mock_get_schema):
        """Tier rate limit check failure returns 429."""
        body = {"question": "Test question"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()
        handler._check_rate_limit = MagicMock(return_value=True)
        handler._check_tier_rate_limit = MagicMock(return_value=False)
        result = h._create_debate(handler)
        assert _status(result) == 429
        assert "tier" in _body(result).get("error", "").lower()

    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_tier_rate_limit_error_proceeds(self, mock_import, mock_get_schema):
        """Tier rate limit exception is non-fatal -- debate creation continues."""
        mock_get_schema.return_value = lambda body, schema: _MockValidationResult(is_valid=True)

        body = {"question": "Should we refactor?", "rounds": 3}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()
        handler._check_tier_rate_limit = MagicMock(side_effect=ValueError("tier check broken"))

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True, "debate_id": "d-1"}).encode(),
            )
            result = h._create_debate(handler)

        assert _status(result) == 200

    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_create_debate_no_rate_limit_attr(self, mock_import, mock_get_schema):
        """Handler without _check_rate_limit attr skips rate limit check."""
        mock_get_schema.return_value = lambda body, schema: _MockValidationResult(is_valid=True)

        body = {"question": "Test question"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()
        # Ensure no rate limit attrs
        del handler._check_rate_limit
        del handler._check_tier_rate_limit

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True}).encode(),
            )
            result = h._create_debate(handler)

        assert _status(result) == 200


# ---------------------------------------------------------------------------
# _create_debate_direct tests
# ---------------------------------------------------------------------------


class TestCreateDebateDirect:
    """Tests for _create_debate_direct (direct controller path)."""

    @patch("aragora.server.handlers.debates.create.emit_handler_event")
    def test_direct_success(self, mock_emit):
        """Successful direct creation returns response from controller."""
        body = {"question": "Rate limiter design", "rounds": 5}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        mock_response = _MockDebateResponse(
            success=True,
            debate_id="debate-456",
            status="starting",
            task="Rate limiter design",
        )

        mock_controller = MagicMock()
        mock_controller.start_debate.return_value = mock_response
        handler._get_debate_controller = MagicMock(return_value=mock_controller)

        with patch("aragora.server.debate_controller.DebateRequest") as MockReq:
            MockReq.from_dict.return_value = MagicMock()
            result = h._create_debate_direct(handler, body, _ORG_SCOPE)

        assert _status(result) == 200
        body_data = _body(result)
        assert body_data["success"] is True
        assert body_data["debate_id"] == "debate-456"
        mock_emit.assert_called_once()

    @patch("aragora.server.handlers.debates.create.emit_handler_event")
    def test_direct_invalid_request(self, mock_emit):
        """ValueError from DebateRequest.from_dict returns 400."""
        body = {}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        with patch("aragora.server.debate_controller.DebateRequest") as MockReq:
            MockReq.from_dict.side_effect = ValueError("question required")
            result = h._create_debate_direct(handler, body, _ORG_SCOPE)

        assert _status(result) == 400
        assert "invalid" in _body(result).get("error", "").lower()
        mock_emit.assert_not_called()

    @patch("aragora.server.handlers.debates.create.emit_handler_event")
    def test_direct_controller_error(self, mock_emit):
        """Controller RuntimeError returns 500."""
        body = {"question": "Test"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        mock_controller = MagicMock()
        mock_controller.start_debate.side_effect = RuntimeError("orchestrator crash")
        handler._get_debate_controller = MagicMock(return_value=mock_controller)

        with patch("aragora.server.debate_controller.DebateRequest") as MockReq:
            MockReq.from_dict.return_value = MagicMock()
            result = h._create_debate_direct(handler, body, _ORG_SCOPE)

        assert _status(result) == 500
        mock_emit.assert_not_called()

    @patch("aragora.server.handlers.debates.create.emit_handler_event")
    def test_direct_controller_type_error(self, mock_emit):
        """Controller TypeError returns 500."""
        body = {"question": "Test"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        mock_controller = MagicMock()
        mock_controller.start_debate.side_effect = TypeError("bad arg")
        handler._get_debate_controller = MagicMock(return_value=mock_controller)

        with patch("aragora.server.debate_controller.DebateRequest") as MockReq:
            MockReq.from_dict.return_value = MagicMock()
            result = h._create_debate_direct(handler, body, _ORG_SCOPE)

        assert _status(result) == 500
        mock_emit.assert_not_called()

    @patch("aragora.server.handlers.debates.create.emit_handler_event")
    def test_direct_controller_attribute_error(self, mock_emit):
        """Controller AttributeError returns 500."""
        body = {"question": "Test"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        mock_controller = MagicMock()
        mock_controller.start_debate.side_effect = AttributeError("missing attr")
        handler._get_debate_controller = MagicMock(return_value=mock_controller)

        with patch("aragora.server.debate_controller.DebateRequest") as MockReq:
            MockReq.from_dict.return_value = MagicMock()
            result = h._create_debate_direct(handler, body, _ORG_SCOPE)

        assert _status(result) == 500
        mock_emit.assert_not_called()

    @patch("aragora.server.handlers.debates.create.emit_handler_event")
    def test_direct_emits_handler_event(self, mock_emit):
        """Successful direct creation emits handler event with debate_id."""
        body = {"question": "Test"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        mock_response = _MockDebateResponse(
            success=True,
            debate_id="debate-789",
            status="starting",
        )
        mock_controller = MagicMock()
        mock_controller.start_debate.return_value = mock_response
        handler._get_debate_controller = MagicMock(return_value=mock_controller)

        with patch("aragora.server.debate_controller.DebateRequest") as MockReq:
            MockReq.from_dict.return_value = MagicMock()
            h._create_debate_direct(handler, body, _ORG_SCOPE)

        mock_emit.assert_called_once_with("debate", "created", {"debate_id": "debate-789"})

    @patch("aragora.server.handlers.debates.create.emit_handler_event")
    def test_direct_response_status_code_passthrough(self, mock_emit):
        """Controller response status_code is used as HTTP status."""
        body = {"question": "Test"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        mock_response = _MockDebateResponse(
            success=True,
            debate_id="debate-202",
            status="queued",
            status_code=202,
        )
        mock_controller = MagicMock()
        mock_controller.start_debate.return_value = mock_response
        handler._get_debate_controller = MagicMock(return_value=mock_controller)

        with patch("aragora.server.debate_controller.DebateRequest") as MockReq:
            MockReq.from_dict.return_value = MagicMock()
            result = h._create_debate_direct(handler, body, _ORG_SCOPE)

        assert _status(result) == 202


# ---------------------------------------------------------------------------
# _cancel_debate tests
# ---------------------------------------------------------------------------


class TestCancelDebate:
    """Tests for POST /api/v1/debates/{id}/cancel (_cancel_debate)."""

    @patch("aragora.server.state.get_state_manager")
    @patch("aragora.server.debate_utils.update_debate_status")
    def test_cancel_running_debate(self, mock_update_status, mock_get_manager):
        """Cancelling a running debate returns success."""
        mock_state = MagicMock()
        mock_state.status = "running"
        mock_state.metadata = {}
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = mock_state
        mock_get_manager.return_value = mock_manager

        h = _make_handler()
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "debate-123")

        assert _status(result) == 200
        body_data = _body(result)
        assert body_data["success"] is True
        assert body_data["debate_id"] == "debate-123"
        assert body_data["status"] == "cancelled"
        mock_update_status.assert_called_once_with(
            "debate-123", "cancelled", error="Cancelled by user"
        )
        mock_manager.update_debate_status.assert_called_once_with("debate-123", status="cancelled")

    @patch("aragora.server.state.get_state_manager")
    @patch("aragora.server.debate_utils.update_debate_status")
    def test_cancel_starting_debate(self, mock_update_status, mock_get_manager):
        """Cancelling a starting debate returns success."""
        mock_state = MagicMock()
        mock_state.status = "starting"
        mock_state.metadata = {}
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = mock_state
        mock_get_manager.return_value = mock_manager

        h = _make_handler()
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "debate-start-1")

        assert _status(result) == 200
        assert _body(result)["success"] is True

    @patch("aragora.server.state.get_state_manager")
    def test_cancel_debate_not_found_no_storage(self, mock_get_manager):
        """Cancelling a non-existent debate without storage returns 404."""
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = None
        mock_get_manager.return_value = mock_manager

        h = _make_handler(storage=None)
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "nonexistent")

        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    @patch("aragora.server.state.get_state_manager")
    def test_cancel_already_completed(self, mock_get_manager):
        """Cancelling an already completed debate returns 400."""
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = None
        mock_get_manager.return_value = mock_manager

        storage = MagicMock()
        storage.get_debate.return_value = {"status": "completed"}

        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "debate-done")

        assert _status(result) == 400
        assert "already completed" in _body(result).get("error", "").lower()

    @patch("aragora.server.state.get_state_manager")
    def test_cancel_completed_shows_status(self, mock_get_manager):
        """Already-completed debate error message includes the current status."""
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = None
        mock_get_manager.return_value = mock_manager

        storage = MagicMock()
        storage.get_debate.return_value = {"status": "failed"}

        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "debate-fail-1")

        assert _status(result) == 400
        assert "failed" in _body(result).get("error", "").lower()

    @patch("aragora.server.state.get_state_manager")
    def test_cancel_non_cancellable_status(self, mock_get_manager):
        """Cancelling a debate in non-cancellable status returns 400."""
        mock_state = MagicMock()
        mock_state.status = "completed"
        mock_state.metadata = {}
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = mock_state
        mock_get_manager.return_value = mock_manager

        h = _make_handler()
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "debate-completed")

        assert _status(result) == 400
        assert "cannot be cancelled" in _body(result).get("error", "").lower()

    @patch("aragora.server.state.get_state_manager")
    def test_cancel_cancelled_status(self, mock_get_manager):
        """Cancelling an already-cancelled debate returns 400."""
        mock_state = MagicMock()
        mock_state.status = "cancelled"
        mock_state.metadata = {}
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = mock_state
        mock_get_manager.return_value = mock_manager

        h = _make_handler()
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "debate-cancelled")

        assert _status(result) == 400
        assert "cannot be cancelled" in _body(result).get("error", "").lower()

    @patch("aragora.server.state.get_state_manager")
    @patch("aragora.server.debate_utils.update_debate_status")
    def test_cancel_with_async_task(self, mock_update_status, mock_get_manager):
        """Cancelling a debate with a tracked task cancels the task."""
        mock_task = MagicMock()
        mock_task.done.return_value = False

        mock_state = MagicMock()
        mock_state.status = "running"
        mock_state.metadata = {"_task": mock_task}
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = mock_state
        mock_get_manager.return_value = mock_manager

        h = _make_handler()
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "debate-with-task")

        assert _status(result) == 200
        mock_task.cancel.assert_called_once()

    @patch("aragora.server.state.get_state_manager")
    @patch("aragora.server.debate_utils.update_debate_status")
    def test_cancel_with_done_task(self, mock_update_status, mock_get_manager):
        """Cancelling a debate with a completed task does not call cancel."""
        mock_task = MagicMock()
        mock_task.done.return_value = True

        mock_state = MagicMock()
        mock_state.status = "running"
        mock_state.metadata = {"_task": mock_task}
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = mock_state
        mock_get_manager.return_value = mock_manager

        h = _make_handler()
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "debate-done-task")

        assert _status(result) == 200
        mock_task.cancel.assert_not_called()

    @patch("aragora.server.state.get_state_manager")
    @patch("aragora.server.debate_utils.update_debate_status")
    def test_cancel_task_cancel_fails_gracefully(self, mock_update_status, mock_get_manager):
        """Task cancel failure is logged but doesn't fail the operation."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel.side_effect = RuntimeError("cannot cancel")

        mock_state = MagicMock()
        mock_state.status = "running"
        mock_state.metadata = {"_task": mock_task}
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = mock_state
        mock_get_manager.return_value = mock_manager

        h = _make_handler()
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "debate-cancel-err")

        assert _status(result) == 200
        assert _body(result)["success"] is True

    @patch("aragora.server.state.get_state_manager")
    @patch("aragora.server.debate_utils.update_debate_status")
    def test_cancel_emits_stream_event(self, mock_update_status, mock_get_manager):
        """Successful cancellation emits a DEBATE_END stream event."""
        mock_state = MagicMock()
        mock_state.status = "running"
        mock_state.metadata = {}
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = mock_state
        mock_get_manager.return_value = mock_manager

        h = _make_handler()
        handler = _mock_http_handler()

        with patch(
            "aragora.server.stream.StreamEvent",
            side_effect=lambda **kwargs: SimpleNamespace(**kwargs),
        ):
            result = h._cancel_debate(handler, "debate-emit-1")

        assert _status(result) == 200
        handler.stream_emitter.emit.assert_called_once()
        event = handler.stream_emitter.emit.call_args[0][0]
        assert event.data["debate_id"] == "debate-emit-1"
        assert event.data["status"] == "cancelled"

    @patch("aragora.server.state.get_state_manager")
    @patch("aragora.server.debate_utils.update_debate_status")
    def test_cancel_no_stream_emitter(self, mock_update_status, mock_get_manager):
        """Successful cancellation without stream emitter still succeeds."""
        mock_state = MagicMock()
        mock_state.status = "running"
        mock_state.metadata = {}
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = mock_state
        mock_get_manager.return_value = mock_manager

        h = _make_handler()
        handler = _mock_http_handler()
        handler.stream_emitter = None

        result = h._cancel_debate(handler, "debate-no-emit")

        assert _status(result) == 200
        assert _body(result)["success"] is True

    @patch("aragora.server.state.get_state_manager")
    def test_cancel_not_found_no_storage_present(self, mock_get_manager):
        """Debate not in state manager and no storage returns 404."""
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = None
        mock_get_manager.return_value = mock_manager

        h = _make_handler(storage=None)
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "gone-debate")

        assert _status(result) == 404

    @patch("aragora.server.state.get_state_manager")
    def test_cancel_not_found_storage_has_no_record(self, mock_get_manager):
        """Debate not in state manager and not in storage returns 404."""
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = None
        mock_get_manager.return_value = mock_manager

        storage = MagicMock()
        storage.get_debate.return_value = None
        h = _make_handler(storage=storage)
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "truly-gone")

        assert _status(result) == 404

    @patch("aragora.server.state.get_state_manager")
    @patch("aragora.server.debate_utils.update_debate_status")
    def test_cancel_message_text(self, mock_update_status, mock_get_manager):
        """Cancel response message is 'Debate cancelled successfully'."""
        mock_state = MagicMock()
        mock_state.status = "running"
        mock_state.metadata = {}
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = mock_state
        mock_get_manager.return_value = mock_manager

        h = _make_handler()
        handler = _mock_http_handler()

        result = h._cancel_debate(handler, "d-msg")

        assert _body(result)["message"] == "Debate cancelled successfully"


# ---------------------------------------------------------------------------
# _debate_this tests
# ---------------------------------------------------------------------------


class TestDebateThis:
    """Tests for POST /api/v1/debate-this (_debate_this)."""

    def test_debate_this_success(self):
        """Successful one-click debate creation returns 200 with spectate_url."""
        body = {"question": "Is Python better than JavaScript?"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        mock_response_data = {
            "success": True,
            "debate_id": "quick-debate-1",
            "status": "starting",
        }

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps(mock_response_data).encode(),
            )
            result = h._debate_this(handler)

        assert _status(result) == 200
        body_data = _body(result)
        assert body_data["debate_id"] == "quick-debate-1"
        assert body_data["spectate_url"] == "/spectate/quick-debate-1"

    def test_debate_this_no_body(self):
        """Missing body returns 400."""
        h = _make_handler(json_body=None)
        handler = _mock_http_handler()
        result = h._debate_this(handler)
        assert _status(result) == 400
        assert "json body" in _body(result).get("error", "").lower()

    def test_debate_this_missing_question(self):
        """Missing question field returns 400."""
        h = _make_handler(json_body={"context": "some context"})
        handler = _mock_http_handler()
        result = h._debate_this(handler)
        assert _status(result) == 400
        assert "question" in _body(result).get("error", "").lower()

    def test_debate_this_empty_question(self):
        """Empty question string returns 400."""
        h = _make_handler(json_body={"question": "   "})
        handler = _mock_http_handler()
        result = h._debate_this(handler)
        assert _status(result) == 400
        assert "question" in _body(result).get("error", "").lower()

    def test_debate_this_short_question_4_rounds(self):
        """Short question (<=200 chars) gets 4 rounds."""
        body = {"question": "Short question here"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True}).encode(),
            )
            h._debate_this(handler)

        call_body = mock_direct.call_args[0][1]
        assert call_body["rounds"] == 4

    def test_debate_this_long_question_9_rounds(self):
        """Long question (>200 chars) gets 9 rounds."""
        long_question = "A" * 201
        body = {"question": long_question}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True}).encode(),
            )
            h._debate_this(handler)

        call_body = mock_direct.call_args[0][1]
        assert call_body["rounds"] == 9

    def test_debate_this_custom_rounds_override(self):
        """Custom rounds in body overrides auto-detected rounds."""
        body = {"question": "Short Q", "rounds": 7}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True}).encode(),
            )
            h._debate_this(handler)

        call_body = mock_direct.call_args[0][1]
        assert call_body["rounds"] == 7

    def test_debate_this_auto_select_enabled(self):
        """Debate-this always sets auto_select=True."""
        body = {"question": "Test Q"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True}).encode(),
            )
            h._debate_this(handler)

        call_body = mock_direct.call_args[0][1]
        assert call_body["auto_select"] is True

    def test_debate_this_with_context(self):
        """Context is forwarded to the debate body."""
        body = {"question": "Test Q", "context": "Important background info"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True}).encode(),
            )
            h._debate_this(handler)

        call_body = mock_direct.call_args[0][1]
        assert call_body["context"] == "Important background info"

    def test_debate_this_no_context(self):
        """Without context, debate body has no context key."""
        body = {"question": "Test Q"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True}).encode(),
            )
            h._debate_this(handler)

        call_body = mock_direct.call_args[0][1]
        assert "context" not in call_body

    def test_debate_this_default_source_metadata(self):
        """Default source is 'debate_this' in metadata."""
        body = {"question": "Test Q"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True}).encode(),
            )
            h._debate_this(handler)

        call_body = mock_direct.call_args[0][1]
        assert call_body["metadata"]["source"] == "debate_this"

    def test_debate_this_custom_source(self):
        """Custom source overrides default in metadata."""
        body = {"question": "Test Q", "source": "mobile_app"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True}).encode(),
            )
            h._debate_this(handler)

        call_body = mock_direct.call_args[0][1]
        assert call_body["metadata"]["source"] == "mobile_app"

    def test_debate_this_non_200_passthrough(self):
        """Non-200 response from _create_debate_direct is passed through."""
        body = {"question": "Test Q"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        from aragora.server.handlers.utils.responses import error_response

        err_result = error_response("Controller error", 500)

        with patch.object(h, "_create_debate_direct", return_value=err_result):
            result = h._debate_this(handler)

        assert _status(result) == 500

    def test_debate_this_no_debate_id_in_response(self):
        """Response without debate_id still returns successfully (no spectate_url)."""
        body = {"question": "Test Q"}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True}).encode(),
            )
            result = h._debate_this(handler)

        assert _status(result) == 200
        body_data = _body(result)
        assert "spectate_url" not in body_data

    def test_debate_this_question_field_stripped(self):
        """Leading/trailing whitespace is stripped from question."""
        body = {"question": "  Real question  "}
        h = _make_handler(json_body=body)
        handler = _mock_http_handler()

        with patch.object(h, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True}).encode(),
            )
            h._debate_this(handler)

        call_body = mock_direct.call_args[0][1]
        assert call_body["question"] == "Real question"


# ---------------------------------------------------------------------------
# _check_spam_content tests
# ---------------------------------------------------------------------------


class TestCheckSpamContent:
    """Tests for _check_spam_content."""

    def test_no_proposal_returns_none(self):
        """Empty proposal passes (let schema validation handle it)."""
        handler = _make_spam_handler()
        result = handler._check_spam_content({"context": "some text"})
        assert result is None

    def test_moderation_import_error(self):
        """If moderation module is not available, public creation fails closed."""
        handler = _make_spam_handler()

        with patch.dict("sys.modules", {"aragora.moderation": None}):
            result = handler._check_spam_content({"question": "Buy stuff!"})
        assert _status(result) == 503

    @patch("aragora.server.handlers.debates.create.run_async")
    def test_spam_blocked(self, mock_run_async):
        """Content flagged as spam returns 400."""
        handler = _make_spam_handler()

        mock_result = MagicMock()
        mock_result.should_block = True
        mock_result.verdict = MagicMock()
        mock_result.verdict.value = "spam"
        mock_result.confidence = 0.95
        mock_result.reasons = ["repetitive content"]
        mock_run_async.return_value = mock_result

        mock_mod = MagicMock()
        mock_mod.check_debate_content = MagicMock()
        mock_mod.ContentModerationError = Exception
        with patch.dict("sys.modules", {"aragora.moderation": mock_mod}):
            result = handler._check_spam_content({"question": "Buy cheap stuff!"})

        assert result is not None
        assert _status(result) == 400
        assert "spam" in _body(result).get("error", "").lower()

    @patch("aragora.server.handlers.debates.create.run_async")
    def test_spam_flagged_but_allowed(self, mock_run_async):
        """Content flagged for review but not blocked passes."""
        handler = _make_spam_handler()

        mock_result = MagicMock()
        mock_result.should_block = False
        mock_result.should_flag_for_review = True
        mock_result.verdict = MagicMock()
        mock_result.verdict.value = "suspicious"
        mock_result.confidence = 0.6
        mock_run_async.return_value = mock_result

        mock_mod = MagicMock()
        mock_mod.check_debate_content = MagicMock()
        mock_mod.ContentModerationError = Exception
        with patch.dict("sys.modules", {"aragora.moderation": mock_mod}):
            result = handler._check_spam_content({"question": "Somewhat sus content"})

        assert result is None

    def test_spam_check_runtime_error(self):
        """Runtime error during spam check blocks unless explicitly overridden."""
        handler = _make_spam_handler()

        mock_mod = MagicMock()
        mock_mod.check_debate_content = MagicMock(side_effect=RuntimeError("boom"))
        mock_mod.ContentModerationError = type("ContentModerationError", (Exception,), {})

        with patch.dict("sys.modules", {"aragora.moderation": mock_mod}):
            with patch(
                "aragora.server.handlers.debates.create.run_async",
                side_effect=RuntimeError("async fail"),
            ):
                result = handler._check_spam_content({"question": "Normal question"})

        assert _status(result) == 503

    def test_spam_check_uses_task_or_question(self):
        """Legacy task alias is normalized to question before spam checking."""
        handler = _make_spam_handler()
        from aragora.server.handlers.debates.create import _normalize_debate_body

        mock_result = MagicMock()
        mock_result.should_block = False
        mock_result.should_flag_for_review = False

        mock_mod = MagicMock()
        mock_mod.check_debate_content = MagicMock()
        mock_mod.ContentModerationError = Exception

        with patch.dict("sys.modules", {"aragora.moderation": mock_mod}):
            with patch(
                "aragora.server.handlers.debates.create.run_async",
                return_value=mock_result,
            ):
                handler._check_spam_content(_normalize_debate_body({"task": "Design a system"}))

        mock_mod.check_debate_content.assert_called_once()
        call_args = mock_mod.check_debate_content.call_args
        assert call_args[0][0] == "Design a system"

    @patch("aragora.server.handlers.debates.create.run_async")
    def test_spam_clean_content_passes(self, mock_run_async):
        """Clean content passes without blocking or flagging."""
        handler = _make_spam_handler()

        mock_result = MagicMock()
        mock_result.should_block = False
        mock_result.should_flag_for_review = False
        mock_run_async.return_value = mock_result

        mock_mod = MagicMock()
        mock_mod.check_debate_content = MagicMock()
        mock_mod.ContentModerationError = Exception

        with patch.dict("sys.modules", {"aragora.moderation": mock_mod}):
            result = handler._check_spam_content({"question": "Legitimate debate topic"})

        assert result is None


# ---------------------------------------------------------------------------
# handle_post routing tests (via DebatesHandler)
# ---------------------------------------------------------------------------


class TestHandlePostRouting:
    """Tests for route dispatch to create/cancel/debate-this via handle_post."""

    @patch("aragora.server.handlers.debates.create.emit_handler_event")
    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_post_debates_routes_to_create(self, mock_import, mock_get_schema, mock_emit):
        """POST /api/v1/debates routes to _create_debate."""
        mock_get_schema.return_value = lambda body, schema: _MockValidationResult(is_valid=True)

        from aragora.server.handlers.debates.handler import DebatesHandler

        storage = MagicMock()
        dh = DebatesHandler(ctx={"storage": storage})

        handler = _mock_http_handler()
        mock_response = _MockDebateResponse(success=True, debate_id="routed-1", status="starting")
        mock_controller = MagicMock()
        mock_controller.start_debate.return_value = mock_response
        handler._get_debate_controller = MagicMock(return_value=mock_controller)

        # Override read_json_body to return test body
        dh.read_json_body = lambda h, max_size=None: {"question": "Test routing"}
        dh._check_spam_content = lambda body: None

        with patch("aragora.server.debate_controller.DebateRequest") as MockReq:
            MockReq.from_dict.return_value = MagicMock()
            result = dh.handle_post("/api/v1/debates", {}, handler)

        assert result is not None
        assert _status(result) == 200

    @patch("aragora.server.state.get_state_manager")
    @patch("aragora.server.debate_utils.update_debate_status")
    def test_post_cancel_routes_correctly(self, mock_update, mock_get_manager):
        """POST /api/v1/debates/{id}/cancel routes to _cancel_debate."""
        mock_state = MagicMock()
        mock_state.status = "running"
        mock_state.metadata = {}
        mock_manager = MagicMock()
        mock_manager.get_debate.return_value = mock_state
        mock_get_manager.return_value = mock_manager

        from aragora.server.handlers.debates.handler import DebatesHandler

        dh = DebatesHandler(ctx={})
        handler = _mock_http_handler()

        result = dh.handle_post("/api/v1/debates/test-debate-id/cancel", {}, handler)

        assert result is not None
        assert _status(result) == 200
        assert _body(result)["status"] == "cancelled"

    def test_post_debate_this_routes_correctly(self):
        """POST /api/v1/debate-this routes to _debate_this."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        dh = DebatesHandler(ctx={})
        handler = _mock_http_handler()

        dh.read_json_body = lambda h, max_size=None: {"question": "Quick debate"}

        with patch.object(dh, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=json.dumps({"success": True, "debate_id": "dt-1"}).encode(),
            )
            result = dh.handle_post("/api/v1/debate-this", {}, handler)

        assert result is not None
        assert _status(result) == 200

    @patch("aragora.server.handlers.debates.create.emit_handler_event")
    @patch("aragora.server.handlers.debates.create._get_validate_against_schema")
    @patch("aragora.server.handlers.debates.create.importlib.import_module")
    def test_post_legacy_debate_endpoint_adds_deprecation(
        self, mock_import, mock_get_schema, mock_emit
    ):
        """POST /api/v1/debate (legacy) adds deprecation headers."""
        mock_get_schema.return_value = lambda body, schema: _MockValidationResult(is_valid=True)

        from aragora.server.handlers.debates.handler import DebatesHandler

        dh = DebatesHandler(ctx={})
        handler = _mock_http_handler()
        dh.read_json_body = lambda h, max_size=None: {"question": "Legacy endpoint"}
        dh._check_spam_content = lambda body: None

        mock_response = _MockDebateResponse(success=True, debate_id="legacy-1", status="starting")
        mock_controller = MagicMock()
        mock_controller.start_debate.return_value = mock_response
        handler._get_debate_controller = MagicMock(return_value=mock_controller)

        with patch("aragora.server.debate_controller.DebateRequest") as MockReq:
            MockReq.from_dict.return_value = MagicMock()
            result = dh.handle_post("/api/v1/debate", {}, handler)

        assert result is not None
        assert _status(result) == 200
        assert result.headers.get("Deprecation") == "true"
        assert "Sunset" in result.headers


# ---------------------------------------------------------------------------
# _get_validate_against_schema tests
# ---------------------------------------------------------------------------


class TestGetValidateAgainstSchema:
    """Tests for _get_validate_against_schema helper."""

    def test_returns_default_when_handler_module_not_loaded(self):
        """Returns the local validate_against_schema by default."""
        from aragora.server.handlers.debates.create import _get_validate_against_schema

        with patch.dict("sys.modules", {"aragora.server.handlers.debates.handler": None}):
            result = _get_validate_against_schema()

        # Should return the imported validate_against_schema
        assert callable(result)

    def test_returns_handler_module_version_when_available(self):
        """Returns handler module's validate_against_schema if loaded."""
        from aragora.server.handlers.debates.create import _get_validate_against_schema

        mock_handler_module = MagicMock()
        custom_validator = MagicMock()
        mock_handler_module.validate_against_schema = custom_validator

        with patch.dict(
            "sys.modules",
            {"aragora.server.handlers.debates.handler": mock_handler_module},
        ):
            result = _get_validate_against_schema()

        assert result is custom_validator
