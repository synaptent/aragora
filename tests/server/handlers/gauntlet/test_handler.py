"""
Tests for gauntlet handler.

Tests cover:
- Request routing (can_handle)
- Path normalization and version handling
- ID extraction and validation
- Route handling (direct and parameterized)
- Version header management
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.gauntlet import (
    GauntletHandler,
    _gauntlet_runs,
    get_gauntlet_runs,
)


@pytest.fixture
def handler():
    """Create a GauntletHandler instance."""
    return GauntletHandler({})


@pytest.fixture(autouse=True)
def clear_state():
    """Clear in-memory state before each test."""
    _gauntlet_runs.clear()
    yield
    _gauntlet_runs.clear()


class TestRouting:
    """Tests for request routing."""

    def test_can_handle_run_post(self, handler):
        """Test can_handle for POST /run endpoint."""
        assert handler.can_handle("/api/gauntlet/run", "POST")
        assert handler.can_handle("/api/v1/gauntlet/run", "POST")

    def test_can_handle_personas_get(self, handler):
        """Test can_handle for GET /personas endpoint."""
        assert handler.can_handle("/api/gauntlet/personas", "GET")
        assert handler.can_handle("/api/v1/gauntlet/personas", "GET")

    def test_can_handle_results_get(self, handler):
        """Test can_handle for GET /results endpoint."""
        assert handler.can_handle("/api/gauntlet/results", "GET")
        assert handler.can_handle("/api/v1/gauntlet/results", "GET")

    def test_can_handle_status_get(self, handler):
        """Test can_handle for GET /{id} status endpoint."""
        assert handler.can_handle("/api/gauntlet/gauntlet-abc123", "GET")
        assert handler.can_handle("/api/v1/gauntlet/gauntlet-abc123", "GET")

    def test_can_handle_receipt_get(self, handler):
        """Test can_handle for GET /{id}/receipt endpoint."""
        assert handler.can_handle("/api/gauntlet/gauntlet-abc123/receipt", "GET")
        assert handler.can_handle("/api/v1/gauntlet/gauntlet-abc123/receipt", "GET")

    def test_can_handle_heatmap_get(self, handler):
        """Test can_handle for GET /{id}/heatmap endpoint."""
        assert handler.can_handle("/api/gauntlet/gauntlet-abc123/heatmap", "GET")
        assert handler.can_handle("/api/v1/gauntlet/gauntlet-abc123/heatmap", "GET")

    def test_can_handle_delete(self, handler):
        """Test can_handle for DELETE /{id} endpoint."""
        assert handler.can_handle("/api/gauntlet/gauntlet-abc123", "DELETE")
        assert handler.can_handle("/api/v1/gauntlet/gauntlet-abc123", "DELETE")

    def test_cannot_handle_other_paths(self, handler):
        """Test can_handle rejects non-gauntlet paths."""
        assert not handler.can_handle("/api/payments/charge", "POST")
        assert not handler.can_handle("/api/orchestration/deliberate", "POST")


class TestPathNormalization:
    """Tests for path normalization."""

    def test_normalize_legacy_path(self, handler):
        """Test legacy path remains unchanged."""
        assert handler._normalize_path("/api/gauntlet/run") == "/api/gauntlet/run"
        assert (
            handler._normalize_path("/api/gauntlet/gauntlet-abc123")
            == "/api/gauntlet/gauntlet-abc123"
        )

    def test_normalize_versioned_path(self, handler):
        """Test versioned path is normalized."""
        normalized = handler._normalize_path("/api/v1/gauntlet/run")
        assert normalized == "/api/gauntlet/run"

    def test_is_legacy_route(self, handler):
        """Test legacy route detection."""
        assert handler._is_legacy_route("/api/gauntlet/run")
        assert handler._is_legacy_route("/api/gauntlet/gauntlet-abc123")
        assert not handler._is_legacy_route("/api/v1/gauntlet/run")
        assert not handler._is_legacy_route("/api/v1/gauntlet/gauntlet-abc123")


class TestIdValidation:
    """Tests for ID extraction and validation."""

    def test_extract_valid_id(self, handler):
        """Test extraction of valid gauntlet ID."""
        gauntlet_id, err = handler._extract_and_validate_id("/api/gauntlet/gauntlet-abc123")
        assert gauntlet_id == "gauntlet-abc123"
        assert err is None

    def test_extract_id_from_receipt_path(self, handler):
        """Test extraction of ID from receipt path."""
        gauntlet_id, err = handler._extract_and_validate_id(
            "/api/gauntlet/gauntlet-abc123/receipt", -2
        )
        assert gauntlet_id == "gauntlet-abc123"
        assert err is None

    def test_extract_id_from_verify_path(self, handler):
        """Test extraction of ID from verify path."""
        gauntlet_id, err = handler._extract_and_validate_id(
            "/api/gauntlet/gauntlet-abc123/receipt/verify", -3
        )
        assert gauntlet_id == "gauntlet-abc123"
        assert err is None

    def test_reject_reserved_words(self, handler):
        """Test rejection of reserved words as IDs."""
        gauntlet_id, err = handler._extract_and_validate_id("/api/gauntlet/run")
        assert gauntlet_id is None
        assert err is not None
        assert err.status_code == 400

    def test_reject_empty_id(self, handler):
        """Test rejection of empty ID."""
        gauntlet_id, err = handler._extract_and_validate_id("/api/gauntlet/")
        assert gauntlet_id is None
        assert err is not None


class TestVersionHeaders:
    """Tests for API version header management."""

    def test_add_version_header(self, handler):
        """Test API version header is added."""
        from aragora.server.handlers.base import json_response

        result = json_response({"test": "data"})
        result = handler._add_version_headers(result, "/api/v1/gauntlet/gauntlet-abc123")

        assert result.headers is not None
        assert result.headers["X-API-Version"] == "v1"

    def test_add_deprecation_header_legacy(self, handler):
        """Test deprecation header for legacy routes."""
        from aragora.server.handlers.base import json_response

        result = json_response({"test": "data"})
        result = handler._add_version_headers(result, "/api/gauntlet/gauntlet-abc123")

        assert result.headers is not None
        assert result.headers.get("Deprecation") == "true"
        assert "Sunset" in result.headers
        assert "Link" in result.headers

    def test_no_deprecation_header_versioned(self, handler):
        """Test no deprecation header for versioned routes."""
        from aragora.server.handlers.base import json_response

        result = json_response({"test": "data"})
        result = handler._add_version_headers(result, "/api/v1/gauntlet/gauntlet-abc123")

        assert result.headers is not None
        assert result.headers.get("Deprecation") is None


class TestListPersonas:
    """Tests for GET /personas endpoint."""

    @pytest.mark.asyncio
    async def test_list_personas(self, handler):
        """Test personas listing."""
        mock_handler = MagicMock()
        mock_handler.command = "GET"

        result = await handler.handle("/api/gauntlet/personas", {}, mock_handler)

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert "personas" in body
        assert isinstance(body["personas"], list)


class TestListResults:
    """Tests for GET /results endpoint."""

    @pytest.mark.asyncio
    async def test_list_results_empty(self, handler):
        """Test results listing when empty."""
        mock_handler = MagicMock()
        mock_handler.command = "GET"

        result = await handler.handle("/api/gauntlet/results", {}, mock_handler)

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert "results" in body
        assert "total" in body

    @pytest.mark.asyncio
    async def test_list_results_with_data(self, handler):
        """Test results listing with data."""
        from datetime import datetime

        # Create a mock result object
        mock_result = MagicMock()
        mock_result.gauntlet_id = "gauntlet-test-123"
        mock_result.input_hash = "abc123"
        mock_result.input_summary = "Test summary"
        mock_result.verdict = "pass"
        mock_result.confidence = 0.95
        mock_result.robustness_score = 0.8
        mock_result.critical_count = 0
        mock_result.high_count = 1
        mock_result.total_findings = 5
        mock_result.created_at = datetime(2025, 1, 15, 10, 0, 0)
        mock_result.duration_seconds = 10.5

        mock_storage = MagicMock()
        mock_storage.list_recent.return_value = [mock_result]
        mock_storage.count.return_value = 1

        mock_handler = MagicMock()
        mock_handler.command = "GET"

        with patch(
            "aragora.server.handlers.gauntlet.results._get_storage_proxy",
            return_value=mock_storage,
        ):
            result = await handler.handle("/api/gauntlet/results", {}, mock_handler)

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert body["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_results_pagination(self, handler):
        """Test results listing with pagination."""
        # Add multiple runs
        for i in range(5):
            _gauntlet_runs[f"gauntlet-test-{i}"] = {
                "gauntlet_id": f"gauntlet-test-{i}",
                "status": "completed",
                "created_at": f"2025-01-15T10:0{i}:00",
            }

        mock_handler = MagicMock()
        mock_handler.command = "GET"

        result = await handler.handle("/api/gauntlet/results", {"limit": "2"}, mock_handler)

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert len(body["results"]) <= 2


class TestGetStatus:
    """Tests for GET /{id} status endpoint."""

    @pytest.mark.asyncio
    async def test_get_status_found(self, handler):
        """Test status retrieval for existing run."""
        _gauntlet_runs["gauntlet-test-123"] = {
            "gauntlet_id": "gauntlet-test-123",
            "status": "running",
            "progress_percent": 50,
            "current_phase": "critique",
        }

        mock_handler = MagicMock()
        mock_handler.command = "GET"

        result = await handler.handle("/api/gauntlet/gauntlet-test-123", {}, mock_handler)

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert body["gauntlet_id"] == "gauntlet-test-123"
        assert body["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, handler):
        """Test status retrieval for non-existent run."""
        mock_handler = MagicMock()
        mock_handler.command = "GET"

        result = await handler.handle("/api/gauntlet/gauntlet-nonexistent", {}, mock_handler)

        assert result is not None
        assert result.status_code == 404


class TestRouteMatching:
    """Tests for route matching logic."""

    def test_routes_list(self, handler):
        """Test ROUTES list contains expected endpoints."""
        expected_routes = [
            "/api/gauntlet/run",
            "/api/gauntlet/personas",
            "/api/gauntlet/results",
            "/api/v1/gauntlet/run",
            "/api/v1/gauntlet/personas",
            "/api/v1/gauntlet/results",
        ]
        for route in expected_routes:
            assert any(r == route or r.startswith(route.replace("/*", "")) for r in handler.ROUTES)

    def test_direct_routes_mapping(self, handler):
        """Test direct routes mapping is configured."""
        assert ("/api/gauntlet/run", "POST") in handler._direct_routes
        assert ("/api/gauntlet/personas", "GET") not in handler._direct_routes
        assert ("/api/gauntlet/results", "GET") in handler._direct_routes
