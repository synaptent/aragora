"""Tests for the Decision Router HTTP handler.

Tests the decision API endpoints:
- GET  /api/v1/decisions - List recent decisions
- GET  /api/v1/decisions/:id - Get decision result by ID
- GET  /api/v1/decisions/:id/status - Get decision status for polling
- POST /api/v1/decisions - Create a new decision request
- POST /api/v1/decisions/:id/cancel - Cancel a pending/running decision
- POST /api/v1/decisions/:id/retry - Retry a failed/cancelled decision
"""

import asyncio
import inspect
import json
import sqlite3
from contextlib import closing, suppress
from datetime import datetime, timezone
from enum import Enum
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")

ORG = "test-org-001"
USER = "test-user-001"
OTHER_ORG = "other-org-999"
NOT_FOUND_BODY = {"error": "Decision not found", "code": "not_found"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


def _make_http_handler(body: dict[str, Any] | None = None, content_type: str = "application/json"):
    """Create mock HTTP handler with optional JSON body."""
    h = MagicMock()
    h.client_address = ("127.0.0.1", 12345)
    if body is not None:
        raw = json.dumps(body).encode()
        h.headers = {
            "Content-Length": str(len(raw)),
            "Content-Type": content_type,
        }
        h.rfile = MagicMock()
        h.rfile.read.return_value = raw
    else:
        h.headers = {"Content-Length": "2", "Content-Type": content_type}
        h.rfile = MagicMock()
        h.rfile.read.return_value = b"{}"
    return h


# ---------------------------------------------------------------------------
# Mock types for DecisionRouter results
# ---------------------------------------------------------------------------


class _DecisionType(Enum):
    DEBATE = "debate"
    WORKFLOW = "workflow"
    GAUNTLET = "gauntlet"
    QUICK = "quick"
    AUTO = "auto"


class _MockDecisionResult:
    """Mock for DecisionResult returned by router.route()."""

    def __init__(
        self,
        success: bool = True,
        decision_type: _DecisionType = _DecisionType.DEBATE,
        answer: str = "Test answer",
        confidence: float = 0.85,
        consensus_reached: bool = True,
        reasoning: str = "Test reasoning",
        evidence_used: list[str] | None = None,
        duration_seconds: float = 1.5,
        error: str | None = None,
    ):
        self.success = success
        self.decision_type = decision_type
        self.answer = answer
        self.confidence = confidence
        self.consensus_reached = consensus_reached
        self.reasoning = reasoning
        self.evidence_used = evidence_used or []
        self.duration_seconds = duration_seconds
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "decision_type": self.decision_type.value,
            "answer": self.answer,
            "confidence": self.confidence,
            "consensus_reached": self.consensus_reached,
            "reasoning": self.reasoning,
            "evidence_used": self.evidence_used,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


class _MockDecisionContext:
    """Mock for DecisionRequest context."""

    def __init__(self, user_id=None, workspace_id=None, metadata=None):
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.metadata = metadata


class _MockDecisionRequest:
    """Mock for DecisionRequest."""

    def __init__(self, request_id="dec_test123456", content="Test question"):
        self.request_id = request_id
        self.content = content
        self.context = _MockDecisionContext()

    @classmethod
    def from_http(cls, body, headers):
        req = cls(content=body.get("content", ""))
        return req


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a DecisionHandler instance with empty context."""
    from aragora.server.handlers.decision import DecisionHandler

    return DecisionHandler(ctx={})


@pytest.fixture
def mock_http_handler():
    """Create mock HTTP handler (no body)."""
    return _make_http_handler()


@pytest.fixture(autouse=True)
def reset_decision_module_state():
    """Reset module-level singletons and caches before each test."""
    import aragora.server.handlers.decision as mod

    # Reset the in-memory fallback cache
    mod._decision_results_fallback.clear()
    # Reset the lazy router
    mod._decision_router = None
    yield
    # Clean up after test
    mod._decision_results_fallback.clear()
    mod._decision_router = None


# ---------------------------------------------------------------------------
# can_handle routing
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for the can_handle routing method."""

    def test_can_handle_decisions_root(self, handler):
        assert handler.can_handle("/api/v1/decisions")

    def test_can_handle_decision_by_id(self, handler):
        assert handler.can_handle("/api/v1/decisions/dec_abc123")

    def test_can_handle_decision_status(self, handler):
        assert handler.can_handle("/api/v1/decisions/dec_abc123/status")

    def test_can_handle_decision_cancel(self, handler):
        assert handler.can_handle("/api/v1/decisions/dec_abc123/cancel")

    def test_can_handle_decision_retry(self, handler):
        assert handler.can_handle("/api/v1/decisions/dec_abc123/retry")

    def test_cannot_handle_unrelated_path(self, handler):
        assert not handler.can_handle("/api/v1/debates")

    def test_cannot_handle_other_api(self, handler):
        assert not handler.can_handle("/api/health")

    def test_cannot_handle_partial_prefix(self, handler):
        assert not handler.can_handle("/api/v1/decision")

    def test_cannot_handle_plans_subpath(self, handler):
        # This is handled by DecisionPipelineHandler
        # but can_handle here checks prefix so it would match
        assert handler.can_handle("/api/v1/decisions/plans")


# ---------------------------------------------------------------------------
# Handler initialization
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for handler initialization."""

    def test_init_default_context(self):
        from aragora.server.handlers.decision import DecisionHandler

        h = DecisionHandler()
        assert h.ctx == {}

    def test_init_none_context(self):
        from aragora.server.handlers.decision import DecisionHandler

        h = DecisionHandler(ctx=None)
        assert h.ctx == {}

    def test_init_with_context(self):
        from aragora.server.handlers.decision import DecisionHandler

        h = DecisionHandler(ctx={"document_store": "mock"})
        assert h.ctx["document_store"] == "mock"

    def test_routes_attribute(self, handler):
        assert "/api/v1/decisions" in handler.ROUTES
        assert "/api/v1/decisions/*" in handler.ROUTES


# ---------------------------------------------------------------------------
# GET /api/v1/decisions (list decisions)
# ---------------------------------------------------------------------------


class TestListDecisions:
    """Tests for listing recent decisions."""

    def test_list_decisions_empty_fallback(self, handler, mock_http_handler):
        """With no store and empty fallback, returns empty list."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        result = handler.handle("/api/v1/decisions", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["decisions"] == []
        assert body["total"] == 0

    def test_list_decisions_with_fallback_data(self, handler, mock_http_handler):
        """Returns decisions from in-memory fallback when store unavailable."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_001"] = {
            "request_id": "dec_001",
            "org_id": ORG,
            "status": "completed",
            "completed_at": "2026-01-01T00:00:00Z",
        }
        mod._decision_results_fallback["dec_002"] = {
            "request_id": "dec_002",
            "org_id": ORG,
            "status": "failed",
            "completed_at": "2026-01-02T00:00:00Z",
        }

        result = handler.handle("/api/v1/decisions", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 2
        assert len(body["decisions"]) == 2

    def test_list_decisions_with_store(self, handler, mock_http_handler):
        """Returns decisions from persistent store when available."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mock_store.list_recent_for_org.return_value = [
            {"request_id": "dec_001", "status": "completed"}
        ]
        mock_store.count_for_org.return_value = 1
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        result = handler.handle("/api/v1/decisions", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 1
        assert body["decisions"][0]["request_id"] == "dec_001"
        mock_store.list_recent_for_org.assert_called_once_with(ORG, 20)
        mock_store.count_for_org.assert_called_once_with(ORG)
        mock_store.list_recent.assert_not_called()

    def test_list_decisions_store_error_falls_back(self, handler, mock_http_handler):
        """Falls back to in-memory when store raises."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mock_store.list_recent_for_org.side_effect = OSError("connection lost")
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        result = handler.handle("/api/v1/decisions", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["decisions"] == []

    def test_list_decisions_respects_limit(self, handler, mock_http_handler):
        """Limit parameter controls how many decisions are returned from fallback."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        for i in range(5):
            mod._decision_results_fallback[f"dec_{i:03d}"] = {
                "request_id": f"dec_{i:03d}",
                "org_id": ORG,
                "status": "completed",
            }

        result = handler.handle("/api/v1/decisions", {"limit": "2"}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert len(body["decisions"]) == 2
        assert body["total"] == 5

    def test_list_decisions_invalid_limit_uses_default(self, handler, mock_http_handler):
        """Invalid limit falls back to default."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        result = handler.handle("/api/v1/decisions", {"limit": "not_a_number"}, mock_http_handler)
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# GET /api/v1/decisions/:id (get decision)
# ---------------------------------------------------------------------------


class TestGetDecision:
    """Tests for getting a decision by ID."""

    def test_get_decision_found_in_fallback(self, handler, mock_http_handler):
        """Returns decision from in-memory fallback."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_test123"] = {
            "request_id": "dec_test123",
            "org_id": ORG,
            "status": "completed",
            "result": {"answer": "Yes"},
        }

        result = handler.handle("/api/v1/decisions/dec_test123", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["request_id"] == "dec_test123"

    def test_get_decision_found_in_store(self, handler, mock_http_handler):
        """Returns decision from persistent store."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mock_store.get_for_org.return_value = {
            "request_id": "dec_store123",
            "status": "completed",
            "org_id": ORG,
        }
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        result = handler.handle("/api/v1/decisions/dec_store123", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["request_id"] == "dec_store123"

    def test_get_decision_not_found(self, handler, mock_http_handler):
        """Returns 404 when decision not found."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        result = handler.handle("/api/v1/decisions/dec_nonexist", {}, mock_http_handler)
        assert _status(result) == 404
        assert _body(result) == NOT_FOUND_BODY

    def test_get_decision_store_error_falls_back(self, handler, mock_http_handler):
        """Falls back to in-memory when store raises."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mock_store.get_for_org.side_effect = TypeError("broken")
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        mod._decision_results_fallback["dec_fallback"] = {
            "request_id": "dec_fallback",
            "org_id": ORG,
            "status": "completed",
        }

        result = handler.handle("/api/v1/decisions/dec_fallback", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["request_id"] == "dec_fallback"


# ---------------------------------------------------------------------------
# GET /api/v1/decisions/:id/status (polling)
# ---------------------------------------------------------------------------


class TestGetDecisionStatus:
    """Tests for getting decision status for polling."""

    def test_status_from_store(self, handler, mock_http_handler):
        """Returns status from persistent store."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mock_store.get_for_org.return_value = {
            "request_id": "dec_123",
            "status": "running",
            "org_id": ORG,
        }
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        result = handler.handle("/api/v1/decisions/dec_123/status", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "running"

    def test_status_store_error_falls_back(self, handler, mock_http_handler):
        """Falls back to in-memory when store raises."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mock_store.get_for_org.side_effect = KeyError("missing")
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        mod._decision_results_fallback["dec_456"] = {
            "request_id": "dec_456",
            "org_id": ORG,
            "status": "completed",
            "completed_at": "2026-01-01T00:00:00Z",
        }

        result = handler.handle("/api/v1/decisions/dec_456/status", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "completed"
        assert body["completed_at"] == "2026-01-01T00:00:00Z"

    def test_status_not_found_returns_404(self, handler, mock_http_handler):
        """A decision found nowhere answers the standard not-found 404."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        result = handler.handle("/api/v1/decisions/dec_unknown/status", {}, mock_http_handler)
        assert _status(result) == 404
        assert _body(result) == NOT_FOUND_BODY

    def test_status_fallback_missing_completed_at(self, handler, mock_http_handler):
        """Fallback result without completed_at returns None."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_789"] = {
            "request_id": "dec_789",
            "org_id": ORG,
            "status": "pending",
        }

        result = handler.handle("/api/v1/decisions/dec_789/status", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "pending"
        assert body["completed_at"] is None


# ---------------------------------------------------------------------------
# GET routing edge cases
# ---------------------------------------------------------------------------


class TestGetRouting:
    """Tests for GET request routing edge cases."""

    def test_handle_returns_none_for_unmatched_path(self, handler, mock_http_handler):
        """Returns None for paths that don't match any route."""
        result = handler.handle("/api/v1/other", {}, mock_http_handler)
        assert result is None

    def test_handle_short_path_returns_none(self, handler, mock_http_handler):
        """Returns None for path with less than 5 parts."""
        result = handler.handle("/api/v1", {}, mock_http_handler)
        assert result is None

    def test_handle_decisions_slash_with_id(self, handler, mock_http_handler):
        """Decision paths with ID dispatch correctly."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["myid"] = {
            "request_id": "myid",
            "org_id": ORG,
            "status": "completed",
        }

        result = handler.handle("/api/v1/decisions/myid", {}, mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["request_id"] == "myid"


# ---------------------------------------------------------------------------
# POST /api/v1/decisions (create decision)
# ---------------------------------------------------------------------------


class TestCreateDecision:
    """Tests for creating a new decision."""

    @pytest.mark.asyncio
    async def test_create_decision_success(self, handler):
        """Successfully creates a decision and returns result."""
        mock_result = _MockDecisionResult(success=True)
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        mock_request = _MockDecisionRequest()

        h = _make_http_handler({"content": "Should we deploy?"})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "completed"
        assert body["answer"] == "Test answer"
        assert body["confidence"] == 0.85
        assert body["consensus_reached"] is True

    @pytest.mark.asyncio
    async def test_create_decision_failed_result(self, handler):
        """Returns failed status when decision fails."""
        mock_result = _MockDecisionResult(success=False, error="No consensus")
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        mock_request = _MockDecisionRequest()

        h = _make_http_handler({"content": "Test question"})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "failed"
        assert body["error"] == "No consensus"

    @pytest.mark.asyncio
    async def test_create_decision_missing_content(self, handler):
        """Returns 400 when content field is missing."""
        h = _make_http_handler({"decision_type": "debate"})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 400
        assert "content" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_create_decision_empty_content(self, handler):
        """Returns 400 when content field is empty string."""
        h = _make_http_handler({"content": ""})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 400
        assert "content" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_create_decision_router_unavailable(self, handler):
        """Returns 503 when decision router is not available."""
        mock_request = _MockDecisionRequest()

        h = _make_http_handler({"content": "Test question"})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 503
        assert "router" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_create_decision_timeout(self, handler):
        """Returns 408 when decision times out."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=asyncio.TimeoutError())

        mock_request = _MockDecisionRequest()

        h = _make_http_handler({"content": "Test question"})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 408
        assert "timed out" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_create_decision_connection_error(self, handler):
        """Returns 500 when routing fails with ConnectionError."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=ConnectionError("refused"))

        mock_request = _MockDecisionRequest()

        h = _make_http_handler({"content": "Test question"})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 500
        assert "failed" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_create_decision_runtime_error(self, handler):
        """Returns 500 when routing fails with RuntimeError."""
        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=RuntimeError("internal"))

        mock_request = _MockDecisionRequest()

        h = _make_http_handler({"content": "Test question"})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_create_decision_invalid_request_value_error(self, handler):
        """Returns 400 when DecisionRequest.from_http raises ValueError."""
        h = _make_http_handler({"content": "Test question"})

        with (
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.side_effect = ValueError("Invalid decision type")
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_decision_import_error(self, handler):
        """Returns 400 when DecisionRequest import fails."""
        h = _make_http_handler({"content": "Test question"})

        with (
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.side_effect = ImportError("no module")
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_decision_permission_error(self, handler):
        """Returns permission error when require_permission_or_error fails."""
        from aragora.server.handlers.base import error_response

        perm_error = error_response("Forbidden", 403)
        h = _make_http_handler({"content": "Test question"})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(None, perm_error),
        ):
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 403

    @pytest.mark.asyncio
    async def test_create_decision_stores_result(self, handler):
        """Verifies the result is saved to the store/fallback."""
        import aragora.server.handlers.decision as mod

        mock_result = _MockDecisionResult(success=True)
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        mock_request = _MockDecisionRequest(request_id="dec_save_test")

        h = _make_http_handler({"content": "Test question"})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            # Ensure store is not available so fallback is used
            mod._decision_result_store = MagicMock()
            mod._decision_result_store.get.return_value = None
            await handler.handle_post("/api/v1/decisions", {}, h)

        assert "dec_save_test" in mod._decision_results_fallback
        saved = mod._decision_results_fallback["dec_save_test"]
        assert saved["status"] == "completed"

    @pytest.mark.asyncio
    async def test_create_decision_timeout_stores_result(self, handler):
        """Timeout result is saved for later polling."""
        import aragora.server.handlers.decision as mod

        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=asyncio.TimeoutError())

        mock_request = _MockDecisionRequest(request_id="dec_timeout_save")

        h = _make_http_handler({"content": "Test question"})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            mod._decision_result_store = MagicMock()
            mod._decision_result_store.get.return_value = None
            await handler.handle_post("/api/v1/decisions", {}, h)

        assert "dec_timeout_save" in mod._decision_results_fallback
        assert mod._decision_results_fallback["dec_timeout_save"]["status"] == "timeout"

    @pytest.mark.asyncio
    async def test_create_decision_error_stores_result(self, handler):
        """Connection error result is saved for later polling."""
        import aragora.server.handlers.decision as mod

        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=ConnectionError("refused"))

        mock_request = _MockDecisionRequest(request_id="dec_err_save")

        h = _make_http_handler({"content": "Test question"})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            mod._decision_result_store = MagicMock()
            mod._decision_result_store.get.return_value = None
            await handler.handle_post("/api/v1/decisions", {}, h)

        assert "dec_err_save" in mod._decision_results_fallback
        assert mod._decision_results_fallback["dec_err_save"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_create_decision_invalid_json_body(self, handler):
        """Returns 400 for invalid JSON body."""
        h = MagicMock()
        h.client_address = ("127.0.0.1", 12345)
        h.headers = {"Content-Length": "7", "Content-Type": "application/json"}
        h.rfile = MagicMock()
        h.rfile.read.return_value = b"notjson"

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_decision_unmatched_post_path(self, handler):
        """Returns None for unmatched POST path."""
        h = _make_http_handler({"content": "test"})
        result = await handler.handle_post("/api/v1/other", {}, h)
        assert result is None

    @pytest.mark.asyncio
    async def test_create_decision_with_auth_context(self, handler):
        """The caller's scope sets the request user and workspace, overriding the body."""
        mock_result = _MockDecisionResult(success=True)
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        mock_request = _MockDecisionRequest()
        mock_request.context = _MockDecisionContext(user_id="body-user", workspace_id="other-org")

        h = _make_http_handler({"content": "Test question"})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions", {}, h)

        assert _status(result) == 200
        assert mock_request.context.user_id == USER
        assert mock_request.context.workspace_id == ORG


# ---------------------------------------------------------------------------
# POST /api/v1/decisions/:id/cancel
# ---------------------------------------------------------------------------


class TestCancelDecision:
    """Tests for cancelling a decision."""

    @pytest.mark.asyncio
    async def test_cancel_pending_decision(self, handler):
        """Successfully cancels a pending decision."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_cancel_001"] = {
            "request_id": "dec_cancel_001",
            "org_id": ORG,
            "status": "pending",
        }

        h = _make_http_handler({"reason": "No longer needed"})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_cancel_001/cancel", {}, h)

        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "cancelled"
        assert body["reason"] == "No longer needed"
        assert "cancelled_at" in body

    @pytest.mark.asyncio
    async def test_cancel_running_decision(self, handler):
        """Successfully cancels a running decision."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_cancel_002"] = {
            "request_id": "dec_cancel_002",
            "org_id": ORG,
            "status": "running",
        }

        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_cancel_002/cancel", {}, h)

        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_processing_decision(self, handler):
        """Successfully cancels a processing decision."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_cancel_003"] = {
            "request_id": "dec_cancel_003",
            "org_id": ORG,
            "status": "processing",
        }

        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_cancel_003/cancel", {}, h)

        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_cancel_completed_decision_conflict(self, handler):
        """Returns 409 when trying to cancel completed decision."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_cancel_done"] = {
            "request_id": "dec_cancel_done",
            "org_id": ORG,
            "status": "completed",
        }

        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_cancel_done/cancel", {}, h)

        assert _status(result) == 409
        assert "cannot cancel" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_cancel_failed_decision_conflict(self, handler):
        """Returns 409 when trying to cancel failed decision."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_cancel_fail"] = {
            "request_id": "dec_cancel_fail",
            "org_id": ORG,
            "status": "failed",
        }

        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_cancel_fail/cancel", {}, h)

        assert _status(result) == 409

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, handler):
        """Returns 404 when decision not found."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_nonexist/cancel", {}, h)

        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_cancel_without_reason(self, handler):
        """Cancel without reason succeeds and reason is None."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_noreason"] = {
            "request_id": "dec_noreason",
            "org_id": ORG,
            "status": "pending",
        }

        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_noreason/cancel", {}, h)

        assert _status(result) == 200
        body = _body(result)
        assert body["reason"] is None

    @pytest.mark.asyncio
    async def test_cancel_updates_fallback_store(self, handler):
        """Cancel persists status change in fallback."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_upd"] = {
            "request_id": "dec_upd",
            "org_id": ORG,
            "status": "running",
        }

        h = _make_http_handler({"reason": "test"})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            await handler.handle_post("/api/v1/decisions/dec_upd/cancel", {}, h)

        saved = mod._decision_results_fallback["dec_upd"]
        assert saved["status"] == "cancelled"
        assert "cancelled_at" in saved
        assert saved["cancellation_reason"] == "test"

    @pytest.mark.asyncio
    async def test_cancel_permission_error(self, handler):
        """Returns permission error when require_permission_or_error fails."""
        from aragora.server.handlers.base import error_response

        perm_error = error_response("Forbidden", 403)
        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(None, perm_error),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_perm/cancel", {}, h)

        assert _status(result) == 403


# ---------------------------------------------------------------------------
# POST /api/v1/decisions/:id/retry
# ---------------------------------------------------------------------------


class TestRetryDecision:
    """Tests for retrying a failed/cancelled decision."""

    @pytest.mark.asyncio
    async def test_retry_failed_decision(self, handler):
        """Successfully retries a failed decision."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_001"] = {
            "request_id": "dec_retry_001",
            "org_id": ORG,
            "status": "failed",
            "result": {
                "request": {
                    "content": "Test question",
                    "decision_type": "auto",
                    "config": {},
                    "context": {},
                },
                "retry_count": 0,
            },
            "content": "Test question",
        }

        mock_result = _MockDecisionResult(success=True)
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        mock_request = _MockDecisionRequest(request_id="dec_new123456")
        mock_request.context.metadata = {}

        h = _make_http_handler({})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions/dec_retry_001/retry", {}, h)

        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "completed"
        assert body["retried_from"] == "dec_retry_001"

    @pytest.mark.asyncio
    async def test_retry_cancelled_decision(self, handler):
        """Successfully retries a cancelled decision."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_can"] = {
            "request_id": "dec_retry_can",
            "org_id": ORG,
            "status": "cancelled",
            "result": {
                "request": {"content": "Another question"},
            },
        }

        mock_result = _MockDecisionResult(success=True)
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        mock_request = _MockDecisionRequest(request_id="dec_new_can")
        mock_request.context.metadata = {}

        h = _make_http_handler({})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions/dec_retry_can/retry", {}, h)

        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_retry_timeout_decision(self, handler):
        """Successfully retries a timed out decision."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_to"] = {
            "request_id": "dec_retry_to",
            "org_id": ORG,
            "status": "timeout",
            "result": {"task": "Timeout question"},
        }

        mock_result = _MockDecisionResult(success=True)
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        mock_request = _MockDecisionRequest(request_id="dec_new_to")
        mock_request.context.metadata = {}

        h = _make_http_handler({})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions/dec_retry_to/retry", {}, h)

        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_retry_completed_decision_conflict(self, handler):
        """Returns 409 when trying to retry completed decision."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_done"] = {
            "request_id": "dec_retry_done",
            "org_id": ORG,
            "status": "completed",
        }

        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_retry_done/retry", {}, h)

        assert _status(result) == 409
        assert "cannot retry" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_retry_running_decision_conflict(self, handler):
        """Returns 409 when trying to retry running decision."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_run"] = {
            "request_id": "dec_retry_run",
            "org_id": ORG,
            "status": "running",
        }

        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_retry_run/retry", {}, h)

        assert _status(result) == 409

    @pytest.mark.asyncio
    async def test_retry_not_found(self, handler):
        """Returns 404 when decision to retry is not found."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_nonexist/retry", {}, h)

        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_retry_no_content_returns_400(self, handler):
        """Returns 400 when original decision content cannot be found."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_nocontent"] = {
            "request_id": "dec_retry_nocontent",
            "org_id": ORG,
            "status": "failed",
            "result": {},
        }

        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(authenticated=False), None),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_retry_nocontent/retry", {}, h)

        assert _status(result) == 400
        assert "content not found" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_retry_router_unavailable(self, handler):
        """Returns 503 when decision router is not available for retry."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_norouter"] = {
            "request_id": "dec_retry_norouter",
            "org_id": ORG,
            "status": "failed",
            "result": {"request": {"content": "Question"}},
        }

        h = _make_http_handler({})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_retry_norouter/retry", {}, h)

        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_retry_timeout_on_retry(self, handler):
        """Returns 408 when retried decision times out."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_to2"] = {
            "request_id": "dec_retry_to2",
            "org_id": ORG,
            "status": "failed",
            "result": {"request": {"content": "Question"}},
        }

        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=asyncio.TimeoutError())

        mock_request = _MockDecisionRequest(request_id="dec_new_retry_to")
        mock_request.context.metadata = {}

        h = _make_http_handler({})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions/dec_retry_to2/retry", {}, h)

        assert _status(result) == 408
        assert "timed out" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_retry_connection_error_on_retry(self, handler):
        """Returns 500 when retried decision fails with ConnectionError."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_ce"] = {
            "request_id": "dec_retry_ce",
            "org_id": ORG,
            "status": "failed",
            "result": {"request": {"content": "Question"}},
        }

        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=ConnectionError("refused"))

        mock_request = _MockDecisionRequest(request_id="dec_new_retry_ce")
        mock_request.context.metadata = {}

        h = _make_http_handler({})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions/dec_retry_ce/retry", {}, h)

        assert _status(result) == 500
        assert "failed" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_retry_build_request_failure(self, handler):
        """Returns 400 when building retry request fails."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_build"] = {
            "request_id": "dec_retry_build",
            "org_id": ORG,
            "status": "failed",
            "result": {"request": {"content": "Question"}},
        }

        mock_router = MagicMock()

        h = _make_http_handler({})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.side_effect = TypeError("invalid")
            result = await handler.handle_post("/api/v1/decisions/dec_retry_build/retry", {}, h)

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_retry_permission_error(self, handler):
        """Returns permission error when require_permission_or_error fails."""
        from aragora.server.handlers.base import error_response

        perm_error = error_response("Forbidden", 403)
        h = _make_http_handler({})

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(None, perm_error),
        ):
            result = await handler.handle_post("/api/v1/decisions/dec_perm/retry", {}, h)

        assert _status(result) == 403

    @pytest.mark.asyncio
    async def test_retry_stores_new_result(self, handler):
        """Verifies the retry result is saved with lineage data."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_store"] = {
            "request_id": "dec_retry_store",
            "org_id": ORG,
            "status": "failed",
            "result": {"request": {"content": "Question"}},
        }

        mock_result = _MockDecisionResult(success=True)
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        mock_request = _MockDecisionRequest(request_id="dec_new_retry_store")
        mock_request.context.metadata = {}

        h = _make_http_handler({})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            await handler.handle_post("/api/v1/decisions/dec_retry_store/retry", {}, h)

        # The new request_id is dynamically generated, find it
        new_ids = [k for k in mod._decision_results_fallback if k != "dec_retry_store"]
        assert len(new_ids) >= 1
        new_saved = mod._decision_results_fallback[new_ids[0]]
        assert new_saved["retried_from"] == "dec_retry_store"

    @pytest.mark.asyncio
    async def test_retry_content_from_task_field(self, handler):
        """Retry extracts content from result.task when request.content is missing."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_task"] = {
            "request_id": "dec_retry_task",
            "org_id": ORG,
            "status": "failed",
            "result": {"task": "Question from task field"},
        }

        mock_result = _MockDecisionResult(success=True)
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        mock_request = _MockDecisionRequest(request_id="dec_new_task")
        mock_request.context.metadata = {}

        h = _make_http_handler({})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions/dec_retry_task/retry", {}, h)

        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_retry_content_from_top_level(self, handler):
        """Retry extracts content from top-level content field as fallback."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["dec_retry_top"] = {
            "request_id": "dec_retry_top",
            "org_id": ORG,
            "status": "failed",
            "result": {},
            "content": "Top level content",
        }

        mock_result = _MockDecisionResult(success=True)
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        mock_request = _MockDecisionRequest(request_id="dec_new_top")
        mock_request.context.metadata = {}

        h = _make_http_handler({})

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(authenticated=False), None),
            ),
            patch(
                "aragora.core.decision.DecisionRequest",
            ) as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post("/api/v1/decisions/dec_retry_top/retry", {}, h)

        assert _status(result) == 200


# ---------------------------------------------------------------------------
# POST routing edge cases
# ---------------------------------------------------------------------------


class TestPostRouting:
    """Tests for POST request routing edge cases."""

    @pytest.mark.asyncio
    async def test_post_unmatched_path_returns_none(self, handler):
        """POST to unknown path returns None."""
        h = _make_http_handler({})
        result = await handler.handle_post("/api/v1/other", {}, h)
        assert result is None

    @pytest.mark.asyncio
    async def test_post_cancel_wrong_segment_count(self, handler):
        """POST cancel with wrong segment count returns None."""
        h = _make_http_handler({})
        # 7 segments: /api/v1/decisions/id/extra/cancel
        result = await handler.handle_post("/api/v1/decisions/id/extra/cancel", {}, h)
        assert result is None

    @pytest.mark.asyncio
    async def test_post_retry_wrong_segment_count(self, handler):
        """POST retry with wrong segment count returns None."""
        h = _make_http_handler({})
        result = await handler.handle_post("/api/v1/decisions/id/extra/retry", {}, h)
        assert result is None


# ---------------------------------------------------------------------------
# _get_decision_router tests
# ---------------------------------------------------------------------------


class TestGetDecisionRouter:
    """Tests for the decision router singleton."""

    def test_get_router_creates_singleton(self):
        """Creates and caches the router instance."""
        import aragora.server.handlers.decision as mod

        mock_router = MagicMock()
        with patch("aragora.core.decision.DecisionRouter", return_value=mock_router):
            result = mod._get_decision_router({"document_store": "ds", "evidence_store": "es"})

        assert result is mock_router

    def test_get_router_returns_none_on_import_error(self):
        """Returns None when DecisionRouter cannot be imported."""
        import aragora.server.handlers.decision as mod

        mod._decision_router = None
        with patch("aragora.core.decision.DecisionRouter", side_effect=ImportError("no module")):
            result = mod._get_decision_router()

        assert result is None

    def test_get_router_returns_cached(self):
        """Returns cached router on subsequent calls."""
        import aragora.server.handlers.decision as mod

        mock_router = MagicMock()
        mod._decision_router = mock_router
        result = mod._get_decision_router()
        assert result is mock_router

    def test_get_router_fills_stores_on_cached(self):
        """Fills in missing stores on cached router when ctx provided."""
        import aragora.server.handlers.decision as mod

        mock_router = MagicMock()
        mock_router._document_store = None
        mock_router._evidence_store = None
        mod._decision_router = mock_router

        mod._get_decision_router({"document_store": "ds", "evidence_store": "es"})
        assert mock_router._document_store == "ds"
        assert mock_router._evidence_store == "es"


# ---------------------------------------------------------------------------
# _save_result / _get_result tests
# ---------------------------------------------------------------------------


class TestSaveAndGetResult:
    """Tests for result persistence helpers."""

    def test_save_to_store(self):
        """Saves to persistent store, passing the owner, when available."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        mod._save_result("test_id", {"status": "completed"}, org_id=ORG, created_by=USER)
        mock_store.save.assert_called_once_with(
            "test_id", {"status": "completed"}, org_id=ORG, created_by=USER
        )

    def test_save_fallback_on_store_error(self):
        """Falls back to in-memory when store raises."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mock_store.save.side_effect = OSError("disk full")
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        mod._save_result("test_id", {"status": "completed"}, org_id=ORG, created_by=USER)
        saved = mod._decision_results_fallback["test_id"]
        assert saved["status"] == "completed"
        assert saved["org_id"] == ORG
        assert saved["created_by"] == USER

    def test_save_to_fallback_when_no_store(self):
        """Saves to in-memory fallback when no store available."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._save_result("test_id", {"status": "completed"}, org_id=ORG, created_by=USER)
        assert mod._decision_results_fallback["test_id"]["status"] == "completed"
        assert mod._decision_results_fallback["test_id"]["org_id"] == ORG

    def test_save_fallback_owner_update_keeps_creator(self):
        """A later fallback save by the owning org updates the entry, not its creator."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        assert mod._save_result("test_id", {"status": "pending"}, org_id=ORG, created_by=USER)
        assert mod._save_result("test_id", {"status": "completed"}, org_id=ORG, created_by="u2")
        saved = mod._decision_results_fallback["test_id"]
        assert saved["status"] == "completed"
        assert (saved["org_id"], saved["created_by"]) == (ORG, USER)

    @pytest.mark.parametrize("owner", [OTHER_ORG, None])
    def test_save_fallback_rejects_entry_not_owned_by_org(self, owner):
        """A fallback entry of another org or without an owner is neither overwritten nor claimed."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None
        mod._decision_results_fallback["test_id"] = {"status": "pending", "org_id": owner}

        saved = mod._save_result("test_id", {"status": "completed"}, org_id=ORG, created_by=USER)

        assert saved is False
        assert mod._decision_results_fallback["test_id"] == {"status": "pending", "org_id": owner}

    def test_save_store_conflict_does_not_fall_back(self, tmp_path):
        """A store ownership conflict is reported, never retried in the fallback."""
        import aragora.server.handlers.decision as mod

        store = _real_store(mod, tmp_path)
        store.save("test_id", {"status": "pending"}, org_id=OTHER_ORG, created_by="owner")

        saved = mod._save_result("test_id", {"status": "completed"}, org_id=ORG, created_by=USER)

        assert saved is False
        assert mod._decision_results_fallback == {}
        assert store.get("test_id")["status"] == "pending"

    def test_get_from_store(self):
        """Gets from persistent store, scoped to the org, when available."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mock_store.get_for_org.return_value = {
            "request_id": "test_id",
            "status": "completed",
            "org_id": ORG,
        }
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        result = mod._get_result("test_id", ORG)
        assert result["status"] == "completed"
        mock_store.get_for_org.assert_called_once_with("test_id", ORG)
        mock_store.get.assert_not_called()

    def test_get_fallback_on_store_error(self):
        """Falls back to in-memory when store raises."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mock_store.get_for_org.side_effect = ValueError("broken")
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        mod._decision_results_fallback["test_id"] = {"status": "completed", "org_id": ORG}
        result = mod._get_result("test_id", ORG)
        assert result["status"] == "completed"

    def test_get_from_fallback_when_no_store(self):
        """Gets from in-memory fallback when no store."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["test_id"] = {"status": "completed", "org_id": ORG}
        result = mod._get_result("test_id", ORG)
        assert result["status"] == "completed"

    def test_get_returns_none_when_not_found(self):
        """Returns None when result not found anywhere."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        result = mod._get_result("nonexistent", ORG)
        assert result is None

    def test_get_store_returns_none_falls_through(self):
        """When store returns None, checks fallback."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mock_store.get_for_org.return_value = None
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        mod._decision_results_fallback["test_id"] = {"status": "in_fallback", "org_id": ORG}
        result = mod._get_result("test_id", ORG)
        assert result["status"] == "in_fallback"

    @pytest.mark.parametrize("owner", [OTHER_ORG, None])
    def test_get_fallback_hides_entry_not_owned_by_org(self, owner):
        """Fallback entries of another org or without an owner are not returned."""
        import aragora.server.handlers.decision as mod

        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = None

        mod._decision_results_fallback["test_id"] = {"status": "completed", "org_id": owner}
        assert mod._get_result("test_id", ORG) is None

    @pytest.mark.parametrize("org_id", [None, ""])
    def test_get_without_org_returns_none(self, org_id):
        """A falsy org never reads anything, not even ownerless entries."""
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        mod._decision_results_fallback["test_id"] = {"status": "completed", "org_id": None}
        assert mod._get_result("test_id", org_id) is None
        mock_store.get_for_org.assert_not_called()


# ---------------------------------------------------------------------------
# Org ownership
# ---------------------------------------------------------------------------


def _use_fallback_only():
    import aragora.server.handlers.decision as mod

    mod._decision_result_store = MagicMock()
    mod._decision_result_store.get.return_value = None
    return mod


def _real_store(mod, tmp_path):
    from aragora.storage.decision_result_store import DecisionResultStore

    store = DecisionResultStore(db_path=tmp_path / "decision_results.db", ttl_seconds=3600)
    mod._decision_result_store = MagicMock()
    mod._decision_result_store.get.return_value = store
    return store


def _seed(mod, request_id: str, org_id: str | None, status: str = "failed", **extra):
    mod._decision_results_fallback[request_id] = {
        "request_id": request_id,
        "status": status,
        "org_id": org_id,
        "result": {"request": {"content": "Question"}},
        **extra,
    }


class TestOrgOwnership:
    """Decisions are visible only to the org that owns them."""

    @pytest.mark.parametrize("owner", [OTHER_ORG, None])
    def test_get_unowned_decision_is_identical_to_missing(self, handler, mock_http_handler, owner):
        mod = _use_fallback_only()
        _seed(mod, "dec_foreign", owner, status="completed")

        foreign = handler.handle("/api/v1/decisions/dec_foreign", {}, mock_http_handler)
        missing = handler.handle("/api/v1/decisions/dec_missing", {}, mock_http_handler)

        assert _status(foreign) == _status(missing) == 404
        assert _body(foreign) == _body(missing) == NOT_FOUND_BODY

    def test_status_of_other_org_decision_is_404(self, handler, mock_http_handler):
        mod = _use_fallback_only()
        _seed(mod, "dec_foreign", OTHER_ORG, status="running", completed_at="2026-01-01")

        result = handler.handle("/api/v1/decisions/dec_foreign/status", {}, mock_http_handler)

        assert _status(result) == 404
        assert _body(result) == NOT_FOUND_BODY

    def test_status_of_unowned_decision_is_identical_to_missing(
        self, handler, mock_http_handler, tmp_path
    ):
        import aragora.server.handlers.decision as mod

        store = _real_store(mod, tmp_path)
        store.save("dec_mine", {"status": "running"}, org_id=ORG, created_by=USER)
        store.save("dec_theirs", {"status": "running"}, org_id=OTHER_ORG, created_by="u-other")
        store.save("dec_ownerless", {"status": "running"})

        def status_of(request_id: str):
            return handler.handle(f"/api/v1/decisions/{request_id}/status", {}, mock_http_handler)

        own = status_of("dec_mine")
        assert _status(own) == 200
        assert _body(own) == {"request_id": "dec_mine", "status": "running", "completed_at": None}

        missing = status_of("dec_missing")
        assert _status(missing) == 404
        assert _body(missing) == NOT_FOUND_BODY
        for request_id in ("dec_theirs", "dec_ownerless"):
            result = status_of(request_id)
            assert (result.status_code, result.body) == (missing.status_code, missing.body)
            assert store.get(request_id)["status"] == "running"

    def test_status_store_lookup_is_scoped_to_org(self, handler, mock_http_handler):
        import aragora.server.handlers.decision as mod

        mock_store = MagicMock()
        mock_store.get_for_org.return_value = None
        mod._decision_result_store = MagicMock()
        mod._decision_result_store.get.return_value = mock_store

        result = handler.handle("/api/v1/decisions/dec_x/status", {}, mock_http_handler)

        assert _status(result) == 404
        assert _body(result) == NOT_FOUND_BODY
        mock_store.get_for_org.assert_called_once_with("dec_x", ORG)
        mock_store.get_status.assert_not_called()

    def test_list_returns_only_caller_org_entries(self, handler, mock_http_handler):
        mod = _use_fallback_only()
        _seed(mod, "dec_mine_1", ORG, status="completed")
        _seed(mod, "dec_theirs", OTHER_ORG, status="completed")
        _seed(mod, "dec_ownerless", None, status="completed")
        _seed(mod, "dec_mine_2", ORG, status="pending")

        body = _body(handler.handle("/api/v1/decisions", {}, mock_http_handler))

        assert body["total"] == 2
        assert [d["request_id"] for d in body["decisions"]] == ["dec_mine_1", "dec_mine_2"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["cancel", "retry"])
    @pytest.mark.parametrize("owner", [OTHER_ORG, None])
    async def test_mutation_of_unowned_decision_is_identical_to_missing(
        self, handler, action, owner
    ):
        mod = _use_fallback_only()
        status = "running" if action == "cancel" else "failed"
        _seed(mod, "dec_foreign", owner, status=status)
        before = dict(mod._decision_results_fallback["dec_foreign"])
        mock_router = MagicMock()
        mock_router.route = AsyncMock()

        with (
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(), None),
            ),
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch("aragora.server.handlers.decision._save_result") as mock_save,
        ):
            foreign = await handler.handle_post(
                f"/api/v1/decisions/dec_foreign/{action}", {}, _make_http_handler({})
            )
            missing = await handler.handle_post(
                f"/api/v1/decisions/dec_missing/{action}", {}, _make_http_handler({})
            )

        assert _status(foreign) == _status(missing) == 404
        assert _body(foreign) == _body(missing) == NOT_FOUND_BODY
        mock_save.assert_not_called()
        mock_router.route.assert_not_called()
        assert mod._decision_results_fallback == {"dec_foreign": before}

    @pytest.mark.asyncio
    async def test_cancel_keeps_original_creator(self, handler):
        mod = _use_fallback_only()
        _seed(mod, "dec_own", ORG, status="running", created_by="original-user")

        with patch(
            "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
            return_value=(MagicMock(), None),
        ):
            result = await handler.handle_post(
                "/api/v1/decisions/dec_own/cancel", {}, _make_http_handler({})
            )

        assert _status(result) == 200
        saved = mod._decision_results_fallback["dec_own"]
        assert saved["status"] == "cancelled"
        assert saved["org_id"] == ORG
        assert saved["created_by"] == "original-user"

    @pytest.mark.asyncio
    async def test_cancel_that_cannot_be_saved_is_identical_to_missing(self, handler):
        mod = _use_fallback_only()
        _seed(mod, "dec_own", ORG, status="running")
        taken = {**mod._decision_results_fallback["dec_own"], "org_id": OTHER_ORG}

        def owner_changes_before_the_save(request_id, data, **kwargs):
            mod._decision_results_fallback[request_id] = dict(taken)
            return False

        with (
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(), None),
            ),
            patch(
                "aragora.server.handlers.decision._save_result_if_status",
                side_effect=owner_changes_before_the_save,
            ),
        ):
            result = await handler.handle_post(
                "/api/v1/decisions/dec_own/cancel", {}, _make_http_handler({})
            )

        assert _status(result) == 404
        assert _body(result) == NOT_FOUND_BODY
        assert mod._decision_results_fallback == {"dec_own": taken}

    @pytest.mark.asyncio
    async def test_retry_saves_new_decision_for_caller(self, handler):
        mod = _use_fallback_only()
        _seed(mod, "dec_own", ORG, status="failed", created_by="original-user")
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=_MockDecisionResult(success=True))
        mock_request = _MockDecisionRequest(request_id="ignored")
        mock_request.context.metadata = {}

        with (
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(), None),
            ),
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch("aragora.core.decision.DecisionRequest") as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = mock_request
            result = await handler.handle_post(
                "/api/v1/decisions/dec_own/retry", {}, _make_http_handler({})
            )

        new_id = _body(result)["request_id"]
        saved = mod._decision_results_fallback[new_id]
        assert saved["org_id"] == ORG
        assert saved["created_by"] == USER

    @pytest.mark.asyncio
    async def test_create_saves_with_caller_org_and_user(self, handler):
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=_MockDecisionResult(success=True))

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch("aragora.core.decision.DecisionRequest") as mock_dr_cls,
            patch(f"{_HANDLER}._claim_result", return_value="pending") as mock_claim,
            patch(f"{_HANDLER}._save_result_if_status", return_value=True) as mock_save,
        ):
            mock_dr_cls.from_http.return_value = _MockDecisionRequest(request_id="dec_created")
            result = await handler.handle_post(
                "/api/v1/decisions", {}, _make_http_handler({"content": "Q?"})
            )

        assert _status(result) == 200
        claim = mock_claim.call_args
        assert (claim.args[0], claim.args[1]["status"]) == ("dec_created", "pending")
        assert claim.kwargs == {"org_id": ORG, "created_by": USER}
        save = mock_save.call_args
        assert (save.args[0], save.args[1]["status"]) == ("dec_created", "completed")
        assert save.kwargs == {"org_id": ORG, "expected_status": "pending"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "route_error",
        [None, asyncio.TimeoutError(), RuntimeError("boom")],
        ids=["routed", "timeout", "failed"],
    )
    @pytest.mark.parametrize("owner", [OTHER_ORG, None])
    async def test_create_reusing_unowned_request_id_is_identical_to_missing(
        self, handler, mock_http_handler, tmp_path, owner, route_error
    ):
        import aragora.server.handlers.decision as mod

        store = _real_store(mod, tmp_path)
        store.save(
            "dec_taken",
            {"status": "completed", "result": {"answer": "owner answer"}},
            org_id=owner,
            created_by="owner-user",
        )
        before = store.get("dec_taken")
        mock_router = MagicMock()
        mock_router.route = AsyncMock(
            return_value=_MockDecisionResult(answer="caller answer"), side_effect=route_error
        )

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router",
                return_value=mock_router,
            ),
            patch(
                "aragora.server.handlers.decision.DecisionHandler.require_permission_or_error",
                return_value=(MagicMock(), None),
            ),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MagicMock(authenticated=False),
            ),
            patch("aragora.core.decision.DecisionRequest") as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = _MockDecisionRequest(request_id="dec_taken")
            result = await handler.handle_post(
                "/api/v1/decisions", {}, _make_http_handler({"content": "Q?"})
            )
        missing = handler.handle("/api/v1/decisions/dec_missing", {}, mock_http_handler)

        assert _status(result) == _status(missing) == 404
        assert _body(result) == _body(missing) == NOT_FOUND_BODY
        mock_router.route.assert_not_awaited()
        assert store.get("dec_taken") == before
        fresh = type(store)(db_path=tmp_path / "decision_results.db").get("dec_taken")
        assert (fresh["result"], fresh["org_id"]) == ({"answer": "owner answer"}, owner)
        assert mod._decision_results_fallback == {}

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_anonymous_post_is_rejected(self, handler):
        _use_fallback_only()
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=MagicMock(is_authenticated=False),
        ):
            result = await handler.handle_post(
                "/api/v1/decisions", {}, _make_http_handler({"content": "Q?"})
            )

        assert _status(result) == 401
        assert _body(result) == {"error": "Authentication required", "code": "auth_required"}

    @pytest.mark.no_auto_auth
    def test_anonymous_get_is_rejected(self, handler):
        _use_fallback_only()
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=MagicMock(is_authenticated=False),
        ):
            result = handler.handle("/api/v1/decisions", {}, _make_http_handler())

        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_authenticated_user_without_org_is_rejected(self, handler):
        _use_fallback_only()
        user = MagicMock(is_authenticated=True, user_id=USER, org_id=None, role="admin")
        with patch("aragora.billing.jwt_auth.extract_user_from_request", return_value=user):
            result = await handler.handle_post(
                "/api/v1/decisions", {}, _make_http_handler({"content": "Q?"})
            )

        assert _status(result) == 403
        assert _body(result)["code"] == "org_required"


# ---------------------------------------------------------------------------
# Request id claim before routing, and atomic fallback ownership
# ---------------------------------------------------------------------------


_HANDLER = "aragora.server.handlers.decision"
_ALLOWED = (MagicMock(), None)


async def _post_with_attachment(handler, request_id: str, on_run=None):
    """POST a decision with an attachment through a real router with spy stores."""
    from aragora.core.decision import DecisionRouter

    runs: list[str] = []

    class _Arena:
        def __init__(self, environment, **kwargs):
            self.task = environment.task

        async def run(self):
            runs.append(self.task)
            if on_run:
                outcome = on_run()
                if inspect.isawaitable(outcome):
                    await outcome
            summary = lambda: "debate summary"  # noqa: E731 - DebateResult.summary is a method
            return SimpleNamespace(final_answer="ok", consensus_reached=True, summary=summary)

    doc_store = MagicMock()
    router = DecisionRouter(
        debate_engine=_Arena,
        document_store=doc_store,
        enable_caching=False,
        enable_deduplication=False,
    )
    router._maybe_build_decision_integrity = AsyncMock(return_value=None)
    body = {
        "request_id": request_id,
        "content": "Should we ship the attached plan?",
        "decision_type": "debate",
        "config": {"agents": [], "use_knowledge_mound": False},
        "attachments": [{"filename": "plan.txt", "content": "Ship on Friday."}],
    }
    with (
        patch(f"{_HANDLER}._get_decision_router", return_value=router),
        patch(f"{_HANDLER}.DecisionHandler.require_permission_or_error", return_value=_ALLOWED),
    ):
        result = await handler.handle_post("/api/v1/decisions", {}, _make_http_handler(body))
    return result, doc_store, runs


class TestCreateClaimsRequestIdFirst:
    """A create claims its request id for the caller's org before anything is routed."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("owner", [OTHER_ORG, None])
    @pytest.mark.parametrize("store_mode", ["durable", "fallback"])
    async def test_unowned_request_id_is_refused_before_routing(
        self, handler, mock_http_handler, tmp_path, store_mode, owner
    ):
        import aragora.server.handlers.decision as mod

        if store_mode == "durable":
            store = _real_store(mod, tmp_path)
            store.save("dec_taken", {"status": "completed"}, org_id=owner, created_by="owner-user")
            read = lambda: type(store)(db_path=tmp_path / "decision_results.db").get("dec_taken")
        else:
            _seed(_use_fallback_only(), "dec_taken", owner, status="completed")
            read = lambda: dict(mod._decision_results_fallback["dec_taken"])
        before = read()

        result, doc_store, runs = await _post_with_attachment(handler, "dec_taken")
        missing = handler.handle("/api/v1/decisions/dec_missing", {}, mock_http_handler)

        assert _status(result) == _status(missing) == 404
        assert _body(result) == _body(missing) == NOT_FOUND_BODY
        doc_store.add.assert_not_called()
        assert runs == []
        assert read() == before

    @pytest.mark.asyncio
    @pytest.mark.parametrize("store_mode", ["durable", "fallback"])
    async def test_owner_create_is_pending_while_routing_then_completed(
        self, handler, tmp_path, store_mode
    ):
        import aragora.server.handlers.decision as mod

        _real_store(mod, tmp_path) if store_mode == "durable" else _use_fallback_only()
        seen = []

        def during_routing():
            for org in (ORG, OTHER_ORG):
                seen.append((mod._get_result("dec_fresh", org) or {}).get("status"))

        result, doc_store, runs = await _post_with_attachment(handler, "dec_fresh", during_routing)

        assert (_status(result), _body(result)["status"]) == (200, "completed")
        doc_store.add.assert_called_once()
        assert len(runs) == 1
        assert seen == ["pending", None]
        saved = mod._get_result("dec_fresh", ORG)
        assert (saved["status"], saved["org_id"], saved["created_by"]) == ("completed", ORG, USER)
        assert _body(result)["reasoning"] == saved["result"]["reasoning"] == "debate summary"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [LookupError("boom"), asyncio.CancelledError()],
        ids=["unexpected-error", "cancelled"],
    )
    async def test_routing_error_leaves_the_claim_failed_and_retryable(self, handler, error):
        mod = _use_fallback_only()
        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=[error, _MockDecisionResult(success=True)])
        retry_request = _MockDecisionRequest(request_id="ignored")
        retry_request.context.metadata = {}

        with (
            patch(f"{_HANDLER}._get_decision_router", return_value=mock_router),
            patch(f"{_HANDLER}.DecisionHandler.require_permission_or_error", return_value=_ALLOWED),
            patch("aragora.core.decision.DecisionRequest") as mock_dr_cls,
        ):
            first_request = _MockDecisionRequest(request_id="dec_broken")
            mock_dr_cls.from_http.side_effect = [first_request, retry_request]
            with suppress(asyncio.CancelledError):
                await handler.handle_post(
                    "/api/v1/decisions", {}, _make_http_handler({"content": "Q?"})
                )
            stored = dict(mod._decision_results_fallback.get("dec_broken") or {})
            retried = await handler.handle_post(
                "/api/v1/decisions/dec_broken/retry", {}, _make_http_handler({})
            )

        assert (stored.get("status"), stored.get("org_id")) == ("failed", ORG)
        assert _status(retried) == 200
        assert _body(retried)["retried_from"] == "dec_broken"


def test_concurrent_fallback_claims_of_a_new_id_have_one_owner(monkeypatch):
    """B claims while A is paused between reading and writing: A keeps the id."""
    from tests.utils.interleave import PausingDict, race

    mod = _use_fallback_only()
    racy = PausingDict()
    monkeypatch.setattr(mod, "_decision_results_fallback", racy)

    claim = lambda org: mod._save_result("dec_race", {"status": "pending"}, org_id=org)

    assert race(racy, claim, ORG, OTHER_ORG) == {ORG: True, OTHER_ORG: False}
    assert racy.writes == [ORG]
    assert racy["dec_race"]["org_id"] == ORG


# ---------------------------------------------------------------------------
# Cancel and request id reuse while a decision is routing
# ---------------------------------------------------------------------------


def _use_store_mode(mod, tmp_path, store_mode: str):
    """Use a durable store or the in-memory fallback; return a reader that skips caches."""
    if store_mode == "durable":
        store = _real_store(mod, tmp_path)
        return lambda request_id: type(store)(db_path=tmp_path / "decision_results.db").get(
            request_id
        )
    _use_fallback_only()
    return lambda request_id: _copy_record(mod._decision_results_fallback.get(request_id))


def _copy_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if record is None else json.loads(json.dumps(record))


async def _post_action(handler, request_id: str, action: str, body: dict | None = None):
    with patch(f"{_HANDLER}.DecisionHandler.require_permission_or_error", return_value=_ALLOWED):
        return await handler.handle_post(
            f"/api/v1/decisions/{request_id}/{action}", {}, _make_http_handler(body or {})
        )


class TestCancelDuringRouting:
    """A cancel during routing sticks, and a retry cannot run the decision a second time."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("store_mode", ["durable", "fallback"])
    async def test_late_routing_result_does_not_overwrite_the_cancel(
        self, handler, tmp_path, store_mode
    ):
        import aragora.server.handlers.decision as mod

        read = _use_store_mode(mod, tmp_path, store_mode)
        cancels = []

        async def cancel_while_routing():
            cancels.append(await _post_action(handler, "dec_cancel", "cancel", {"reason": "no"}))

        result, _doc_store, runs = await _post_with_attachment(
            handler, "dec_cancel", cancel_while_routing
        )

        assert [_status(c) for c in cancels] == [200]
        assert len(runs) == 1
        assert _status(result) == 409
        assert (_body(result)["request_id"], _body(result)["status"]) == ("dec_cancel", "cancelled")
        stored = read("dec_cancel")
        assert (stored["status"], stored["org_id"]) == ("cancelled", ORG)
        assert "answer" not in stored["result"]
        assert _status(await _post_action(handler, "dec_cancel", "cancel")) == 409

    @pytest.mark.asyncio
    @pytest.mark.parametrize("store_mode", ["durable", "fallback"])
    async def test_cancel_does_not_overwrite_a_result_saved_after_it_read_pending(
        self, handler, tmp_path, store_mode
    ):
        import aragora.server.handlers.decision as mod

        read = _use_store_mode(mod, tmp_path, store_mode)
        assert mod._save_result(
            "dec_raced",
            {"request_id": "dec_raced", "status": "pending", "result": {}},
            org_id=ORG,
            created_by=USER,
        )
        stale = _copy_record(mod._get_result("dec_raced", ORG))
        assert mod._save_result_if_status(
            "dec_raced",
            {"request_id": "dec_raced", "status": "completed", "result": {"answer": "done"}},
            org_id=ORG,
            expected_status="pending",
        )
        real_get = mod._get_result
        stale_reads = iter([stale])

        def get_result(request_id, org_id):
            return next(stale_reads, None) or real_get(request_id, org_id)

        with patch(f"{_HANDLER}._get_result", side_effect=get_result):
            cancelled = await _post_action(handler, "dec_raced", "cancel")

        assert _status(cancelled) == 409
        assert "'completed'" in _body(cancelled)["error"]
        stored = read("dec_raced")
        assert (stored["status"], stored["result"]["answer"]) == ("completed", "done")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("store_mode", ["durable", "fallback"])
    async def test_retry_is_refused_until_the_cancelled_run_stops(
        self, handler, tmp_path, store_mode
    ):
        import aragora.server.handlers.decision as mod

        read = _use_store_mode(mod, tmp_path, store_mode)
        during = []

        async def cancel_then_retry():
            if during:
                return
            for action in ("cancel", "retry"):
                during.append(await _post_action(handler, "dec_twice", action))

        result, _doc_store, runs = await _post_with_attachment(
            handler, "dec_twice", cancel_then_retry
        )

        assert [_status(r) for r in during] == [200, 409]
        assert "running" in _body(during[1])["error"]
        assert len(runs) == 1
        assert _status(result) == 409
        assert read("dec_twice")["status"] == "cancelled"

        later_router = MagicMock()
        later_router.route = AsyncMock(return_value=_MockDecisionResult(success=True))
        with patch(f"{_HANDLER}._get_decision_router", return_value=later_router):
            retried = await _post_action(handler, "dec_twice", "retry")

        assert _status(retried) == 200
        assert _body(retried)["retried_from"] == "dec_twice"
        later_router.route.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("store_mode", ["durable", "fallback"])
    async def test_reusing_a_completed_request_id_keeps_its_result_while_routing(
        self, handler, tmp_path, store_mode
    ):
        import aragora.server.handlers.decision as mod

        read = _use_store_mode(mod, tmp_path, store_mode)
        assert mod._save_result(
            "dec_done",
            {"request_id": "dec_done", "status": "completed", "result": {"answer": "first"}},
            org_id=ORG,
            created_by=USER,
        )
        seen = []

        result, _doc_store, runs = await _post_with_attachment(
            handler, "dec_done", lambda: seen.append(read("dec_done"))
        )

        assert [(s["status"], s["result"].get("answer")) for s in seen] == [("completed", "first")]
        assert (_status(result), _body(result)["status"]) == (200, "completed")
        assert len(runs) == 1
        stored = read("dec_done")
        assert (stored["status"], stored["org_id"], stored["created_by"]) == (
            "completed",
            ORG,
            USER,
        )
        assert stored["result"]["answer"] == _body(result)["answer"] != "first"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("store_mode", ["durable", "fallback"])
    async def test_interrupted_reuse_of_a_completed_request_id_keeps_its_result(
        self, handler, tmp_path, store_mode
    ):
        import aragora.server.handlers.decision as mod

        read = _use_store_mode(mod, tmp_path, store_mode)
        assert mod._save_result(
            "dec_done",
            {"request_id": "dec_done", "status": "completed", "result": {"answer": "first"}},
            org_id=ORG,
            created_by=USER,
        )
        before = read("dec_done")
        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=asyncio.CancelledError())

        with (
            patch(f"{_HANDLER}._get_decision_router", return_value=mock_router),
            patch(f"{_HANDLER}.DecisionHandler.require_permission_or_error", return_value=_ALLOWED),
            patch("aragora.core.decision.DecisionRequest") as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = _MockDecisionRequest(request_id="dec_done")
            with pytest.raises(asyncio.CancelledError):
                await handler.handle_post(
                    "/api/v1/decisions", {}, _make_http_handler({"content": "Q?"})
                )

        assert read("dec_done") == before

    @pytest.mark.asyncio
    async def test_store_error_while_recording_an_interrupted_run_keeps_the_interruption(
        self, handler, tmp_path, monkeypatch
    ):
        import aragora.server.handlers.decision as mod
        from aragora.storage.decision_result_store import DecisionResultStore

        holder = MagicMock()
        holder.get.return_value = DecisionResultStore(
            db_path=tmp_path / "decision_results.db", ttl_seconds=3600
        )
        monkeypatch.setattr(mod, "_decision_result_store", holder)
        broken = MagicMock()
        for name in ("save", "claim", "save_if_status", "get", "get_for_org"):
            getattr(broken, name).side_effect = sqlite3.OperationalError("database is locked")

        async def route(_request):
            holder.get.return_value = broken
            raise asyncio.CancelledError()

        mock_router = MagicMock()
        mock_router.route = route

        with (
            patch(f"{_HANDLER}._get_decision_router", return_value=mock_router),
            patch(f"{_HANDLER}.DecisionHandler.require_permission_or_error", return_value=_ALLOWED),
            patch("aragora.core.decision.DecisionRequest") as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = _MockDecisionRequest(request_id="dec_lost")
            with pytest.raises(asyncio.CancelledError):
                await handler.handle_post(
                    "/api/v1/decisions", {}, _make_http_handler({"content": "Q?"})
                )


# ---------------------------------------------------------------------------
# Store capacity on the create and cancel paths
# ---------------------------------------------------------------------------


def _capped_store(monkeypatch, tmp_path, max_entries: int):
    """A real durable store holding at most ``max_entries`` live results."""
    import aragora.server.handlers.decision as mod
    from aragora.storage.decision_result_store import DecisionResultStore

    store = DecisionResultStore(
        db_path=tmp_path / "decision_results.db", ttl_seconds=3600, max_entries=max_entries
    )
    holder = MagicMock()
    holder.get.return_value = store
    monkeypatch.setattr(mod, "_decision_result_store", holder)
    return store


def _durable_statuses(tmp_path) -> list[tuple[str, str]]:
    with closing(sqlite3.connect(tmp_path / "decision_results.db")) as conn:
        return conn.execute(
            "SELECT request_id, status FROM decision_results ORDER BY created_at"
        ).fetchall()


class TestStoreCapacityOnCreate:
    """Creates keep the store within max_entries without losing a decision that is routing."""

    @pytest.mark.asyncio
    async def test_creates_keep_the_store_within_max_entries(self, handler, tmp_path, monkeypatch):
        store = _capped_store(monkeypatch, tmp_path, max_entries=3)

        for i in range(5):
            result, _doc_store, _runs = await _post_with_attachment(handler, f"dec_cap_{i}")
            assert (_status(result), _body(result)["status"]) == (200, "completed")
            assert len(_durable_statuses(tmp_path)) <= 3

        assert _durable_statuses(tmp_path) == [(f"dec_cap_{i}", "completed") for i in range(2, 5)]
        assert type(store)(db_path=tmp_path / "decision_results.db").count() == 3

    @pytest.mark.asyncio
    async def test_resubmit_of_a_completed_id_under_capacity_pressure_keeps_its_result(
        self, handler, tmp_path, monkeypatch
    ):
        import aragora.server.handlers.decision as mod

        store = _capped_store(monkeypatch, tmp_path, max_entries=2)
        assert mod._save_result(
            "dec_reuse",
            {"request_id": "dec_reuse", "status": "completed", "result": {"answer": "first"}},
            org_id=ORG,
            created_by=USER,
        )
        during = []

        async def same_id_again_then_other_creates():
            for request_id in ("dec_reuse", "dec_other_0", "dec_other_1"):
                during.append((await _post_with_attachment(handler, request_id))[0])
                assert ("dec_reuse", "completed") in _durable_statuses(tmp_path)

        result, _doc_store, runs = await _post_with_attachment(
            handler, "dec_reuse", same_id_again_then_other_creates
        )

        assert [_status(r) for r in during] == [409, 200, 200]
        assert len(runs) == 1
        assert (_status(result), _body(result)["status"]) == (200, "completed")
        stored = store.get_for_org("dec_reuse", ORG)
        assert stored["result"]["answer"] == _body(result)["answer"] != "first"
        assert _durable_statuses(tmp_path) == [
            ("dec_reuse", "completed"),
            ("dec_other_1", "completed"),
        ]
        assert store._routing_ids == set()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [asyncio.CancelledError(), LookupError("boom"), RuntimeError("provider down")],
        ids=["cancelled", "unexpected-error", "routing-error"],
    )
    @pytest.mark.parametrize("stored_status", ["completed", None], ids=["resubmit", "new-id"])
    async def test_a_cancelled_or_failed_route_leaves_no_pin(
        self, handler, tmp_path, monkeypatch, error, stored_status
    ):
        import aragora.server.handlers.decision as mod

        store = _capped_store(monkeypatch, tmp_path, max_entries=2)
        if stored_status:
            record = {"request_id": "dec_pin", "status": stored_status}
            assert mod._save_result("dec_pin", record, org_id=ORG, created_by=USER)
        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=error)

        with (
            patch(f"{_HANDLER}._get_decision_router", return_value=mock_router),
            patch(f"{_HANDLER}.DecisionHandler.require_permission_or_error", return_value=_ALLOWED),
            patch("aragora.core.decision.DecisionRequest") as mock_dr_cls,
        ):
            mock_dr_cls.from_http.return_value = _MockDecisionRequest(request_id="dec_pin")
            with suppress(asyncio.CancelledError, LookupError):
                await handler.handle_post(
                    "/api/v1/decisions", {}, _make_http_handler({"content": "Q?"})
                )

        mock_router.route.assert_awaited_once()
        assert store._routing_ids == set()

    @pytest.mark.asyncio
    async def test_cancel_during_routing_still_answers_409_under_capacity_pressure(
        self, handler, tmp_path, monkeypatch
    ):
        store = _capped_store(monkeypatch, tmp_path, max_entries=1)
        during = []

        async def another_create_then_cancel():
            other, _doc_store, _runs = await _post_with_attachment(handler, "dec_other")
            during.append(other)
            during.append(await _post_action(handler, "dec_cancel", "cancel", {"reason": "no"}))

        result, _doc_store, runs = await _post_with_attachment(
            handler, "dec_cancel", another_create_then_cancel
        )

        assert [_status(r) for r in during] == [200, 200]
        assert len(runs) == 1
        assert _status(result) == 409
        assert (_body(result)["request_id"], _body(result)["status"]) == ("dec_cancel", "cancelled")
        assert _durable_statuses(tmp_path) == [("dec_cancel", "cancelled")]
        assert store._routing_ids == set()


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------


class TestModuleExports:
    """Tests for module-level exports and structure."""

    def test_all_exports(self):
        """Verify __all__ contains DecisionHandler."""
        import aragora.server.handlers.decision as mod

        assert "DecisionHandler" in mod.__all__

    def test_handler_has_required_methods(self, handler):
        """Handler has can_handle, handle, and handle_post."""
        assert hasattr(handler, "can_handle")
        assert hasattr(handler, "handle")
        assert hasattr(handler, "handle_post")
        assert callable(handler.can_handle)
        assert callable(handler.handle)
        assert callable(handler.handle_post)
