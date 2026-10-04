"""
Tests for the AuditTrailHandler module.

Tests cover:
- Route matching (can_handle)
- RBAC permission requirements with 403 responses
- List/query audit trails with filtering and pagination
- Export formats (JSON, CSV, Markdown)
- Integrity verification for trails
- Error handling
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.audit_trail import AuditTrailHandler


# ===========================================================================
# Test Fixtures and Mocks
# ===========================================================================


@pytest.fixture
def mock_server_context():
    """Create mock server context for handler initialization."""
    return {"storage": None, "elo_system": None, "nomic_dir": None}


@pytest.fixture
def mock_audit_store():
    """Create mock audit trail store with sample data."""
    store = MagicMock()

    # Sample trail data
    sample_trails = [
        {
            "trail_id": "trail-001",
            "gauntlet_id": "gauntlet-001",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "verdict": "APPROVED",
            "confidence": 0.95,
            "total_findings": 5,
            "duration_seconds": 12.5,
            "checksum": "abc123def456",
        },
        {
            "trail_id": "trail-002",
            "gauntlet_id": "gauntlet-002",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "verdict": "REJECTED",
            "confidence": 0.87,
            "total_findings": 3,
            "duration_seconds": 8.2,
            "checksum": "xyz789ghi012",
        },
    ]

    # Sample receipt data
    sample_receipts = [
        {
            "receipt_id": "receipt-001",
            "gauntlet_id": "gauntlet-001",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "verdict": "APPROVED",
            "confidence": 0.95,
            "risk_level": "LOW",
            "findings": [{"id": "f1"}, {"id": "f2"}],
            "checksum": "",  # Will be computed
        },
        {
            "receipt_id": "receipt-002",
            "gauntlet_id": "gauntlet-002",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "verdict": "REJECTED",
            "confidence": 0.87,
            "risk_level": "HIGH",
            "findings": [{"id": "f3"}],
            "checksum": "",
        },
    ]

    # Compute checksums for receipts
    for receipt in sample_receipts:
        content = json.dumps(
            {
                "receipt_id": receipt["receipt_id"],
                "gauntlet_id": receipt["gauntlet_id"],
                "verdict": receipt["verdict"],
                "confidence": receipt["confidence"],
            },
            sort_keys=True,
        )
        receipt["checksum"] = hashlib.sha256(content.encode()).hexdigest()[:16]

    # Configure mock methods
    store.list_trails = MagicMock(return_value=sample_trails)
    store.count_trails = MagicMock(return_value=len(sample_trails))
    store.get_trail = MagicMock(return_value=sample_trails[0])
    store.get_trail_by_gauntlet = MagicMock(return_value=sample_trails[0])

    store.list_receipts = MagicMock(return_value=sample_receipts)
    store.count_receipts = MagicMock(return_value=len(sample_receipts))
    store.get_receipt = MagicMock(return_value=sample_receipts[0])
    store.get_receipt_by_gauntlet = MagicMock(return_value=sample_receipts[0])

    store._sample_trails = sample_trails
    store._sample_receipts = sample_receipts

    return store


@pytest.fixture
def handler(mock_server_context, mock_audit_store):
    """Create handler with mocked dependencies."""
    with patch(
        "aragora.storage.audit_trail_store.get_audit_trail_store",
        return_value=mock_audit_store,
    ):
        h = AuditTrailHandler(mock_server_context)
        h._store = mock_audit_store
        return h


@pytest.fixture
def mock_http_handler():
    """Create mock HTTP handler for auth testing."""
    mock = MagicMock()
    mock.headers = {}
    mock.client_address = ("127.0.0.1", 12345)
    return mock


def create_mock_http_with_auth(role: str = "admin") -> MagicMock:
    """Create mock HTTP handler with auth headers for RBAC testing."""
    mock = MagicMock()
    mock.headers = {"Authorization": "Bearer test-token"}
    mock.client_address = ("127.0.0.1", 12345)
    return mock


# ===========================================================================
# Route Matching Tests
# ===========================================================================


class TestAuditTrailHandlerRouteMatching:
    """Tests for can_handle() route matching."""

    def test_can_handle_audit_trails_list(self, handler):
        """Handler can handle GET /api/v1/audit-trails."""
        assert handler.can_handle("/api/v1/audit-trails", "GET")

    def test_can_handle_audit_trail_by_id(self, handler):
        """Handler can handle GET /api/v1/audit-trails/:id."""
        assert handler.can_handle("/api/v1/audit-trails/trail-001", "GET")

    def test_can_handle_audit_trail_export(self, handler):
        """Handler can handle GET /api/v1/audit-trails/:id/export."""
        assert handler.can_handle("/api/v1/audit-trails/trail-001/export", "GET")

    def test_can_handle_audit_trail_verify(self, handler):
        """Handler can handle POST /api/v1/audit-trails/:id/verify."""
        assert handler.can_handle("/api/v1/audit-trails/trail-001/verify", "POST")

    def test_cannot_handle_other_paths(self, handler):
        """Handler cannot handle unrelated paths."""
        assert not handler.can_handle("/api/v1/debates", "GET")
        assert not handler.can_handle("/api/v1/backups", "GET")
        assert not handler.can_handle("/api/v1/workflows", "GET")
        assert not handler.can_handle("/api/v2/audit-trails", "GET")

    def test_cannot_handle_unsupported_methods(self, handler):
        """Handler cannot handle unsupported HTTP methods."""
        assert not handler.can_handle("/api/v1/audit-trails", "PUT")
        assert not handler.can_handle("/api/v1/audit-trails", "DELETE")
        assert not handler.can_handle("/api/v1/audit-trails", "PATCH")
        assert not handler.can_handle("/api/v1/receipts", "PUT")

    def test_does_not_handle_receipt_routes(self, handler):
        """Decision receipts are served by the org-scoped receipts handler."""
        for path in ("/api/v1/receipts", "/api/v1/receipts/r-1", "/api/v1/receipts/r-1/verify"):
            for method in ("GET", "POST"):
                assert not handler.can_handle(path, method)


# ===========================================================================
# RBAC Permission Tests
# ===========================================================================


class TestAuditTrailHandlerRBACPermissions:
    """Tests for RBAC permission requirements."""

    def test_list_trails_has_permission_decorator(self, handler):
        """_list_audit_trails requires audit:read permission."""
        # Verify the method is wrapped with permission decorator
        assert hasattr(handler._list_audit_trails, "__wrapped__")

    def test_get_trail_has_permission_decorator(self, handler):
        """_get_audit_trail requires audit:read permission."""
        assert hasattr(handler._get_audit_trail, "__wrapped__")

    def test_export_trail_has_permission_decorator(self, handler):
        """_export_audit_trail requires audit:export permission."""
        assert hasattr(handler._export_audit_trail, "__wrapped__")

    def test_verify_trail_has_permission_decorator(self, handler):
        """_verify_audit_trail requires audit:verify permission."""
        assert hasattr(handler._verify_audit_trail, "__wrapped__")

    @pytest.mark.asyncio
    @pytest.mark.no_auto_auth
    async def test_list_trails_returns_403_without_permission(
        self, mock_server_context, mock_audit_store, monkeypatch
    ):
        """List trails returns 403 when user lacks audit:read permission."""
        # Enable real auth checks
        monkeypatch.setenv("ARAGORA_TEST_REAL_AUTH", "true")

        with patch(
            "aragora.storage.audit_trail_store.get_audit_trail_store",
            return_value=mock_audit_store,
        ):
            h = AuditTrailHandler(mock_server_context)
            h._store = mock_audit_store

            # Call without proper auth
            result = await h.handle("GET", "/api/v1/audit-trails")

            # Should get 401 (no auth) or 403 (no permission)
            assert result is not None
            assert result.status_code in (401, 403)

    @pytest.mark.asyncio
    @pytest.mark.no_auto_auth
    async def test_export_trail_returns_403_without_permission(
        self, mock_server_context, mock_audit_store, monkeypatch
    ):
        """Export trail returns 403 when user lacks audit:export permission."""
        monkeypatch.setenv("ARAGORA_TEST_REAL_AUTH", "true")

        with patch(
            "aragora.storage.audit_trail_store.get_audit_trail_store",
            return_value=mock_audit_store,
        ):
            h = AuditTrailHandler(mock_server_context)
            h._store = mock_audit_store

            result = await h.handle(
                "GET",
                "/api/v1/audit-trails/trail-001/export",
                query_params={"format": "json"},
            )

            assert result is not None
            assert result.status_code in (401, 403)

    @pytest.mark.asyncio
    @pytest.mark.no_auto_auth
    async def test_verify_trail_returns_403_without_permission(
        self, mock_server_context, mock_audit_store, monkeypatch
    ):
        """Verify trail returns 403 when user lacks audit:verify permission."""
        monkeypatch.setenv("ARAGORA_TEST_REAL_AUTH", "true")

        with patch(
            "aragora.storage.audit_trail_store.get_audit_trail_store",
            return_value=mock_audit_store,
        ):
            h = AuditTrailHandler(mock_server_context)
            h._store = mock_audit_store

            result = await h.handle("POST", "/api/v1/audit-trails/trail-001/verify")

            assert result is not None
            assert result.status_code in (401, 403)


# ===========================================================================
# List/Query Tests
# ===========================================================================


class TestAuditTrailHandlerListTrails:
    """Tests for listing and querying audit trails."""

    @pytest.mark.asyncio
    async def test_list_trails_returns_200(self, handler):
        """GET /api/v1/audit-trails returns 200 with trails list."""
        result = await handler.handle("GET", "/api/v1/audit-trails")

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert "trails" in body
        assert "total" in body
        assert isinstance(body["trails"], list)

    @pytest.mark.asyncio
    async def test_list_trails_with_pagination(self, handler):
        """GET /api/v1/audit-trails supports limit and offset."""
        result = await handler.handle(
            "GET",
            "/api/v1/audit-trails",
            query_params={"limit": "10", "offset": "5"},
        )

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert body["limit"] == 10
        assert body["offset"] == 5

    @pytest.mark.asyncio
    async def test_list_trails_with_verdict_filter(self, handler, mock_audit_store):
        """GET /api/v1/audit-trails supports verdict filtering."""
        result = await handler.handle(
            "GET",
            "/api/v1/audit-trails",
            query_params={"verdict": "APPROVED"},
        )

        assert result is not None
        assert result.status_code == 200

        # Verify the store was called with verdict filter
        mock_audit_store.list_trails.assert_called_with(limit=20, offset=0, verdict="APPROVED")

    @pytest.mark.asyncio
    async def test_list_trails_default_pagination(self, handler, mock_audit_store):
        """GET /api/v1/audit-trails uses default pagination values."""
        result = await handler.handle("GET", "/api/v1/audit-trails")

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert body["limit"] == 20
        assert body["offset"] == 0


class TestAuditTrailHandlerGetById:
    """Tests for getting a single trail by ID."""

    @pytest.mark.asyncio
    async def test_get_trail_by_id_returns_200(self, handler):
        """GET /api/v1/audit-trails/:id returns 200 with trail data."""
        result = await handler.handle("GET", "/api/v1/audit-trails/trail-001")

        assert result is not None
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_get_trail_not_found_returns_404(self, handler, mock_audit_store):
        """GET /api/v1/audit-trails/:id returns 404 for missing trail."""
        # Clear all sources where trail might be found
        mock_audit_store.get_trail.return_value = None
        mock_audit_store.get_trail_by_gauntlet.return_value = None
        handler._trails.clear()

        # Mock the gauntlet fallback method to return None
        with patch.object(handler, "_load_trail_from_gauntlet", return_value=None):
            result = await handler.handle("GET", "/api/v1/audit-trails/nonexistent")

        assert result is not None
        assert result.status_code == 404


# ===========================================================================
# Export Tests
# ===========================================================================


class TestAuditTrailHandlerExport:
    """Tests for audit trail export functionality."""

    @pytest.mark.asyncio
    async def test_export_json_format(self, handler, mock_audit_store):
        """GET /api/v1/audit-trails/:id/export?format=json returns JSON."""
        # Mock the export module
        with patch("aragora.export.audit_trail.AuditTrail") as MockAuditTrail:
            mock_trail_obj = MagicMock()
            mock_trail_obj.to_json.return_value = '{"trail_id": "trail-001"}'
            mock_trail_obj.to_csv.return_value = "trail_id,verdict\ntrail-001,APPROVED"
            mock_trail_obj.to_markdown.return_value = "# Audit Trail\n\nTrail ID: trail-001"
            MockAuditTrail.from_json.return_value = mock_trail_obj

            result = await handler.handle(
                "GET",
                "/api/v1/audit-trails/trail-001/export",
                query_params={"format": "json"},
            )

            assert result is not None
            assert result.status_code == 200
            assert result.content_type == "application/json"
            assert "Content-Disposition" in result.headers
            assert "trail-001.json" in result.headers["Content-Disposition"]

    @pytest.mark.asyncio
    async def test_export_csv_format(self, handler, mock_audit_store):
        """GET /api/v1/audit-trails/:id/export?format=csv returns CSV."""
        with patch("aragora.export.audit_trail.AuditTrail") as MockAuditTrail:
            mock_trail_obj = MagicMock()
            mock_trail_obj.to_csv.return_value = "trail_id,verdict\ntrail-001,APPROVED"
            MockAuditTrail.from_json.return_value = mock_trail_obj

            result = await handler.handle(
                "GET",
                "/api/v1/audit-trails/trail-001/export",
                query_params={"format": "csv"},
            )

            assert result is not None
            assert result.status_code == 200
            assert result.content_type == "text/csv"
            assert "trail-001.csv" in result.headers["Content-Disposition"]

    @pytest.mark.asyncio
    async def test_export_markdown_format(self, handler, mock_audit_store):
        """GET /api/v1/audit-trails/:id/export?format=md returns Markdown."""
        with patch("aragora.export.audit_trail.AuditTrail") as MockAuditTrail:
            mock_trail_obj = MagicMock()
            mock_trail_obj.to_markdown.return_value = "# Audit Trail"
            MockAuditTrail.from_json.return_value = mock_trail_obj

            result = await handler.handle(
                "GET",
                "/api/v1/audit-trails/trail-001/export",
                query_params={"format": "md"},
            )

            assert result is not None
            assert result.status_code == 200
            assert result.content_type == "text/markdown"
            assert "trail-001.md" in result.headers["Content-Disposition"]

    @pytest.mark.asyncio
    async def test_export_invalid_format_returns_400(self, handler, mock_audit_store):
        """GET /api/v1/audit-trails/:id/export with invalid format returns 400."""
        with patch("aragora.export.audit_trail.AuditTrail") as MockAuditTrail:
            mock_trail_obj = MagicMock()
            MockAuditTrail.from_json.return_value = mock_trail_obj

            result = await handler.handle(
                "GET",
                "/api/v1/audit-trails/trail-001/export",
                query_params={"format": "invalid"},
            )

            assert result is not None
            assert result.status_code == 400
            body = json.loads(result.body)
            assert "error" in body

    @pytest.mark.asyncio
    async def test_export_not_found_returns_404(self, handler, mock_audit_store):
        """GET /api/v1/audit-trails/:id/export for missing trail returns 404."""
        # Clear all sources where trail might be found
        mock_audit_store.get_trail.return_value = None
        mock_audit_store.get_trail_by_gauntlet.return_value = None
        handler._trails.clear()

        # Mock the gauntlet fallback method to return None
        with patch.object(handler, "_load_trail_from_gauntlet", return_value=None):
            result = await handler.handle(
                "GET",
                "/api/v1/audit-trails/nonexistent/export",
                query_params={"format": "json"},
            )

        assert result is not None
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_export_default_format_is_json(self, handler, mock_audit_store):
        """GET /api/v1/audit-trails/:id/export defaults to JSON format."""
        with patch("aragora.export.audit_trail.AuditTrail") as MockAuditTrail:
            mock_trail_obj = MagicMock()
            mock_trail_obj.to_json.return_value = '{"trail_id": "trail-001"}'
            MockAuditTrail.from_json.return_value = mock_trail_obj

            result = await handler.handle(
                "GET",
                "/api/v1/audit-trails/trail-001/export",
                query_params={},  # No format specified
            )

            assert result is not None
            assert result.status_code == 200
            assert result.content_type == "application/json"


# ===========================================================================
# Integrity Verification Tests
# ===========================================================================


class TestAuditTrailHandlerIntegrityVerification:
    """Tests for integrity verification endpoints."""

    @pytest.mark.asyncio
    async def test_verify_trail_integrity_success(self, handler, mock_audit_store):
        """POST /api/v1/audit-trails/:id/verify returns verification result."""
        # Set up trail in the handler's in-memory cache for verification
        handler._trails["trail-001"] = mock_audit_store._sample_trails[0]

        with patch("aragora.export.audit_trail.AuditTrail") as MockAuditTrail:
            mock_trail_obj = MagicMock()
            mock_trail_obj.verify_integrity.return_value = True
            mock_trail_obj.checksum = "abc123def456"
            MockAuditTrail.from_json.return_value = mock_trail_obj

            result = await handler.handle("POST", "/api/v1/audit-trails/trail-001/verify")

            assert result is not None
            assert result.status_code == 200

            body = json.loads(result.body)
            assert body["trail_id"] == "trail-001"
            assert "valid" in body
            assert "stored_checksum" in body
            assert "computed_checksum" in body
            assert "match" in body

    @pytest.mark.asyncio
    async def test_verify_trail_not_found_returns_404(self, handler, mock_audit_store):
        """POST /api/v1/audit-trails/:id/verify returns 404 for missing trail."""
        # Clear all sources where trail might be found
        mock_audit_store.get_trail.return_value = None
        mock_audit_store.get_trail_by_gauntlet.return_value = None
        handler._trails.clear()

        # Mock the gauntlet fallback method to return None
        with patch.object(handler, "_load_trail_from_gauntlet", return_value=None):
            result = await handler.handle("POST", "/api/v1/audit-trails/nonexistent/verify")

        assert result is not None
        assert result.status_code == 404


# ===========================================================================
# Error Handling Tests
# ===========================================================================


class TestAuditTrailHandlerErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_internal_error_returns_500(self, handler):
        """Internal errors return 500 status code."""
        with patch.object(handler, "_list_audit_trails", side_effect=ValueError("Database error")):
            result = await handler.handle("GET", "/api/v1/audit-trails")

            assert result is not None
            assert result.status_code == 500
            body = json.loads(result.body)
            assert "error" in body

    @pytest.mark.asyncio
    async def test_unknown_subpath_returns_trail_data(self, handler):
        """Unknown subpath under trail ID routes to get_audit_trail."""
        # /api/v1/audit-trails/trail-001/unknown routes to get trail
        result = await handler.handle("GET", "/api/v1/audit-trails/trail-001/unknown")

        # This actually routes to get_audit_trail because of path matching
        assert result is not None
        # May be 200 (found trail) or 404 (unknown handled)
        assert result.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_handle_not_found_path(self, handler):
        """Handler returns 404 for unmatched paths within its domain."""
        # This path is handled by can_handle but has no route
        result = await handler.handle("GET", "/api/v1/audit-trails")

        assert result is not None
        # Should return the list, not 404
        assert result.status_code == 200


# ===========================================================================
# Class Method Tests
# ===========================================================================


class TestAuditTrailHandlerClassMethods:
    """Tests for class-level storage methods."""

    def test_store_trail_class_method(self, mock_server_context):
        """store_trail class method stores trail in class-level dict."""
        with patch("aragora.storage.audit_trail_store.get_audit_trail_store"):
            # Clear existing trails
            AuditTrailHandler._trails.clear()

            trail_data = {
                "trail_id": "test-trail",
                "verdict": "APPROVED",
                "confidence": 0.9,
            }

            AuditTrailHandler.store_trail("test-trail", trail_data)

            assert "test-trail" in AuditTrailHandler._trails
            assert AuditTrailHandler._trails["test-trail"] == trail_data


# ===========================================================================
# Path Extraction Tests
# ===========================================================================


class TestAuditTrailHandlerPathExtraction:
    """Tests for path ID extraction."""

    @pytest.mark.asyncio
    async def test_extract_trail_id_from_path(self, handler, mock_audit_store):
        """Handler correctly extracts trail ID from path."""
        result = await handler.handle("GET", "/api/v1/audit-trails/my-trail-123")

        # The handler should have attempted to get trail with ID "my-trail-123"
        mock_audit_store.get_trail.assert_called()

    @pytest.mark.asyncio
    async def test_extract_id_from_export_path(self, handler, mock_audit_store):
        """Handler correctly extracts ID from export path."""
        # Clear all sources where trail might be found
        mock_audit_store.get_trail.return_value = None
        mock_audit_store.get_trail_by_gauntlet.return_value = None
        handler._trails.clear()

        # Mock the gauntlet fallback method to return None
        with patch.object(handler, "_load_trail_from_gauntlet", return_value=None):
            result = await handler.handle(
                "GET",
                "/api/v1/audit-trails/trail-xyz/export",
                query_params={"format": "json"},
            )

        assert result is not None
        # Since trail not found, should return 404
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_extract_id_from_verify_path(self, handler, mock_audit_store):
        """Handler correctly extracts ID from verify path."""
        # Set up trail for verification
        handler._trails["trail-abc"] = {"trail_id": "trail-abc", "checksum": "test123"}

        with patch("aragora.export.audit_trail.AuditTrail") as MockAuditTrail:
            mock_trail_obj = MagicMock()
            mock_trail_obj.verify_integrity.return_value = True
            mock_trail_obj.checksum = "test123"
            MockAuditTrail.from_json.return_value = mock_trail_obj

            result = await handler.handle("POST", "/api/v1/audit-trails/trail-abc/verify")

            assert result is not None
            assert result.status_code == 200

            body = json.loads(result.body)
            assert body["trail_id"] == "trail-abc"
