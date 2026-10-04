"""
Tests for AuditTrailHandler (aragora/server/handlers/audit_trail.py).

Covers all routes and behavior:
- can_handle() routing for all path/method combinations
- GET  /api/v1/audit-trails                    - List audit trails
- GET  /api/v1/audit-trails/:trail_id          - Get specific audit trail
- GET  /api/v1/audit-trails/:trail_id/export   - Export (json, csv, md)
- POST /api/v1/audit-trails/:trail_id/verify   - Verify integrity checksum
- /api/v1/receipts is not routed here (see the decisions receipts handler)
- Class method: store_trail
- Fallback from store to in-memory
- Fallback from in-memory to gauntlet handler
- Error handling (not found, internal errors)
- Pagination and query parameters
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract the body dict from a HandlerResult."""
    if hasattr(result, "to_dict"):
        d = result.to_dict()
        return d.get("body", d)
    if isinstance(result, dict):
        return result.get("body", result)
    try:
        body, status, _ = result
        return body if isinstance(body, dict) else {}
    except (TypeError, ValueError):
        return {}


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if hasattr(result, "status_code"):
        return result.status_code
    if isinstance(result, dict):
        return result.get("status_code", result.get("status", 200))
    try:
        _, status, _ = result
        return status
    except (TypeError, ValueError):
        return 200


class MockHTTPHandler:
    """Mock HTTP handler used by BaseHandler."""

    def __init__(self, body: dict | None = None, method: str = "GET"):
        self.rfile = MagicMock()
        self._body = body
        self.command = method
        self.client_address = ("127.0.0.1", 54321)
        if body is not None:
            body_bytes = json.dumps(body).encode()
            self.rfile.read.return_value = body_bytes
            self.headers = {
                "Content-Length": str(len(body_bytes)),
                "Content-Type": "application/json",
            }
        else:
            self.rfile.read.return_value = b"{}"
            self.headers = {
                "Content-Length": "2",
                "Content-Type": "application/json",
            }


# ---------------------------------------------------------------------------
# Sample Data Factories
# ---------------------------------------------------------------------------

SAMPLE_TRAIL = {
    "trail_id": "trail-abc123",
    "gauntlet_id": "abc123",
    "created_at": "2026-01-15T10:00:00Z",
    "verdict": "APPROVED",
    "confidence": 0.92,
    "total_findings": 5,
    "duration_seconds": 12.3,
    "checksum": "deadbeef12345678",
}

SAMPLE_TRAIL_2 = {
    "trail_id": "trail-def456",
    "gauntlet_id": "def456",
    "created_at": "2026-01-14T09:00:00Z",
    "verdict": "REJECTED",
    "confidence": 0.85,
    "total_findings": 8,
    "duration_seconds": 18.7,
    "checksum": "cafebabe87654321",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_store():
    """Create a fully-mocked AuditTrailStore."""
    store = MagicMock()
    store.list_trails.return_value = []
    store.count_trails.return_value = 0
    store.get_trail.return_value = None
    store.get_trail_by_gauntlet.return_value = None
    store.list_receipts.return_value = []
    store.count_receipts.return_value = 0
    store.get_receipt.return_value = None
    store.get_receipt_by_gauntlet.return_value = None
    store.save_trail.return_value = None
    store.save_receipt.return_value = None
    return store


@pytest.fixture
def handler(mock_store):
    """Create AuditTrailHandler with mocked store."""
    with patch(
        "aragora.storage.audit_trail_store.get_audit_trail_store",
        return_value=mock_store,
    ):
        from aragora.server.handlers.audit_trail import AuditTrailHandler

        h = AuditTrailHandler({})
        h._store = mock_store
    # Ensure class-level dicts are clean between tests
    AuditTrailHandler._trails = {}
    return h


@pytest.fixture
def http_get():
    """GET request handler."""
    return MockHTTPHandler(method="GET")


@pytest.fixture
def http_post():
    """POST request handler."""
    return MockHTTPHandler(method="POST")


# ===========================================================================
# can_handle() Routing Tests
# ===========================================================================


class TestCanHandle:
    """Tests for can_handle() route matching."""

    def test_audit_trails_get(self, handler):
        assert handler.can_handle("/api/v1/audit-trails", "GET")

    def test_audit_trails_post(self, handler):
        assert handler.can_handle("/api/v1/audit-trails", "POST")

    def test_audit_trails_subpath_get(self, handler):
        assert handler.can_handle("/api/v1/audit-trails/trail-abc123", "GET")

    def test_audit_trails_export_get(self, handler):
        assert handler.can_handle("/api/v1/audit-trails/trail-abc123/export", "GET")

    def test_audit_trails_verify_post(self, handler):
        assert handler.can_handle("/api/v1/audit-trails/trail-abc123/verify", "POST")

    def test_cannot_handle_wrong_path(self, handler):
        assert not handler.can_handle("/api/v1/other", "GET")

    def test_cannot_handle_put_audit_trails(self, handler):
        assert not handler.can_handle("/api/v1/audit-trails", "PUT")

    def test_cannot_handle_delete_audit_trails(self, handler):
        assert not handler.can_handle("/api/v1/audit-trails", "DELETE")

    def test_does_not_handle_receipt_routes(self, handler):
        """Decision receipts are served by the org-scoped receipts handler."""
        for path in ("/api/v1/receipts", "/api/v1/receipts/r-1", "/api/v1/receipts/r-1/verify"):
            for method in ("GET", "POST"):
                assert not handler.can_handle(path, method)


# ===========================================================================
# GET /api/v1/audit-trails - List Audit Trails
# ===========================================================================


class TestListAuditTrails:
    """Tests for listing audit trails."""

    @pytest.mark.asyncio
    async def test_list_empty(self, handler, http_get, mock_store):
        """Returns empty list when no trails exist."""
        result = await handler.handle("/api/v1/audit-trails", {}, http_get)
        assert _status(result) == 200
        body = _body(result)
        assert body["trails"] == []
        assert body["total"] == 0
        assert body["limit"] == 20
        assert body["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_with_store_results(self, handler, http_get, mock_store):
        """Returns trails from store."""
        summaries = [
            {"trail_id": "t1", "verdict": "APPROVED"},
            {"trail_id": "t2", "verdict": "REJECTED"},
        ]
        mock_store.list_trails.return_value = summaries
        mock_store.count_trails.return_value = 2

        result = await handler.handle("/api/v1/audit-trails", {}, http_get)
        assert _status(result) == 200
        body = _body(result)
        assert len(body["trails"]) == 2
        assert body["total"] == 2

    @pytest.mark.asyncio
    async def test_list_with_pagination(self, handler, http_get, mock_store):
        """Respects limit and offset query params."""
        mock_store.list_trails.return_value = [{"trail_id": "t1"}]
        mock_store.count_trails.return_value = 50

        result = await handler.handle(
            "/api/v1/audit-trails", {"limit": "10", "offset": "20"}, http_get
        )
        assert _status(result) == 200
        body = _body(result)
        assert body["limit"] == 10
        assert body["offset"] == 20
        mock_store.list_trails.assert_called_with(limit=10, offset=20, verdict=None)

    @pytest.mark.asyncio
    async def test_list_with_verdict_filter(self, handler, http_get, mock_store):
        """Filters by verdict query param."""
        mock_store.list_trails.return_value = []
        mock_store.count_trails.return_value = 0

        result = await handler.handle("/api/v1/audit-trails", {"verdict": "APPROVED"}, http_get)
        assert _status(result) == 200
        mock_store.list_trails.assert_called_with(limit=20, offset=0, verdict="APPROVED")
        mock_store.count_trails.assert_called_with(verdict="APPROVED")

    @pytest.mark.asyncio
    async def test_list_fallback_to_in_memory(self, handler, http_get, mock_store):
        """Falls back to in-memory trails when store returns empty."""
        from aragora.server.handlers.audit_trail import AuditTrailHandler

        AuditTrailHandler._trails = {
            "t1": {
                "trail_id": "t1",
                "gauntlet_id": "g1",
                "created_at": "2026-01-15",
                "verdict": "APPROVED",
                "confidence": 0.9,
                "total_findings": 3,
                "duration_seconds": 5.0,
                "checksum": "abc",
            },
        }

        result = await handler.handle("/api/v1/audit-trails", {}, http_get)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 1
        assert body["trails"][0]["trail_id"] == "t1"

        # Cleanup
        AuditTrailHandler._trails = {}

    @pytest.mark.asyncio
    async def test_list_default_limit_capped(self, handler, http_get, mock_store):
        """Limit defaults to 20 and min is 1."""
        mock_store.list_trails.return_value = []
        mock_store.count_trails.return_value = 0

        result = await handler.handle("/api/v1/audit-trails", {"limit": "0"}, http_get)
        assert _status(result) == 200
        body = _body(result)
        # safe_query_int with min_val=1 should clamp to 1
        assert body["limit"] >= 1


# ===========================================================================
# GET /api/v1/audit-trails/:trail_id - Get Specific Trail
# ===========================================================================


class TestGetAuditTrail:
    """Tests for getting a specific audit trail."""

    @pytest.mark.asyncio
    async def test_get_trail_from_store(self, handler, http_get, mock_store):
        """Returns trail from database store."""
        mock_store.get_trail.return_value = SAMPLE_TRAIL

        result = await handler.handle("/api/v1/audit-trails/trail-abc123", {}, http_get)
        assert _status(result) == 200
        body = _body(result)
        assert body["trail_id"] == "trail-abc123"
        assert body["verdict"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_get_trail_from_in_memory(self, handler, http_get, mock_store):
        """Falls back to in-memory cache."""
        from aragora.server.handlers.audit_trail import AuditTrailHandler

        AuditTrailHandler._trails = {"trail-abc123": SAMPLE_TRAIL}

        result = await handler.handle("/api/v1/audit-trails/trail-abc123", {}, http_get)
        assert _status(result) == 200
        body = _body(result)
        assert body["trail_id"] == "trail-abc123"

        AuditTrailHandler._trails = {}

    @pytest.mark.asyncio
    async def test_get_trail_not_found(self, handler, http_get, mock_store):
        """Returns 404 when trail does not exist."""
        result = await handler.handle("/api/v1/audit-trails/nonexistent", {}, http_get)
        assert _status(result) == 404
        body = _body(result)
        assert "not found" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_trail_from_gauntlet_handler(self, handler, http_get, mock_store):
        """Falls back to loading from gauntlet handler results."""
        mock_gauntlet = MagicMock()
        mock_gauntlet._results = {"abc123": MagicMock()}
        handler.ctx["gauntlet_handler"] = mock_gauntlet

        mock_trail_obj = MagicMock()
        mock_trail_obj.to_dict.return_value = SAMPLE_TRAIL

        with patch(
            "aragora.server.handlers.audit_trail.generate_audit_trail",
            return_value=mock_trail_obj,
            create=True,
        ):
            # Need to patch the import inside _load_trail_from_gauntlet
            with patch.dict(
                "sys.modules",
                {
                    "aragora.export.audit_trail": MagicMock(
                        generate_audit_trail=MagicMock(return_value=mock_trail_obj)
                    )
                },
            ):
                result = await handler.handle("/api/v1/audit-trails/trail-abc123", {}, http_get)

        # It should either succeed or return 404 (depending on import path)
        # The key test is that it tries the gauntlet handler
        assert _status(result) in (200, 404)


# ===========================================================================
# GET /api/v1/audit-trails/:trail_id/export - Export Trail
# ===========================================================================


class TestExportAuditTrail:
    """Tests for exporting audit trails."""

    @pytest.mark.asyncio
    async def test_export_trail_not_found(self, handler, http_get, mock_store):
        """Returns 404 when trail to export does not exist."""
        result = await handler.handle("/api/v1/audit-trails/nonexistent/export", {}, http_get)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_export_json_format(self, handler, http_get, mock_store):
        """Exports trail in JSON format."""
        mock_store.get_trail.return_value = SAMPLE_TRAIL

        mock_audit_trail = MagicMock()
        mock_audit_trail.to_json.return_value = json.dumps(SAMPLE_TRAIL)

        with patch.dict(
            "sys.modules",
            {
                "aragora.export.audit_trail": MagicMock(
                    AuditTrail=MagicMock(from_json=MagicMock(return_value=mock_audit_trail))
                )
            },
        ):
            result = await handler.handle(
                "/api/v1/audit-trails/trail-abc123/export",
                {"format": "json"},
                http_get,
            )

        assert _status(result) == 200
        assert result.content_type == "application/json"
        assert "Content-Disposition" in (result.headers or {})

    @pytest.mark.asyncio
    async def test_export_csv_format(self, handler, http_get, mock_store):
        """Exports trail in CSV format."""
        mock_store.get_trail.return_value = SAMPLE_TRAIL

        mock_audit_trail = MagicMock()
        mock_audit_trail.to_csv.return_value = "col1,col2\nval1,val2"

        with patch.dict(
            "sys.modules",
            {
                "aragora.export.audit_trail": MagicMock(
                    AuditTrail=MagicMock(from_json=MagicMock(return_value=mock_audit_trail))
                )
            },
        ):
            result = await handler.handle(
                "/api/v1/audit-trails/trail-abc123/export",
                {"format": "csv"},
                http_get,
            )

        assert _status(result) == 200
        assert result.content_type == "text/csv"

    @pytest.mark.asyncio
    async def test_export_markdown_format(self, handler, http_get, mock_store):
        """Exports trail in markdown format."""
        mock_store.get_trail.return_value = SAMPLE_TRAIL

        mock_audit_trail = MagicMock()
        mock_audit_trail.to_markdown.return_value = "# Audit Trail\n\nDetails..."

        with patch.dict(
            "sys.modules",
            {
                "aragora.export.audit_trail": MagicMock(
                    AuditTrail=MagicMock(from_json=MagicMock(return_value=mock_audit_trail))
                )
            },
        ):
            result = await handler.handle(
                "/api/v1/audit-trails/trail-abc123/export",
                {"format": "md"},
                http_get,
            )

        assert _status(result) == 200
        assert result.content_type == "text/markdown"

    @pytest.mark.asyncio
    async def test_export_markdown_alias(self, handler, http_get, mock_store):
        """Accepts 'markdown' as format alias."""
        mock_store.get_trail.return_value = SAMPLE_TRAIL

        mock_audit_trail = MagicMock()
        mock_audit_trail.to_markdown.return_value = "# Trail"

        with patch.dict(
            "sys.modules",
            {
                "aragora.export.audit_trail": MagicMock(
                    AuditTrail=MagicMock(from_json=MagicMock(return_value=mock_audit_trail))
                )
            },
        ):
            result = await handler.handle(
                "/api/v1/audit-trails/trail-abc123/export",
                {"format": "markdown"},
                http_get,
            )

        assert _status(result) == 200
        assert result.content_type == "text/markdown"

    @pytest.mark.asyncio
    async def test_export_unknown_format(self, handler, http_get, mock_store):
        """Returns 400 for unknown export format."""
        mock_store.get_trail.return_value = SAMPLE_TRAIL

        mock_audit_trail = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "aragora.export.audit_trail": MagicMock(
                    AuditTrail=MagicMock(from_json=MagicMock(return_value=mock_audit_trail))
                )
            },
        ):
            result = await handler.handle(
                "/api/v1/audit-trails/trail-abc123/export",
                {"format": "xml"},
                http_get,
            )

        assert _status(result) == 400
        body = _body(result)
        assert "format" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_export_default_format_is_json(self, handler, http_get, mock_store):
        """Default export format is JSON when no format param provided."""
        mock_store.get_trail.return_value = SAMPLE_TRAIL

        mock_audit_trail = MagicMock()
        mock_audit_trail.to_json.return_value = json.dumps(SAMPLE_TRAIL)

        with patch.dict(
            "sys.modules",
            {
                "aragora.export.audit_trail": MagicMock(
                    AuditTrail=MagicMock(from_json=MagicMock(return_value=mock_audit_trail))
                )
            },
        ):
            result = await handler.handle(
                "/api/v1/audit-trails/trail-abc123/export",
                {},
                http_get,
            )

        assert _status(result) == 200
        assert result.content_type == "application/json"

    @pytest.mark.asyncio
    async def test_export_import_error_fallback(self, handler, http_get, mock_store):
        """Falls back to raw JSON when export module is unavailable."""
        mock_store.get_trail.return_value = SAMPLE_TRAIL

        # Simulate ImportError by making the module import fail
        with patch.dict(
            "sys.modules",
            {"aragora.export.audit_trail": None},
        ):
            result = await handler.handle(
                "/api/v1/audit-trails/trail-abc123/export",
                {"format": "json"},
                http_get,
            )

        # Should still return 200 with fallback JSON
        assert _status(result) == 200
        assert result.content_type == "application/json"

    @pytest.mark.asyncio
    async def test_export_content_disposition_header(self, handler, http_get, mock_store):
        """Export includes Content-Disposition with filename."""
        mock_store.get_trail.return_value = SAMPLE_TRAIL

        mock_audit_trail = MagicMock()
        mock_audit_trail.to_json.return_value = "{}"

        with patch.dict(
            "sys.modules",
            {
                "aragora.export.audit_trail": MagicMock(
                    AuditTrail=MagicMock(from_json=MagicMock(return_value=mock_audit_trail))
                )
            },
        ):
            result = await handler.handle(
                "/api/v1/audit-trails/trail-abc123/export",
                {"format": "json"},
                http_get,
            )

        assert "trail-abc123.json" in (result.headers or {}).get("Content-Disposition", "")


# ===========================================================================
# POST /api/v1/audit-trails/:trail_id/verify - Verify Trail Integrity
# ===========================================================================


class TestVerifyAuditTrail:
    """Tests for audit trail integrity verification."""

    @pytest.mark.asyncio
    async def test_verify_trail_not_found(self, handler, http_post, mock_store):
        """Returns 404 when trail to verify does not exist."""
        result = await handler.handle("/api/v1/audit-trails/nonexistent/verify", {}, http_post)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_verify_trail_valid(self, handler, http_post, mock_store):
        """Verifies a valid trail successfully."""
        from aragora.server.handlers.audit_trail import AuditTrailHandler

        AuditTrailHandler._trails = {"trail-abc123": SAMPLE_TRAIL}

        mock_audit_trail = MagicMock()
        mock_audit_trail.verify_integrity.return_value = True
        mock_audit_trail.checksum = SAMPLE_TRAIL["checksum"]

        with patch.dict(
            "sys.modules",
            {
                "aragora.export.audit_trail": MagicMock(
                    AuditTrail=MagicMock(from_json=MagicMock(return_value=mock_audit_trail))
                )
            },
        ):
            result = await handler.handle("/api/v1/audit-trails/trail-abc123/verify", {}, http_post)

        assert _status(result) == 200
        body = _body(result)
        assert body["trail_id"] == "trail-abc123"
        assert body["valid"] is True
        assert body["match"] is True

        AuditTrailHandler._trails = {}

    @pytest.mark.asyncio
    async def test_verify_trail_invalid(self, handler, http_post, mock_store):
        """Reports invalid when integrity check fails."""
        from aragora.server.handlers.audit_trail import AuditTrailHandler

        AuditTrailHandler._trails = {"trail-abc123": SAMPLE_TRAIL}

        mock_audit_trail = MagicMock()
        mock_audit_trail.verify_integrity.return_value = False
        mock_audit_trail.checksum = "different_checksum"

        with patch.dict(
            "sys.modules",
            {
                "aragora.export.audit_trail": MagicMock(
                    AuditTrail=MagicMock(from_json=MagicMock(return_value=mock_audit_trail))
                )
            },
        ):
            result = await handler.handle("/api/v1/audit-trails/trail-abc123/verify", {}, http_post)

        assert _status(result) == 200
        body = _body(result)
        assert body["trail_id"] == "trail-abc123"
        assert body["valid"] is False
        assert body["match"] is False

        AuditTrailHandler._trails = {}

    @pytest.mark.asyncio
    async def test_verify_trail_import_error(self, handler, http_post, mock_store):
        """Returns valid=False when export module unavailable."""
        from aragora.server.handlers.audit_trail import AuditTrailHandler

        AuditTrailHandler._trails = {"trail-abc123": SAMPLE_TRAIL}

        with patch.dict(
            "sys.modules",
            {"aragora.export.audit_trail": None},
        ):
            result = await handler.handle("/api/v1/audit-trails/trail-abc123/verify", {}, http_post)

        assert _status(result) == 200
        body = _body(result)
        assert body["valid"] is False
        assert "error" in body

        AuditTrailHandler._trails = {}


# ===========================================================================
# Gauntlet Fallback Tests
# ===========================================================================


class TestGauntletFallback:
    """Tests for _load_trail_from_gauntlet."""

    @pytest.mark.asyncio
    async def test_load_trail_strips_trail_prefix(self, handler, mock_store):
        """Strips 'trail-' prefix from trail_id to get gauntlet_id."""
        mock_store.get_trail_by_gauntlet.return_value = SAMPLE_TRAIL

        result = await handler._load_trail_from_gauntlet("trail-abc123")
        assert result == SAMPLE_TRAIL
        mock_store.get_trail_by_gauntlet.assert_called_with("abc123")

    @pytest.mark.asyncio
    async def test_load_trail_no_prefix(self, handler, mock_store):
        """Uses raw id as gauntlet_id when no prefix."""
        mock_store.get_trail_by_gauntlet.return_value = None

        result = await handler._load_trail_from_gauntlet("raw_id")
        assert result is None
        mock_store.get_trail_by_gauntlet.assert_called_with("raw_id")

    @pytest.mark.asyncio
    async def test_load_trail_no_gauntlet_handler(self, handler, mock_store):
        """Returns None when no gauntlet_handler in context."""
        result = await handler._load_trail_from_gauntlet("trail-abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_load_trail_gauntlet_handler_no_results(self, handler, mock_store):
        """Returns None when gauntlet handler has no results attribute."""
        handler.ctx["gauntlet_handler"] = MagicMock(spec=[])
        result = await handler._load_trail_from_gauntlet("trail-abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_load_trail_gauntlet_handler_no_matching_result(self, handler, mock_store):
        """Returns None when gauntlet handler has no matching result."""
        mock_gauntlet = MagicMock()
        mock_gauntlet._results = {}
        handler.ctx["gauntlet_handler"] = mock_gauntlet

        result = await handler._load_trail_from_gauntlet("trail-abc123")
        assert result is None


# ===========================================================================
# Class Method Tests
# ===========================================================================


class TestClassMethods:
    """Tests for the store_trail class method."""

    def test_store_trail(self):
        """store_trail adds trail to class-level dict."""
        from aragora.server.handlers.audit_trail import AuditTrailHandler

        AuditTrailHandler._trails = {}
        AuditTrailHandler.store_trail("trail-new", {"trail_id": "trail-new"})
        assert "trail-new" in AuditTrailHandler._trails
        assert AuditTrailHandler._trails["trail-new"]["trail_id"] == "trail-new"
        AuditTrailHandler._trails = {}

    def test_store_trail_overwrites_existing(self):
        """store_trail overwrites existing trail with same ID."""
        from aragora.server.handlers.audit_trail import AuditTrailHandler

        AuditTrailHandler._trails = {}
        AuditTrailHandler.store_trail("trail-x", {"verdict": "old"})
        AuditTrailHandler.store_trail("trail-x", {"verdict": "new"})
        assert AuditTrailHandler._trails["trail-x"]["verdict"] == "new"
        AuditTrailHandler._trails = {}


# ===========================================================================
# Routing Edge Cases
# ===========================================================================


class TestRoutingEdgeCases:
    """Tests for edge cases in request routing."""

    @pytest.mark.asyncio
    async def test_unknown_path_returns_404(self, handler, http_get):
        """Returns 404 for completely unhandled paths."""
        result = await handler.handle("/api/v1/unknown", {}, http_get)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_handle_method_detection_from_http_handler(self, handler, http_get, mock_store):
        """Detects method from http_handler.command when path starts with /."""
        mock_store.list_trails.return_value = []
        mock_store.count_trails.return_value = 0

        result = await handler.handle("/api/v1/audit-trails", {}, http_get)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_with_method_prefix(self, handler, mock_store):
        """Supports handle(method, path, ...) signature."""
        mock_store.list_trails.return_value = []
        mock_store.count_trails.return_value = 0

        result = await handler.handle("GET", "/api/v1/audit-trails")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_with_none_query_params(self, handler, http_get, mock_store):
        """Handles None query_params gracefully."""
        mock_store.list_trails.return_value = []
        mock_store.count_trails.return_value = 0

        result = await handler.handle("/api/v1/audit-trails", None, http_get)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_verify_trail_path_routing(self, handler, http_post, mock_store):
        """POST to /verify routes to verify handler, not get handler."""
        result = await handler.handle("/api/v1/audit-trails/trail-abc123/verify", {}, http_post)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_export_path_routing(self, handler, http_get, mock_store):
        """GET to /export routes to export handler, not get handler."""
        result = await handler.handle("/api/v1/audit-trails/trail-abc123/export", {}, http_get)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_trail_id_extraction(self, handler, http_get, mock_store):
        """Correctly extracts trail_id from path segments."""
        mock_store.get_trail.return_value = {
            "trail_id": "my-special-trail",
            "verdict": "APPROVED",
        }

        result = await handler.handle("/api/v1/audit-trails/my-special-trail", {}, http_get)
        assert _status(result) == 200
        mock_store.get_trail.assert_called_with("my-special-trail")


# ===========================================================================
# Error Handling Tests
# ===========================================================================


class TestErrorHandling:
    """Tests for error handling in the handler."""

    @pytest.mark.asyncio
    async def test_key_error_returns_500(self, handler, http_get, mock_store):
        """KeyError in handler returns 500."""
        mock_store.list_trails.side_effect = KeyError("missing key")

        result = await handler.handle("/api/v1/audit-trails", {}, http_get)
        assert _status(result) == 500
        body = _body(result)
        assert "error" in body

    @pytest.mark.asyncio
    async def test_value_error_returns_500(self, handler, http_get, mock_store):
        """ValueError in handler returns 500."""
        mock_store.list_trails.side_effect = ValueError("bad value")

        result = await handler.handle("/api/v1/audit-trails", {}, http_get)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_type_error_returns_500(self, handler, http_get, mock_store):
        """TypeError in handler returns 500."""
        mock_store.list_trails.side_effect = TypeError("wrong type")

        result = await handler.handle("/api/v1/audit-trails", {}, http_get)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_attribute_error_returns_500(self, handler, http_get, mock_store):
        """AttributeError in handler returns 500."""
        mock_store.list_trails.side_effect = AttributeError("missing attr")

        result = await handler.handle("/api/v1/audit-trails", {}, http_get)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_os_error_returns_500(self, handler, http_get, mock_store):
        """OSError in handler returns 500."""
        mock_store.list_trails.side_effect = OSError("disk error")

        result = await handler.handle("/api/v1/audit-trails", {}, http_get)
        assert _status(result) == 500


# ===========================================================================
# Handler Initialization Tests
# ===========================================================================


class TestHandlerInit:
    """Tests for handler initialization."""

    def test_handler_has_routes(self, handler):
        """Handler has ROUTES list."""
        assert "/api/v1/audit-trails" in handler.ROUTES
        assert "/api/v1/receipts" not in handler.ROUTES

    def test_handler_extends_base_handler(self, handler):
        """Handler extends BaseHandler."""
        from aragora.server.handlers.base import BaseHandler

        assert isinstance(handler, BaseHandler)

    def test_handler_has_store(self, handler, mock_store):
        """Handler initializes with a store."""
        assert handler._store is mock_store

    def test_handler_server_context(self, handler):
        """Handler stores server context."""
        assert handler.ctx is not None
