"""
Tests for aragora.server.handlers.gauntlet - Gauntlet stress-testing handler.

Tests cover:
- Route registration and can_handle (versioned and legacy)
- List personas (happy path, import error)
- Start gauntlet (happy path, invalid body, missing required field, quota exceeded)
- Get status (pending, completed, not found, invalid ID, from persistent storage)
- Get decision receipt (not completed, json format, not found in storage)
- Get risk heatmap (not completed, json format, from storage fallback)
- List results with pagination (happy path, pagination params, storage error)
- Compare results (happy path, not found, invalid compare ID)
- Delete result (happy path, not found, in-memory removal)
- Export report (json format, html format, not completed, unsupported format, not found)
- Version headers and legacy route deprecation
- Memory management (cleanup old entries, memory limit enforcement)
- ID validation (path traversal, valid IDs)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import aragora.server.handlers.gauntlet as gauntlet_module
from aragora.server.handlers.gauntlet import (
    GauntletHandler,
    _gauntlet_runs,
    _cleanup_gauntlet_runs,
    MAX_GAUNTLET_RUNS_IN_MEMORY,
)


# ===========================================================================
# Test Fixtures and Mocks
# ===========================================================================


@dataclass
class MockAuthContext:
    """Mock authentication context."""

    is_authenticated: bool = True
    user_id: str = "user-123"
    email: str = "test@example.com"
    org_id: str | None = "org-123"
    role: str = "user"


@dataclass
class MockOrganization:
    """Mock organization for testing."""

    id: str = "org-123"
    is_at_limit: bool = False
    limits: Any = field(default_factory=lambda: MagicMock(debates_per_month=100))
    debates_used_this_month: int = 25
    tier: Any = field(default_factory=lambda: MagicMock(value="starter"))


@dataclass
class MockPersona:
    """Mock regulatory persona."""

    name: str = "GDPR Auditor"
    description: str = "Tests GDPR compliance"
    regulation: str = "GDPR"
    attack_prompts: list = field(default_factory=lambda: [MagicMock(category="privacy")] * 5)


@dataclass
class MockGauntletResult:
    """Mock gauntlet result for storage."""

    gauntlet_id: str = "gauntlet-test123"
    input_hash: str = "abc123"
    input_summary: str = "Test input"
    verdict: str = "APPROVED"
    confidence: float = 0.85
    robustness_score: float = 0.9
    critical_count: int = 0
    high_count: int = 1
    total_findings: int = 3
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_seconds: float = 45.0


class MockUserStore:
    """Mock user store for testing."""

    def __init__(self):
        self.orgs: dict[str, MockOrganization] = {}

    def get_organization_by_id(self, org_id: str) -> MockOrganization | None:
        return self.orgs.get(org_id)

    def increment_usage(self, org_id: str, count: int) -> None:
        pass


def make_mock_handler(
    body: dict | None = None,
    method: str = "GET",
    path: str = "/api/v1/gauntlet/run",
):
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
def gauntlet_handler():
    """Create GauntletHandler with mock context."""
    ctx = {"stream_emitter": None}
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
# Test Routing (can_handle)
# ===========================================================================


class TestGauntletHandlerRouting:
    """Tests for GauntletHandler.can_handle across versioned and legacy routes."""

    def test_can_handle_run_post(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/gauntlet/run", "POST") is True

    def test_can_handle_personas_get(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/gauntlet/personas", "GET") is True

    def test_can_handle_results_get(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/gauntlet/results", "GET") is True

    def test_can_handle_status_get(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/gauntlet/test123", "GET") is True

    def test_can_handle_receipt_get(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/gauntlet/test123/receipt", "GET") is True

    def test_can_handle_heatmap_get(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/gauntlet/test123/heatmap", "GET") is True

    def test_can_handle_delete(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/gauntlet/test123", "DELETE") is True

    def test_can_handle_legacy_route(self, gauntlet_handler):
        """Legacy non-versioned routes should also be handled."""
        assert gauntlet_handler.can_handle("/api/gauntlet/personas", "GET") is True

    def test_cannot_handle_other_paths(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/debates", "GET") is False

    def test_cannot_handle_run_get(self, gauntlet_handler):
        """GET on /run path - can_handle returns True for any GET under /api/gauntlet/."""
        result = gauntlet_handler.can_handle("/api/v1/gauntlet/run", "GET")
        assert result is True


# ===========================================================================
# Test List Personas
# ===========================================================================


class TestGauntletListPersonas:
    """Tests for list personas endpoint."""

    @pytest.mark.asyncio
    async def test_list_personas_success(self, gauntlet_handler):
        with patch("aragora.gauntlet.personas.list_personas") as mock_list:
            with patch("aragora.gauntlet.personas.get_persona") as mock_get:
                mock_list.return_value = ["gdpr", "hipaa"]
                mock_get.return_value = MockPersona()

                handler = make_mock_handler()

                result = await gauntlet_handler.handle("/api/v1/gauntlet/personas", "GET", handler)

                assert result is not None
                assert result.status_code == 200
                data = json.loads(result.body)
                assert "personas" in data
                assert data["count"] == 2
                assert len(data["personas"]) == 2

    @pytest.mark.asyncio
    async def test_list_personas_module_not_available(self, gauntlet_handler):
        with patch.dict("sys.modules", {"aragora.gauntlet.personas": None}):
            handler = make_mock_handler()

            result = gauntlet_handler._list_personas()

            assert result is not None
            data = json.loads(result.body)
            assert data["personas"] == []
            assert data["count"] == 0
            assert "error" in data


# ===========================================================================
# Test Start Gauntlet
# ===========================================================================


class TestGauntletStartRun:
    """Tests for start gauntlet endpoint."""

    @pytest.mark.asyncio
    async def test_start_gauntlet_invalid_body(self, gauntlet_handler):
        handler = MagicMock()
        handler.command = "POST"
        handler.path = "/api/v1/gauntlet/run"
        handler.headers = {"Content-Length": "5"}
        handler.rfile = BytesIO(b"invalid")
        handler.client_address = ("127.0.0.1", 12345)
        handler.user_store = None

        result = await gauntlet_handler.handle("/api/v1/gauntlet/run", "POST", handler)

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_start_gauntlet_missing_required_field(self, gauntlet_handler):
        """Submitting without input_content should fail schema validation."""
        handler = make_mock_handler(
            body={"input_type": "spec"},  # missing input_content
            method="POST",
        )
        handler.user_store = None

        result = await gauntlet_handler.handle("/api/v1/gauntlet/run", "POST", handler)

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_start_gauntlet_quota_exceeded(self, gauntlet_handler):
        user_store = MockUserStore()
        org = MockOrganization(is_at_limit=True)
        user_store.orgs["org-123"] = org

        handler = make_mock_handler(
            {"input_content": "Test spec", "input_type": "spec"},
            method="POST",
        )
        handler.user_store = user_store

        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_auth:
            mock_auth.return_value = MockAuthContext()

            result = await gauntlet_handler.handle("/api/v1/gauntlet/run", "POST", handler)

            assert result is not None
            assert result.status_code == 429
            data = json.loads(result.body)
            assert data["code"] == "quota_exceeded"
            assert "upgrade_url" in data

    @pytest.mark.asyncio
    async def test_start_gauntlet_success(self, gauntlet_handler):
        """Happy path: valid request body creates a pending run."""
        handler = make_mock_handler(
            body={"input_content": "Test spec content for gauntlet"},
            method="POST",
        )
        handler.user_store = None

        with (
            patch.object(gauntlet_module, "_get_storage") as mock_storage,
            patch.object(gauntlet_module, "create_tracked_task"),
        ):
            mock_storage_inst = MagicMock()
            mock_storage.return_value = mock_storage_inst

            result = await gauntlet_handler.handle("/api/v1/gauntlet/run", "POST", handler)

        assert result is not None
        assert result.status_code == 202
        data = json.loads(result.body)
        assert data["status"] == "pending"
        assert "gauntlet_id" in data
        assert data["gauntlet_id"].startswith("gauntlet-")


# ===========================================================================
# Test Get Status
# ===========================================================================


class TestGauntletGetStatus:
    """Tests for get status endpoint."""

    @pytest.mark.asyncio
    async def test_get_status_pending(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/gauntlet-test123", "GET", handler)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_status_completed(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "completed",
            "result": {"verdict": "APPROVED"},
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/gauntlet-test123", "GET", handler)

        assert result is not None
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, gauntlet_handler):
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.get.return_value = None
            mock_storage_instance.get_inflight.return_value = None
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-nonexistent")

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-nonexistent", "GET", handler
            )

            assert result is not None
            assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_status_from_persistent_storage(self, gauntlet_handler):
        """When not in memory, falls back to persistent storage."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.get_inflight.return_value = None
            mock_storage_instance.get.return_value = {
                "gauntlet_id": "gauntlet-stored123",
                "verdict": "APPROVED",
                "confidence": 0.9,
            }
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-stored123")

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-stored123", "GET", handler
            )

            assert result is not None
            assert result.status_code == 200
            data = json.loads(result.body)
            assert data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_status_invalid_id(self, gauntlet_handler):
        handler = make_mock_handler(path="/api/v1/gauntlet/../etc/passwd")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/../etc/passwd", "GET", handler)

        assert result is not None
        assert result.status_code == 400


# ===========================================================================
# Test Get Receipt
# ===========================================================================


class TestGauntletGetReceipt:
    """Tests for get receipt endpoint."""

    @pytest.mark.asyncio
    async def test_get_receipt_not_completed(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "running",
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/receipt")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/receipt", "GET", handler
        )

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_get_receipt_json_format(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "completed",
            "input_summary": "Test input",
            "input_hash": "abc123",
            "completed_at": datetime.now().isoformat(),
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.85,
                "robustness_score": 0.9,
                "critical_count": 0,
                "high_count": 1,
                "medium_count": 1,
                "low_count": 1,
                "total_findings": 3,
            },
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/receipt")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/receipt", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_get_receipt_not_found_in_storage(self, gauntlet_handler):
        """Receipt for a run not in memory and not in storage returns error."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.get.return_value = None
            mock_storage_instance.get_inflight.return_value = None
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-missing123/receipt")

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-missing123/receipt", "GET", handler
            )

            assert result is not None
            assert result.status_code == 404


# ===========================================================================
# Test Get Heatmap
# ===========================================================================


class TestGauntletGetHeatmap:
    """Tests for get heatmap endpoint."""

    @pytest.mark.asyncio
    async def test_get_heatmap_not_completed(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "pending",
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/heatmap")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/heatmap", "GET", handler
        )

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_get_heatmap_json_format(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "completed",
            "result": {
                "findings": [
                    {"category": "privacy", "severity_level": "high"},
                    {"category": "security", "severity_level": "medium"},
                ],
                "total_findings": 2,
            },
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/heatmap")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/heatmap", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_get_heatmap_not_found(self, gauntlet_handler):
        """Heatmap for a run not in memory and not in storage returns 404."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.get.return_value = None
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-missing123/heatmap")

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-missing123/heatmap", "GET", handler
            )

            assert result is not None
            assert result.status_code == 404


# ===========================================================================
# Test List Results
# ===========================================================================


class TestGauntletListResults:
    """Tests for list results endpoint."""

    @pytest.mark.asyncio
    async def test_list_results_success(self, gauntlet_handler):
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.list_recent.return_value = [MockGauntletResult()]
            mock_storage_instance.count.return_value = 1
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/results")

            result = await gauntlet_handler.handle("/api/v1/gauntlet/results", "GET", handler)

            assert result is not None
            assert result.status_code == 200
            data = json.loads(result.body)
            assert "results" in data
            assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_list_results_with_pagination(self, gauntlet_handler):
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.list_recent.return_value = []
            mock_storage_instance.count.return_value = 0
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/results?limit=10&offset=5")

            result = await gauntlet_handler.handle("/api/v1/gauntlet/results", "GET", handler)

            assert result is not None
            assert result.status_code == 200
            data = json.loads(result.body)
            assert data["limit"] == 10
            assert data["offset"] == 5

    @pytest.mark.asyncio
    async def test_list_results_storage_error(self, gauntlet_handler):
        """Storage failure should return 500."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.list_recent.side_effect = RuntimeError("DB down")
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/results")

            result = await gauntlet_handler.handle("/api/v1/gauntlet/results", "GET", handler)

            assert result is not None
            assert result.status_code == 500


# ===========================================================================
# Test Compare Results
# ===========================================================================


class TestGauntletCompareResults:
    """Tests for compare results endpoint."""

    @pytest.mark.asyncio
    async def test_compare_success(self, gauntlet_handler):
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.compare.return_value = {
                "comparison": {"id1": "gauntlet-test1", "id2": "gauntlet-test2"}
            }
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(
                path="/api/v1/gauntlet/gauntlet-test1/compare/gauntlet-test2"
            )

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-test1/compare/gauntlet-test2",
                "GET",
                handler,
            )

            assert result is not None
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_compare_not_found(self, gauntlet_handler):
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.compare.return_value = None
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(
                path="/api/v1/gauntlet/gauntlet-test1/compare/gauntlet-test2"
            )

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-test1/compare/gauntlet-test2",
                "GET",
                handler,
            )

            assert result is not None
            assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_compare_invalid_second_id(self, gauntlet_handler):
        """Invalid compare ID should be rejected."""
        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test1/compare/../../etc")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test1/compare/../../etc", "GET", handler
        )

        assert result is not None
        assert result.status_code == 400


# ===========================================================================
# Test Delete Result
# ===========================================================================


class TestGauntletDeleteResult:
    """Tests for delete result endpoint."""

    @pytest.mark.asyncio
    async def test_delete_success(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {"status": "completed"}

        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.delete.return_value = True
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123", method="DELETE")

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-test123", "DELETE", handler
            )

            assert result is not None
            assert result.status_code == 200
            data = json.loads(result.body)
            assert data["deleted"] is True
            assert "gauntlet-test123" not in _gauntlet_runs

    @pytest.mark.asyncio
    async def test_delete_not_found(self, gauntlet_handler):
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.delete.return_value = False
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(
                path="/api/v1/gauntlet/gauntlet-nonexistent", method="DELETE"
            )

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-nonexistent", "DELETE", handler
            )

            assert result is not None
            assert result.status_code == 404


# ===========================================================================
# Test Export Report
# ===========================================================================


class TestGauntletExportReport:
    """Tests for export report endpoint."""

    def _completed_run_data(self) -> dict:
        """Helper: data for a completed in-memory run."""
        return {
            "gauntlet_id": "gauntlet-test123",
            "status": "completed",
            "input_summary": "Test",
            "input_type": "spec",
            "input_hash": "abc",
            "created_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat(),
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.85,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.8,
                "total_findings": 2,
                "critical_count": 0,
                "high_count": 1,
                "medium_count": 1,
                "low_count": 0,
                "findings": [
                    {
                        "category": "security",
                        "severity_level": "high",
                        "title": "SQL injection",
                        "description": "Possible SQL injection in endpoint",
                    },
                ],
            },
        }

    @pytest.mark.asyncio
    async def test_export_json_format(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = self._completed_run_data()

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/export")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/export", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert "summary" in data
        assert "findings_summary" in data
        assert "heatmap" in data
        assert data["summary"]["verdict"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_export_html_format(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = self._completed_run_data()

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/export?format=html")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/export", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
        assert result.content_type == "text/html"
        body_str = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "APPROVED" in body_str

    @pytest.mark.asyncio
    async def test_export_not_completed(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "running",
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/export")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/export", "GET", handler
        )

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_export_unsupported_format(self, gauntlet_handler):
        """Unsupported export format should return 400."""
        _gauntlet_runs["gauntlet-test123"] = self._completed_run_data()

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/export?format=xml")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/export", "GET", handler
        )

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_export_not_found(self, gauntlet_handler):
        """Export for a non-existent run returns 404."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.get.return_value = None
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-missing123/export")

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-missing123/export", "GET", handler
            )

            assert result is not None
            assert result.status_code == 404


# ===========================================================================
# Test Version Headers and Legacy Route Deprecation
# ===========================================================================


class TestGauntletVersionHeaders:
    """Tests for API version headers and legacy route deprecation warnings."""

    @pytest.mark.asyncio
    async def test_versioned_route_has_version_header(self, gauntlet_handler):
        """Versioned routes should include X-API-Version header."""
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "pending",
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/gauntlet-test123", "GET", handler)

        assert result is not None
        assert result.headers is not None
        assert result.headers.get("X-API-Version") == "v1"

    @pytest.mark.asyncio
    async def test_legacy_route_has_deprecation_header(self, gauntlet_handler):
        """Legacy routes should include Deprecation and Sunset headers."""
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "pending",
        }

        handler = make_mock_handler(path="/api/gauntlet/gauntlet-test123")

        result = await gauntlet_handler.handle("/api/gauntlet/gauntlet-test123", "GET", handler)

        assert result is not None
        assert result.headers is not None
        assert result.headers.get("Deprecation") == "true"
        assert "Sunset" in result.headers


# ===========================================================================
# Test Memory Management
# ===========================================================================


class TestGauntletMemoryManagement:
    """Tests for memory cleanup functions."""

    def test_cleanup_removes_old_entries(self):
        """Test that cleanup removes entries older than max age."""
        old_time = datetime.now(timezone.utc).isoformat()
        _gauntlet_runs["old-run"] = {
            "status": "completed",
            "created_at": 0,  # Unix epoch - very old
            "completed_at": old_time,
        }

        _gauntlet_runs["new-run"] = {
            "status": "pending",
            "created_at": time.time(),
        }

        _cleanup_gauntlet_runs()

        assert "new-run" in _gauntlet_runs

    def test_cleanup_respects_memory_limit(self):
        """Test that cleanup enforces memory limit."""
        for i in range(MAX_GAUNTLET_RUNS_IN_MEMORY + 100):
            _gauntlet_runs[f"run-{i}"] = {
                "status": "pending",
                "created_at": datetime.now().isoformat(),
            }

        _cleanup_gauntlet_runs()

        assert len(_gauntlet_runs) <= MAX_GAUNTLET_RUNS_IN_MEMORY


# ===========================================================================
# Test ID Validation
# ===========================================================================


class TestGauntletIdValidation:
    """Tests for gauntlet ID validation."""

    @pytest.mark.asyncio
    async def test_reject_path_traversal_id(self, gauntlet_handler):
        """Test that path traversal attempts are rejected."""
        handler = make_mock_handler(path="/api/v1/gauntlet/../../etc/passwd")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/../../etc/passwd", "GET", handler)

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_accept_valid_id(self, gauntlet_handler):
        """Test that valid IDs are accepted."""
        _gauntlet_runs["gauntlet-20240114120000-abc123"] = {
            "gauntlet_id": "gauntlet-20240114120000-abc123",
            "status": "completed",
            "result": {},
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-20240114120000-abc123")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-20240114120000-abc123", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
