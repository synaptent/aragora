"""Tests for public status page handler (aragora/server/handlers/public/status_page.py).

Covers all routes and behavior of the StatusPageHandler class:
- can_handle() routing for all ROUTES and prefix matching
- GET /status                  - HTML status page
- GET /api/status              - JSON status summary
- GET /api/status/summary      - JSON status summary (alias)
- GET /api/status/history      - Historical uptime data
- GET /api/status/components   - Individual component status
- GET /api/status/incidents    - Current and recent incidents
- Overall status calculation logic
- Individual component health checks (API, DB, Redis, Debate, Knowledge, Codebase, WS, Auth)
- Error handling and graceful degradation
- Data class construction and enum values
- Uptime formatting
- Status message mapping
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.public.status_page import (
    ComponentHealth,
    Incident,
    ServiceStatus,
    StatusPageHandler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: Any) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result: Any) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler() -> StatusPageHandler:
    """Create a StatusPageHandler with empty context."""
    return StatusPageHandler(ctx={})


@pytest.fixture
def mock_http_handler() -> MagicMock:
    """Create a mock HTTP request handler."""
    h = MagicMock()
    h.command = "GET"
    h.client_address = ("127.0.0.1", 12345)
    h.headers = {"Content-Length": "0"}
    return h


# ============================================================================
# Data Classes and Enums
# ============================================================================


class TestServiceStatus:
    """Tests for ServiceStatus enum values."""

    def test_operational(self):
        assert ServiceStatus.OPERATIONAL.value == "operational"

    def test_degraded(self):
        assert ServiceStatus.DEGRADED.value == "degraded"

    def test_partial_outage(self):
        assert ServiceStatus.PARTIAL_OUTAGE.value == "partial_outage"

    def test_major_outage(self):
        assert ServiceStatus.MAJOR_OUTAGE.value == "major_outage"

    def test_maintenance(self):
        assert ServiceStatus.MAINTENANCE.value == "maintenance"

    def test_all_values_unique(self):
        values = [s.value for s in ServiceStatus]
        assert len(values) == len(set(values))

    def test_member_count(self):
        assert len(ServiceStatus) == 5


class TestComponentHealth:
    """Tests for ComponentHealth dataclass."""

    def test_minimal_construction(self):
        ch = ComponentHealth(name="test", status=ServiceStatus.OPERATIONAL)
        assert ch.name == "test"
        assert ch.status == ServiceStatus.OPERATIONAL
        assert ch.response_time_ms is None
        assert ch.last_check is None
        assert ch.message is None

    def test_full_construction(self):
        now = datetime.now(timezone.utc)
        ch = ComponentHealth(
            name="API",
            status=ServiceStatus.DEGRADED,
            response_time_ms=42.5,
            last_check=now,
            message="Slow response times",
        )
        assert ch.name == "API"
        assert ch.status == ServiceStatus.DEGRADED
        assert ch.response_time_ms == 42.5
        assert ch.last_check == now
        assert ch.message == "Slow response times"


class TestIncident:
    """Tests for Incident dataclass."""

    def test_construction(self):
        now = datetime.now(timezone.utc)
        inc = Incident(
            id="inc-001",
            title="API outage",
            status="investigating",
            severity="major",
            components=["api", "database"],
            created_at=now,
            updated_at=now,
        )
        assert inc.id == "inc-001"
        assert inc.title == "API outage"
        assert inc.resolved_at is None
        assert inc.updates == []

    def test_with_updates(self):
        now = datetime.now(timezone.utc)
        updates = [{"time": now.isoformat(), "message": "Investigating"}]
        inc = Incident(
            id="inc-002",
            title="Degraded performance",
            status="identified",
            severity="minor",
            components=["redis"],
            created_at=now,
            updated_at=now,
            resolved_at=now,
            updates=updates,
        )
        assert inc.resolved_at == now
        assert len(inc.updates) == 1


# ============================================================================
# Route Matching (can_handle)
# ============================================================================


class TestCanHandle:
    """Tests for can_handle() route matching."""

    def test_status_html(self, handler):
        assert handler.can_handle("/status") is True

    def test_api_status(self, handler):
        assert handler.can_handle("/api/status") is True

    def test_api_status_summary(self, handler):
        assert handler.can_handle("/api/status/summary") is True

    def test_api_status_history(self, handler):
        assert handler.can_handle("/api/status/history") is True

    def test_api_status_components(self, handler):
        assert handler.can_handle("/api/status/components") is True

    def test_api_status_incidents(self, handler):
        assert handler.can_handle("/api/status/incidents") is True

    def test_api_status_prefix_match(self, handler):
        """Paths starting with /api/status/ are accepted by prefix matching."""
        assert handler.can_handle("/api/status/something-custom") is True

    def test_rejects_unrelated_paths(self, handler):
        assert handler.can_handle("/api/debates") is False
        assert handler.can_handle("/api/agents") is False
        assert handler.can_handle("/api/health") is False
        assert handler.can_handle("/other") is False

    def test_rejects_partial_prefix(self, handler):
        assert handler.can_handle("/api/statusx") is False
        assert handler.can_handle("/statuspage") is False


# ============================================================================
# Initialization
# ============================================================================


class TestInit:
    """Tests for handler initialization."""

    def test_default_ctx(self):
        h = StatusPageHandler()
        assert h.ctx == {}

    def test_none_ctx(self):
        h = StatusPageHandler(ctx=None)
        assert h.ctx == {}

    def test_custom_ctx(self):
        ctx = {"storage": MagicMock()}
        h = StatusPageHandler(ctx=ctx)
        assert h.ctx is ctx


# ============================================================================
# ROUTES constant
# ============================================================================


class TestRoutes:
    """Tests for ROUTES constant."""

    def test_contains_all_expected_routes(self):
        expected = [
            "/status",
            "/api/status",
            "/api/status/summary",
            "/api/status/history",
            "/api/status/components",
            "/api/status/incidents",
            # Versioned v1 routes (public, no auth, return {"data": ...} envelope)
            "/api/v1/status",
            "/api/v1/status/components",
            "/api/v1/status/incidents",
            "/api/v1/status/uptime",
            "/api/v1/public/surfaces",
        ]
        assert StatusPageHandler.ROUTES == expected

    def test_components_count(self):
        assert len(StatusPageHandler.COMPONENTS) == 8

    def test_component_ids(self):
        ids = [c["id"] for c in StatusPageHandler.COMPONENTS]
        expected = [
            "api",
            "database",
            "redis",
            "debates",
            "knowledge",
            "codebase_context",
            "websocket",
            "auth",
        ]
        assert ids == expected


# ============================================================================
# Handle dispatch
# ============================================================================


class TestHandleDispatch:
    """Tests for handle() method dispatch."""

    def test_unknown_path_returns_none(self, handler, mock_http_handler):
        result = handler.handle("/api/unknown", {}, mock_http_handler)
        assert result is None

    def test_status_html_returns_result(self, handler, mock_http_handler):
        with patch.object(handler, "_check_all_components", return_value=[]):
            result = handler.handle("/status", {}, mock_http_handler)
        assert result is not None
        assert result.status_code == 200
        assert "text/html" in result.content_type

    def test_api_status_returns_json(self, handler, mock_http_handler):
        with patch.object(handler, "_check_all_components", return_value=[]):
            result = handler.handle("/api/status", {}, mock_http_handler)
        assert result is not None
        body = _body(result)
        assert "status" in body
        assert "public_surfaces_summary" in body

    def test_api_status_summary_alias(self, handler, mock_http_handler):
        with patch.object(handler, "_check_all_components", return_value=[]):
            result = handler.handle("/api/status/summary", {}, mock_http_handler)
        assert result is not None
        body = _body(result)
        assert "status" in body

    def test_api_status_history(self, handler, mock_http_handler):
        with patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL):
            result = handler.handle("/api/status/history", {}, mock_http_handler)
        assert result is not None
        body = _body(result)
        assert "periods" in body

    def test_api_status_components(self, handler, mock_http_handler):
        with patch.object(handler, "_check_all_components", return_value=[]):
            result = handler.handle("/api/status/components", {}, mock_http_handler)
        assert result is not None
        body = _body(result)
        assert "components" in body
        assert "public_surfaces" in body

    def test_api_status_incidents(self, handler, mock_http_handler):
        result = handler.handle("/api/status/incidents", {}, mock_http_handler)
        assert result is not None
        body = _body(result)
        assert "active" in body
        assert "recent" in body


# ============================================================================
# Overall Status Calculation
# ============================================================================


class TestOverallStatus:
    """Tests for _get_overall_status() aggregation logic."""

    def _make_components(self, statuses: list[ServiceStatus]) -> list[ComponentHealth]:
        return [ComponentHealth(name=f"c{i}", status=s) for i, s in enumerate(statuses)]

    def test_all_operational(self, handler):
        comps = self._make_components([ServiceStatus.OPERATIONAL] * 4)
        with patch.object(handler, "_check_all_components", return_value=comps):
            assert handler._get_overall_status() == ServiceStatus.OPERATIONAL

    def test_one_major_outage_yields_major(self, handler):
        comps = self._make_components(
            [
                ServiceStatus.OPERATIONAL,
                ServiceStatus.MAJOR_OUTAGE,
                ServiceStatus.OPERATIONAL,
            ]
        )
        with patch.object(handler, "_check_all_components", return_value=comps):
            assert handler._get_overall_status() == ServiceStatus.MAJOR_OUTAGE

    def test_two_partial_outages_yield_major(self, handler):
        comps = self._make_components(
            [
                ServiceStatus.PARTIAL_OUTAGE,
                ServiceStatus.PARTIAL_OUTAGE,
                ServiceStatus.OPERATIONAL,
            ]
        )
        with patch.object(handler, "_check_all_components", return_value=comps):
            assert handler._get_overall_status() == ServiceStatus.MAJOR_OUTAGE

    def test_one_partial_outage_yields_partial(self, handler):
        comps = self._make_components(
            [
                ServiceStatus.OPERATIONAL,
                ServiceStatus.PARTIAL_OUTAGE,
                ServiceStatus.OPERATIONAL,
            ]
        )
        with patch.object(handler, "_check_all_components", return_value=comps):
            assert handler._get_overall_status() == ServiceStatus.PARTIAL_OUTAGE

    def test_one_degraded_yields_degraded(self, handler):
        comps = self._make_components(
            [
                ServiceStatus.OPERATIONAL,
                ServiceStatus.DEGRADED,
                ServiceStatus.OPERATIONAL,
            ]
        )
        with patch.object(handler, "_check_all_components", return_value=comps):
            assert handler._get_overall_status() == ServiceStatus.DEGRADED

    def test_one_maintenance_yields_maintenance(self, handler):
        comps = self._make_components(
            [
                ServiceStatus.OPERATIONAL,
                ServiceStatus.MAINTENANCE,
            ]
        )
        with patch.object(handler, "_check_all_components", return_value=comps):
            assert handler._get_overall_status() == ServiceStatus.MAINTENANCE

    def test_major_outage_takes_precedence_over_degraded(self, handler):
        comps = self._make_components(
            [
                ServiceStatus.DEGRADED,
                ServiceStatus.MAJOR_OUTAGE,
            ]
        )
        with patch.object(handler, "_check_all_components", return_value=comps):
            assert handler._get_overall_status() == ServiceStatus.MAJOR_OUTAGE

    def test_partial_takes_precedence_over_degraded(self, handler):
        comps = self._make_components(
            [
                ServiceStatus.DEGRADED,
                ServiceStatus.PARTIAL_OUTAGE,
            ]
        )
        with patch.object(handler, "_check_all_components", return_value=comps):
            assert handler._get_overall_status() == ServiceStatus.PARTIAL_OUTAGE

    def test_degraded_takes_precedence_over_maintenance(self, handler):
        comps = self._make_components(
            [
                ServiceStatus.DEGRADED,
                ServiceStatus.MAINTENANCE,
            ]
        )
        with patch.object(handler, "_check_all_components", return_value=comps):
            assert handler._get_overall_status() == ServiceStatus.DEGRADED

    def test_empty_components_yields_operational(self, handler):
        with patch.object(handler, "_check_all_components", return_value=[]):
            assert handler._get_overall_status() == ServiceStatus.OPERATIONAL


# ============================================================================
# Individual Component Health Checks
# ============================================================================


class TestCheckComponent:
    """Tests for _check_component() dispatch and error handling."""

    def test_unknown_component_is_operational(self, handler):
        result = handler._check_component("nonexistent")
        assert result.status == ServiceStatus.OPERATIONAL
        assert result.name == "nonexistent"

    def test_checker_exception_yields_partial_outage(self, handler):
        with patch.object(handler, "_check_api_health", side_effect=RuntimeError("boom")):
            result = handler._check_component("api")
        assert result.status == ServiceStatus.PARTIAL_OUTAGE
        assert "RuntimeError" in result.message

    def test_checker_os_error(self, handler):
        with patch.object(handler, "_check_database_health", side_effect=OSError("disk")):
            result = handler._check_component("database")
        assert result.status == ServiceStatus.PARTIAL_OUTAGE

    def test_checker_value_error(self, handler):
        with patch.object(handler, "_check_redis_health", side_effect=ValueError("bad")):
            result = handler._check_component("redis")
        assert result.status == ServiceStatus.PARTIAL_OUTAGE

    def test_checker_type_error(self, handler):
        with patch.object(handler, "_check_debate_health", side_effect=TypeError("oops")):
            result = handler._check_component("debates")
        assert result.status == ServiceStatus.PARTIAL_OUTAGE

    def test_checker_attribute_error(self, handler):
        with patch.object(handler, "_check_knowledge_health", side_effect=AttributeError("x")):
            result = handler._check_component("knowledge")
        assert result.status == ServiceStatus.PARTIAL_OUTAGE


class TestCheckAllComponents:
    """Tests for _check_all_components()."""

    def test_returns_list_with_last_check(self, handler):
        with patch.object(handler, "_check_component") as mock_check:
            mock_check.return_value = ComponentHealth(name="test", status=ServiceStatus.OPERATIONAL)
            results = handler._check_all_components()

        assert len(results) == len(handler.COMPONENTS)
        for r in results:
            assert r.last_check is not None

    def test_calls_check_for_each_component(self, handler):
        with patch.object(handler, "_check_component") as mock_check:
            mock_check.return_value = ComponentHealth(name="test", status=ServiceStatus.OPERATIONAL)
            handler._check_all_components()

        expected_ids = [c["id"] for c in handler.COMPONENTS]
        called_ids = [call.args[0] for call in mock_check.call_args_list]
        assert called_ids == expected_ids


class TestPublicSurfaceReadiness:
    """Tests for public-surface readiness inventory."""

    def test_summary_counts_live_and_partial_surfaces(self, handler):
        surfaces = handler._get_public_surface_readiness()
        summary = handler._summarize_public_surfaces(surfaces)

        assert summary["total"] == len(surfaces)
        assert summary["live"] >= 1
        assert summary["partial"] >= 1

    def test_component_status_includes_surface_inventory(self, handler, mock_http_handler):
        result = handler.handle("/api/status/components", {}, mock_http_handler)
        body = _body(result)

        surfaces = {surface["id"]: surface for surface in body["public_surfaces"]}
        assert surfaces["status_page"]["readiness"] == "live"
        assert surfaces["openapi"]["placeholder_backed"] is True
        assert surfaces["memory_progressive"]["backend_conditional"] is True

    def test_v1_component_status_includes_surface_inventory(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/status/components", {}, mock_http_handler)
        body = _body(result)

        surfaces = {surface["id"]: surface for surface in body["data"]["public_surfaces"]}
        assert surfaces["status_page"]["readiness"] == "live"
        assert surfaces["openapi"]["readiness"] == "partial"
        assert surfaces["memory_progressive"]["readiness"] == "partial"

    def test_memory_surface_is_live_with_capable_backend(self, handler):
        handler.ctx["continuum_memory"] = type(
            "ContinuumStub",
            (),
            {"get_timeline_entries": object(), "get_many": object()},
        )()

        surface = handler._get_memory_surface_readiness()

        assert surface.readiness == "live"
        assert surface.backend_conditional is False

    def test_openapi_surface_uses_placeholder_audit(self, handler):
        with patch.object(
            handler,
            "_audit_openapi_placeholders",
            return_value={"spec_available": True, "placeholder_operations": 7},
        ):
            surface = handler._get_openapi_surface_readiness()

        assert surface.readiness == "partial"
        assert surface.placeholder_backed is True
        assert surface.details["placeholder_operations"] == 7


class TestApiHealth:
    """Tests for _check_api_health()."""

    def test_always_operational(self, handler):
        result = handler._check_api_health()
        assert result.status == ServiceStatus.OPERATIONAL
        assert result.name == "API"
        assert result.response_time_ms is not None
        assert result.response_time_ms >= 0


class TestDatabaseHealth:
    """Tests for _check_database_health()."""

    def test_sqlite_db_exists(self, handler, tmp_path, monkeypatch):
        db_file = tmp_path / "debates.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        monkeypatch.delenv("ARAGORA_DB_BACKEND", raising=False)
        with (
            patch(
                "aragora.server.handlers.public.status_page.os.environ.get",
                return_value="sqlite",
            ),
            patch("aragora.server.handlers.public.status_page.run_async"),
            patch(
                "aragora.persistence.db_config.get_db_path",
                return_value=db_file,
            ),
        ):
            result = handler._check_database_health()
        assert result.status == ServiceStatus.OPERATIONAL
        assert result.response_time_ms is not None

    def test_sqlite_db_not_exists(self, handler, tmp_path):
        db_file = tmp_path / "nonexistent.db"
        with (
            patch(
                "aragora.server.handlers.public.status_page.os.environ.get",
                return_value="sqlite",
            ),
            patch(
                "aragora.persistence.db_config.get_db_path",
                return_value=db_file,
            ),
        ):
            result = handler._check_database_health()
        assert result.status == ServiceStatus.OPERATIONAL
        assert result.message == "Database not yet initialized"

    def test_postgres_with_pool(self, handler):
        mock_pool = MagicMock()
        with (
            patch(
                "aragora.server.handlers.public.status_page.os.environ.get",
                return_value="postgres",
            ),
            patch(
                "aragora.server.handlers.public.status_page.run_async",
                return_value=mock_pool,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres": MagicMock()}),
        ):
            result = handler._check_database_health()
        assert result.status == ServiceStatus.OPERATIONAL

    def test_postgres_no_pool(self, handler):
        with (
            patch(
                "aragora.server.handlers.public.status_page.os.environ.get",
                return_value="postgres",
            ),
            patch(
                "aragora.server.handlers.public.status_page.run_async",
                return_value=None,
            ),
            patch.dict("sys.modules", {"aragora.storage.postgres": MagicMock()}),
        ):
            result = handler._check_database_health()
        assert result.status == ServiceStatus.PARTIAL_OUTAGE

    def test_postgres_import_error(self, handler):
        with patch(
            "aragora.server.handlers.public.status_page.os.environ.get",
            return_value="postgresql",
        ):
            # Force ImportError by patching the import inside the method
            import builtins

            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "aragora.storage.postgres":
                    raise ImportError("no psycopg2")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = handler._check_database_health()
        assert result.status == ServiceStatus.DEGRADED
        assert "not installed" in result.message

    def test_database_exception_fallback(self, handler):
        with (
            patch(
                "aragora.server.handlers.public.status_page.os.environ.get",
                return_value="sqlite",
            ),
            patch(
                "aragora.persistence.db_config.get_db_path",
                side_effect=ImportError("no module"),
            ),
        ):
            result = handler._check_database_health()
        assert result.status == ServiceStatus.PARTIAL_OUTAGE
        assert "unavailable" in result.message


class TestRedisHealth:
    """Tests for _check_redis_health()."""

    def test_redis_available_and_pingable(self, handler):
        mock_client = MagicMock()
        mock_client.ping.return_value = True

        with (
            patch(
                "aragora.server.handlers.public.status_page.is_redis_available",
                return_value=True,
                create=True,
            ) as _,
            patch(
                "aragora.server.handlers.public.status_page.get_redis_client",
                return_value=mock_client,
                create=True,
            ) as _,
        ):
            # The method imports from aragora.utils.redis_config inside, so patch that module
            mock_redis_config = MagicMock()
            mock_redis_config.is_redis_available.return_value = True
            mock_redis_config.get_redis_client.return_value = mock_client
            with patch.dict("sys.modules", {"aragora.utils.redis_config": mock_redis_config}):
                result = handler._check_redis_health()

        assert result.status == ServiceStatus.OPERATIONAL
        assert result.response_time_ms is not None

    def test_redis_not_available(self, handler):
        mock_redis_config = MagicMock()
        mock_redis_config.is_redis_available.return_value = False
        with patch.dict("sys.modules", {"aragora.utils.redis_config": mock_redis_config}):
            result = handler._check_redis_health()
        assert result.status == ServiceStatus.DEGRADED
        assert "unavailable" in result.message

    def test_redis_client_none(self, handler):
        mock_redis_config = MagicMock()
        mock_redis_config.is_redis_available.return_value = True
        mock_redis_config.get_redis_client.return_value = None
        with patch.dict("sys.modules", {"aragora.utils.redis_config": mock_redis_config}):
            result = handler._check_redis_health()
        assert result.status == ServiceStatus.DEGRADED

    def test_redis_import_error(self, handler):
        # Remove the module so import fails
        import sys

        saved = sys.modules.pop("aragora.utils.redis_config", None)
        try:
            import builtins

            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if "redis_config" in name:
                    raise ImportError("no redis")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = handler._check_redis_health()
            assert result.status == ServiceStatus.DEGRADED
        finally:
            if saved is not None:
                sys.modules["aragora.utils.redis_config"] = saved

    def test_redis_ping_connection_error(self, handler):
        mock_client = MagicMock()
        mock_client.ping.side_effect = ConnectionError("refused")

        mock_redis_config = MagicMock()
        mock_redis_config.is_redis_available.return_value = True
        mock_redis_config.get_redis_client.return_value = mock_client
        with patch.dict("sys.modules", {"aragora.utils.redis_config": mock_redis_config}):
            result = handler._check_redis_health()
        assert result.status == ServiceStatus.DEGRADED


class TestDebateHealth:
    """Tests for _check_debate_health()."""

    def test_module_available(self, handler):
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            result = handler._check_debate_health()
        assert result.status == ServiceStatus.OPERATIONAL
        assert result.name == "Debate Engine"

    def test_module_not_available(self, handler):
        with patch("importlib.util.find_spec", return_value=None):
            result = handler._check_debate_health()
        assert result.status == ServiceStatus.PARTIAL_OUTAGE
        assert "not available" in result.message


class TestKnowledgeHealth:
    """Tests for _check_knowledge_health()."""

    def test_module_available(self, handler):
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            result = handler._check_knowledge_health()
        assert result.status == ServiceStatus.OPERATIONAL
        assert result.name == "Knowledge Mound"

    def test_module_not_available(self, handler):
        with patch("importlib.util.find_spec", return_value=None):
            result = handler._check_knowledge_health()
        assert result.status == ServiceStatus.DEGRADED
        assert "not fully available" in result.message


class TestCodebaseContextHealth:
    """Tests for _check_codebase_context_health()."""

    def test_available_status(self, handler):
        mock_check = MagicMock(return_value={"status": "available"})
        mock_module = MagicMock()
        mock_module.check_codebase_context = mock_check
        with patch.dict(
            "sys.modules",
            {"aragora.server.handlers.admin.health.knowledge_mound_utils": mock_module},
        ):
            result = handler._check_codebase_context_health()
        assert result.status == ServiceStatus.OPERATIONAL
        assert result.response_time_ms is not None

    def test_missing_status_optional(self, handler, monkeypatch):
        monkeypatch.setenv("ARAGORA_CODEBASE_STATUS_OPTIONAL", "1")
        mock_check = MagicMock(return_value={"status": "missing"})
        mock_module = MagicMock()
        mock_module.check_codebase_context = mock_check
        with patch.dict(
            "sys.modules",
            {"aragora.server.handlers.admin.health.knowledge_mound_utils": mock_module},
        ):
            result = handler._check_codebase_context_health()
        assert result.status == ServiceStatus.OPERATIONAL
        assert result.message == "not configured"

    def test_missing_status_required(self, handler, monkeypatch):
        monkeypatch.setenv("ARAGORA_CODEBASE_STATUS_OPTIONAL", "0")
        mock_check = MagicMock(return_value={"status": "missing"})
        mock_module = MagicMock()
        mock_module.check_codebase_context = mock_check
        with patch.dict(
            "sys.modules",
            {"aragora.server.handlers.admin.health.knowledge_mound_utils": mock_module},
        ):
            result = handler._check_codebase_context_health()
        assert result.status == ServiceStatus.DEGRADED
        assert result.message == "manifest missing"

    def test_error_status(self, handler):
        mock_check = MagicMock(return_value={"status": "error", "error": "disk full"})
        mock_module = MagicMock()
        mock_module.check_codebase_context = mock_check
        with patch.dict(
            "sys.modules",
            {"aragora.server.handlers.admin.health.knowledge_mound_utils": mock_module},
        ):
            result = handler._check_codebase_context_health()
        assert result.status == ServiceStatus.PARTIAL_OUTAGE
        assert result.message == "disk full"

    def test_error_status_no_detail(self, handler):
        mock_check = MagicMock(return_value={"status": "error"})
        mock_module = MagicMock()
        mock_module.check_codebase_context = mock_check
        with patch.dict(
            "sys.modules",
            {"aragora.server.handlers.admin.health.knowledge_mound_utils": mock_module},
        ):
            result = handler._check_codebase_context_health()
        assert result.status == ServiceStatus.PARTIAL_OUTAGE
        assert result.message == "health check error"

    def test_import_error_fallback(self, handler):
        import builtins

        original_import = builtins.__import__

        import sys

        saved = sys.modules.pop("aragora.server.handlers.admin.health.knowledge_mound_utils", None)
        try:

            def mock_import(name, *args, **kwargs):
                if "knowledge_mound_utils" in name:
                    raise ImportError("no module")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = handler._check_codebase_context_health()
            assert result.status == ServiceStatus.DEGRADED
            assert result.message == "health check unavailable"
        finally:
            if saved is not None:
                sys.modules["aragora.server.handlers.admin.health.knowledge_mound_utils"] = saved

    def test_runtime_error_fallback(self, handler):
        mock_check = MagicMock(side_effect=RuntimeError("check failed"))
        mock_module = MagicMock()
        mock_module.check_codebase_context = mock_check
        with patch.dict(
            "sys.modules",
            {"aragora.server.handlers.admin.health.knowledge_mound_utils": mock_module},
        ):
            result = handler._check_codebase_context_health()
        assert result.status == ServiceStatus.DEGRADED
        assert result.message == "health check unavailable"

    def test_default_optional_env(self, handler, monkeypatch):
        """ARAGORA_CODEBASE_STATUS_OPTIONAL defaults to '1'."""
        monkeypatch.delenv("ARAGORA_CODEBASE_STATUS_OPTIONAL", raising=False)
        mock_check = MagicMock(return_value={"status": "missing"})
        mock_module = MagicMock()
        mock_module.check_codebase_context = mock_check
        with patch.dict(
            "sys.modules",
            {"aragora.server.handlers.admin.health.knowledge_mound_utils": mock_module},
        ):
            result = handler._check_codebase_context_health()
        assert result.status == ServiceStatus.OPERATIONAL


class TestWebsocketHealth:
    """Tests for _check_websocket_health()."""

    def test_always_operational(self, handler):
        result = handler._check_websocket_health()
        assert result.status == ServiceStatus.OPERATIONAL
        assert result.name == "Real-time"


class TestAuthHealth:
    """Tests for _check_auth_health()."""

    def test_module_available(self, handler):
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            result = handler._check_auth_health()
        assert result.status == ServiceStatus.OPERATIONAL
        assert result.name == "Authentication"

    def test_module_not_available(self, handler):
        with patch("importlib.util.find_spec", return_value=None):
            result = handler._check_auth_health()
        assert result.status == ServiceStatus.DEGRADED
        assert "not available" in result.message


# ============================================================================
# JSON Status Summary Endpoint
# ============================================================================


class TestJsonStatusSummary:
    """Tests for _json_status_summary() response."""

    def test_response_shape(self, handler):
        comps = [
            ComponentHealth(name="API", status=ServiceStatus.OPERATIONAL, response_time_ms=1.0),
        ]
        with (
            patch.object(handler, "_check_all_components", return_value=comps),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler._json_status_summary()

        body = _body(result)
        assert body["status"] == "operational"
        assert body["message"] == "All Systems Operational"
        assert "uptime_seconds" in body
        assert "uptime_formatted" in body
        assert "timestamp" in body
        assert "components" in body

    def test_component_fields(self, handler):
        comps = [
            ComponentHealth(
                name="API",
                status=ServiceStatus.OPERATIONAL,
                response_time_ms=2.5,
                message=None,
            ),
        ]
        with (
            patch.object(handler, "_check_all_components", return_value=comps),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler._json_status_summary()

        body = _body(result)
        comp = body["components"][0]
        assert comp["id"] == "api"
        assert comp["name"] == "API"
        assert comp["status"] == "operational"
        assert comp["response_time_ms"] == 2.5
        assert comp["message"] is None

    def test_status_code_200(self, handler):
        with (
            patch.object(handler, "_check_all_components", return_value=[]),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler._json_status_summary()
        assert _status(result) == 200

    def test_degraded_message(self, handler):
        with (
            patch.object(handler, "_check_all_components", return_value=[]),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.DEGRADED),
        ):
            result = handler._json_status_summary()
        body = _body(result)
        assert body["message"] == "Degraded Performance"

    def test_major_outage_message(self, handler):
        with (
            patch.object(handler, "_check_all_components", return_value=[]),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.MAJOR_OUTAGE),
        ):
            result = handler._json_status_summary()
        body = _body(result)
        assert body["message"] == "Major System Outage"


# ============================================================================
# Component Status Endpoint
# ============================================================================


class TestComponentStatusEndpoint:
    """Tests for _component_status() response."""

    def test_response_shape(self, handler):
        comps = [
            ComponentHealth(
                name="API",
                status=ServiceStatus.OPERATIONAL,
                response_time_ms=1.0,
                last_check=datetime(2025, 1, 1, tzinfo=timezone.utc),
                message=None,
            ),
        ]
        with patch.object(handler, "_check_all_components", return_value=comps):
            result = handler._component_status()

        body = _body(result)
        assert "components" in body
        assert "timestamp" in body
        comp = body["components"][0]
        assert comp["id"] == "api"
        assert comp["description"] == "Core API endpoints"
        assert comp["last_check"] is not None

    def test_last_check_none_serialized(self, handler):
        comps = [
            ComponentHealth(name="API", status=ServiceStatus.OPERATIONAL, last_check=None),
        ]
        with patch.object(handler, "_check_all_components", return_value=comps):
            result = handler._component_status()

        body = _body(result)
        assert body["components"][0]["last_check"] is None


# ============================================================================
# Uptime History Endpoint
# ============================================================================


class TestUptimeHistory:
    """Tests for _uptime_history() response."""

    def test_response_shape(self, handler):
        with patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL):
            result = handler._uptime_history()

        body = _body(result)
        assert "current" in body
        assert "periods" in body
        assert "timestamp" in body
        assert "note" in body

    def test_period_keys(self, handler):
        with patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL):
            result = handler._uptime_history()

        periods = _body(result)["periods"]
        assert set(periods.keys()) == {"24h", "7d", "30d", "90d"}

    def test_period_fields(self, handler):
        with patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL):
            result = handler._uptime_history()

        for period_data in _body(result)["periods"].values():
            assert "uptime_percent" in period_data
            assert "incidents" in period_data

    def test_current_status(self, handler):
        with patch.object(handler, "_get_overall_status", return_value=ServiceStatus.DEGRADED):
            result = handler._uptime_history()
        assert _body(result)["current"]["status"] == "degraded"


# ============================================================================
# Incidents Endpoint
# ============================================================================


class TestIncidentsEndpoint:
    """Tests for _incidents() response."""

    def test_empty_when_no_store(self, handler):
        result = handler._incidents()
        body = _body(result)
        assert body["active"] == []
        assert body["recent"] == []
        assert body["scheduled_maintenance"] == []
        assert "timestamp" in body

    def test_with_incident_store(self, handler):
        mock_active = MagicMock()
        mock_active.to_dict.return_value = {"id": "inc-1", "title": "Outage"}
        mock_recent = MagicMock()
        mock_recent.to_dict.return_value = {"id": "inc-2", "title": "Resolved"}

        mock_store = MagicMock()
        mock_store.get_active_incidents.return_value = [mock_active]
        mock_store.get_recent_incidents.return_value = [mock_recent]

        mock_module = MagicMock()
        mock_module.get_incident_store.return_value = mock_store

        with patch.dict(
            "sys.modules",
            {"aragora.observability.incident_store": mock_module},
        ):
            result = handler._incidents()

        body = _body(result)
        assert len(body["active"]) == 1
        assert body["active"][0]["id"] == "inc-1"
        assert len(body["recent"]) == 1

    def test_store_runtime_error(self, handler):
        mock_module = MagicMock()
        mock_module.get_incident_store.side_effect = RuntimeError("DB down")
        with patch.dict(
            "sys.modules",
            {"aragora.observability.incident_store": mock_module},
        ):
            result = handler._incidents()
        body = _body(result)
        assert body["active"] == []
        assert body["recent"] == []

    def test_store_import_error(self, handler):
        import builtins
        import sys

        original_import = builtins.__import__
        saved = sys.modules.pop("aragora.observability.incident_store", None)
        try:

            def mock_import(name, *args, **kwargs):
                if "incident_store" in name:
                    raise ImportError("no module")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = handler._incidents()
            body = _body(result)
            assert body["active"] == []
        finally:
            if saved is not None:
                sys.modules["aragora.observability.incident_store"] = saved

    def test_store_attribute_error(self, handler):
        mock_module = MagicMock()
        mock_module.get_incident_store.side_effect = AttributeError("missing")
        with patch.dict(
            "sys.modules",
            {"aragora.observability.incident_store": mock_module},
        ):
            result = handler._incidents()
        body = _body(result)
        assert body["active"] == []


# ============================================================================
# HTML Status Page
# ============================================================================


class TestHtmlStatusPage:
    """Tests for _html_status_page() response."""

    def test_returns_html_content_type(self, handler):
        with (
            patch.object(handler, "_check_all_components", return_value=[]),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler._html_status_page()
        assert "text/html" in result.content_type

    def test_html_contains_title(self, handler):
        with (
            patch.object(handler, "_check_all_components", return_value=[]),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler._html_status_page()
        html = result.body.decode("utf-8")
        assert "<title>Aragora Status</title>" in html

    def test_html_contains_status_message(self, handler):
        with (
            patch.object(handler, "_check_all_components", return_value=[]),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler._html_status_page()
        html = result.body.decode("utf-8")
        assert "All Systems Operational" in html

    def test_html_contains_component_names(self, handler):
        # HTML rendering iterates COMPONENTS[i]["name"] for display, so we must
        # provide exactly len(COMPONENTS) entries so the zip works correctly.
        comps = [
            ComponentHealth(name=c["name"], status=ServiceStatus.OPERATIONAL)
            for c in handler.COMPONENTS
        ]
        with (
            patch.object(handler, "_check_all_components", return_value=comps),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler._html_status_page()
        html = result.body.decode("utf-8")
        # Verify COMPONENTS names appear in HTML
        assert "API" in html
        assert "Cache" in html
        assert "Debate Engine" in html
        assert "Knowledge Mound" in html

    def test_html_status_colors(self, handler):
        comps = [
            ComponentHealth(name="API", status=ServiceStatus.OPERATIONAL),
        ]
        with (
            patch.object(handler, "_check_all_components", return_value=comps),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler._html_status_page()
        html = result.body.decode("utf-8")
        assert "#22c55e" in html  # operational green

    def test_html_degraded_color(self, handler):
        comps = [
            ComponentHealth(name="Cache", status=ServiceStatus.DEGRADED),
        ]
        with (
            patch.object(handler, "_check_all_components", return_value=comps),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.DEGRADED),
        ):
            result = handler._html_status_page()
        html = result.body.decode("utf-8")
        assert "#eab308" in html  # degraded yellow

    def test_html_contains_api_link(self, handler):
        with (
            patch.object(handler, "_check_all_components", return_value=[]),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler._html_status_page()
        html = result.body.decode("utf-8")
        assert "/api/status" in html

    def test_html_status_200(self, handler):
        with (
            patch.object(handler, "_check_all_components", return_value=[]),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler._html_status_page()
        assert _status(result) == 200

    def test_html_body_is_bytes(self, handler):
        with (
            patch.object(handler, "_check_all_components", return_value=[]),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler._html_status_page()
        assert isinstance(result.body, bytes)


# ============================================================================
# Status Message Mapping
# ============================================================================


class TestStatusMessage:
    """Tests for _status_message()."""

    def test_operational(self, handler):
        assert handler._status_message(ServiceStatus.OPERATIONAL) == "All Systems Operational"

    def test_degraded(self, handler):
        assert handler._status_message(ServiceStatus.DEGRADED) == "Degraded Performance"

    def test_partial_outage(self, handler):
        assert handler._status_message(ServiceStatus.PARTIAL_OUTAGE) == "Partial System Outage"

    def test_major_outage(self, handler):
        assert handler._status_message(ServiceStatus.MAJOR_OUTAGE) == "Major System Outage"

    def test_maintenance(self, handler):
        assert handler._status_message(ServiceStatus.MAINTENANCE) == "Scheduled Maintenance"


# ============================================================================
# Uptime Formatting
# ============================================================================


class TestFormatUptime:
    """Tests for _format_uptime()."""

    def test_less_than_one_minute(self, handler):
        assert handler._format_uptime(30) == "< 1m"

    def test_zero_seconds(self, handler):
        assert handler._format_uptime(0) == "< 1m"

    def test_exactly_one_minute(self, handler):
        assert handler._format_uptime(60) == "1m"

    def test_one_hour(self, handler):
        assert handler._format_uptime(3600) == "1h"

    def test_one_day(self, handler):
        assert handler._format_uptime(86400) == "1d"

    def test_mixed(self, handler):
        # 1d 2h 3m
        seconds = 86400 + 7200 + 180
        assert handler._format_uptime(seconds) == "1d 2h 3m"

    def test_days_and_hours(self, handler):
        seconds = 86400 * 2 + 3600 * 5
        assert handler._format_uptime(seconds) == "2d 5h"

    def test_hours_and_minutes(self, handler):
        seconds = 3600 * 3 + 60 * 45
        assert handler._format_uptime(seconds) == "3h 45m"

    def test_only_minutes(self, handler):
        seconds = 60 * 15
        assert handler._format_uptime(seconds) == "15m"

    def test_large_uptime(self, handler):
        # 100 days
        seconds = 86400 * 100
        result = handler._format_uptime(seconds)
        assert "100d" in result


# ============================================================================
# Integration-style Tests
# ============================================================================


class TestEndToEnd:
    """Integration-like tests using handle() with mocked components."""

    def test_api_status_returns_all_component_ids(self, handler, mock_http_handler):
        """Verify /api/status returns a component entry for each COMPONENTS entry."""
        # Use real component checks but mock all externals
        comps = [
            ComponentHealth(name=c["name"], status=ServiceStatus.OPERATIONAL)
            for c in handler.COMPONENTS
        ]
        with (
            patch.object(handler, "_check_all_components", return_value=comps),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler.handle("/api/status", {}, mock_http_handler)

        body = _body(result)
        returned_ids = [c["id"] for c in body["components"]]
        expected_ids = [c["id"] for c in handler.COMPONENTS]
        assert returned_ids == expected_ids

    def test_api_status_history_uptime_seconds_positive(self, handler, mock_http_handler):
        with patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL):
            result = handler.handle("/api/status/history", {}, mock_http_handler)
        body = _body(result)
        assert body["current"]["uptime_seconds"] > 0

    def test_html_status_page_via_handle(self, handler, mock_http_handler):
        comps = [
            ComponentHealth(name=c["name"], status=ServiceStatus.OPERATIONAL)
            for c in handler.COMPONENTS
        ]
        with (
            patch.object(handler, "_check_all_components", return_value=comps),
            patch.object(handler, "_get_overall_status", return_value=ServiceStatus.OPERATIONAL),
        ):
            result = handler.handle("/status", {}, mock_http_handler)
        assert result.status_code == 200
        html = result.body.decode("utf-8")
        assert "<!DOCTYPE html>" in html

    def test_incidents_via_handle(self, handler, mock_http_handler):
        result = handler.handle("/api/status/incidents", {}, mock_http_handler)
        body = _body(result)
        assert body["scheduled_maintenance"] == []

    def test_components_via_handle(self, handler, mock_http_handler):
        comps = [
            ComponentHealth(
                name=c["name"],
                status=ServiceStatus.OPERATIONAL,
                last_check=datetime(2025, 6, 1, tzinfo=timezone.utc),
            )
            for c in handler.COMPONENTS
        ]
        with patch.object(handler, "_check_all_components", return_value=comps):
            result = handler.handle("/api/status/components", {}, mock_http_handler)
        body = _body(result)
        assert len(body["components"]) == len(handler.COMPONENTS)
        for comp in body["components"]:
            assert comp["status"] == "operational"
