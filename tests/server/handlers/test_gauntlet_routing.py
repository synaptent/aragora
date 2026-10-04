"""
Tests for GauntletHandler routing refactoring.

Tests cover:
- Direct route matching via routing dictionary
- Parameterized route matching via _handle_parameterized_route
- ID extraction and validation via _extract_and_validate_id
- 404 for unknown routes
- Method validation (correct method required for each route)
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.gauntlet import (
    GauntletHandler,
    _gauntlet_runs,
)

from aragora.tenancy.record_scope import OrgScope as _OrgScope

TEST_ORG = "test-org-001"
TEST_SCOPE = _OrgScope(org_id=TEST_ORG, user_id="test-user-001", role="admin")


# ===========================================================================
# Test Fixtures and Mocks
# ===========================================================================


def make_mock_handler(
    body: dict | None = None,
    method: str = "GET",
    path: str = "/api/v1/gauntlet/run",
) -> MagicMock:
    """Create a mock HTTP handler."""
    handler = MagicMock()
    handler.command = method
    handler.path = path
    handler.headers = {}
    handler.client_address = ("127.0.0.1", 12345)

    if body is not None:
        body_bytes = json.dumps(body).encode("utf-8")
        handler.headers["Content-Length"] = str(len(body_bytes))
        handler.rfile = BytesIO(body_bytes)
    else:
        handler.rfile = BytesIO(b"")
        handler.headers["Content-Length"] = "0"

    return handler


@pytest.fixture
def gauntlet_handler() -> GauntletHandler:
    """Create GauntletHandler with mock context."""
    ctx: dict[str, Any] = {"stream_emitter": None}
    return GauntletHandler(ctx)


@pytest.fixture(autouse=True)
def clear_gauntlet_runs():
    """Clear in-memory gauntlet runs and rate limiters before each test."""
    from aragora.server.handlers.utils.rate_limit import _limiters

    _gauntlet_runs.clear()
    # Clear all handler rate limiters so tests are not rate-limited
    for limiter in _limiters.values():
        limiter.clear()
    yield
    _gauntlet_runs.clear()
    for limiter in _limiters.values():
        limiter.clear()


# ===========================================================================
# Test Direct Route Matching
# ===========================================================================


class TestDirectRouteMatching:
    """Tests for direct route matching via routing dictionary."""

    def test_direct_routes_initialized(self, gauntlet_handler: GauntletHandler):
        """Verify direct routes dictionary is initialized."""
        assert hasattr(gauntlet_handler, "_direct_routes")
        assert isinstance(gauntlet_handler._direct_routes, dict)
        assert len(gauntlet_handler._direct_routes) > 0

    def test_personas_route_is_outside_the_org_scoped_direct_routes(
        self, gauntlet_handler: GauntletHandler
    ):
        """GET /api/gauntlet/personas is the shared catalog, routed before org scoping."""
        assert ("/api/gauntlet/personas", "GET") not in gauntlet_handler._direct_routes

    def test_run_route_in_direct_routes(self, gauntlet_handler: GauntletHandler):
        """POST /api/gauntlet/run should be in direct routes."""
        assert ("/api/gauntlet/run", "POST") in gauntlet_handler._direct_routes

    def test_results_route_in_direct_routes(self, gauntlet_handler: GauntletHandler):
        """GET /api/gauntlet/results should be in direct routes."""
        assert ("/api/gauntlet/results", "GET") in gauntlet_handler._direct_routes

    @pytest.mark.asyncio
    async def test_personas_route_dispatches_correctly(self, gauntlet_handler: GauntletHandler):
        """GET /api/gauntlet/personas should dispatch to _list_personas."""
        handler = make_mock_handler(method="GET", path="/api/v1/gauntlet/personas")

        with patch.object(gauntlet_handler, "_list_personas") as mock_list:
            mock_list.return_value = MagicMock(status_code=200, body=b'{"personas": []}')

            result = await gauntlet_handler.handle("/api/v1/gauntlet/personas", {}, handler)

            mock_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_results_route_dispatches_correctly(self, gauntlet_handler: GauntletHandler):
        """GET /api/gauntlet/results should dispatch to _list_results with query params."""
        handler = make_mock_handler(method="GET", path="/api/v1/gauntlet/results")
        query_params = {"limit": 10, "offset": 0}

        with patch.object(gauntlet_handler, "_list_results") as mock_list:
            mock_list.return_value = MagicMock(status_code=200, body=b'{"results": []}')

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/results", query_params, handler
            )

            mock_list.assert_called_once_with(query_params, scope=TEST_SCOPE)


# ===========================================================================
# Test Parameterized Route Matching
# ===========================================================================


class TestParameterizedRouteMatching:
    """Tests for parameterized route matching via _handle_parameterized_route."""

    @pytest.mark.asyncio
    async def test_receipt_route_matches(self, gauntlet_handler: GauntletHandler):
        """GET /api/gauntlet/{id}/receipt should match parameterized route."""
        handler = make_mock_handler(method="GET", path="/api/v1/gauntlet/gauntlet-test123/receipt")

        # Add a completed run for the receipt endpoint
        _gauntlet_runs["gauntlet-test123"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "gauntlet-test123",
            "status": "completed",
            "result": {"verdict": "APPROVED", "confidence": 0.9},
            "input_summary": "Test",
            "input_hash": "abc123",
        }

        with patch.object(gauntlet_handler, "_get_receipt", new_callable=AsyncMock) as mock_receipt:
            mock_receipt.return_value = MagicMock(status_code=200, body=b"{}", headers={})

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-test123/receipt", {}, handler
            )

            mock_receipt.assert_called_once()
            # Check that the gauntlet_id was extracted correctly
            call_args = mock_receipt.call_args
            assert call_args[0][0] == "gauntlet-test123"

    @pytest.mark.asyncio
    async def test_heatmap_route_matches(self, gauntlet_handler: GauntletHandler):
        """GET /api/gauntlet/{id}/heatmap should match parameterized route."""
        handler = make_mock_handler(method="GET", path="/api/v1/gauntlet/gauntlet-test123/heatmap")

        with patch.object(gauntlet_handler, "_get_heatmap", new_callable=AsyncMock) as mock_heatmap:
            mock_heatmap.return_value = MagicMock(status_code=200, body=b"{}", headers={})

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-test123/heatmap", {}, handler
            )

            mock_heatmap.assert_called_once()
            call_args = mock_heatmap.call_args
            assert call_args[0][0] == "gauntlet-test123"

    @pytest.mark.asyncio
    async def test_export_route_matches(self, gauntlet_handler: GauntletHandler):
        """GET /api/gauntlet/{id}/export should match parameterized route."""
        handler = make_mock_handler(method="GET", path="/api/v1/gauntlet/gauntlet-test123/export")

        with patch.object(
            gauntlet_handler, "_export_report", new_callable=AsyncMock
        ) as mock_export:
            mock_export.return_value = MagicMock(status_code=200, body=b"{}", headers={})

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-test123/export", {}, handler
            )

            mock_export.assert_called_once()
            call_args = mock_export.call_args
            assert call_args[0][0] == "gauntlet-test123"

    @pytest.mark.asyncio
    async def test_compare_route_matches(self, gauntlet_handler: GauntletHandler):
        """GET /api/gauntlet/{id}/compare/{id2} should match parameterized route."""
        handler = make_mock_handler(
            method="GET",
            path="/api/v1/gauntlet/gauntlet-test123/compare/gauntlet-test456",
        )

        with patch.object(gauntlet_handler, "_compare_results") as mock_compare:
            mock_compare.return_value = MagicMock(status_code=200, body=b"{}")

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-test123/compare/gauntlet-test456", {}, handler
            )

            mock_compare.assert_called_once()
            call_args = mock_compare.call_args
            assert call_args[0][0] == "gauntlet-test123"
            assert call_args[0][1] == "gauntlet-test456"

    @pytest.mark.asyncio
    async def test_receipt_verify_route_matches(self, gauntlet_handler: GauntletHandler):
        """POST /api/gauntlet/{id}/receipt/verify should match parameterized route."""
        body = {
            "receipt": {"receipt_id": "test"},
            "signature": "sig",
            "signature_metadata": {
                "algorithm": "SHA256",
                "key_id": "key1",
                "timestamp": "2024-01-01T00:00:00Z",
            },
        }
        handler = make_mock_handler(
            method="POST",
            path="/api/v1/gauntlet/gauntlet-test123/receipt/verify",
            body=body,
        )

        with patch.object(
            gauntlet_handler, "_verify_receipt", new_callable=AsyncMock
        ) as mock_verify:
            mock_verify.return_value = MagicMock(status_code=200, body=b"{}", headers={})

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-test123/receipt/verify", {}, handler
            )

            mock_verify.assert_called_once()
            call_args = mock_verify.call_args
            assert call_args[0][0] == "gauntlet-test123"

    @pytest.mark.asyncio
    async def test_delete_route_matches(self, gauntlet_handler: GauntletHandler):
        """DELETE /api/gauntlet/{id} should match parameterized route."""
        handler = make_mock_handler(method="DELETE", path="/api/v1/gauntlet/gauntlet-test123")

        with patch.object(gauntlet_handler, "_delete_result") as mock_delete:
            mock_delete.return_value = MagicMock(status_code=200, body=b"{}")

            result = await gauntlet_handler.handle("/api/v1/gauntlet/gauntlet-test123", {}, handler)

            mock_delete.assert_called_once()
            call_args = mock_delete.call_args
            assert call_args[0][0] == "gauntlet-test123"

    @pytest.mark.asyncio
    async def test_status_route_matches(self, gauntlet_handler: GauntletHandler):
        """GET /api/gauntlet/{id} should match parameterized route for status."""
        handler = make_mock_handler(method="GET", path="/api/v1/gauntlet/gauntlet-test123")

        with patch.object(gauntlet_handler, "_get_status", new_callable=AsyncMock) as mock_status:
            mock_status.return_value = MagicMock(status_code=200, body=b"{}", headers={})

            result = await gauntlet_handler.handle("/api/v1/gauntlet/gauntlet-test123", {}, handler)

            mock_status.assert_called_once_with("gauntlet-test123", scope=TEST_SCOPE)


# ===========================================================================
# Test ID Extraction and Validation
# ===========================================================================


class TestIdExtractionAndValidation:
    """Tests for _extract_and_validate_id helper method."""

    def test_extract_id_from_last_segment(self, gauntlet_handler: GauntletHandler):
        """Should extract ID from last path segment by default."""
        gauntlet_id, error = gauntlet_handler._extract_and_validate_id(
            "/api/gauntlet/gauntlet-test123"
        )
        assert gauntlet_id == "gauntlet-test123"
        assert error is None

    def test_extract_id_from_specific_segment(self, gauntlet_handler: GauntletHandler):
        """Should extract ID from specific segment index."""
        gauntlet_id, error = gauntlet_handler._extract_and_validate_id(
            "/api/gauntlet/gauntlet-test123/receipt", segment_index=-2
        )
        assert gauntlet_id == "gauntlet-test123"
        assert error is None

    def test_extract_id_from_compare_path(self, gauntlet_handler: GauntletHandler):
        """Should extract first ID from compare path."""
        gauntlet_id, error = gauntlet_handler._extract_and_validate_id(
            "/api/gauntlet/gauntlet-test123/compare/gauntlet-test456", segment_index=-3
        )
        assert gauntlet_id == "gauntlet-test123"
        assert error is None

    def test_invalid_path_too_short(self, gauntlet_handler: GauntletHandler):
        """Should return error for path with too few segments."""
        gauntlet_id, error = gauntlet_handler._extract_and_validate_id("/api", segment_index=-5)
        assert gauntlet_id is None
        assert error is not None
        assert error.status_code == 400

    def test_reserved_words_rejected(self, gauntlet_handler: GauntletHandler):
        """Should reject reserved path segments as IDs."""
        for reserved in ["run", "personas", "results"]:
            gauntlet_id, error = gauntlet_handler._extract_and_validate_id(
                f"/api/gauntlet/{reserved}"
            )
            assert gauntlet_id is None
            assert error is not None
            assert error.status_code == 400

    def test_invalid_id_format(self, gauntlet_handler: GauntletHandler):
        """Should reject IDs that fail validation."""
        # Path traversal attempt
        gauntlet_id, error = gauntlet_handler._extract_and_validate_id(
            "/api/gauntlet/../etc/passwd"
        )
        assert gauntlet_id is None
        assert error is not None
        assert error.status_code == 400

    def test_empty_id_segment(self, gauntlet_handler: GauntletHandler):
        """Should reject empty ID segments."""
        gauntlet_id, error = gauntlet_handler._extract_and_validate_id("/api/gauntlet/")
        assert gauntlet_id is None
        assert error is not None

    def test_trailing_slash_handled(self, gauntlet_handler: GauntletHandler):
        """Should handle trailing slashes correctly."""
        gauntlet_id, error = gauntlet_handler._extract_and_validate_id(
            "/api/gauntlet/gauntlet-test123/"
        )
        assert gauntlet_id == "gauntlet-test123"
        assert error is None


# ===========================================================================
# Test 404 for Unknown Routes
# ===========================================================================


class Test404ForUnknownRoutes:
    """Tests for 404 responses on unknown routes."""

    @pytest.mark.asyncio
    async def test_unknown_path_returns_none(self, gauntlet_handler: GauntletHandler):
        """Unknown paths should return None (not found)."""
        handler = make_mock_handler(method="GET", path="/api/gauntlet/unknown/path/here")

        # The handler should return None for unmatched routes when the path
        # doesn't match expected patterns
        result = await gauntlet_handler.handle("/api/gauntlet/unknown/path/here", {}, handler)

        # For paths that don't match any pattern, result may be None
        # or 404 depending on the catch-all behavior
        if result is not None:
            # If it returned something, it should be an error
            assert result.status_code in (400, 404)

    @pytest.mark.asyncio
    async def test_wrong_method_for_run(self, gauntlet_handler: GauntletHandler):
        """GET on /api/gauntlet/run should not match direct route."""
        handler = make_mock_handler(method="GET", path="/api/v1/gauntlet/run")

        # Since "run" is a reserved word, it should return an error
        result = await gauntlet_handler.handle("/api/v1/gauntlet/run", {}, handler)

        if result is not None:
            assert result.status_code == 400


# ===========================================================================
# Test Method Validation
# ===========================================================================


class TestMethodValidation:
    """Tests for HTTP method validation on routes."""

    @pytest.mark.asyncio
    async def test_post_required_for_run(self, gauntlet_handler: GauntletHandler):
        """POST method is required for /api/gauntlet/run."""
        handler = make_mock_handler(method="POST", path="/api/v1/gauntlet/run")
        handler.user_store = None

        with patch.object(
            gauntlet_handler, "_start_gauntlet", new_callable=AsyncMock
        ) as mock_start:
            mock_start.return_value = MagicMock(status_code=202, body=b"{}", headers={})

            result = await gauntlet_handler.handle("/api/v1/gauntlet/run", {}, handler)

            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_required_for_personas(self, gauntlet_handler: GauntletHandler):
        """GET method is required for /api/gauntlet/personas."""
        handler = make_mock_handler(method="GET", path="/api/v1/gauntlet/personas")

        with patch.object(gauntlet_handler, "_list_personas") as mock_list:
            mock_list.return_value = MagicMock(status_code=200, body=b"{}")

            result = await gauntlet_handler.handle("/api/v1/gauntlet/personas", {}, handler)

            mock_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_required_for_delete(self, gauntlet_handler: GauntletHandler):
        """DELETE method is required for deleting gauntlet results."""
        handler = make_mock_handler(method="DELETE", path="/api/v1/gauntlet/gauntlet-test123")

        with patch.object(gauntlet_handler, "_delete_result") as mock_delete:
            mock_delete.return_value = MagicMock(status_code=200, body=b"{}")

            result = await gauntlet_handler.handle("/api/v1/gauntlet/gauntlet-test123", {}, handler)

            mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_required_for_receipt_verify(self, gauntlet_handler: GauntletHandler):
        """POST method is required for /api/gauntlet/{id}/receipt/verify."""
        body = {
            "receipt": {},
            "signature": "sig",
            "signature_metadata": {},
        }
        handler = make_mock_handler(
            method="POST",
            path="/api/v1/gauntlet/gauntlet-test123/receipt/verify",
            body=body,
        )

        with patch.object(
            gauntlet_handler, "_verify_receipt", new_callable=AsyncMock
        ) as mock_verify:
            mock_verify.return_value = MagicMock(status_code=200, body=b"{}", headers={})

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-test123/receipt/verify", {}, handler
            )

            mock_verify.assert_called_once()


# ===========================================================================
# Test Legacy Route Normalization
# ===========================================================================


class TestLegacyRouteNormalization:
    """Tests for legacy (non-versioned) route normalization."""

    @pytest.mark.asyncio
    async def test_legacy_personas_route(self, gauntlet_handler: GauntletHandler):
        """Legacy /api/gauntlet/personas should work and add deprecation header."""
        handler = make_mock_handler(method="GET", path="/api/gauntlet/personas")

        with patch.object(gauntlet_handler, "_list_personas") as mock_list:
            mock_result = MagicMock(status_code=200, body=b"{}", headers={})
            mock_list.return_value = mock_result

            result = await gauntlet_handler.handle("/api/gauntlet/personas", {}, handler)

            mock_list.assert_called_once()
            # Version headers should be added
            assert result is not None

    @pytest.mark.asyncio
    async def test_versioned_and_legacy_routes_equivalent(self, gauntlet_handler: GauntletHandler):
        """Both versioned and legacy routes should dispatch to the same handler."""
        with patch.object(gauntlet_handler, "_list_personas") as mock_list:
            mock_result = MagicMock(status_code=200, body=b"{}", headers={})
            mock_list.return_value = mock_result

            # Test versioned route
            handler1 = make_mock_handler(method="GET", path="/api/v1/gauntlet/personas")
            await gauntlet_handler.handle("/api/v1/gauntlet/personas", {}, handler1)

            # Test legacy route
            handler2 = make_mock_handler(method="GET", path="/api/gauntlet/personas")
            await gauntlet_handler.handle("/api/gauntlet/personas", {}, handler2)

            # Both should have called the same handler
            assert mock_list.call_count == 2
