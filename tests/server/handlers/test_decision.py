"""
Tests for Decision Handler HTTP API.

Tests cover:
- Route matching (can_handle)
- GET /api/v1/decisions - List decisions
- GET /api/v1/decisions/:id - Get decision by ID
- GET /api/v1/decisions/:id/status - Get decision status
- POST /api/v1/decisions/:id/cancel - Cancel decision
- POST /api/v1/decisions/:id/retry - Retry decision
- Permission checks
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.decision import (
    DecisionHandler,
    _decision_results_fallback,
    _get_result,
    _save_result,
)
from aragora.tenancy.record_scope import OrgScope

ORG = "test-org-001"
USER = "test-user-001"
SCOPE = OrgScope(org_id=ORG, user_id=USER, role="admin")


# ===========================================================================
# Helper Functions
# ===========================================================================


def parse_result(result) -> dict:
    """Parse HandlerResult body to get response data."""
    body = result.body
    if isinstance(body, bytes):
        return json.loads(body.decode("utf-8"))
    return json.loads(body)


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def handler():
    """Create a DecisionHandler instance."""
    # Pass empty dict as server_context
    return DecisionHandler({})


@pytest.fixture
def clear_fallback():
    """Clear the fallback cache before and after each test."""
    _decision_results_fallback.clear()
    yield
    _decision_results_fallback.clear()


@pytest.fixture
def mock_handler():
    """Create a mock HTTP handler for POST requests."""
    handler = MagicMock()
    handler.headers = {}
    return handler


@pytest.fixture
def auth_context():
    """Create an authorization context fixture."""
    from aragora.rbac.models import AuthorizationContext

    return AuthorizationContext(
        user_id="test-user",
        org_id="test-org",
        roles={"admin"},
        permissions={"decisions:read", "decisions:create", "decisions:update"},
    )


# ===========================================================================
# Test Route Matching
# ===========================================================================


class TestCanHandle:
    """Tests for route matching."""

    def test_handles_base_path(self, handler):
        """Matches /api/v1/decisions."""
        assert handler.can_handle("/api/v1/decisions") is True

    def test_handles_decision_id(self, handler):
        """Matches /api/v1/decisions/:id."""
        assert handler.can_handle("/api/v1/decisions/dec_123abc") is True

    def test_handles_status_path(self, handler):
        """Matches /api/v1/decisions/:id/status."""
        assert handler.can_handle("/api/v1/decisions/dec_123abc/status") is True

    def test_handles_cancel_path(self, handler):
        """Matches /api/v1/decisions/:id/cancel."""
        assert handler.can_handle("/api/v1/decisions/dec_123abc/cancel") is True

    def test_handles_retry_path(self, handler):
        """Matches /api/v1/decisions/:id/retry."""
        assert handler.can_handle("/api/v1/decisions/dec_123abc/retry") is True

    def test_rejects_other_paths(self, handler):
        """Rejects unrelated paths."""
        assert handler.can_handle("/api/v1/other") is False
        assert handler.can_handle("/api/v1/debate") is False
        assert handler.can_handle("/api/v1/decision") is False  # singular


# ===========================================================================
# Test List Decisions
# ===========================================================================


class TestListDecisions:
    """Tests for GET /api/v1/decisions."""

    def test_returns_empty_list(self, handler, clear_fallback):
        """Returns empty list when no decisions exist."""
        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = handler._list_decisions({}, SCOPE)
            parsed = parse_result(result)

            assert "decisions" in parsed
            assert parsed["decisions"] == []
            assert parsed["total"] == 0

    def test_returns_decisions_from_fallback(self, handler, clear_fallback):
        """Returns decisions from fallback cache."""
        # Add some test decisions to fallback
        _decision_results_fallback["dec_001"] = {
            "request_id": "dec_001",
            "org_id": ORG,
            "status": "completed",
            "completed_at": "2024-01-01T12:00:00Z",
        }
        _decision_results_fallback["dec_002"] = {
            "request_id": "dec_002",
            "org_id": ORG,
            "status": "failed",
            "completed_at": "2024-01-02T12:00:00Z",
        }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = handler._list_decisions({}, SCOPE)
            parsed = parse_result(result)

            assert len(parsed["decisions"]) == 2
            assert parsed["total"] == 2

    def test_respects_limit(self, handler, clear_fallback):
        """Respects limit parameter."""
        for i in range(10):
            _decision_results_fallback[f"dec_{i:03d}"] = {
                "request_id": f"dec_{i:03d}",
                "org_id": ORG,
                "status": "completed",
            }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = handler._list_decisions({"limit": "3"}, SCOPE)
            parsed = parse_result(result)

            assert len(parsed["decisions"]) == 3

    def test_uses_persistent_store(self, handler, clear_fallback):
        """Uses persistent store when available."""
        mock_store = MagicMock()
        mock_store.list_recent_for_org.return_value = [
            {"request_id": "dec_001", "status": "completed"}
        ]
        mock_store.count_for_org.return_value = 1

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=mock_store
        ):
            result = handler._list_decisions({}, SCOPE)
            parsed = parse_result(result)

            assert len(parsed["decisions"]) == 1
            assert parsed["total"] == 1
            mock_store.list_recent_for_org.assert_called_once_with(ORG, 20)
            mock_store.count_for_org.assert_called_once_with(ORG)

    def test_excludes_other_org_fallback_entries(self, handler, clear_fallback):
        """Fallback listing only includes the caller org's decisions."""
        _decision_results_fallback["dec_mine"] = {"request_id": "dec_mine", "org_id": ORG}
        _decision_results_fallback["dec_theirs"] = {"request_id": "dec_theirs", "org_id": "o2"}

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            parsed = parse_result(handler._list_decisions({}, SCOPE))

            assert [d["request_id"] for d in parsed["decisions"]] == ["dec_mine"]
            assert parsed["total"] == 1


# ===========================================================================
# Test Get Decision
# ===========================================================================


class TestGetDecision:
    """Tests for GET /api/v1/decisions/:id."""

    def test_returns_decision_by_id(self, handler, clear_fallback):
        """Returns decision when found."""
        _decision_results_fallback["dec_123"] = {
            "request_id": "dec_123",
            "org_id": ORG,
            "status": "completed",
            "result": {"answer": "Test answer"},
        }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = handler._get_decision("dec_123", SCOPE)
            parsed = parse_result(result)

            assert parsed["request_id"] == "dec_123"
            assert parsed["status"] == "completed"

    def test_returns_404_when_not_found(self, handler, clear_fallback):
        """Returns 404 when decision not found."""
        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = handler._get_decision("nonexistent", SCOPE)
            parsed = parse_result(result)

            assert result.status_code == 404
            assert parsed == {"error": "Decision not found", "code": "not_found"}

    def test_returns_404_for_other_org(self, handler, clear_fallback):
        """Another org's decision is reported like a missing one."""
        _decision_results_fallback["dec_123"] = {"request_id": "dec_123", "org_id": "o2"}

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = handler._get_decision("dec_123", SCOPE)

            assert result.status_code == 404
            assert parse_result(result) == {"error": "Decision not found", "code": "not_found"}

    def test_uses_persistent_store(self, handler, clear_fallback):
        """Uses persistent store when available."""
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = {
            "request_id": "dec_123",
            "status": "completed",
            "org_id": ORG,
        }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=mock_store
        ):
            result = handler._get_decision("dec_123", SCOPE)
            parsed = parse_result(result)

            assert parsed["request_id"] == "dec_123"
            mock_store.get_for_org.assert_called_once_with("dec_123", ORG)


# ===========================================================================
# Test Get Decision Status
# ===========================================================================


class TestGetDecisionStatus:
    """Tests for GET /api/v1/decisions/:id/status."""

    def test_returns_status_from_fallback(self, handler, clear_fallback):
        """Returns status from fallback cache."""
        _decision_results_fallback["dec_123"] = {
            "request_id": "dec_123",
            "org_id": ORG,
            "status": "completed",
            "completed_at": "2024-01-01T12:00:00Z",
        }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = handler._get_decision_status("dec_123", SCOPE)
            parsed = parse_result(result)

            assert parsed["request_id"] == "dec_123"
            assert parsed["status"] == "completed"

    def test_returns_404_for_missing_decision(self, handler, clear_fallback):
        """A missing decision answers the standard not-found 404."""
        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = handler._get_decision_status("nonexistent", SCOPE)

            assert result.status_code == 404
            assert parse_result(result) == {"error": "Decision not found", "code": "not_found"}

    def test_uses_persistent_store(self, handler, clear_fallback):
        """Uses persistent store when available."""
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = {
            "request_id": "dec_123",
            "status": "running",
            "org_id": ORG,
        }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=mock_store
        ):
            result = handler._get_decision_status("dec_123", SCOPE)
            parsed = parse_result(result)

            assert parsed["status"] == "running"
            mock_store.get_for_org.assert_called_once_with("dec_123", ORG)
            mock_store.get_status.assert_not_called()


# ===========================================================================
# Test Cancel Decision
# ===========================================================================


class TestCancelDecision:
    """Tests for POST /api/v1/decisions/:id/cancel."""

    @pytest.mark.asyncio
    async def test_cancels_pending_decision(self, handler, clear_fallback, mock_handler):
        """Cancels a pending decision."""
        _decision_results_fallback["dec_123"] = {
            "request_id": "dec_123",
            "org_id": ORG,
            "status": "pending",
        }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = await handler._cancel_decision("dec_123", mock_handler, SCOPE)
            parsed = parse_result(result)

            assert parsed["request_id"] == "dec_123"
            assert parsed["status"] == "cancelled"
            assert "cancelled_at" in parsed

    @pytest.mark.asyncio
    async def test_cancels_running_decision(self, handler, clear_fallback, mock_handler):
        """Cancels a running decision."""
        _decision_results_fallback["dec_123"] = {
            "request_id": "dec_123",
            "org_id": ORG,
            "status": "running",
        }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = await handler._cancel_decision("dec_123", mock_handler, SCOPE)
            parsed = parse_result(result)

            assert parsed["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cannot_cancel_completed(self, handler, clear_fallback, mock_handler):
        """Cannot cancel a completed decision."""
        _decision_results_fallback["dec_123"] = {
            "request_id": "dec_123",
            "org_id": ORG,
            "status": "completed",
        }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = await handler._cancel_decision("dec_123", mock_handler, SCOPE)
            parsed = parse_result(result)

            assert result.status_code == 409
            assert "error" in parsed
            assert "Cannot cancel" in parsed["error"]

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, handler, clear_fallback, mock_handler):
        """Returns 404 for nonexistent decision."""
        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = await handler._cancel_decision("nonexistent", mock_handler, SCOPE)
            parsed = parse_result(result)

            assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_with_reason(self, handler, clear_fallback):
        """Includes cancellation reason if provided."""
        _decision_results_fallback["dec_123"] = {
            "request_id": "dec_123",
            "org_id": ORG,
            "status": "pending",
        }

        # Mock handler with reason in body
        mock_handler = MagicMock()
        handler.read_json_body_validated = MagicMock(
            return_value=({"reason": "User requested cancellation"}, None)
        )

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = await handler._cancel_decision("dec_123", mock_handler, SCOPE)
            parsed = parse_result(result)

            assert parsed["reason"] == "User requested cancellation"


# ===========================================================================
# Test Retry Decision
# ===========================================================================


class TestRetryDecision:
    """Tests for POST /api/v1/decisions/:id/retry."""

    @pytest.mark.asyncio
    async def test_cannot_retry_completed(self, handler, clear_fallback, mock_handler):
        """Cannot retry a completed decision."""
        _decision_results_fallback["dec_123"] = {
            "request_id": "dec_123",
            "org_id": ORG,
            "status": "completed",
        }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = await handler._retry_decision("dec_123", mock_handler, SCOPE)
            parsed = parse_result(result)

            assert result.status_code == 409
            assert "Cannot retry" in parsed["error"]

    @pytest.mark.asyncio
    async def test_retry_not_found(self, handler, clear_fallback, mock_handler):
        """Returns 404 for nonexistent decision."""
        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = await handler._retry_decision("nonexistent", mock_handler, SCOPE)
            parsed = parse_result(result)

            assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_failed_decision(self, handler, clear_fallback, mock_handler):
        """Can retry a failed decision."""
        _decision_results_fallback["dec_123"] = {
            "request_id": "dec_123",
            "org_id": ORG,
            "status": "failed",
            "result": {
                "request": {"content": "Test question", "decision_type": "auto"},
            },
        }

        # Mock the router
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.decision_type.value = "debate"
        mock_result.answer = "Test answer"
        mock_result.confidence = 0.9
        mock_result.consensus_reached = True
        mock_result.to_dict.return_value = {}

        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            with patch(
                "aragora.server.handlers.decision._get_decision_router", return_value=mock_router
            ):
                result = await handler._retry_decision("dec_123", mock_handler, SCOPE)
                parsed = parse_result(result)

                assert parsed["status"] == "completed"
                assert parsed["retried_from"] == "dec_123"
                assert "request_id" in parsed
                assert parsed["request_id"] != "dec_123"  # New ID

    @pytest.mark.asyncio
    async def test_retry_cancelled_decision(self, handler, clear_fallback, mock_handler):
        """Can retry a cancelled decision."""
        _decision_results_fallback["dec_123"] = {
            "request_id": "dec_123",
            "org_id": ORG,
            "status": "cancelled",
            "result": {
                "request": {"content": "Test question"},
            },
        }

        # Mock the router
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.decision_type.value = "quick"
        mock_result.answer = "Quick answer"
        mock_result.confidence = 0.8
        mock_result.consensus_reached = False
        mock_result.to_dict.return_value = {}

        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            with patch(
                "aragora.server.handlers.decision._get_decision_router", return_value=mock_router
            ):
                result = await handler._retry_decision("dec_123", mock_handler, SCOPE)
                parsed = parse_result(result)

                assert parsed["retried_from"] == "dec_123"

    @pytest.mark.asyncio
    async def test_retry_requires_content(self, handler, clear_fallback, mock_handler):
        """Returns error if original content not found."""
        _decision_results_fallback["dec_123"] = {
            "request_id": "dec_123",
            "org_id": ORG,
            "status": "failed",
            "result": {},  # No content
        }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = await handler._retry_decision("dec_123", mock_handler, SCOPE)
            parsed = parse_result(result)

            assert result.status_code == 400
            assert "content not found" in parsed["error"]

    @pytest.mark.asyncio
    async def test_retry_router_unavailable(self, handler, clear_fallback, mock_handler):
        """Returns 503 if router unavailable."""
        _decision_results_fallback["dec_123"] = {
            "request_id": "dec_123",
            "org_id": ORG,
            "status": "failed",
            "result": {"request": {"content": "Test"}},
        }

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            with patch("aragora.server.handlers.decision._get_decision_router", return_value=None):
                result = await handler._retry_decision("dec_123", mock_handler, SCOPE)
                parsed = parse_result(result)

                assert result.status_code == 503
                assert "not available" in parsed["error"]


# ===========================================================================
# Test Handle Method (GET routing)
# ===========================================================================


class TestHandleRouting:
    """Tests for GET request routing."""

    def test_routes_list_decisions(self, handler, clear_fallback):
        """Routes to list decisions."""
        with patch.object(handler, "_list_decisions") as mock_list:
            mock_list.return_value = MagicMock(body=b"{}", status_code=200)
            handler.handle("/api/v1/decisions", {})
            mock_list.assert_called_once_with({}, SCOPE)

    def test_routes_get_decision(self, handler, clear_fallback):
        """Routes to get decision by ID."""
        with patch.object(handler, "_get_decision") as mock_get:
            mock_get.return_value = MagicMock(body=b"{}", status_code=200)
            handler.handle("/api/v1/decisions/dec_123", {})
            mock_get.assert_called_once_with("dec_123", SCOPE)

    def test_routes_get_status(self, handler, clear_fallback):
        """Routes to get decision status."""
        with patch.object(handler, "_get_decision_status") as mock_status:
            mock_status.return_value = MagicMock(body=b"{}", status_code=200)
            handler.handle("/api/v1/decisions/dec_123/status", {})
            mock_status.assert_called_once_with("dec_123", SCOPE)

    def test_returns_none_for_unknown_path(self, handler):
        """Returns None for unknown paths."""
        result = handler.handle("/api/v1/other", {})
        assert result is None


# ===========================================================================
# Test Handle Post Method
# ===========================================================================


class TestHandlePost:
    """Tests for POST request routing."""

    @pytest.mark.asyncio
    async def test_routes_create_decision(self, handler, mock_handler):
        """Routes to create decision."""
        with patch.object(handler, "_create_decision") as mock_create:
            with patch.object(handler, "require_permission_or_error", return_value=(True, None)):
                mock_create.return_value = MagicMock(body=b"{}", status_code=200)
                await handler.handle_post("/api/v1/decisions", {}, mock_handler)
                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_cancel_decision(self, handler, mock_handler):
        """Routes to cancel decision."""
        with patch.object(handler, "_cancel_decision") as mock_cancel:
            with patch.object(handler, "require_permission_or_error", return_value=(True, None)):
                mock_cancel.return_value = MagicMock(body=b"{}", status_code=200)
                await handler.handle_post("/api/v1/decisions/dec_123/cancel", {}, mock_handler)
                mock_cancel.assert_called_once_with("dec_123", mock_handler, SCOPE)

    @pytest.mark.asyncio
    async def test_routes_retry_decision(self, handler, mock_handler):
        """Routes to retry decision."""
        with patch.object(handler, "_retry_decision") as mock_retry:
            with patch.object(handler, "require_permission_or_error", return_value=(True, None)):
                mock_retry.return_value = MagicMock(body=b"{}", status_code=200)
                await handler.handle_post("/api/v1/decisions/dec_123/retry", {}, mock_handler)
                mock_retry.assert_called_once_with("dec_123", mock_handler, SCOPE)

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_post_path(self, handler, mock_handler):
        """Returns None for unknown POST paths."""
        result = await handler.handle_post("/api/v1/other", {}, mock_handler)
        assert result is None


# ===========================================================================
# Test Helper Functions
# ===========================================================================


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_save_and_get_result(self, clear_fallback):
        """save_result and get_result work together."""
        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            _save_result("test_id", {"status": "completed"}, org_id=ORG, created_by=USER)
            result = _get_result("test_id", ORG)
            assert result["status"] == "completed"
            assert result["created_by"] == USER
            assert _get_result("test_id", "other-org") is None

    def test_get_result_returns_none_for_missing(self, clear_fallback):
        """get_result returns None for missing ID."""
        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=None
        ):
            result = _get_result("nonexistent", ORG)
            assert result is None

    def test_uses_persistent_store_for_save(self, clear_fallback):
        """Uses persistent store for save when available."""
        mock_store = MagicMock()

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=mock_store
        ):
            _save_result("test_id", {"status": "completed"}, org_id=ORG, created_by=USER)
            mock_store.save.assert_called_once_with(
                "test_id", {"status": "completed"}, org_id=ORG, created_by=USER
            )

    def test_falls_back_on_store_error(self, clear_fallback):
        """Falls back to in-memory on store error."""
        mock_store = MagicMock()
        mock_store.save.side_effect = ValueError("Store error")

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get", return_value=mock_store
        ):
            _save_result("test_id", {"status": "completed"})
            # Should be saved to fallback
            assert _decision_results_fallback["test_id"]["status"] == "completed"


# ===========================================================================
# Test ROUTES Class Attribute
# ===========================================================================


class TestRoutes:
    """Tests for handler route configuration."""

    def test_routes_defined(self, handler):
        """Handler has ROUTES defined."""
        assert hasattr(handler, "ROUTES")
        assert "/api/v1/decisions" in handler.ROUTES
        assert "/api/v1/decisions/*" in handler.ROUTES
