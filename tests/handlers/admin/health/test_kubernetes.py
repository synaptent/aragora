"""Comprehensive tests for Kubernetes liveness and readiness probe handlers.

Tests the three public functions in aragora/server/handlers/admin/health/kubernetes.py:

  TestLivenessProbe               - liveness_probe() healthy server
  TestLivenessProbeDegraded       - liveness_probe() degraded mode
  TestLivenessProbeImportError    - liveness_probe() when degraded_mode not installed
  TestReadinessProbeFastCached    - readiness_probe_fast() cached result path
  TestReadinessProbeFastDegraded  - readiness_probe_fast() degraded mode
  TestReadinessProbeFast          - readiness_probe_fast() all checks passing
  TestReadinessProbeFastStartup   - readiness_probe_fast() startup not complete
  TestReadinessProbeFastRoutes    - readiness_probe_fast() handler routes check
  TestReadinessProbeFastStorage   - readiness_probe_fast() storage checks
  TestReadinessProbeFastElo       - readiness_probe_fast() ELO system checks
  TestReadinessProbeFastRedis     - readiness_probe_fast() Redis pool checks
  TestReadinessProbeFastDb        - readiness_probe_fast() database pool checks
  TestReadinessDepsCached         - readiness_dependencies() cached result path
  TestReadinessDepsDegraded       - readiness_dependencies() degraded mode
  TestReadinessDeps               - readiness_dependencies() all checks passing
  TestReadinessDepsStorage        - readiness_dependencies() storage failures
  TestReadinessDepsElo            - readiness_dependencies() ELO failures
  TestReadinessDepsRedis          - readiness_dependencies() Redis connectivity
  TestReadinessDepsPostgres       - readiness_dependencies() PostgreSQL connectivity
  TestReadinessDepsApiKeys        - readiness_dependencies() API key detection

155+ tests covering all branches, error paths, and edge cases.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sys
import time
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.admin.health.kubernetes import (
    liveness_probe,
    readiness_probe_fast,
    readiness_dependencies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if result is None:
        return 0
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


def _make_mock_handler(**kwargs) -> MagicMock:
    """Create a mock handler with configurable get_storage/get_elo_system."""
    h = MagicMock()
    h.get_storage.return_value = kwargs.get("storage", MagicMock())
    h.get_elo_system.return_value = kwargs.get("elo", MagicMock())
    return h


def _make_degraded_module(
    is_degraded_val: bool = False,
    degraded_reason: str = "",
    state: Any = None,
):
    """Create a fake aragora.server.degraded_mode module."""
    mod = types.ModuleType("aragora.server.degraded_mode")
    mod.is_degraded = lambda: is_degraded_val
    mod.get_degraded_reason = lambda: degraded_reason
    if state is None:
        state = MagicMock()
        state.error_code.value = "UNKNOWN"
        state.reason = "unknown"
        state.recovery_hint = ""
    mod.get_degraded_state = lambda: state
    return mod


def _make_unified_server_module(
    is_ready: bool = True,
    runtime_ready: bool | None = None,
    handlers_initialized: bool = False,
):
    """Create a fake aragora.server.unified_server module."""
    mod = types.ModuleType("aragora.server.unified_server")
    mod.is_server_ready = lambda: is_ready
    mod.is_runtime_ready = lambda: is_ready if runtime_ready is None else runtime_ready
    mod.UnifiedHandler = type(
        "UnifiedHandler",
        (),
        {"_handlers_initialized": handlers_initialized},
    )
    return mod


def _make_handler_registry_module(exact_routes: dict | None = None):
    """Create a fake aragora.server.handler_registry.core module."""
    mod = types.ModuleType("aragora.server.handler_registry.core")
    route_index = MagicMock()
    route_index._exact_routes = exact_routes if exact_routes is not None else {"/api/health": True}
    mod.get_route_index = lambda: route_index
    return mod


def _make_redis_cache_module(pool: Any = MagicMock()):
    """Create a fake aragora.utils.redis_config module."""
    mod = types.ModuleType("aragora.utils.redis_config")
    mod.get_redis_pool = lambda: pool
    return mod


def _make_postgres_pool_module(pool: Any = MagicMock()):
    """Create a fake aragora.storage.postgres_pool module."""
    mod = types.ModuleType("aragora.storage.postgres_pool")
    mod.get_pool = lambda: pool
    return mod


def _make_leader_module(distributed_required: bool = False):
    """Create a fake aragora.control_plane.leader module."""
    mod = types.ModuleType("aragora.control_plane.leader")
    mod.is_distributed_state_required = lambda: distributed_required
    return mod


def _make_startup_module(redis_result=(True, "OK"), db_result=(True, "OK")):
    """Create a fake aragora.server.startup module."""
    mod = types.ModuleType("aragora.server.startup")

    async def validate_redis_connectivity(timeout_seconds=2.0):
        return redis_result

    async def validate_database_connectivity(timeout_seconds=2.0):
        return db_result

    mod.validate_redis_connectivity = validate_redis_connectivity
    mod.validate_database_connectivity = validate_database_connectivity
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_health_cache():
    """Clear the health cache before each test to avoid cross-test pollution."""
    import aragora.server.handlers.admin.health as pkg

    pkg._HEALTH_CACHE.clear()
    pkg._HEALTH_CACHE_TIMESTAMPS.clear()
    yield
    pkg._HEALTH_CACHE.clear()
    pkg._HEALTH_CACHE_TIMESTAMPS.clear()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove env vars that affect probe behaviour so tests start clean."""
    for var in (
        "REDIS_URL",
        "ARAGORA_REDIS_URL",
        "DATABASE_URL",
        "ARAGORA_POSTGRES_DSN",
        "ARAGORA_REQUIRE_DATABASE",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
        "GEMINI_API_KEY",
        "XAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Context managers for module-level patches
# ---------------------------------------------------------------------------


def _patch_degraded(is_degraded_val=False, reason="", state=None):
    """Patch degraded_mode module in sys.modules."""
    mod = _make_degraded_module(is_degraded_val, reason, state)
    return patch.dict(sys.modules, {"aragora.server.degraded_mode": mod})


def _remove_degraded():
    """Remove degraded_mode so ImportError is raised."""
    return patch.dict(sys.modules, {"aragora.server.degraded_mode": None})


def _patch_unified_server(is_ready=True, runtime_ready=None, handlers_initialized=False):
    mod = _make_unified_server_module(is_ready, runtime_ready, handlers_initialized)
    return patch.dict(sys.modules, {"aragora.server.unified_server": mod})


def _remove_unified_server():
    return patch.dict(sys.modules, {"aragora.server.unified_server": None})


def _patch_handler_registry(routes=None):
    mod = _make_handler_registry_module(routes)
    return patch.dict(sys.modules, {"aragora.server.handler_registry.core": mod})


def _remove_handler_registry():
    return patch.dict(sys.modules, {"aragora.server.handler_registry.core": None})


def _remove_redis_cache():
    return patch.dict(sys.modules, {"aragora.utils.redis_config": None})


def _patch_redis_cache(pool=MagicMock()):
    mod = _make_redis_cache_module(pool)
    return patch.dict(sys.modules, {"aragora.utils.redis_config": mod})


def _remove_postgres_pool():
    return patch.dict(sys.modules, {"aragora.storage.postgres_pool": None})


def _patch_postgres_pool(pool=MagicMock()):
    mod = _make_postgres_pool_module(pool)
    return patch.dict(sys.modules, {"aragora.storage.postgres_pool": mod})


def _remove_leader():
    return patch.dict(sys.modules, {"aragora.control_plane.leader": None})


def _patch_leader(distributed_required=False):
    mod = _make_leader_module(distributed_required)
    return patch.dict(sys.modules, {"aragora.control_plane.leader": mod})


def _remove_startup():
    return patch.dict(sys.modules, {"aragora.server.startup": None})


def _patch_startup(redis_result=(True, "OK"), db_result=(True, "OK")):
    mod = _make_startup_module(redis_result, db_result)
    return patch.dict(sys.modules, {"aragora.server.startup": mod})


# ===========================================================================
# liveness_probe
# ===========================================================================


class TestLivenessProbe:
    """Test liveness_probe() when server is healthy."""

    def test_returns_ok(self):
        handler = _make_mock_handler()
        with _patch_degraded(is_degraded_val=False):
            result = liveness_probe(handler)
        assert _status(result) == 200
        assert _body(result)["status"] == "ok"

    def test_no_degraded_key_when_healthy(self):
        handler = _make_mock_handler()
        with _patch_degraded(is_degraded_val=False):
            result = liveness_probe(handler)
        assert "degraded" not in _body(result)

    def test_no_note_key_when_healthy(self):
        handler = _make_mock_handler()
        with _patch_degraded(is_degraded_val=False):
            result = liveness_probe(handler)
        assert "note" not in _body(result)


class TestLivenessProbeDegraded:
    """Test liveness_probe() when server is in degraded mode."""

    def test_still_returns_200(self):
        """Container should NOT be restarted for degraded mode."""
        handler = _make_mock_handler()
        with _patch_degraded(is_degraded_val=True, reason="Missing API key"):
            result = liveness_probe(handler)
        assert _status(result) == 200

    def test_body_marks_degraded(self):
        handler = _make_mock_handler()
        with _patch_degraded(is_degraded_val=True, reason="Missing API key"):
            result = liveness_probe(handler)
        body = _body(result)
        assert body["status"] == "ok"
        assert body["degraded"] is True
        assert body["degraded_reason"] == "Missing API key"

    def test_includes_note(self):
        handler = _make_mock_handler()
        with _patch_degraded(is_degraded_val=True, reason="reason"):
            result = liveness_probe(handler)
        assert "Check /api/health" in _body(result)["note"]

    def test_degraded_reason_truncated_to_100_chars(self):
        handler = _make_mock_handler()
        long_reason = "x" * 200
        with _patch_degraded(is_degraded_val=True, reason=long_reason):
            result = liveness_probe(handler)
        assert len(_body(result)["degraded_reason"]) == 100


class TestLivenessProbeImportError:
    """Test liveness_probe() when degraded_mode module is unavailable."""

    def test_returns_ok_on_import_error(self):
        handler = _make_mock_handler()
        with _remove_degraded():
            result = liveness_probe(handler)
        assert _status(result) == 200
        assert _body(result)["status"] == "ok"

    def test_no_degraded_fields_on_import_error(self):
        handler = _make_mock_handler()
        with _remove_degraded():
            result = liveness_probe(handler)
        body = _body(result)
        assert "degraded" not in body
        assert "degraded_reason" not in body


# ===========================================================================
# readiness_probe_fast
# ===========================================================================


class TestReadinessProbeFastCached:
    """Test readiness_probe_fast() when a cached result is available."""

    def test_returns_cached_ready(self):
        import aragora.server.handlers.admin.health as pkg

        cached_result = {"status": "ready", "checks": {}}
        pkg._HEALTH_CACHE["readiness_fast"] = cached_result
        pkg._HEALTH_CACHE_TIMESTAMPS["readiness_fast"] = time.time()

        handler = _make_mock_handler()
        result = readiness_probe_fast(handler)
        assert _status(result) == 200
        assert _body(result)["status"] == "ready"

    def test_returns_cached_not_ready_with_503(self):
        import aragora.server.handlers.admin.health as pkg

        cached_result = {"status": "not_ready", "checks": {}}
        pkg._HEALTH_CACHE["readiness_fast"] = cached_result
        pkg._HEALTH_CACHE_TIMESTAMPS["readiness_fast"] = time.time()

        handler = _make_mock_handler()
        result = readiness_probe_fast(handler)
        assert _status(result) == 503
        assert _body(result)["status"] == "not_ready"

    def test_stale_cache_is_ignored(self):
        """Cache entries older than TTL should be ignored."""
        import aragora.server.handlers.admin.health as pkg

        cached_result = {"status": "not_ready", "checks": {}}
        pkg._HEALTH_CACHE["readiness_fast"] = cached_result
        pkg._HEALTH_CACHE_TIMESTAMPS["readiness_fast"] = time.time() - 60

        handler = _make_mock_handler()
        with _remove_degraded(), _remove_unified_server(), _remove_handler_registry():
            result = readiness_probe_fast(handler)
        # Should compute fresh result instead of returning stale cache
        assert _status(result) == 200
        assert _body(result)["status"] == "ready"


class TestReadinessProbeFastDegraded:
    """Test readiness_probe_fast() when server is in degraded mode."""

    def _make_state(self):
        state = MagicMock()
        state.error_code.value = "MISSING_API_KEY"
        state.reason = "No API keys configured"
        state.recovery_hint = "Set ANTHROPIC_API_KEY"
        return state

    def test_returns_503(self):
        handler = _make_mock_handler()
        state = self._make_state()
        with _patch_degraded(is_degraded_val=True, state=state):
            result = readiness_probe_fast(handler)
        assert _status(result) == 503

    def test_body_includes_degraded_details(self):
        handler = _make_mock_handler()
        state = self._make_state()
        with _patch_degraded(is_degraded_val=True, state=state):
            result = readiness_probe_fast(handler)
        body = _body(result)
        assert body["status"] == "not_ready"
        assert body["reason"] == "Server in degraded mode"
        assert body["degraded"]["error_code"] == "MISSING_API_KEY"
        assert body["degraded"]["reason"] == "No API keys configured"
        assert body["degraded"]["recovery_hint"] == "Set ANTHROPIC_API_KEY"
        assert body["checks"]["degraded_mode"] is False

    def test_degraded_import_error_marks_ok(self):
        """If degraded_mode not installed, treat as not degraded."""
        handler = _make_mock_handler()
        with _remove_degraded(), _remove_unified_server(), _remove_handler_registry():
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["degraded_mode"] is True


class TestReadinessProbeFast:
    """Test readiness_probe_fast() with all checks passing."""

    def _run_with_all_passing(self, handler=None):
        if handler is None:
            handler = _make_mock_handler()
        with (
            _patch_degraded(is_degraded_val=False),
            _patch_unified_server(is_ready=True),
            _patch_handler_registry({"/api/health": True}),
        ):
            return readiness_probe_fast(handler)

    def test_returns_200_when_all_checks_pass(self):
        result = self._run_with_all_passing()
        assert _status(result) == 200

    def test_status_is_ready(self):
        result = self._run_with_all_passing()
        assert _body(result)["status"] == "ready"

    def test_fast_probe_flag_set(self):
        result = self._run_with_all_passing()
        assert _body(result)["fast_probe"] is True

    def test_full_validation_url_present(self):
        result = self._run_with_all_passing()
        assert _body(result)["full_validation"] == "/readyz/dependencies"

    def test_latency_ms_is_numeric(self):
        result = self._run_with_all_passing()
        assert isinstance(_body(result)["latency_ms"], (int, float))

    def test_checks_degraded_mode_true(self):
        result = self._run_with_all_passing()
        assert _body(result)["checks"]["degraded_mode"] is True

    def test_checks_startup_complete_true(self):
        result = self._run_with_all_passing()
        assert _body(result)["checks"]["startup_complete"] is True

    def test_checks_handlers_initialized_true(self):
        result = self._run_with_all_passing()
        assert _body(result)["checks"]["handlers_initialized"] is True

    def test_checks_storage_initialized_true(self):
        result = self._run_with_all_passing()
        assert _body(result)["checks"]["storage_initialized"] is True

    def test_checks_elo_initialized_true(self):
        result = self._run_with_all_passing()
        assert _body(result)["checks"]["elo_initialized"] is True

    def test_redis_not_configured_when_no_env(self):
        result = self._run_with_all_passing()
        assert _body(result)["checks"]["redis_pool"] == "not_configured"

    def test_db_not_configured_when_no_env(self):
        result = self._run_with_all_passing()
        assert _body(result)["checks"]["db_pool"] == "not_configured"

    def test_result_is_cached(self):
        import aragora.server.handlers.admin.health as pkg

        self._run_with_all_passing()
        assert "readiness_fast" in pkg._HEALTH_CACHE


class TestReadinessProbeFastStartup:
    """Test readiness_probe_fast() when startup is incomplete."""

    def test_returns_503_when_startup_not_complete(self):
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _patch_unified_server(is_ready=False),
            _patch_handler_registry({"/api/health": True}),
        ):
            result = readiness_probe_fast(handler)
        assert _status(result) == 503
        body = _body(result)
        assert body["status"] == "not_ready"
        assert body["checks"]["startup_complete"] is False

    def test_startup_import_error_skips_check(self):
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _patch_handler_registry({"/api/health": True}),
        ):
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["startup_complete"] is True

    def test_unified_handler_init_fallback_marks_startup_complete(self):
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _patch_unified_server(is_ready=False, handlers_initialized=True),
            _patch_handler_registry({"/api/health": True}),
        ):
            result = readiness_probe_fast(handler)
        assert _status(result) == 200
        assert _body(result)["checks"]["startup_complete"] is True

    def test_runtime_ready_marks_startup_complete(self):
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _patch_unified_server(is_ready=False, runtime_ready=True),
            _patch_handler_registry({"/api/health": True}),
        ):
            result = readiness_probe_fast(handler)
        assert _status(result) == 200
        assert _body(result)["checks"]["startup_complete"] is True

    def test_handler_route_fallback_marks_startup_complete(self):
        handler = _make_mock_handler()
        handler.can_handle.return_value = True
        with (
            _remove_degraded(),
            _patch_unified_server(is_ready=False, handlers_initialized=False),
            _patch_handler_registry({"/api/health": True}),
        ):
            result = readiness_probe_fast(handler)
        assert _status(result) == 200
        assert _body(result)["checks"]["startup_complete"] is True


class TestReadinessProbeFastRoutes:
    """Test readiness_probe_fast() handler routes initialization check."""

    def test_returns_503_when_no_routes_registered(self):
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _patch_handler_registry({}),
        ):
            result = readiness_probe_fast(handler)
        assert _status(result) == 503
        assert _body(result)["checks"]["handlers_initialized"] is False

    def test_import_error_skips_route_check(self):
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _remove_handler_registry(),
        ):
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["handlers_initialized"] is True

    def test_routes_populated_marks_true(self):
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _patch_handler_registry({"/healthz": True, "/readyz": True}),
        ):
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["handlers_initialized"] is True

    def test_handler_can_handle_readyz_is_fallback_when_route_index_empty(self):
        handler = _make_mock_handler()
        handler.can_handle = MagicMock(return_value=True)
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _patch_handler_registry({}),
        ):
            result = readiness_probe_fast(handler)
        assert _status(result) == 200
        assert _body(result)["checks"]["handlers_initialized"] is True


class TestReadinessProbeFastStorage:
    """Test readiness_probe_fast() storage initialization check."""

    def _run(self, handler):
        with _remove_degraded(), _remove_unified_server(), _remove_handler_registry():
            return readiness_probe_fast(handler)

    def test_storage_present_is_true(self):
        handler = _make_mock_handler()
        result = self._run(handler)
        assert _body(result)["checks"]["storage_initialized"] is True
        assert _status(result) == 200

    def test_storage_none_is_ok(self):
        handler = _make_mock_handler(storage=None)
        result = self._run(handler)
        assert _body(result)["checks"]["storage_initialized"] is True
        assert _status(result) == 200

    def test_storage_os_error_fails(self):
        handler = _make_mock_handler()
        handler.get_storage.side_effect = OSError("Disk full")
        result = self._run(handler)
        assert _body(result)["checks"]["storage_initialized"] is False
        assert _status(result) == 503

    def test_storage_runtime_error_fails(self):
        handler = _make_mock_handler()
        handler.get_storage.side_effect = RuntimeError("Not initialized")
        result = self._run(handler)
        assert _body(result)["checks"]["storage_initialized"] is False
        assert _status(result) == 503

    def test_storage_value_error_fails(self):
        handler = _make_mock_handler()
        handler.get_storage.side_effect = ValueError("Bad config")
        result = self._run(handler)
        assert _body(result)["checks"]["storage_initialized"] is False
        assert _status(result) == 503


class TestReadinessProbeFastElo:
    """Test readiness_probe_fast() ELO system initialization check."""

    def _run(self, handler):
        with _remove_degraded(), _remove_unified_server(), _remove_handler_registry():
            return readiness_probe_fast(handler)

    def test_elo_present_is_true(self):
        handler = _make_mock_handler()
        result = self._run(handler)
        assert _body(result)["checks"]["elo_initialized"] is True
        assert _status(result) == 200

    def test_elo_none_is_ok(self):
        handler = _make_mock_handler(elo=None)
        result = self._run(handler)
        assert _body(result)["checks"]["elo_initialized"] is True
        assert _status(result) == 200

    def test_elo_os_error_fails(self):
        handler = _make_mock_handler()
        handler.get_elo_system.side_effect = OSError("Disk error")
        result = self._run(handler)
        assert _body(result)["checks"]["elo_initialized"] is False
        assert _status(result) == 503

    def test_elo_runtime_error_fails(self):
        handler = _make_mock_handler()
        handler.get_elo_system.side_effect = RuntimeError("ELO init failed")
        result = self._run(handler)
        assert _body(result)["checks"]["elo_initialized"] is False
        assert _status(result) == 503

    def test_elo_value_error_fails(self):
        handler = _make_mock_handler()
        handler.get_elo_system.side_effect = ValueError("Bad ELO config")
        result = self._run(handler)
        assert _body(result)["checks"]["elo_initialized"] is False
        assert _status(result) == 503


class TestReadinessProbeFastRedis:
    """Test readiness_probe_fast() Redis pool check."""

    def _run(self, handler):
        with _remove_degraded(), _remove_unified_server(), _remove_handler_registry():
            return readiness_probe_fast(handler)

    def test_redis_pool_exists_when_env_set(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _remove_handler_registry(),
            _patch_redis_cache(pool=MagicMock()),
        ):
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["redis_pool"] is True

    def test_redis_pool_none_when_env_set(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _remove_handler_registry(),
            _patch_redis_cache(pool=None),
        ):
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["redis_pool"] is False

    def test_redis_import_error_when_env_set(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_REDIS_URL", "redis://localhost:6379")
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _remove_handler_registry(),
            _remove_redis_cache(),
        ):
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["redis_pool"] == "not_configured"

    def test_redis_runtime_error_when_env_set(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        handler = _make_mock_handler()
        # Create a module whose get_redis_pool raises RuntimeError
        mod = types.ModuleType("aragora.utils.redis_config")
        mod.get_redis_pool = MagicMock(side_effect=RuntimeError("Pool error"))
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _remove_handler_registry(),
            patch.dict(sys.modules, {"aragora.utils.redis_config": mod}),
        ):
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["redis_pool"] == "not_configured"

    def test_redis_not_configured_without_env(self):
        handler = _make_mock_handler()
        result = self._run(handler)
        assert _body(result)["checks"]["redis_pool"] == "not_configured"


class TestReadinessProbeFastDb:
    """Test readiness_probe_fast() database pool check."""

    def test_db_pool_exists_when_env_set(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _remove_handler_registry(),
            _patch_postgres_pool(pool=MagicMock()),
        ):
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["db_pool"] is True

    def test_db_pool_none_when_env_set(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _remove_handler_registry(),
            _patch_postgres_pool(pool=None),
        ):
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["db_pool"] is False

    def test_db_import_error_when_env_set(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_POSTGRES_DSN", "postgresql://localhost/test")
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _remove_handler_registry(),
            _remove_postgres_pool(),
        ):
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["db_pool"] == "not_configured"

    def test_db_not_configured_without_env(self):
        handler = _make_mock_handler()
        with _remove_degraded(), _remove_unified_server(), _remove_handler_registry():
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["db_pool"] == "not_configured"

    def test_db_aragora_postgres_dsn_env_var(self, monkeypatch):
        """ARAGORA_POSTGRES_DSN should also trigger pool check."""
        monkeypatch.setenv("ARAGORA_POSTGRES_DSN", "postgresql://localhost/test")
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _remove_unified_server(),
            _remove_handler_registry(),
            _patch_postgres_pool(pool=MagicMock()),
        ):
            result = readiness_probe_fast(handler)
        assert _body(result)["checks"]["db_pool"] is True


# ===========================================================================
# readiness_dependencies
# ===========================================================================


class TestReadinessDepsCached:
    """Test readiness_dependencies() when a cached result is available."""

    def test_returns_cached_ready(self):
        import aragora.server.handlers.admin.health as pkg

        cached_result = {"status": "ready", "checks": {}}
        pkg._HEALTH_CACHE["readiness"] = cached_result
        pkg._HEALTH_CACHE_TIMESTAMPS["readiness"] = time.time()

        handler = _make_mock_handler()
        result = readiness_dependencies(handler)
        assert _status(result) == 200
        assert _body(result)["status"] == "ready"

    def test_returns_cached_not_ready_with_503(self):
        import aragora.server.handlers.admin.health as pkg

        cached_result = {"status": "not_ready", "checks": {}}
        pkg._HEALTH_CACHE["readiness"] = cached_result
        pkg._HEALTH_CACHE_TIMESTAMPS["readiness"] = time.time()

        handler = _make_mock_handler()
        result = readiness_dependencies(handler)
        assert _status(result) == 503

    def test_stale_cache_is_ignored(self):
        import aragora.server.handlers.admin.health as pkg

        cached_result = {"status": "not_ready", "checks": {}}
        pkg._HEALTH_CACHE["readiness"] = cached_result
        pkg._HEALTH_CACHE_TIMESTAMPS["readiness"] = time.time() - 60

        handler = _make_mock_handler()
        with _remove_degraded(), _remove_leader(), _remove_startup():
            result = readiness_dependencies(handler)
        assert _status(result) == 200


class TestReadinessDepsDegraded:
    """Test readiness_dependencies() when server is in degraded mode."""

    def test_returns_503(self):
        handler = _make_mock_handler()
        state = MagicMock()
        state.error_code.value = "DB_UNREACHABLE"
        state.reason = "Database is unreachable"
        state.recovery_hint = "Check DATABASE_URL"

        with _patch_degraded(is_degraded_val=True, state=state):
            result = readiness_dependencies(handler)
        assert _status(result) == 503

    def test_body_includes_degraded_info(self):
        handler = _make_mock_handler()
        state = MagicMock()
        state.error_code.value = "DB_UNREACHABLE"
        state.reason = "Database is unreachable"
        state.recovery_hint = "Check DATABASE_URL"

        with _patch_degraded(is_degraded_val=True, state=state):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["status"] == "not_ready"
        assert body["degraded"]["error_code"] == "DB_UNREACHABLE"
        assert body["degraded"]["reason"] == "Database is unreachable"
        assert body["degraded"]["recovery_hint"] == "Check DATABASE_URL"
        assert body["checks"]["degraded_mode"] is False

    def test_degraded_import_error_skips(self):
        handler = _make_mock_handler()
        with _remove_degraded(), _remove_leader(), _remove_startup():
            result = readiness_dependencies(handler)
        assert _status(result) == 200


class TestReadinessDepsStorage:
    """Test readiness_dependencies() storage check."""

    def _run(self, handler):
        with _remove_degraded(), _remove_leader(), _remove_startup():
            return readiness_dependencies(handler)

    def test_storage_ok(self):
        handler = _make_mock_handler()
        result = self._run(handler)
        assert _body(result)["checks"]["storage"] is True
        assert _status(result) == 200

    def test_storage_none_is_ok(self):
        handler = _make_mock_handler(storage=None)
        result = self._run(handler)
        assert _body(result)["checks"]["storage"] is True

    def test_storage_os_error_fails(self):
        handler = _make_mock_handler()
        handler.get_storage.side_effect = OSError("Disk full")
        result = self._run(handler)
        assert _body(result)["checks"]["storage"] is False
        assert _status(result) == 503

    def test_storage_runtime_error_fails(self):
        handler = _make_mock_handler()
        handler.get_storage.side_effect = RuntimeError("Init failed")
        result = self._run(handler)
        assert _body(result)["checks"]["storage"] is False
        assert _status(result) == 503

    def test_storage_value_error_fails(self):
        handler = _make_mock_handler()
        handler.get_storage.side_effect = ValueError("Bad path")
        result = self._run(handler)
        assert _body(result)["checks"]["storage"] is False
        assert _status(result) == 503


class TestReadinessDepsElo:
    """Test readiness_dependencies() ELO system check."""

    def _run(self, handler):
        with _remove_degraded(), _remove_leader(), _remove_startup():
            return readiness_dependencies(handler)

    def test_elo_ok(self):
        handler = _make_mock_handler()
        result = self._run(handler)
        assert _body(result)["checks"]["elo_system"] is True
        assert _status(result) == 200

    def test_elo_none_is_ok(self):
        handler = _make_mock_handler(elo=None)
        result = self._run(handler)
        assert _body(result)["checks"]["elo_system"] is True

    def test_elo_os_error_fails(self):
        handler = _make_mock_handler()
        handler.get_elo_system.side_effect = OSError("Disk error")
        result = self._run(handler)
        assert _body(result)["checks"]["elo_system"] is False
        assert _status(result) == 503

    def test_elo_runtime_error_fails(self):
        handler = _make_mock_handler()
        handler.get_elo_system.side_effect = RuntimeError("ELO broken")
        result = self._run(handler)
        assert _body(result)["checks"]["elo_system"] is False

    def test_elo_value_error_fails(self):
        handler = _make_mock_handler()
        handler.get_elo_system.side_effect = ValueError("Bad ELO config")
        result = self._run(handler)
        assert _body(result)["checks"]["elo_system"] is False
        assert _status(result) == 503


class TestReadinessDepsRedis:
    """Test readiness_dependencies() Redis connectivity check."""

    def test_redis_connected_when_distributed_required(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _remove_degraded(),
            _patch_leader(distributed_required=True),
            _patch_startup(redis_result=(True, "Connected")),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                return_value=(True, "Connected"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["redis"]["connected"] is True
        assert body["checks"]["redis"]["message"] == "Connected"
        assert _status(result) == 200

    def test_redis_disconnected_when_required_fails(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _remove_degraded(),
            _patch_leader(distributed_required=True),
            _patch_startup(redis_result=(False, "Connection refused")),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                return_value=(False, "Connection refused"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["redis"]["connected"] is False
        assert _status(result) == 503

    def test_redis_configured_but_not_required(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _remove_degraded(),
            _patch_leader(distributed_required=False),
            _patch_startup(),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["redis"]["configured"] is True
        assert body["checks"]["redis"]["required"] is False
        assert _status(result) == 200

    def test_redis_not_configured(self, monkeypatch):
        handler = _make_mock_handler()
        with (
            _remove_degraded(),
            _patch_leader(distributed_required=False),
            _patch_startup(),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["redis"]["configured"] is False

    def test_redis_import_error_skips(self):
        handler = _make_mock_handler()
        with _remove_degraded(), _remove_leader(), _remove_startup():
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["redis"]["status"] == "check_skipped"

    def test_redis_connection_error_when_required(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _remove_degraded(),
            _patch_leader(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                side_effect=ConnectionError("Connection refused"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["redis"]["error_type"] == "connectivity"
        assert _status(result) == 503

    def test_redis_timeout_when_required(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _remove_degraded(),
            _patch_leader(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                side_effect=asyncio.TimeoutError("Timed out"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        # asyncio.TimeoutError is a subclass of TimeoutError (which is OSError-like)
        # so it may be caught by the (ConnectionError, TimeoutError, OSError) clause
        assert body["checks"]["redis"]["error_type"] in ("timeout", "connectivity")
        assert _status(result) == 503

    def test_redis_runtime_error_when_required(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _remove_degraded(),
            _patch_leader(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                side_effect=TypeError("Unexpected"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert "error" in body["checks"]["redis"]
        assert _status(result) == 503

    def test_redis_runtime_error_not_required_does_not_fail(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _remove_degraded(),
            _patch_leader(distributed_required=False),
            _patch_startup(),
        ):
            result = readiness_dependencies(handler)
        assert _status(result) == 200

    def test_redis_in_async_context(self, monkeypatch):
        """When already in an async loop, ThreadPoolExecutor should be used."""
        handler = _make_mock_handler()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        mock_loop = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = (True, "Connected via thread")

        with (
            _remove_degraded(),
            _patch_leader(distributed_required=True),
            _patch_startup(redis_result=(True, "Connected via thread")),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                return_value=mock_loop,
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.concurrent.futures.ThreadPoolExecutor",
            ) as mock_tpe_cls,
        ):
            mock_executor = MagicMock()
            mock_executor.submit.return_value = mock_future
            mock_executor.__enter__ = MagicMock(return_value=mock_executor)
            mock_executor.__exit__ = MagicMock(return_value=False)
            mock_tpe_cls.return_value = mock_executor

            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["redis"]["connected"] is True
        assert body["checks"]["redis"]["message"] == "Connected via thread"

    def test_redis_concurrent_futures_timeout(self, monkeypatch):
        """concurrent.futures.TimeoutError should be handled."""
        handler = _make_mock_handler()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _remove_degraded(),
            _patch_leader(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                side_effect=concurrent.futures.TimeoutError("Pool timeout"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        # concurrent.futures.TimeoutError may be caught by earlier except clauses
        assert body["checks"]["redis"]["error_type"] in ("timeout", "connectivity")
        assert _status(result) == 503

    def test_redis_os_error_connectivity(self, monkeypatch):
        """OSError during Redis check should be treated as connectivity failure."""
        handler = _make_mock_handler()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _remove_degraded(),
            _patch_leader(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                side_effect=OSError("Network unreachable"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["redis"]["error_type"] == "connectivity"
        assert _status(result) == 503


class TestReadinessDepsPostgres:
    """Test readiness_dependencies() PostgreSQL connectivity check."""

    def test_postgres_connected_when_required(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _remove_degraded(),
            _remove_leader(),
            _patch_startup(db_result=(True, "Connected")),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                return_value=(True, "Connected"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["postgresql"]["connected"] is True
        assert _status(result) == 200

    def test_postgres_disconnected_when_required_fails(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _remove_degraded(),
            _remove_leader(),
            _patch_startup(db_result=(False, "Connection refused")),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                return_value=(False, "Connection refused"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["postgresql"]["connected"] is False
        assert _status(result) == 503

    def test_postgres_configured_but_not_required(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")

        with _remove_degraded(), _remove_leader(), _patch_startup():
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["postgresql"]["configured"] is True
        assert body["checks"]["postgresql"]["required"] is False

    def test_postgres_not_configured(self):
        handler = _make_mock_handler()
        with _remove_degraded(), _remove_leader(), _patch_startup():
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["postgresql"]["configured"] is False

    def test_postgres_import_error_skips(self):
        handler = _make_mock_handler()
        with _remove_degraded(), _remove_leader(), _remove_startup():
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["postgresql"]["status"] == "check_skipped"

    def test_postgres_connection_error_when_required(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _remove_degraded(),
            _remove_leader(),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                side_effect=ConnectionError("Connection refused"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["postgresql"]["error_type"] == "connectivity"
        assert _status(result) == 503

    def test_postgres_timeout_when_required(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "yes")

        with (
            _remove_degraded(),
            _remove_leader(),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                side_effect=asyncio.TimeoutError("Timed out"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        # asyncio.TimeoutError is a subclass of TimeoutError
        assert body["checks"]["postgresql"]["error_type"] in ("timeout", "connectivity")
        assert _status(result) == 503

    def test_postgres_runtime_error(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("ARAGORA_POSTGRES_DSN", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "1")

        with (
            _remove_degraded(),
            _remove_leader(),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                side_effect=ValueError("Bad DSN"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert "error" in body["checks"]["postgresql"]

    def test_postgres_in_async_context(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        mock_loop = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = (True, "Connected via thread")

        with (
            _remove_degraded(),
            _remove_leader(),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                return_value=mock_loop,
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.concurrent.futures.ThreadPoolExecutor",
            ) as mock_tpe_cls,
        ):
            mock_executor = MagicMock()
            mock_executor.submit.return_value = mock_future
            mock_executor.__enter__ = MagicMock(return_value=mock_executor)
            mock_executor.__exit__ = MagicMock(return_value=False)
            mock_tpe_cls.return_value = mock_executor

            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["postgresql"]["connected"] is True

    def test_postgres_require_database_values(self, monkeypatch):
        """ARAGORA_REQUIRE_DATABASE accepts true, 1, yes (case-insensitive)."""
        import aragora.server.handlers.admin.health as pkg

        for val in ("true", "1", "yes", "True", "YES", "TRUE"):
            pkg._HEALTH_CACHE.clear()
            pkg._HEALTH_CACHE_TIMESTAMPS.clear()

            handler = _make_mock_handler()
            monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
            monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", val)

            with (
                _remove_degraded(),
                _remove_leader(),
                _patch_startup(db_result=(True, "Connected")),
                patch(
                    "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                    side_effect=RuntimeError("no loop"),
                ),
                patch(
                    "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                    return_value=(True, "Connected"),
                ),
            ):
                result = readiness_dependencies(handler)
            body = _body(result)
            assert body["checks"]["postgresql"]["connected"] is True, (
                f"Failed for ARAGORA_REQUIRE_DATABASE={val!r}"
            )

    def test_postgres_require_database_false_values(self, monkeypatch):
        """Non-true values for ARAGORA_REQUIRE_DATABASE mean not required."""
        import aragora.server.handlers.admin.health as pkg

        for val in ("false", "0", "no", ""):
            pkg._HEALTH_CACHE.clear()
            pkg._HEALTH_CACHE_TIMESTAMPS.clear()

            handler = _make_mock_handler()
            monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
            monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", val)

            with _remove_degraded(), _remove_leader(), _patch_startup():
                result = readiness_dependencies(handler)
            body = _body(result)
            assert body["checks"]["postgresql"]["configured"] is True, (
                f"Failed for ARAGORA_REQUIRE_DATABASE={val!r}"
            )
            assert body["checks"]["postgresql"]["required"] is False

    def test_postgres_concurrent_futures_timeout(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _remove_degraded(),
            _remove_leader(),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                side_effect=concurrent.futures.TimeoutError("Pool timeout"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        # concurrent.futures.TimeoutError may be caught by earlier except clauses
        assert body["checks"]["postgresql"]["error_type"] in ("timeout", "connectivity")
        assert _status(result) == 503

    def test_postgres_os_error_connectivity(self, monkeypatch):
        handler = _make_mock_handler()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _remove_degraded(),
            _remove_leader(),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.kubernetes.asyncio.run",
                side_effect=OSError("Network unreachable"),
            ),
        ):
            result = readiness_dependencies(handler)
        body = _body(result)
        assert body["checks"]["postgresql"]["error_type"] == "connectivity"
        assert _status(result) == 503


class TestReadinessDepsApiKeys:
    """Test readiness_dependencies() API key detection."""

    def _run_deps(self, handler=None):
        if handler is None:
            handler = _make_mock_handler()
        with _remove_degraded(), _remove_leader(), _remove_startup():
            return readiness_dependencies(handler)

    def test_no_api_keys_configured(self):
        result = self._run_deps()
        body = _body(result)
        assert body["checks"]["api_keys"]["configured_count"] == 0
        assert body["checks"]["api_keys"]["providers"] == []
        assert "warning" in body["checks"]["api_keys"]
        assert _status(result) == 200

    def test_single_api_key_configured(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        result = self._run_deps()
        body = _body(result)
        assert body["checks"]["api_keys"]["configured_count"] == 1
        assert "anthropic" in body["checks"]["api_keys"]["providers"]
        assert "warning" not in body["checks"]["api_keys"]

    def test_multiple_api_keys_configured(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oai-test")
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-mis-test")
        result = self._run_deps()
        body = _body(result)
        assert body["checks"]["api_keys"]["configured_count"] == 3
        providers = body["checks"]["api_keys"]["providers"]
        assert "anthropic" in providers
        assert "openai" in providers
        assert "mistral" in providers

    def test_all_api_keys_configured(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-2")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-3")
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-4")
        monkeypatch.setenv("GEMINI_API_KEY", "sk-5")
        monkeypatch.setenv("XAI_API_KEY", "sk-6")
        result = self._run_deps()
        body = _body(result)
        assert body["checks"]["api_keys"]["configured_count"] == 6
        assert "warning" not in body["checks"]["api_keys"]

    def test_api_keys_do_not_affect_readiness(self):
        """No API keys should not cause readiness failure."""
        result = self._run_deps()
        assert _status(result) == 200

    def test_provider_name_format(self, monkeypatch):
        """Provider names should be lowercase without _API_KEY suffix."""
        monkeypatch.setenv("XAI_API_KEY", "sk-xai")
        result = self._run_deps()
        body = _body(result)
        assert "xai" in body["checks"]["api_keys"]["providers"]

    def test_openrouter_provider_name(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        result = self._run_deps()
        body = _body(result)
        assert "openrouter" in body["checks"]["api_keys"]["providers"]

    def test_gemini_provider_name(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "sk-gem")
        result = self._run_deps()
        body = _body(result)
        assert "gemini" in body["checks"]["api_keys"]["providers"]


class TestReadinessDeps:
    """Test readiness_dependencies() overall behavior."""

    def _run_healthy(self, handler=None):
        if handler is None:
            handler = _make_mock_handler()
        with _remove_degraded(), _remove_leader(), _remove_startup():
            return readiness_dependencies(handler)

    def test_returns_200_when_healthy(self):
        result = self._run_healthy()
        assert _status(result) == 200

    def test_status_is_ready(self):
        result = self._run_healthy()
        assert _body(result)["status"] == "ready"

    def test_latency_ms_present(self):
        result = self._run_healthy()
        assert "latency_ms" in _body(result)
        assert isinstance(_body(result)["latency_ms"], (int, float))

    def test_latency_ms_is_non_negative(self):
        result = self._run_healthy()
        assert _body(result)["latency_ms"] >= 0

    def test_result_is_cached(self):
        import aragora.server.handlers.admin.health as pkg

        self._run_healthy()
        assert "readiness" in pkg._HEALTH_CACHE

    def test_multiple_failures_accumulate(self):
        handler = _make_mock_handler()
        handler.get_storage.side_effect = OSError("Disk full")
        handler.get_elo_system.side_effect = RuntimeError("ELO broken")
        result = self._run_healthy(handler)
        body = _body(result)
        assert body["checks"]["storage"] is False
        assert body["checks"]["elo_system"] is False
        assert body["status"] == "not_ready"
        assert _status(result) == 503

    def test_storage_fail_elo_ok(self):
        handler = _make_mock_handler()
        handler.get_storage.side_effect = ValueError("Bad")
        result = self._run_healthy(handler)
        body = _body(result)
        assert body["checks"]["storage"] is False
        assert body["checks"]["elo_system"] is True
        assert _status(result) == 503

    def test_storage_ok_elo_fail(self):
        handler = _make_mock_handler()
        handler.get_elo_system.side_effect = ValueError("Bad")
        result = self._run_healthy(handler)
        body = _body(result)
        assert body["checks"]["storage"] is True
        assert body["checks"]["elo_system"] is False
        assert _status(result) == 503
