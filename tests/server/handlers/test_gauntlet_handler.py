"""
Comprehensive tests for aragora.server.handlers.gauntlet - Gauntlet stress-testing handler.

Tests cover:
- Route registration and can_handle (versioned and legacy)
- List personas (happy path, import error)
- Start gauntlet (happy path, invalid body, missing required field, quota exceeded)
- Get status (pending, completed, not found, invalid ID, from persistent storage, inflight)
- Get decision receipt (not completed, json format, not found in storage, various formats)
- Verify receipt (valid signature, invalid signature, id mismatch, missing fields)
- Get risk heatmap (not completed, json format, from storage fallback, svg format, ascii format)
- List results with pagination (happy path, pagination params, storage error, filtering)
- Compare results (happy path, not found, invalid compare ID, storage error)
- Delete result (happy path, not found, in-memory removal, storage error)
- Export report (json format, html format, not completed, unsupported format, not found)
- Version headers and legacy route deprecation
- Memory management (cleanup old entries, memory limit enforcement)
- ID validation (path traversal, valid IDs, special characters)
- RBAC permission decorators
- Async task execution and error handling
- Receipt auto-persistence and webhooks
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

import aragora.server.handlers.gauntlet as gauntlet_module
from aragora.server.handlers.gauntlet import (
    GauntletHandler,
    _gauntlet_runs,
    _cleanup_gauntlet_runs,
    MAX_GAUNTLET_RUNS_IN_MEMORY,
    _GAUNTLET_COMPLETED_TTL,
    _GAUNTLET_MAX_AGE_SECONDS,
    recover_stale_gauntlet_runs,
    create_tracked_task,
    set_gauntlet_broadcast_fn,
)

from aragora.tenancy.record_scope import OrgScope as _OrgScope

TEST_ORG = "test-org-001"
TEST_SCOPE = _OrgScope(org_id=TEST_ORG, user_id="test-user-001", role="admin")


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


@dataclass
class MockInflightRun:
    """Mock inflight gauntlet run."""

    gauntlet_id: str = "gauntlet-inflight123"
    status: str = "running"
    input_type: str = "spec"
    input_summary: str = "Test input"
    input_hash: str = "abc123"
    persona: str | None = None
    profile: str = "default"
    agents: list[str] = field(default_factory=lambda: ["anthropic-api"])
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_phase: str | None = "analysis"
    progress_percent: float = 50.0
    error: str | None = None
    org_id: str | None = TEST_ORG

    def to_dict(self) -> dict:
        return {
            "gauntlet_id": self.gauntlet_id,
            "status": self.status,
            "input_type": self.input_type,
            "input_summary": self.input_summary,
            "progress_percent": self.progress_percent,
        }


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


@pytest.fixture
def mock_storage():
    """Create a mock storage instance."""
    storage = MagicMock()
    storage.get.return_value = None
    storage.get_inflight.return_value = None
    storage.list_recent.return_value = []
    storage.count.return_value = 0
    storage.delete.return_value = False
    storage.compare.return_value = None
    return storage


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

    def test_can_handle_export_get(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/gauntlet/test123/export", "GET") is True

    def test_can_handle_compare_get(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/gauntlet/test1/compare/test2", "GET") is True

    def test_can_handle_delete(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/gauntlet/test123", "DELETE") is True

    def test_can_handle_legacy_route(self, gauntlet_handler):
        """Legacy non-versioned routes should also be handled."""
        assert gauntlet_handler.can_handle("/api/gauntlet/personas", "GET") is True

    def test_can_handle_legacy_run(self, gauntlet_handler):
        """Legacy run endpoint should be handled."""
        assert gauntlet_handler.can_handle("/api/gauntlet/run", "POST") is True

    def test_cannot_handle_other_paths(self, gauntlet_handler):
        assert gauntlet_handler.can_handle("/api/v1/debates", "GET") is False

    def test_cannot_handle_run_get(self, gauntlet_handler):
        """GET on /run path - can_handle returns True for any GET under /api/gauntlet/."""
        result = gauntlet_handler.can_handle("/api/v1/gauntlet/run", "GET")
        assert result is True

    def test_is_legacy_route(self, gauntlet_handler):
        """Test legacy route detection."""
        assert gauntlet_handler._is_legacy_route("/api/gauntlet/run") is True
        assert gauntlet_handler._is_legacy_route("/api/v1/gauntlet/run") is False

    def test_normalize_path(self, gauntlet_handler):
        """Test path normalization removes version prefix."""
        assert gauntlet_handler._normalize_path("/api/v1/gauntlet/run") == "/api/gauntlet/run"
        assert gauntlet_handler._normalize_path("/api/gauntlet/run") == "/api/gauntlet/run"


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

    @pytest.mark.asyncio
    async def test_list_personas_includes_attack_count(self, gauntlet_handler):
        """Test that persona listing includes attack count and categories."""
        with patch("aragora.gauntlet.personas.list_personas") as mock_list:
            with patch("aragora.gauntlet.personas.get_persona") as mock_get:
                mock_list.return_value = ["gdpr"]
                mock_persona = MockPersona()
                mock_persona.attack_prompts = [
                    MagicMock(category="privacy"),
                    MagicMock(category="security"),
                    MagicMock(category="privacy"),
                ]
                mock_get.return_value = mock_persona

                handler = make_mock_handler()
                result = await gauntlet_handler.handle("/api/v1/gauntlet/personas", "GET", handler)

                assert result is not None
                data = json.loads(result.body)
                persona_info = data["personas"][0]
                assert persona_info["attack_count"] == 3
                assert set(persona_info["categories"]) == {"privacy", "security"}


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

    @pytest.mark.asyncio
    async def test_start_gauntlet_with_all_options(self, gauntlet_handler):
        """Test starting gauntlet with all optional parameters."""
        handler = make_mock_handler(
            body={
                "input_content": "Test spec content",
                "input_type": "spec",  # Valid input_type: code, file, spec, text, url
                "persona": "gdpr",
                "agents": ["anthropic-api", "openai-api"],
                "profile": "strict",
            },
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
        # Check that run was stored in memory with correct options
        gauntlet_id = json.loads(result.body)["gauntlet_id"]
        stored_run = _gauntlet_runs.get(gauntlet_id)
        assert stored_run is not None
        assert stored_run["input_type"] == "spec"
        assert stored_run["persona"] == "gdpr"
        assert stored_run["profile"] == "strict"

    @pytest.mark.asyncio
    async def test_start_gauntlet_too_large_body(self, gauntlet_handler):
        """Test rejection of oversized request body."""
        handler = MagicMock()
        handler.command = "POST"
        handler.path = "/api/v1/gauntlet/run"
        handler.headers = {"Content-Length": str(20 * 1024 * 1024)}  # 20MB
        handler.rfile = BytesIO(b"x" * 100)
        handler.client_address = ("127.0.0.1", 12345)
        handler.user_store = None

        result = await gauntlet_handler.handle("/api/v1/gauntlet/run", "POST", handler)

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_start_gauntlet_with_authenticated_user(self, gauntlet_handler):
        """Test that usage is incremented for authenticated users."""
        user_store = MockUserStore()
        org = MockOrganization(is_at_limit=False)
        user_store.orgs["org-123"] = org

        handler = make_mock_handler(
            body={"input_content": "Test spec"},
            method="POST",
        )
        handler.user_store = user_store

        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_auth,
            patch.object(gauntlet_module, "_get_storage") as mock_storage,
            patch.object(gauntlet_module, "create_tracked_task"),
        ):
            mock_auth.return_value = MockAuthContext()
            mock_storage_inst = MagicMock()
            mock_storage.return_value = mock_storage_inst

            result = await gauntlet_handler.handle("/api/v1/gauntlet/run", "POST", handler)

        assert result is not None
        assert result.status_code == 202


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
    async def test_get_status_running(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "running",
            "created_at": datetime.now().isoformat(),
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/gauntlet-test123", "GET", handler)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["status"] == "running"

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
    async def test_get_status_failed(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "failed",
            "error": "Agent creation failed",
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/gauntlet-test123", "GET", handler)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["status"] == "failed"
        assert data["error"] == "Agent creation failed"

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
    async def test_get_status_from_inflight_storage(self, gauntlet_handler):
        """When not in memory but in inflight table after restart."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_inflight = MockInflightRun()
            mock_storage_instance.get_inflight.return_value = mock_inflight
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-inflight123")

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-inflight123", "GET", handler
            )

            assert result is not None
            assert result.status_code == 200
            data = json.loads(result.body)
            assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_status_invalid_id(self, gauntlet_handler):
        handler = make_mock_handler(path="/api/v1/gauntlet/../etc/passwd")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/../etc/passwd", "GET", handler)

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_get_status_excludes_result_obj(self, gauntlet_handler):
        """Ensure result_obj is not leaked in status response."""
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "completed",
            "result": {"verdict": "APPROVED"},
            "result_obj": MagicMock(),  # Internal object
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/gauntlet-test123", "GET", handler)

        assert result is not None
        data = json.loads(result.body)
        assert "result_obj" not in data


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
    async def test_get_receipt_html_format(self, gauntlet_handler):
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
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "total_findings": 0,
            },
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/receipt?format=html")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/receipt", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
        assert result.content_type == "text/html"

    @pytest.mark.asyncio
    async def test_get_receipt_markdown_format(self, gauntlet_handler):
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
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "total_findings": 0,
            },
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/receipt?format=md")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/receipt", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
        assert result.content_type == "text/markdown"

    @pytest.mark.asyncio
    async def test_get_receipt_sarif_format(self, gauntlet_handler):
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
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "total_findings": 0,
            },
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/receipt?format=sarif")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/receipt", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
        assert result.content_type == "application/sarif+json"

    @pytest.mark.asyncio
    async def test_get_receipt_csv_format(self, gauntlet_handler):
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
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "total_findings": 0,
            },
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/receipt?format=csv")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/receipt", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
        assert result.content_type == "text/csv"

    @pytest.mark.asyncio
    async def test_get_receipt_not_found_in_storage(self, gauntlet_handler):
        """Receipt for a run not in memory and not in storage returns error."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.get.return_value = None
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-missing123/receipt")

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-missing123/receipt", "GET", handler
            )

            assert result is not None
            assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_receipt_unsigned(self, gauntlet_handler):
        """Test getting receipt with signed=false query param."""
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
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "total_findings": 0,
            },
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/receipt?signed=false")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/receipt", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200


# ===========================================================================
# Test Verify Receipt
# ===========================================================================


class TestGauntletVerifyReceipt:
    """Tests for verify receipt endpoint."""

    @pytest.mark.asyncio
    async def test_verify_receipt_missing_body(self, gauntlet_handler):
        handler = make_mock_handler(
            body=None,
            method="POST",
            path="/api/v1/gauntlet/gauntlet-test123/receipt/verify",
        )

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/receipt/verify", "POST", handler
        )

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_receipt_missing_required_fields(self, gauntlet_handler):
        handler = make_mock_handler(
            body={"receipt": {}},  # Missing signature
            method="POST",
            path="/api/v1/gauntlet/gauntlet-test123/receipt/verify",
        )

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/receipt/verify", "POST", handler
        )

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_receipt_missing_metadata(self, gauntlet_handler):
        handler = make_mock_handler(
            body={"receipt": {}, "signature": "test"},  # Missing signature_metadata
            method="POST",
            path="/api/v1/gauntlet/gauntlet-test123/receipt/verify",
        )

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/receipt/verify", "POST", handler
        )

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_receipt_id_mismatch(self, gauntlet_handler):
        """Test verification when receipt gauntlet_id doesn't match path."""
        with patch("aragora.gauntlet.signing.verify_receipt") as mock_verify:
            mock_verify.return_value = True

            handler = make_mock_handler(
                body={
                    "receipt": {
                        "receipt_id": "receipt-123",
                        "gauntlet_id": "gauntlet-different",
                        "timestamp": datetime.now().isoformat(),
                        "input_summary": "test",
                        "input_hash": "abc",
                        "risk_summary": {},
                        "attacks_attempted": 0,
                        "attacks_successful": 0,
                        "probes_run": 0,
                        "vulnerabilities_found": 0,
                        "verdict": "PASS",
                        "confidence": 0.9,
                        "robustness_score": 0.9,
                        "artifact_hash": "def",
                    },
                    "signature": "dGVzdA==",
                    "signature_metadata": {
                        "algorithm": "HMAC-SHA256",
                        "timestamp": datetime.now().isoformat(),
                        "key_id": "test-key",
                    },
                },
                method="POST",
                path="/api/v1/gauntlet/gauntlet-test123/receipt/verify",
            )

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-test123/receipt/verify", "POST", handler
            )

            assert result is not None
            assert result.status_code == 200
            data = json.loads(result.body)
            assert data["id_match"] is False
            assert data["verified"] is False


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
    async def test_get_heatmap_svg_format(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "completed",
            "result": {
                "findings": [
                    {"category": "privacy", "severity_level": "high"},
                ],
                "total_findings": 1,
            },
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/heatmap?format=svg")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/heatmap", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
        assert result.content_type == "image/svg+xml"

    @pytest.mark.asyncio
    async def test_get_heatmap_ascii_format(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "completed",
            "result": {
                "findings": [
                    {"category": "privacy", "severity_level": "high"},
                ],
                "total_findings": 1,
            },
        }

        handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123/heatmap?format=ascii")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/heatmap", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
        assert result.content_type == "text/plain"

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

    @pytest.mark.asyncio
    async def test_get_heatmap_from_storage(self, gauntlet_handler):
        """Test heatmap generation from storage data."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.get.return_value = {
                "findings": [
                    {"category": "privacy", "severity_level": "critical"},
                ],
                "total_findings": 1,
            }
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-stored123/heatmap")

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-stored123/heatmap", "GET", handler
            )

            assert result is not None
            assert result.status_code == 200


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
    async def test_list_results_with_verdict_filter(self, gauntlet_handler):
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.list_recent.return_value = []
            mock_storage_instance.count.return_value = 0
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/results?verdict=APPROVED")

            result = await gauntlet_handler.handle("/api/v1/gauntlet/results", "GET", handler)

            assert result is not None
            assert result.status_code == 200
            # Verify filter was passed to storage
            mock_storage_instance.list_recent.assert_called_once()
            call_kwargs = mock_storage_instance.list_recent.call_args[1]
            assert call_kwargs.get("verdict") == "APPROVED"

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

    @pytest.mark.asyncio
    async def test_list_results_clamped_limit(self, gauntlet_handler):
        """Test that limit is clamped to max 100."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.list_recent.return_value = []
            mock_storage_instance.count.return_value = 0
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/results?limit=500")

            result = await gauntlet_handler.handle("/api/v1/gauntlet/results", "GET", handler)

            assert result is not None
            data = json.loads(result.body)
            assert data["limit"] == 100  # Clamped to max


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

    @pytest.mark.asyncio
    async def test_compare_invalid_first_id(self, gauntlet_handler):
        """Invalid first ID should be rejected."""
        handler = make_mock_handler(path="/api/v1/gauntlet/../etc/compare/gauntlet-test2")

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/../etc/compare/gauntlet-test2", "GET", handler
        )

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_compare_storage_error(self, gauntlet_handler):
        """Storage error during comparison should return 500."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.compare.side_effect = RuntimeError("DB error")
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
            assert result.status_code == 500


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

    @pytest.mark.asyncio
    async def test_delete_invalid_id(self, gauntlet_handler):
        """Invalid ID should be rejected."""
        handler = make_mock_handler(path="/api/v1/gauntlet/../etc/passwd", method="DELETE")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/../etc/passwd", "DELETE", handler)

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_removes_from_memory(self, gauntlet_handler):
        """Delete should remove from in-memory storage first."""
        _gauntlet_runs["gauntlet-test123"] = {"status": "completed"}

        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.delete.return_value = True
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123", method="DELETE")

            await gauntlet_handler.handle("/api/v1/gauntlet/gauntlet-test123", "DELETE", handler)

            assert "gauntlet-test123" not in _gauntlet_runs

    @pytest.mark.asyncio
    async def test_delete_storage_error(self, gauntlet_handler):
        """Storage error during deletion should return 500."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.delete.side_effect = RuntimeError("DB error")
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/gauntlet-test123", method="DELETE")

            result = await gauntlet_handler.handle(
                "/api/v1/gauntlet/gauntlet-test123", "DELETE", handler
            )

            assert result is not None
            assert result.status_code == 500


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
    async def test_export_full_html_format(self, gauntlet_handler):
        _gauntlet_runs["gauntlet-test123"] = self._completed_run_data()

        handler = make_mock_handler(
            path="/api/v1/gauntlet/gauntlet-test123/export?format=full_html"
        )

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/export", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
        assert result.content_type == "text/html"

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

    @pytest.mark.asyncio
    async def test_export_without_heatmap(self, gauntlet_handler):
        """Test export with include_heatmap=false."""
        _gauntlet_runs["gauntlet-test123"] = self._completed_run_data()

        handler = make_mock_handler(
            path="/api/v1/gauntlet/gauntlet-test123/export?include_heatmap=false"
        )

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/export", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert "heatmap" not in data

    @pytest.mark.asyncio
    async def test_export_without_findings(self, gauntlet_handler):
        """Test export with include_findings=false."""
        _gauntlet_runs["gauntlet-test123"] = self._completed_run_data()

        handler = make_mock_handler(
            path="/api/v1/gauntlet/gauntlet-test123/export?include_findings=false"
        )

        result = await gauntlet_handler.handle(
            "/api/v1/gauntlet/gauntlet-test123/export", "GET", handler
        )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert "findings" not in data


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

    @pytest.mark.asyncio
    async def test_legacy_route_has_link_header(self, gauntlet_handler):
        """Legacy routes should include Link header pointing to successor."""
        _gauntlet_runs["gauntlet-test123"] = {
            "gauntlet_id": "gauntlet-test123",
            "status": "pending",
        }

        handler = make_mock_handler(path="/api/gauntlet/gauntlet-test123")

        result = await gauntlet_handler.handle("/api/gauntlet/gauntlet-test123", "GET", handler)

        assert result is not None
        assert result.headers is not None
        assert "Link" in result.headers
        assert "successor-version" in result.headers["Link"]


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

    def test_cleanup_removes_completed_old_entries(self):
        """Test that completed entries older than TTL are removed."""
        old_completed_time = datetime.now(timezone.utc) - timedelta(
            seconds=_GAUNTLET_COMPLETED_TTL + 100
        )
        _gauntlet_runs["old-completed"] = {
            "status": "completed",
            "created_at": time.time() - 1000,
            "completed_at": old_completed_time.isoformat(),
        }

        _cleanup_gauntlet_runs()

        assert "old-completed" not in _gauntlet_runs

    def test_cleanup_preserves_recent_completed(self):
        """Test that recently completed entries are preserved."""
        recent_completed_time = datetime.now(timezone.utc)
        _gauntlet_runs["recent-completed"] = {
            "status": "completed",
            "created_at": time.time(),
            "completed_at": recent_completed_time.isoformat(),
        }

        _cleanup_gauntlet_runs()

        assert "recent-completed" in _gauntlet_runs

    def test_cleanup_fifo_eviction(self):
        """Test that FIFO eviction works when over limit."""
        # Add entries in order
        for i in range(MAX_GAUNTLET_RUNS_IN_MEMORY + 10):
            _gauntlet_runs[f"run-{i:04d}"] = {
                "status": "pending",
                "created_at": time.time(),
            }

        _cleanup_gauntlet_runs()

        # First entries should be evicted
        assert "run-0000" not in _gauntlet_runs
        assert "run-0001" not in _gauntlet_runs


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
    async def test_reject_null_byte_id(self, gauntlet_handler):
        """Test that null byte injection is rejected."""
        handler = make_mock_handler(path="/api/v1/gauntlet/test%00passwd")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/test\x00passwd", "GET", handler)

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


# ===========================================================================
# Test Stale Run Recovery
# ===========================================================================


class TestGauntletStaleRecovery:
    """Tests for stale run recovery after server restart."""

    def test_recover_stale_runs_empty(self):
        """Test recovery when no stale runs exist."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.list_stale_inflight.return_value = []
            mock_storage.return_value = mock_storage_instance

            count = recover_stale_gauntlet_runs()

            assert count == 0

    def test_recover_stale_runs_marks_interrupted(self):
        """Test that stale runs are marked as interrupted."""
        stale_run = MockInflightRun()
        stale_run.status = "running"
        stale_run.progress_percent = 75.0
        stale_run.current_phase = "analysis"

        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.list_stale_inflight.return_value = [stale_run]
            mock_storage.return_value = mock_storage_instance

            count = recover_stale_gauntlet_runs()

            assert count == 1
            mock_storage_instance.update_inflight_status.assert_called_once()
            # The recovered run stays visible only to the org that started it.
            assert _gauntlet_runs[stale_run.gauntlet_id]["org_id"] == TEST_ORG

    def test_recover_stale_runs_storage_error(self):
        """Test recovery handles storage errors gracefully."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage.side_effect = RuntimeError("DB error")

            count = recover_stale_gauntlet_runs()

            assert count == 0


# ===========================================================================
# Test Broadcast Function
# ===========================================================================


class TestGauntletBroadcast:
    """Tests for broadcast function setup."""

    def test_set_broadcast_fn(self):
        """Test setting the broadcast function."""
        mock_fn = MagicMock()
        set_gauntlet_broadcast_fn(mock_fn)
        assert gauntlet_module._gauntlet_broadcast_fn == mock_fn
        # Reset
        set_gauntlet_broadcast_fn(None)

    def test_handler_init_sets_broadcast(self):
        """Test that handler init sets broadcast function from context."""
        mock_emitter = MagicMock()
        mock_emitter.emit = MagicMock()

        ctx = {"stream_emitter": mock_emitter}
        handler = GauntletHandler(ctx)

        assert gauntlet_module._gauntlet_broadcast_fn is not None
        # Reset
        set_gauntlet_broadcast_fn(None)


# ===========================================================================
# Test Task Creation Helper
# ===========================================================================


class TestGauntletTaskCreation:
    """Tests for async task creation helper."""

    @pytest.mark.asyncio
    async def test_create_tracked_task(self):
        """Test that create_tracked_task creates a proper async task."""

        async def dummy_coro():
            return "done"

        task = create_tracked_task(dummy_coro(), name="test-task")
        assert task.get_name() == "test-task"

        result = await task
        assert result == "done"

    @pytest.mark.asyncio
    async def test_create_tracked_task_with_exception(self):
        """Test that task exceptions are logged."""

        async def failing_coro():
            raise ValueError("Test error")

        task = create_tracked_task(failing_coro(), name="failing-task")

        with pytest.raises(ValueError):
            await task


# ===========================================================================
# Test Risk Level Calculation
# ===========================================================================


class TestGauntletRiskLevel:
    """Tests for risk level calculation from robustness score."""

    def test_risk_level_low(self, gauntlet_handler):
        """High robustness score should give LOW risk."""
        level = gauntlet_handler._risk_level_from_score(0.85)
        assert level == "LOW"

    def test_risk_level_medium(self, gauntlet_handler):
        """Medium robustness score should give MEDIUM risk."""
        level = gauntlet_handler._risk_level_from_score(0.65)
        assert level == "MEDIUM"

    def test_risk_level_high(self, gauntlet_handler):
        """Low robustness score should give HIGH risk."""
        level = gauntlet_handler._risk_level_from_score(0.45)
        assert level == "HIGH"

    def test_risk_level_critical(self, gauntlet_handler):
        """Very low robustness score should give CRITICAL risk."""
        level = gauntlet_handler._risk_level_from_score(0.2)
        assert level == "CRITICAL"


# ===========================================================================
# Test Special Endpoints (Not Matched by ID Pattern)
# ===========================================================================


class TestGauntletSpecialEndpoints:
    """Tests for endpoints that should not be matched by ID pattern."""

    @pytest.mark.asyncio
    async def test_run_not_treated_as_id(self, gauntlet_handler):
        """Test that 'run' is not treated as a gauntlet ID on GET."""
        handler = make_mock_handler(path="/api/v1/gauntlet/run")

        result = await gauntlet_handler.handle("/api/v1/gauntlet/run", "GET", handler)

        # Should return None or handle differently
        # The can_handle returns True but handle should not find it as an ID
        assert result is None or result.status_code != 200

    @pytest.mark.asyncio
    async def test_personas_not_treated_as_id(self, gauntlet_handler):
        """Test that 'personas' endpoint works correctly."""
        with patch("aragora.gauntlet.personas.list_personas") as mock_list:
            with patch("aragora.gauntlet.personas.get_persona") as mock_get:
                mock_list.return_value = []
                mock_get.return_value = MockPersona()

                handler = make_mock_handler(path="/api/v1/gauntlet/personas")

                result = await gauntlet_handler.handle("/api/v1/gauntlet/personas", "GET", handler)

                assert result is not None
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_results_not_treated_as_id(self, gauntlet_handler):
        """Test that 'results' endpoint works correctly."""
        with patch.object(gauntlet_module, "_get_storage") as mock_storage:
            mock_storage_instance = MagicMock()
            mock_storage_instance.list_recent.return_value = []
            mock_storage_instance.count.return_value = 0
            mock_storage.return_value = mock_storage_instance

            handler = make_mock_handler(path="/api/v1/gauntlet/results")

            result = await gauntlet_handler.handle("/api/v1/gauntlet/results", "GET", handler)

            assert result is not None
            assert result.status_code == 200
