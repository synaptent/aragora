"""Tests for approvals inbox handler (aragora/server/handlers/approvals_inbox.py).

Covers all routes and behavior of the UnifiedApprovalsHandler class:
- can_handle() routing for ROUTES
- GET /api/v1/approvals
- GET /api/v1/approvals/pending
- Method not allowed (POST, PUT, DELETE, PATCH)
- Permission checks (approval:read)
- Status parameter validation (only "pending" allowed)
- Limit parameter with bounds (1-500, default 100)
- Source/sources filtering
- collect_pending_approvals success and error paths
- Response structure validation
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.approvals_inbox import UnifiedApprovalsHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: object) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result: object) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


class MockHTTPHandler:
    """Mock HTTP request handler for approvals inbox tests."""

    def __init__(
        self,
        body: dict | None = None,
        method: str = "GET",
    ):
        self.command = method
        self.client_address = ("127.0.0.1", 12345)
        self.headers: dict[str, str] = {"User-Agent": "test-agent"}
        self.rfile = MagicMock()

        if body:
            body_bytes = json.dumps(body).encode()
            self.rfile.read.return_value = body_bytes
            self.headers["Content-Length"] = str(len(body_bytes))
        else:
            self.rfile.read.return_value = b"{}"
            self.headers["Content-Length"] = "2"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create an UnifiedApprovalsHandler with empty server context."""
    return UnifiedApprovalsHandler(server_context={})


@pytest.fixture
def http_handler():
    """Create a mock HTTP handler with GET method."""
    return MockHTTPHandler(method="GET")


# ---------------------------------------------------------------------------
# can_handle routing tests
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for can_handle() route matching."""

    def test_handles_approvals_route(self, handler):
        assert handler.can_handle("/api/v1/approvals") is True

    def test_handles_approvals_pending_route(self, handler):
        assert handler.can_handle("/api/v1/approvals/pending") is True

    def test_rejects_unknown_route(self, handler):
        assert handler.can_handle("/api/v1/approvals/unknown") is False

    def test_rejects_empty_path(self, handler):
        assert handler.can_handle("") is False

    def test_rejects_partial_match(self, handler):
        assert handler.can_handle("/api/v1/approval") is False

    def test_rejects_extra_path_segments(self, handler):
        assert handler.can_handle("/api/v1/approvals/pending/extra") is False

    def test_rejects_different_version(self, handler):
        assert handler.can_handle("/api/v2/approvals") is False


# ---------------------------------------------------------------------------
# Method not allowed tests
# ---------------------------------------------------------------------------


class TestMethodNotAllowed:
    """Tests for non-GET methods returning 405."""

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
    def test_non_get_returns_405(self, handler, method):
        http = MockHTTPHandler(method=method)
        result = handler.handle("/api/v1/approvals", {}, http)
        assert _status(result) == 405
        assert "Method not allowed" in _body(result)["error"]

    def test_get_does_not_return_405(self, handler, http_handler):
        with patch(
            "aragora.server.handlers.approvals_inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            with patch(
                "aragora.approvals.inbox.collect_pending_approvals",
                return_value=[],
                create=True,
            ):
                result = handler.handle("/api/v1/approvals", {}, http_handler)
                assert _status(result) != 405


# ---------------------------------------------------------------------------
# Permission check tests
# ---------------------------------------------------------------------------


class TestPermissions:
    """Tests for approval:read permission enforcement."""

    @pytest.mark.no_auto_auth
    def test_unauthenticated_returns_401(self, handler):
        """Without auto-auth, unauthenticated users get 401."""
        http = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/approvals", {}, http)
        assert _status(result) in (401, 403)

    def test_authenticated_user_can_access(self, handler, http_handler):
        """With auto-auth (admin), user can access approvals."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            assert _status(result) == 200


# ---------------------------------------------------------------------------
# Status parameter tests
# ---------------------------------------------------------------------------


class TestStatusParameter:
    """Tests for the status query parameter."""

    def test_default_status_is_pending(self, handler, http_handler):
        """When no status param, defaults to pending (succeeds)."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            assert _status(result) == 200

    def test_explicit_pending_status(self, handler, http_handler):
        """Explicit status=pending succeeds."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {"status": "pending"}, http_handler)
            assert _status(result) == 200

    def test_pending_status_case_insensitive(self, handler, http_handler):
        """Status=PENDING (uppercase) should work (lowered internally)."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {"status": "PENDING"}, http_handler)
            assert _status(result) == 200

    def test_mixed_case_pending(self, handler, http_handler):
        """Status=Pending (mixed case) should work."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {"status": "Pending"}, http_handler)
            assert _status(result) == 200

    def test_approved_status_returns_400(self, handler, http_handler):
        """Only pending is supported; 'approved' returns 400."""
        result = handler.handle("/api/v1/approvals", {"status": "approved"}, http_handler)
        assert _status(result) == 400
        assert "Only pending" in _body(result)["error"]

    def test_rejected_status_returns_400(self, handler, http_handler):
        """Only pending is supported; 'rejected' returns 400."""
        result = handler.handle("/api/v1/approvals", {"status": "rejected"}, http_handler)
        assert _status(result) == 400

    def test_empty_status_defaults_to_pending(self, handler, http_handler):
        """Empty string or None status defaults to pending."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {"status": ""}, http_handler)
            assert _status(result) == 200

    def test_none_status_defaults_to_pending(self, handler, http_handler):
        """None status defaults to pending."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {"status": None}, http_handler)
            assert _status(result) == 200


# ---------------------------------------------------------------------------
# Limit parameter tests
# ---------------------------------------------------------------------------


class TestLimitParameter:
    """Tests for the limit query parameter bounds checking."""

    def test_default_limit_is_100(self, handler, http_handler):
        """When no limit param, default is 100."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {}, http_handler)
            mock_collect.assert_called_once_with(limit=100, sources=None)

    def test_custom_limit(self, handler, http_handler):
        """Custom limit is passed through."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {"limit": "50"}, http_handler)
            mock_collect.assert_called_once_with(limit=50, sources=None)

    def test_limit_clamped_to_min_1(self, handler, http_handler):
        """Limit below 1 is clamped to 1."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {"limit": "0"}, http_handler)
            mock_collect.assert_called_once_with(limit=1, sources=None)

    def test_limit_clamped_to_max_500(self, handler, http_handler):
        """Limit above 500 is clamped to 500."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {"limit": "1000"}, http_handler)
            mock_collect.assert_called_once_with(limit=500, sources=None)

    def test_limit_invalid_string_defaults_to_100(self, handler, http_handler):
        """Non-numeric limit falls back to default 100."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {"limit": "abc"}, http_handler)
            mock_collect.assert_called_once_with(limit=100, sources=None)

    def test_limit_negative_clamped_to_1(self, handler, http_handler):
        """Negative limit is clamped to 1."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {"limit": "-5"}, http_handler)
            mock_collect.assert_called_once_with(limit=1, sources=None)


# ---------------------------------------------------------------------------
# Source filtering tests
# ---------------------------------------------------------------------------


class TestSourceFiltering:
    """Tests for source/sources query parameter filtering."""

    def test_no_sources_passes_none(self, handler, http_handler):
        """When no source/sources param, passes None to collector."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {}, http_handler)
            mock_collect.assert_called_once_with(limit=100, sources=None)

    def test_single_source(self, handler, http_handler):
        """Single source value is parsed into a list."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {"source": "workflow"}, http_handler)
            mock_collect.assert_called_once_with(limit=100, sources=["workflow"])

    def test_comma_separated_sources(self, handler, http_handler):
        """Comma-separated source values are split into list."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {"source": "workflow,gateway"}, http_handler)
            mock_collect.assert_called_once_with(limit=100, sources=["workflow", "gateway"])

    def test_sources_param_alternative_key(self, handler, http_handler):
        """The 'sources' key also works for source filtering."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {"sources": "decision_plan"}, http_handler)
            mock_collect.assert_called_once_with(limit=100, sources=["decision_plan"])

    def test_sources_strips_whitespace(self, handler, http_handler):
        """Whitespace around source names is stripped."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {"source": " workflow , gateway "}, http_handler)
            mock_collect.assert_called_once_with(limit=100, sources=["workflow", "gateway"])

    def test_empty_source_ignored(self, handler, http_handler):
        """Empty strings from splitting are filtered out."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle("/api/v1/approvals", {"source": "workflow,,gateway,"}, http_handler)
            mock_collect.assert_called_once_with(limit=100, sources=["workflow", "gateway"])

    def test_source_takes_priority_over_sources(self, handler, http_handler):
        """When both 'source' and 'sources' are present, 'source' wins (or fallback)."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ) as mock_collect:
            handler.handle(
                "/api/v1/approvals",
                {"source": "workflow", "sources": "gateway"},
                http_handler,
            )
            # source key is checked first via `or`
            mock_collect.assert_called_once_with(limit=100, sources=["workflow"])


# ---------------------------------------------------------------------------
# Success response structure tests
# ---------------------------------------------------------------------------


class TestSuccessResponse:
    """Tests for successful response payload structure."""

    def test_response_contains_approvals_key(self, handler, http_handler):
        """Response body has 'approvals' list."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[{"id": "a1", "type": "workflow"}],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            body = _body(result)
            assert "approvals" in body
            assert len(body["approvals"]) == 1

    def test_response_contains_count(self, handler, http_handler):
        """Response body has 'count' matching approvals length."""
        approvals = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=approvals,
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            body = _body(result)
            assert body["count"] == 3

    def test_response_contains_requested_by(self, handler, http_handler):
        """Response body has 'requested_by' with user_id."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            body = _body(result)
            assert "requested_by" in body

    def test_response_default_sources_when_none(self, handler, http_handler):
        """When no source filter, response sources shows default list."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            body = _body(result)
            assert body["sources"] == [
                "workflow",
                "decision_plan",
                "computer_use",
                "gateway",
                "inbox_wedge",
            ]

    def test_response_custom_sources_when_filtered(self, handler, http_handler):
        """When source filter is applied, response reflects filtered sources."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {"source": "workflow"}, http_handler)
            body = _body(result)
            assert body["sources"] == ["workflow"]

    def test_response_status_200_on_success(self, handler, http_handler):
        """Successful request returns 200."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            assert _status(result) == 200

    def test_empty_approvals_returns_200(self, handler, http_handler):
        """Empty approvals list still returns 200 with count=0."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            body = _body(result)
            assert body["count"] == 0
            assert body["approvals"] == []


# ---------------------------------------------------------------------------
# Error handling tests (collect_pending_approvals failures)
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling when collect_pending_approvals fails."""

    def test_import_error_returns_500(self, handler, http_handler):
        """ImportError from missing module returns 500."""
        with patch.dict(
            "sys.modules", {"aragora.approvals": None, "aragora.approvals.inbox": None}
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            assert _status(result) == 500
            assert "Failed to collect approvals" in _body(result)["error"]

    def test_value_error_returns_500(self, handler, http_handler):
        """ValueError from collector returns 500."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            side_effect=ValueError("bad value"),
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            assert _status(result) == 500
            assert "Failed to collect approvals" in _body(result)["error"]

    def test_type_error_returns_500(self, handler, http_handler):
        """TypeError from collector returns 500."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            side_effect=TypeError("type mismatch"),
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            assert _status(result) == 500

    def test_key_error_returns_500(self, handler, http_handler):
        """KeyError from collector returns 500."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            side_effect=KeyError("missing_key"),
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            assert _status(result) == 500

    def test_attribute_error_returns_500(self, handler, http_handler):
        """AttributeError from collector returns 500."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            side_effect=AttributeError("no attr"),
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            assert _status(result) == 500

    def test_os_error_returns_500(self, handler, http_handler):
        """OSError from collector returns 500."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            side_effect=OSError("disk failure"),
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            assert _status(result) == 500

    def test_runtime_error_returns_500(self, handler, http_handler):
        """RuntimeError from collector returns 500."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            side_effect=RuntimeError("runtime issue"),
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            assert _status(result) == 500


# ---------------------------------------------------------------------------
# Route-specific tests (both routes behave identically)
# ---------------------------------------------------------------------------


class TestBothRoutes:
    """Tests verifying both /approvals and /approvals/pending behave the same."""

    def test_approvals_route_returns_data(self, handler, http_handler):
        """GET /api/v1/approvals returns approvals."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[{"id": "x"}],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals", {}, http_handler)
            assert _status(result) == 200
            assert _body(result)["count"] == 1

    def test_approvals_pending_route_returns_data(self, handler, http_handler):
        """GET /api/v1/approvals/pending returns approvals."""
        with patch(
            "aragora.approvals.inbox.collect_pending_approvals",
            return_value=[{"id": "y"}],
            create=True,
        ):
            result = handler.handle("/api/v1/approvals/pending", {}, http_handler)
            assert _status(result) == 200
            assert _body(result)["count"] == 1


# ---------------------------------------------------------------------------
# ROUTES class attribute tests
# ---------------------------------------------------------------------------


class TestRoutesAttribute:
    """Tests for the ROUTES class attribute."""

    def test_routes_contains_approvals(self):
        assert "/api/v1/approvals" in UnifiedApprovalsHandler.ROUTES

    def test_routes_contains_approvals_pending(self):
        assert "/api/v1/approvals/pending" in UnifiedApprovalsHandler.ROUTES

    def test_routes_has_exactly_two_entries(self):
        assert len(UnifiedApprovalsHandler.ROUTES) == 2


# ---------------------------------------------------------------------------
# __all__ export test
# ---------------------------------------------------------------------------


class TestModuleExports:
    """Tests for module-level exports."""

    def test_all_exports_handler(self):
        from aragora.server.handlers import approvals_inbox

        assert "UnifiedApprovalsHandler" in approvals_inbox.__all__
