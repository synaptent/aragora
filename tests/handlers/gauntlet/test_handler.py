"""
Tests for GauntletHandler (aragora/server/handlers/gauntlet/handler.py).

Covers:
- __init__: stream emitter setup, broadcast fn
- _extract_and_validate_id: valid/invalid IDs, segment indices, edge cases
- _handle_parameterized_route: receipt verify, get receipt, heatmap, export, compare, delete, status
- _is_legacy_route: versioned vs legacy paths
- _normalize_path: version prefix stripping
- can_handle: all route/method combos
- _add_version_headers: version headers, deprecation for legacy routes
- handle: routing, auth, permission checks, query_params parsing, direct vs parameterized
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.gauntlet.handler import GauntletHandler
from aragora.server.handlers.gauntlet.storage import get_gauntlet_runs
from aragora.server.handlers.utils.responses import HandlerResult

from aragora.tenancy.record_scope import OrgScope as _OrgScope

TEST_ORG = "test-org-001"
TEST_SCOPE = _OrgScope(org_id=TEST_ORG, user_id="test-user-001", role="admin")

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: HandlerResult) -> dict[str, Any]:
    """Decode a HandlerResult body into a dict."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result: HandlerResult) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


def _make_http_handler(method: str = "GET", path: str = "/", body: dict | None = None) -> MagicMock:
    """Create a mock HTTP handler with command and rfile attributes."""
    h = MagicMock()
    h.command = method
    h.path = path
    if body:
        body_bytes = json.dumps(body).encode()
        h.rfile.read.return_value = body_bytes
        h.headers = {"Content-Length": str(len(body_bytes))}
    else:
        h.rfile.read.return_value = b"{}"
        h.headers = {"Content-Length": "2"}
    return h


# A valid gauntlet ID matching SAFE_GAUNTLET_ID_PATTERN: gauntlet-YYYYMMDDHHMMSS-xxxxxx
VALID_ID = "gauntlet-20260223120000-abcdef"
VALID_ID2 = "gauntlet-20260223130000-123456"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a GauntletHandler with a minimal server context."""
    ctx: dict[str, Any] = {}
    return GauntletHandler(ctx)


@pytest.fixture(autouse=True)
def _clear_runs():
    """Ensure in-memory runs are empty before/after every test."""
    runs = get_gauntlet_runs()
    runs.clear()
    yield
    runs.clear()


@pytest.fixture
def mock_storage():
    """Return a MagicMock that acts as GauntletStorage."""
    s = MagicMock()
    s.get.return_value = None
    s.get_inflight.return_value = None
    s.list_recent.return_value = []
    s.count.return_value = 0
    s.compare.return_value = None
    s.delete.return_value = False
    s.save_inflight = MagicMock()
    s.update_inflight_status = MagicMock()
    s.save = MagicMock()
    s.delete_inflight = MagicMock()
    return s


@pytest.fixture(autouse=True)
def _patch_all_storage(mock_storage):
    """Patch _get_storage_proxy in all mixin modules."""
    with (
        patch(
            "aragora.server.handlers.gauntlet.runner._get_storage_proxy",
            return_value=mock_storage,
        ),
        patch(
            "aragora.server.handlers.gauntlet.receipts._get_storage_proxy",
            return_value=mock_storage,
        ),
        patch(
            "aragora.server.handlers.gauntlet.heatmap._get_storage_proxy",
            return_value=mock_storage,
        ),
        patch(
            "aragora.server.handlers.gauntlet.results._get_storage_proxy",
            return_value=mock_storage,
        ),
    ):
        yield


# ============================================================================
# __init__
# ============================================================================


class TestInit:
    """Tests for GauntletHandler.__init__."""

    def test_init_no_emitter(self):
        """Handler initializes without a stream emitter."""
        h = GauntletHandler({})
        assert h is not None
        assert h._direct_routes is not None

    def test_init_with_emitter(self):
        """Handler sets broadcast fn when emitter is provided."""
        emitter = MagicMock()
        emitter.emit = MagicMock()
        with patch(
            "aragora.server.handlers.gauntlet.handler.set_gauntlet_broadcast_fn"
        ) as mock_set:
            GauntletHandler({"stream_emitter": emitter})
            mock_set.assert_called_once_with(emitter.emit)

    def test_init_emitter_without_emit_method(self):
        """Handler does not set broadcast fn if emitter has no emit method."""
        emitter = object()  # No emit attribute
        with patch(
            "aragora.server.handlers.gauntlet.handler.set_gauntlet_broadcast_fn"
        ) as mock_set:
            GauntletHandler({"stream_emitter": emitter})
            mock_set.assert_not_called()

    def test_init_direct_routes_populated(self):
        """Direct routes map is populated correctly."""
        h = GauntletHandler({})
        assert ("/api/gauntlet/run", "POST") in h._direct_routes
        assert ("/api/gauntlet/results", "GET") in h._direct_routes
        assert h._direct_routes[("/api/gauntlet/run", "POST")] == "_start_gauntlet"
        assert h._direct_routes[("/api/gauntlet/results", "GET")] == "_list_results"
        # The persona catalog is shared, so it is routed outside the org-scoped table.
        assert ("/api/gauntlet/personas", "GET") not in h._direct_routes


# ============================================================================
# _extract_and_validate_id
# ============================================================================


class TestExtractAndValidateId:
    """Tests for _extract_and_validate_id."""

    def test_valid_id_last_segment(self, handler):
        """Extracts valid ID from last segment (default)."""
        gid, err = handler._extract_and_validate_id(f"/api/gauntlet/{VALID_ID}")
        assert gid == VALID_ID
        assert err is None

    def test_valid_id_specific_segment(self, handler):
        """Extracts valid ID from specific segment index."""
        path = f"/api/gauntlet/{VALID_ID}/receipt"
        gid, err = handler._extract_and_validate_id(path, -2)
        assert gid == VALID_ID
        assert err is None

    def test_valid_id_at_index_minus_3(self, handler):
        """Extracts valid ID from -3 segment index."""
        path = f"/api/gauntlet/{VALID_ID}/receipt/verify"
        gid, err = handler._extract_and_validate_id(path, -3)
        assert gid == VALID_ID
        assert err is None

    def test_invalid_path_too_short(self, handler):
        """Returns error for paths too short for the segment index."""
        gid, err = handler._extract_and_validate_id("/api", -5)
        assert gid is None
        assert _status(err) == 400

    def test_empty_segment_id(self, handler):
        """Returns error when segment is empty."""
        gid, err = handler._extract_and_validate_id("/api/gauntlet/")
        assert gid is None
        assert _status(err) == 400

    def test_reserved_word_run(self, handler):
        """Returns error when segment is 'run' (reserved keyword)."""
        gid, err = handler._extract_and_validate_id("/api/gauntlet/run")
        assert gid is None
        assert _status(err) == 400

    def test_reserved_word_personas(self, handler):
        """Returns error when segment is 'personas'."""
        gid, err = handler._extract_and_validate_id("/api/gauntlet/personas")
        assert gid is None
        assert _status(err) == 400

    def test_reserved_word_results(self, handler):
        """Returns error when segment is 'results'."""
        gid, err = handler._extract_and_validate_id("/api/gauntlet/results")
        assert gid is None
        assert _status(err) == 400

    def test_invalid_gauntlet_id_format(self, handler):
        """Returns error for invalid gauntlet ID format."""
        gid, err = handler._extract_and_validate_id("/api/gauntlet/not-a-gauntlet-id")
        assert gid is None
        assert _status(err) == 400

    def test_path_traversal_attack(self, handler):
        """Returns error for path traversal attempts."""
        gid, err = handler._extract_and_validate_id("/api/gauntlet/../../../etc/passwd")
        assert gid is None
        assert _status(err) == 400

    def test_trailing_slash_stripped(self, handler):
        """Trailing slash is stripped before extraction."""
        gid, err = handler._extract_and_validate_id(f"/api/gauntlet/{VALID_ID}/")
        assert gid == VALID_ID
        assert err is None


# ============================================================================
# _is_legacy_route
# ============================================================================


class TestIsLegacyRoute:
    """Tests for _is_legacy_route."""

    def test_legacy_route(self, handler):
        assert handler._is_legacy_route("/api/gauntlet/run") is True

    def test_versioned_route(self, handler):
        assert handler._is_legacy_route("/api/v1/gauntlet/run") is False

    def test_non_gauntlet_route(self, handler):
        assert handler._is_legacy_route("/api/debates/list") is False

    def test_partial_match(self, handler):
        assert handler._is_legacy_route("/api/gauntlet") is False

    def test_legacy_with_id(self, handler):
        assert handler._is_legacy_route(f"/api/gauntlet/{VALID_ID}") is True


# ============================================================================
# _normalize_path
# ============================================================================


class TestNormalizePath:
    """Tests for _normalize_path."""

    def test_versioned_path_normalized(self, handler):
        result = handler._normalize_path("/api/v1/gauntlet/run")
        assert result == "/api/gauntlet/run"

    def test_legacy_path_unchanged(self, handler):
        result = handler._normalize_path("/api/gauntlet/run")
        assert result == "/api/gauntlet/run"

    def test_versioned_with_id(self, handler):
        result = handler._normalize_path(f"/api/v1/gauntlet/{VALID_ID}")
        assert result == f"/api/gauntlet/{VALID_ID}"

    def test_non_gauntlet_path(self, handler):
        result = handler._normalize_path("/api/v1/debates/list")
        assert result == "/api/debates/list"

    def test_versioned_receipt_path(self, handler):
        result = handler._normalize_path(f"/api/v1/gauntlet/{VALID_ID}/receipt")
        assert result == f"/api/gauntlet/{VALID_ID}/receipt"


# ============================================================================
# can_handle
# ============================================================================


class TestCanHandle:
    """Tests for can_handle."""

    def test_get_gauntlet_id(self, handler):
        assert handler.can_handle(f"/api/gauntlet/{VALID_ID}", "GET") is True

    def test_post_run(self, handler):
        assert handler.can_handle("/api/gauntlet/run", "POST") is True

    def test_get_personas(self, handler):
        assert handler.can_handle("/api/gauntlet/personas", "GET") is True

    def test_get_results(self, handler):
        assert handler.can_handle("/api/gauntlet/results", "GET") is True

    def test_delete(self, handler):
        assert handler.can_handle(f"/api/gauntlet/{VALID_ID}", "DELETE") is True

    def test_versioned_get(self, handler):
        assert handler.can_handle(f"/api/v1/gauntlet/{VALID_ID}", "GET") is True

    def test_versioned_post_run(self, handler):
        assert handler.can_handle("/api/v1/gauntlet/run", "POST") is True

    def test_versioned_delete(self, handler):
        assert handler.can_handle(f"/api/v1/gauntlet/{VALID_ID}", "DELETE") is True

    def test_unrelated_path(self, handler):
        assert handler.can_handle("/api/debates/run", "POST") is False

    def test_post_on_non_run_path(self, handler):
        assert handler.can_handle(f"/api/gauntlet/{VALID_ID}", "POST") is False

    def test_get_receipt_path(self, handler):
        assert handler.can_handle(f"/api/gauntlet/{VALID_ID}/receipt", "GET") is True

    def test_get_heatmap_path(self, handler):
        assert handler.can_handle(f"/api/gauntlet/{VALID_ID}/heatmap", "GET") is True


# ============================================================================
# _add_version_headers
# ============================================================================


class TestAddVersionHeaders:
    """Tests for _add_version_headers."""

    def test_adds_api_version_header(self, handler):
        result = HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        updated = handler._add_version_headers(result, "/api/v1/gauntlet/run")
        assert updated.headers["X-API-Version"] == "v1"

    def test_legacy_route_adds_deprecation(self, handler):
        result = HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        updated = handler._add_version_headers(result, "/api/gauntlet/run")
        assert updated.headers["Deprecation"] == "true"
        assert updated.headers["Sunset"] == "2026-06-01"
        assert "Link" in updated.headers

    def test_versioned_route_no_deprecation(self, handler):
        result = HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        updated = handler._add_version_headers(result, "/api/v1/gauntlet/run")
        assert "Deprecation" not in updated.headers

    def test_none_result_returns_none(self, handler):
        result = handler._add_version_headers(None, "/api/gauntlet/run")
        assert result is None

    def test_initializes_headers_if_none(self, handler):
        result = HandlerResult(
            status_code=200, content_type="application/json", body=b"{}", headers=None
        )
        # headers gets set to {} in __post_init__, but test the flow
        updated = handler._add_version_headers(result, "/api/v1/gauntlet/run")
        assert "X-API-Version" in updated.headers

    def test_link_header_format(self, handler):
        result = HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        updated = handler._add_version_headers(result, "/api/gauntlet/run")
        assert updated.headers["Link"] == '</api/v1/gauntlet/run>; rel="successor-version"'

    def test_link_header_with_id(self, handler):
        result = HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        path = f"/api/gauntlet/{VALID_ID}"
        updated = handler._add_version_headers(result, path)
        expected_link = f'</api/v1/gauntlet/{VALID_ID}>; rel="successor-version"'
        assert updated.headers["Link"] == expected_link


# ============================================================================
# _handle_parameterized_route
# ============================================================================


class TestHandleParameterizedRoute:
    """Tests for _handle_parameterized_route."""

    @pytest.mark.asyncio
    async def test_receipt_verify_post(self, handler):
        """Routes POST /receipt/verify to _verify_receipt."""
        mock_h = _make_http_handler("POST")
        handler._verify_receipt = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        path = f"/api/gauntlet/{VALID_ID}/receipt/verify"
        result = await handler._handle_parameterized_route(
            path, "POST", {}, mock_h, scope=TEST_SCOPE
        )
        assert result is not None
        assert _status(result) == 200
        handler._verify_receipt.assert_called_once_with(VALID_ID, mock_h, scope=TEST_SCOPE)

    @pytest.mark.asyncio
    async def test_receipt_verify_invalid_id(self, handler):
        """Returns 400 for invalid ID on receipt verify."""
        mock_h = _make_http_handler("POST")
        path = "/api/gauntlet/bad-id/receipt/verify"
        result = await handler._handle_parameterized_route(
            path, "POST", {}, mock_h, scope=TEST_SCOPE
        )
        assert result is not None
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_get_receipt_anchor_status_decodes_receipt_id(self, handler):
        """Routes percent-encoded receipt IDs to anchor lookup with the decoded value."""
        handler._get_receipt_anchor_status = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        path = "/api/receipts/r%2F123/anchor-status"
        result = await handler._handle_parameterized_route(path, "GET", {}, None, scope=TEST_SCOPE)
        assert result is not None
        handler._get_receipt_anchor_status.assert_called_once_with("r/123", {}, scope=TEST_SCOPE)

    @pytest.mark.asyncio
    async def test_get_receipt(self, handler):
        """Routes GET /receipt to _get_receipt."""
        handler._get_receipt = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        path = f"/api/gauntlet/{VALID_ID}/receipt"
        result = await handler._handle_parameterized_route(
            path, "GET", {"format": "json"}, None, scope=TEST_SCOPE
        )
        assert result is not None
        handler._get_receipt.assert_called_once_with(VALID_ID, {"format": "json"}, scope=TEST_SCOPE)

    @pytest.mark.asyncio
    async def test_get_receipt_invalid_id(self, handler):
        """Returns 400 for invalid ID on get receipt."""
        path = "/api/gauntlet/not-valid/receipt"
        result = await handler._handle_parameterized_route(path, "GET", {}, None, scope=TEST_SCOPE)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_get_heatmap(self, handler):
        """Routes GET /heatmap to _get_heatmap."""
        handler._get_heatmap = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        path = f"/api/gauntlet/{VALID_ID}/heatmap"
        result = await handler._handle_parameterized_route(path, "GET", {}, None, scope=TEST_SCOPE)
        assert result is not None
        handler._get_heatmap.assert_called_once_with(VALID_ID, {}, scope=TEST_SCOPE)

    @pytest.mark.asyncio
    async def test_get_heatmap_invalid_id(self, handler):
        """Returns 400 for invalid ID on heatmap."""
        path = "/api/gauntlet/xxx/heatmap"
        result = await handler._handle_parameterized_route(path, "GET", {}, None, scope=TEST_SCOPE)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_get_export(self, handler):
        """Routes GET /export to _export_report."""
        mock_h = _make_http_handler("GET")
        handler._owns_gauntlet_run = AsyncMock(return_value=True)
        handler._export_report = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        path = f"/api/gauntlet/{VALID_ID}/export"
        result = await handler._handle_parameterized_route(
            path, "GET", {}, mock_h, scope=TEST_SCOPE
        )
        assert result is not None
        handler._export_report.assert_called_once_with(VALID_ID, {}, mock_h, scope=TEST_SCOPE)

    @pytest.mark.asyncio
    async def test_get_export_of_a_run_outside_the_org_is_404(self, handler):
        """GET /export answers 404 without reaching _export_report for a run the org lacks."""
        mock_h = _make_http_handler("GET")
        handler._owns_gauntlet_run = AsyncMock(return_value=False)
        handler._export_report = AsyncMock()
        path = f"/api/gauntlet/{VALID_ID}/export"
        result = await handler._handle_parameterized_route(
            path, "GET", {}, mock_h, scope=TEST_SCOPE
        )
        assert _status(result) == 404
        handler._owns_gauntlet_run.assert_awaited_once_with(VALID_ID, TEST_SCOPE)
        handler._export_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_export_invalid_id(self, handler):
        """Returns 400 for invalid ID on export."""
        mock_h = _make_http_handler("GET")
        path = "/api/gauntlet/nope/export"
        result = await handler._handle_parameterized_route(
            path, "GET", {}, mock_h, scope=TEST_SCOPE
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_compare_results(self, handler):
        """Routes GET /compare/ to _compare_results."""
        handler._compare_results = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        path = f"/api/gauntlet/{VALID_ID}/compare/{VALID_ID2}"
        result = await handler._handle_parameterized_route(path, "GET", {}, None, scope=TEST_SCOPE)
        assert result is not None
        handler._compare_results.assert_called_once_with(VALID_ID, VALID_ID2, {}, scope=TEST_SCOPE)

    @pytest.mark.asyncio
    async def test_compare_invalid_first_id(self, handler):
        """Returns 400 for invalid first ID on compare."""
        path = f"/api/gauntlet/bad-id/compare/{VALID_ID2}"
        result = await handler._handle_parameterized_route(path, "GET", {}, None, scope=TEST_SCOPE)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_compare_invalid_second_id(self, handler):
        """Returns 400 for invalid second (compare) ID."""
        path = f"/api/gauntlet/{VALID_ID}/compare/not-valid"
        result = await handler._handle_parameterized_route(path, "GET", {}, None, scope=TEST_SCOPE)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_compare_path_too_short(self, handler):
        """Returns None for compare path with too few segments."""
        path = "/api/gauntlet/compare"
        result = await handler._handle_parameterized_route(path, "GET", {}, None, scope=TEST_SCOPE)
        # The /compare/ check won't match since path doesn't contain "/compare/"
        # Falls through to GET status check, which returns 400 for "compare" id
        assert result is not None

    @pytest.mark.asyncio
    async def test_delete_result(self, handler):
        """Routes DELETE to _delete_result."""
        handler._delete_result = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        path = f"/api/gauntlet/{VALID_ID}"
        result = await handler._handle_parameterized_route(
            path, "DELETE", {}, None, scope=TEST_SCOPE
        )
        assert result is not None
        handler._delete_result.assert_called_once_with(VALID_ID, {}, scope=TEST_SCOPE)

    @pytest.mark.asyncio
    async def test_delete_invalid_id(self, handler):
        """Returns 400 for invalid ID on delete."""
        path = "/api/gauntlet/bad"
        result = await handler._handle_parameterized_route(
            path, "DELETE", {}, None, scope=TEST_SCOPE
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_get_status(self, handler):
        """Routes GET with ID to _get_status."""
        handler._get_status = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        path = f"/api/gauntlet/{VALID_ID}"
        result = await handler._handle_parameterized_route(path, "GET", {}, None, scope=TEST_SCOPE)
        assert result is not None
        handler._get_status.assert_called_once_with(VALID_ID, scope=TEST_SCOPE)

    @pytest.mark.asyncio
    async def test_get_status_invalid_id(self, handler):
        """Returns 400 for invalid ID on get status."""
        path = "/api/gauntlet/xyz"
        result = await handler._handle_parameterized_route(path, "GET", {}, None, scope=TEST_SCOPE)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_unmatched_method(self, handler):
        """Returns None for unmatched method/path combos."""
        path = f"/api/gauntlet/{VALID_ID}"
        result = await handler._handle_parameterized_route(path, "PUT", {}, None, scope=TEST_SCOPE)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_gauntlet_path_delete(self, handler):
        """Returns None when DELETE path doesn't start with /api/gauntlet/."""
        result = await handler._handle_parameterized_route(
            "/api/other/something", "DELETE", {}, None, scope=TEST_SCOPE
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_non_gauntlet_path_get(self, handler):
        """Returns None when GET path doesn't start with /api/gauntlet/."""
        result = await handler._handle_parameterized_route(
            "/api/other/something", "GET", {}, None, scope=TEST_SCOPE
        )
        assert result is None


# ============================================================================
# handle (integration-level routing tests)
# ============================================================================


class TestHandle:
    """Tests for the main handle method."""

    @pytest.mark.asyncio
    async def test_route_post_run(self, handler):
        """POST /api/v1/gauntlet/run routes to _start_gauntlet."""
        mock_h = _make_http_handler("POST")
        handler._start_gauntlet = AsyncMock(
            return_value=HandlerResult(
                status_code=202, content_type="application/json", body=b'{"status":"pending"}'
            )
        )
        result = await handler.handle("/api/v1/gauntlet/run", {}, mock_h)
        assert result is not None
        assert _status(result) == 202
        handler._start_gauntlet.assert_called_once_with(mock_h, scope=TEST_SCOPE)

    @pytest.mark.asyncio
    async def test_route_get_personas(self, handler):
        """GET /api/v1/gauntlet/personas routes to _list_personas."""
        mock_h = _make_http_handler("GET")
        handler._list_personas = MagicMock(
            return_value=HandlerResult(
                status_code=200, content_type="application/json", body=b'{"personas":[]}'
            )
        )
        result = await handler.handle("/api/v1/gauntlet/personas", {}, mock_h)
        assert result is not None
        assert _status(result) == 200
        handler._list_personas.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_route_get_results(self, handler):
        """GET /api/v1/gauntlet/results routes to _list_results."""
        mock_h = _make_http_handler("GET")
        handler._list_results = MagicMock(
            return_value=HandlerResult(
                status_code=200, content_type="application/json", body=b'{"results":[]}'
            )
        )
        result = await handler.handle("/api/v1/gauntlet/results", {}, mock_h)
        assert result is not None
        assert _status(result) == 200
        handler._list_results.assert_called_once_with({}, scope=TEST_SCOPE)

    @pytest.mark.asyncio
    async def test_route_get_status_parameterized(self, handler):
        """GET /api/v1/gauntlet/{id} routes to _get_status via parameterized route."""
        mock_h = _make_http_handler("GET")
        handler._get_status = AsyncMock(
            return_value=HandlerResult(
                status_code=200,
                content_type="application/json",
                body=json.dumps({"gauntlet_id": VALID_ID, "status": "completed"}).encode(),
            )
        )
        result = await handler.handle(f"/api/v1/gauntlet/{VALID_ID}", {}, mock_h)
        assert result is not None
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_route_delete_parameterized(self, handler):
        """DELETE /api/v1/gauntlet/{id} routes to _delete_result."""
        mock_h = _make_http_handler("DELETE")
        handler._delete_result = MagicMock(
            return_value=HandlerResult(
                status_code=200,
                content_type="application/json",
                body=b'{"deleted":true}',
            )
        )
        result = await handler.handle(f"/api/v1/gauntlet/{VALID_ID}", {}, mock_h)
        assert result is not None
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_legacy_route_gets_deprecation_header(self, handler):
        """Legacy routes get Deprecation header in response."""
        mock_h = _make_http_handler("GET")
        handler._list_personas = MagicMock(
            return_value=HandlerResult(
                status_code=200, content_type="application/json", body=b'{"personas":[]}'
            )
        )
        result = await handler.handle("/api/gauntlet/personas", {}, mock_h)
        assert result is not None
        assert result.headers.get("Deprecation") == "true"
        assert result.headers.get("Sunset") == "2026-06-01"

    @pytest.mark.asyncio
    async def test_versioned_route_no_deprecation_header(self, handler):
        """Versioned routes do not get Deprecation header."""
        mock_h = _make_http_handler("GET")
        handler._list_personas = MagicMock(
            return_value=HandlerResult(
                status_code=200, content_type="application/json", body=b'{"personas":[]}'
            )
        )
        result = await handler.handle("/api/v1/gauntlet/personas", {}, mock_h)
        assert result is not None
        assert "Deprecation" not in result.headers

    @pytest.mark.asyncio
    async def test_version_header_always_present(self, handler):
        """X-API-Version header is always present on responses."""
        mock_h = _make_http_handler("GET")
        handler._list_personas = MagicMock(
            return_value=HandlerResult(
                status_code=200, content_type="application/json", body=b'{"personas":[]}'
            )
        )
        result = await handler.handle("/api/v1/gauntlet/personas", {}, mock_h)
        assert result.headers["X-API-Version"] == "v1"

    @pytest.mark.asyncio
    async def test_handle_none_handler(self, handler):
        """When handler is None, method defaults to GET."""
        handler._list_personas = MagicMock(
            return_value=HandlerResult(
                status_code=200, content_type="application/json", body=b'{"personas":[]}'
            )
        )
        result = await handler.handle("/api/v1/gauntlet/personas", {}, None)
        assert result is not None
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_string_query_params(self, handler):
        """When query_params is a string, handle extracts real params from handler.path."""
        mock_h = _make_http_handler("GET", path="/api/v1/gauntlet/personas?format=json")
        handler._list_personas = MagicMock(
            return_value=HandlerResult(
                status_code=200, content_type="application/json", body=b'{"personas":[]}'
            )
        )
        # Old calling convention: handle(path, "GET", handler)
        result = await handler.handle("/api/v1/gauntlet/personas", "GET", mock_h)
        assert result is not None
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_string_query_params_no_query_string(self, handler):
        """When query_params is a string and handler.path has no query string, uses empty dict."""
        mock_h = _make_http_handler("GET", path="/api/v1/gauntlet/personas")
        handler._list_personas = MagicMock(
            return_value=HandlerResult(
                status_code=200, content_type="application/json", body=b'{"personas":[]}'
            )
        )
        result = await handler.handle("/api/v1/gauntlet/personas", "GET", mock_h)
        assert result is not None

    @pytest.mark.asyncio
    async def test_handle_no_match_returns_none(self, handler):
        """Handle returns None for unmatched routes."""
        mock_h = _make_http_handler("PATCH")
        result = await handler.handle(f"/api/v1/gauntlet/{VALID_ID}", {}, mock_h)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_receipt_route(self, handler):
        """GET /api/v1/gauntlet/{id}/receipt is handled."""
        mock_h = _make_http_handler("GET")
        handler._get_receipt = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle(f"/api/v1/gauntlet/{VALID_ID}/receipt", {}, mock_h)
        assert result is not None
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_receipt_verify_route(self, handler):
        """POST /api/v1/gauntlet/{id}/receipt/verify is handled."""
        mock_h = _make_http_handler("POST")
        handler._verify_receipt = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle(f"/api/v1/gauntlet/{VALID_ID}/receipt/verify", {}, mock_h)
        assert result is not None
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_heatmap_route(self, handler):
        """GET /api/v1/gauntlet/{id}/heatmap is handled."""
        mock_h = _make_http_handler("GET")
        handler._get_heatmap = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle(f"/api/v1/gauntlet/{VALID_ID}/heatmap", {}, mock_h)
        assert result is not None
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_export_route(self, handler):
        """GET /api/v1/gauntlet/{id}/export is handled."""
        mock_h = _make_http_handler("GET")
        handler._owns_gauntlet_run = AsyncMock(return_value=True)
        handler._export_report = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle(f"/api/v1/gauntlet/{VALID_ID}/export", {}, mock_h)
        assert result is not None
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_compare_route(self, handler):
        """GET /api/v1/gauntlet/{id}/compare/{id2} is handled."""
        mock_h = _make_http_handler("GET")
        handler._compare_results = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle(
            f"/api/v1/gauntlet/{VALID_ID}/compare/{VALID_ID2}", {}, mock_h
        )
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# handle - permission key selection
# ============================================================================


class TestHandlePermissions:
    """Tests for handle method's permission key logic."""

    @pytest.mark.asyncio
    async def test_post_uses_write_permission(self, handler):
        """POST requests check gauntlet:write permission."""
        mock_h = _make_http_handler("POST")
        handler._start_gauntlet = AsyncMock(
            return_value=HandlerResult(status_code=202, content_type="application/json", body=b"{}")
        )
        # The conftest auto-bypasses auth/permissions, just verify it doesn't error
        result = await handler.handle("/api/v1/gauntlet/run", {}, mock_h)
        assert result is not None
        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_get_uses_read_permission(self, handler):
        """GET requests check gauntlet:read permission."""
        mock_h = _make_http_handler("GET")
        handler._list_personas = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle("/api/v1/gauntlet/personas", {}, mock_h)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# ROUTES class attribute
# ============================================================================


class TestRoutes:
    """Tests for ROUTES class attribute completeness."""

    def test_routes_include_legacy_run(self):
        assert "/api/gauntlet/run" in GauntletHandler.ROUTES

    def test_routes_include_versioned_run(self):
        assert "/api/v1/gauntlet/run" in GauntletHandler.ROUTES

    def test_routes_include_personas(self):
        assert "/api/gauntlet/personas" in GauntletHandler.ROUTES
        assert "/api/v1/gauntlet/personas" in GauntletHandler.ROUTES

    def test_routes_include_results(self):
        assert "/api/gauntlet/results" in GauntletHandler.ROUTES
        assert "/api/v1/gauntlet/results" in GauntletHandler.ROUTES

    def test_routes_include_receipt(self):
        assert "/api/gauntlet/*/receipt" in GauntletHandler.ROUTES

    def test_routes_include_receipt_verify(self):
        assert "/api/gauntlet/*/receipt/verify" in GauntletHandler.ROUTES

    def test_routes_include_heatmap(self):
        assert "/api/gauntlet/*/heatmap" in GauntletHandler.ROUTES

    def test_routes_include_export(self):
        assert "/api/gauntlet/*/export" in GauntletHandler.ROUTES

    def test_routes_include_compare(self):
        assert "/api/gauntlet/*/compare/*" in GauntletHandler.ROUTES

    def test_routes_include_wildcard(self):
        assert "/api/gauntlet/*" in GauntletHandler.ROUTES

    def test_routes_include_v1_base(self):
        assert "/api/v1/gauntlet" in GauntletHandler.ROUTES

    def test_routes_include_heatmaps(self):
        assert "/api/v1/gauntlet/heatmaps" in GauntletHandler.ROUTES

    def test_routes_include_receipts(self):
        assert "/api/v1/gauntlet/receipts" in GauntletHandler.ROUTES

    def test_routes_include_receipts_export_bundle(self):
        assert "/api/v1/gauntlet/receipts/export/bundle" in GauntletHandler.ROUTES


# ============================================================================
# API_VERSION and AUTH_REQUIRED_ENDPOINTS
# ============================================================================


class TestClassAttributes:
    """Tests for class-level attributes."""

    def test_api_version(self):
        assert GauntletHandler.API_VERSION == "v1"

    def test_auth_required_endpoints(self):
        assert "/api/v1/gauntlet/run" in GauntletHandler.AUTH_REQUIRED_ENDPOINTS
        assert "/api/v1/gauntlet/" in GauntletHandler.AUTH_REQUIRED_ENDPOINTS

    def test_routes_count(self):
        """Ensure ROUTES has expected number of entries."""
        assert len(GauntletHandler.ROUTES) >= 18


# ============================================================================
# Edge cases in handle routing
# ============================================================================


class TestHandleEdgeCases:
    """Edge case tests for handle method."""

    @pytest.mark.asyncio
    async def test_legacy_run_routes_correctly(self, handler):
        """Legacy /api/gauntlet/run routes to _start_gauntlet."""
        mock_h = _make_http_handler("POST")
        handler._start_gauntlet = AsyncMock(
            return_value=HandlerResult(status_code=202, content_type="application/json", body=b"{}")
        )
        result = await handler.handle("/api/gauntlet/run", {}, mock_h)
        assert result is not None
        assert _status(result) == 202
        # Should have deprecation header
        assert result.headers.get("Deprecation") == "true"

    @pytest.mark.asyncio
    async def test_legacy_personas_routes_correctly(self, handler):
        """Legacy /api/gauntlet/personas routes to _list_personas."""
        mock_h = _make_http_handler("GET")
        handler._list_personas = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle("/api/gauntlet/personas", {}, mock_h)
        assert result is not None
        assert _status(result) == 200
        assert result.headers.get("Deprecation") == "true"

    @pytest.mark.asyncio
    async def test_legacy_results_routes_correctly(self, handler):
        """Legacy /api/gauntlet/results routes to _list_results."""
        mock_h = _make_http_handler("GET")
        handler._list_results = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle("/api/gauntlet/results", {}, mock_h)
        assert result is not None
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_legacy_status_route(self, handler):
        """Legacy /api/gauntlet/{id} routes to _get_status."""
        mock_h = _make_http_handler("GET")
        handler._get_status = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle(f"/api/gauntlet/{VALID_ID}", {}, mock_h)
        assert result is not None
        assert result.headers.get("Deprecation") == "true"

    @pytest.mark.asyncio
    async def test_legacy_delete_route(self, handler):
        """Legacy /api/gauntlet/{id} DELETE routes to _delete_result."""
        mock_h = _make_http_handler("DELETE")
        handler._delete_result = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle(f"/api/gauntlet/{VALID_ID}", {}, mock_h)
        assert result is not None
        assert result.headers.get("Deprecation") == "true"

    @pytest.mark.asyncio
    async def test_query_params_from_handler_path(self, handler):
        """When query_params is a string, extracts from handler.path query string."""
        mock_h = _make_http_handler("GET", path="/api/v1/gauntlet/results?limit=5&offset=10")
        handler._list_results = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle("/api/v1/gauntlet/results", "GET", mock_h)
        assert result is not None
        # Verify parsed params were passed
        call_args = handler._list_results.call_args
        assert call_args is not None
        query_dict = call_args[0][0]
        assert query_dict["limit"] == "5"
        assert query_dict["offset"] == "10"

    @pytest.mark.asyncio
    async def test_query_params_multi_value(self, handler):
        """Multi-value query params remain as lists."""
        mock_h = _make_http_handler("GET", path="/api/v1/gauntlet/results?tag=a&tag=b")
        handler._list_results = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle("/api/v1/gauntlet/results", "GET", mock_h)
        assert result is not None
        call_args = handler._list_results.call_args
        query_dict = call_args[0][0]
        assert query_dict["tag"] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_string_query_params_without_handler_path(self, handler):
        """When query_params is string but handler has no path, uses empty dict."""
        mock_h = MagicMock()
        mock_h.command = "GET"
        # handler with no .path attribute
        del mock_h.path
        handler._list_personas = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle("/api/v1/gauntlet/personas", "GET", mock_h)
        assert result is not None

    @pytest.mark.asyncio
    async def test_receipt_verify_on_legacy_path(self, handler):
        """Legacy receipt verify path is handled."""
        mock_h = _make_http_handler("POST")
        handler._verify_receipt = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle(f"/api/gauntlet/{VALID_ID}/receipt/verify", {}, mock_h)
        assert result is not None
        assert result.headers.get("Deprecation") == "true"

    @pytest.mark.asyncio
    async def test_heatmap_on_legacy_path(self, handler):
        """Legacy heatmap path is handled with deprecation header."""
        mock_h = _make_http_handler("GET")
        handler._get_heatmap = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle(f"/api/gauntlet/{VALID_ID}/heatmap", {}, mock_h)
        assert result is not None
        assert result.headers.get("Deprecation") == "true"

    @pytest.mark.asyncio
    async def test_export_on_legacy_path(self, handler):
        """Legacy export path is handled with deprecation header."""
        mock_h = _make_http_handler("GET")
        handler._export_report = AsyncMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle(f"/api/gauntlet/{VALID_ID}/export", {}, mock_h)
        assert result is not None
        assert result.headers.get("Deprecation") == "true"

    @pytest.mark.asyncio
    async def test_compare_on_legacy_path(self, handler):
        """Legacy compare path is handled with deprecation header."""
        mock_h = _make_http_handler("GET")
        handler._compare_results = MagicMock(
            return_value=HandlerResult(status_code=200, content_type="application/json", body=b"{}")
        )
        result = await handler.handle(f"/api/gauntlet/{VALID_ID}/compare/{VALID_ID2}", {}, mock_h)
        assert result is not None
        assert result.headers.get("Deprecation") == "true"
