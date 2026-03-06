"""
Tests for aragora.server.handlers.approvals_inbox - Unified approvals inbox handler.

Tests cover:
- Instantiation and ROUTES
- can_handle() route matching
- GET /api/v1/approvals - list pending approvals
- GET /api/v1/approvals/pending - alias route
- Method not allowed on non-GET
- Permission checks (approval:read)
- Status filter (only 'pending' supported)
- Limit and sources query params
- Error handling when collect_pending_approvals fails
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.approvals_inbox import UnifiedApprovalsHandler


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def handler():
    """Create an UnifiedApprovalsHandler with mocked context."""
    ctx: dict[str, Any] = {"storage": MagicMock()}
    return UnifiedApprovalsHandler(ctx)


@pytest.fixture
def mock_http_get():
    """Create a mock HTTP GET handler."""
    mock = MagicMock()
    mock.command = "GET"
    mock.client_address = ("127.0.0.1", 12345)
    mock.headers = {"Authorization": "Bearer test-token"}
    return mock


@pytest.fixture
def mock_http_post():
    """Create a mock HTTP POST handler."""
    mock = MagicMock()
    mock.command = "POST"
    mock.client_address = ("127.0.0.1", 12345)
    mock.headers = {"Authorization": "Bearer test-token"}
    return mock


# ===========================================================================
# Instantiation and Routes
# ===========================================================================


class TestUnifiedApprovalsHandlerSetup:
    """Tests for handler instantiation and route registration."""

    def test_instantiation(self, handler):
        """Should create handler with context."""
        assert handler is not None
        assert hasattr(handler, "ctx")

    def test_routes_defined(self):
        """Should define expected ROUTES."""
        assert "/api/v1/approvals" in UnifiedApprovalsHandler.ROUTES
        assert "/api/v1/approvals/pending" in UnifiedApprovalsHandler.ROUTES

    def test_routes_count(self):
        """Should have exactly 2 routes."""
        assert len(UnifiedApprovalsHandler.ROUTES) == 2


# ===========================================================================
# can_handle
# ===========================================================================


class TestCanHandle:
    """Tests for can_handle route matching."""

    def test_can_handle_approvals(self, handler):
        """Should handle /api/v1/approvals."""
        assert handler.can_handle("/api/v1/approvals") is True

    def test_can_handle_approvals_pending(self, handler):
        """Should handle /api/v1/approvals/pending."""
        assert handler.can_handle("/api/v1/approvals/pending") is True

    def test_cannot_handle_unknown_path(self, handler):
        """Should not handle unknown paths."""
        assert handler.can_handle("/api/v1/unknown") is False
        assert handler.can_handle("/api/v1/approvals/other") is False

    def test_cannot_handle_different_api(self, handler):
        """Should not handle unrelated API paths."""
        assert handler.can_handle("/api/v1/debates") is False
        assert handler.can_handle("/api/v1/budgets") is False


# ===========================================================================
# Method Not Allowed
# ===========================================================================


class TestMethodNotAllowed:
    """Tests for non-GET method rejection."""

    def test_post_returns_405(self, handler, mock_http_post):
        """Should reject POST requests with 405."""
        result = handler.handle("/api/v1/approvals", {}, mock_http_post)
        assert result.status_code == 405

    def test_put_returns_405(self, handler):
        """Should reject PUT requests with 405."""
        mock = MagicMock()
        mock.command = "PUT"
        result = handler.handle("/api/v1/approvals", {}, mock)
        assert result.status_code == 405


# ===========================================================================
# Permission Checks
# ===========================================================================


class TestPermissionChecks:
    """Tests for RBAC permission enforcement."""

    def test_missing_permission_returns_error(self, handler, mock_http_get):
        """Should return 401/403 when permission check fails."""
        with patch.object(
            handler,
            "require_permission_or_error",
            return_value=(None, MagicMock(status_code=403, body=b'{"error":"Forbidden"}')),
        ):
            result = handler.handle("/api/v1/approvals", {}, mock_http_get)
            assert result.status_code == 403


# ===========================================================================
# Successful Listing
# ===========================================================================


class TestListApprovals:
    """Tests for GET approvals listing."""

    def test_list_pending_approvals_success(self, handler, mock_http_get):
        """Should return pending approvals list."""
        mock_user = MagicMock()
        mock_user.user_id = "user-123"

        mock_approvals = [
            {"id": "approval-1", "type": "workflow", "status": "pending"},
            {"id": "approval-2", "type": "decision_plan", "status": "pending"},
        ]

        with patch.object(handler, "require_permission_or_error", return_value=(mock_user, None)):
            with patch(
                "aragora.approvals.inbox.collect_pending_approvals",
                return_value=mock_approvals,
            ):
                result = handler.handle("/api/v1/approvals", {}, mock_http_get)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["count"] == 2
        assert len(data["approvals"]) == 2
        assert data["requested_by"] == "user-123"

    def test_list_with_limit_param(self, handler, mock_http_get):
        """Should pass limit to collect_pending_approvals."""
        mock_user = MagicMock()
        mock_user.user_id = "user-1"

        with patch.object(handler, "require_permission_or_error", return_value=(mock_user, None)):
            with patch(
                "aragora.approvals.inbox.collect_pending_approvals",
                return_value=[],
            ) as mock_collect:
                handler.handle("/api/v1/approvals", {"limit": "50"}, mock_http_get)
                mock_collect.assert_called_once_with(limit=50, sources=None)

    def test_list_with_sources_filter(self, handler, mock_http_get):
        """Should pass sources filter to collect function."""
        mock_user = MagicMock()
        mock_user.user_id = "user-1"

        with patch.object(handler, "require_permission_or_error", return_value=(mock_user, None)):
            with patch(
                "aragora.approvals.inbox.collect_pending_approvals",
                return_value=[],
            ) as mock_collect:
                handler.handle(
                    "/api/v1/approvals",
                    {"source": "workflow,gateway"},
                    mock_http_get,
                )
                mock_collect.assert_called_once_with(limit=100, sources=["workflow", "gateway"])

    def test_default_sources_in_response(self, handler, mock_http_get):
        """Should include default sources when none specified."""
        mock_user = MagicMock()
        mock_user.user_id = "user-1"

        with patch.object(handler, "require_permission_or_error", return_value=(mock_user, None)):
            with patch(
                "aragora.approvals.inbox.collect_pending_approvals",
                return_value=[],
            ):
                result = handler.handle("/api/v1/approvals", {}, mock_http_get)

        data = json.loads(result.body)
        assert "workflow" in data["sources"]
        assert "decision_plan" in data["sources"]
        assert "computer_use" in data["sources"]
        assert "gateway" in data["sources"]
        assert "inbox_wedge" in data["sources"]

    def test_status_non_pending_returns_400(self, handler, mock_http_get):
        """Should reject non-pending status filter."""
        mock_user = MagicMock()
        mock_user.user_id = "user-1"

        with patch.object(handler, "require_permission_or_error", return_value=(mock_user, None)):
            result = handler.handle(
                "/api/v1/approvals",
                {"status": "completed"},
                mock_http_get,
            )

        assert result.status_code == 400

    def test_pending_route_alias(self, handler, mock_http_get):
        """Should serve the /pending route the same as base route."""
        mock_user = MagicMock()
        mock_user.user_id = "user-1"

        with patch.object(handler, "require_permission_or_error", return_value=(mock_user, None)):
            with patch(
                "aragora.approvals.inbox.collect_pending_approvals",
                return_value=[],
            ):
                result = handler.handle("/api/v1/approvals/pending", {}, mock_http_get)

        assert result.status_code == 200


# ===========================================================================
# Error Handling
# ===========================================================================


class TestErrorHandling:
    """Tests for error cases."""

    def test_collect_failure_returns_500(self, handler, mock_http_get):
        """Should return 500 when approval collection fails."""
        mock_user = MagicMock()
        mock_user.user_id = "user-1"

        with patch.object(handler, "require_permission_or_error", return_value=(mock_user, None)):
            with patch(
                "aragora.approvals.inbox.collect_pending_approvals",
                side_effect=RuntimeError("DB connection failed"),
            ):
                result = handler.handle("/api/v1/approvals", {}, mock_http_get)

        assert result.status_code == 500
        data = json.loads(result.body)
        assert "Failed" in data.get("error", "")
