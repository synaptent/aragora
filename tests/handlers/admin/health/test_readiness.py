"""Comprehensive tests for ReadinessHandler.

Tests all public methods and routes in
aragora/server/handlers/admin/health/readiness.py (78 lines):

  TestReadinessHandlerInit          - __init__ context handling
  TestClassAttributes               - ROUTES, PUBLIC_ROUTES
  TestCanHandle                     - can_handle() route matching
  TestHandleRouting                 - handle() routing and dispatch
  TestReadinessProbesFastDelegate   - _readiness_probe_fast() delegation
  TestReadinessDependenciesDelegate - _readiness_dependencies() delegation
  TestHandleUnknownPaths            - handle() returns None for unknown paths
  TestHandleEdgeCases               - edge cases: None context, empty params
  TestFastProbeIntegration          - readiness_probe_fast via kubernetes.py
  TestDependenciesIntegration       - readiness_dependencies via kubernetes.py

30+ tests covering all branches, error paths, and edge cases.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.admin.health.readiness import ReadinessHandler
from aragora.server.handlers.utils.responses import HandlerResult


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


_READINESS_MOD = "aragora.server.handlers.admin.health.readiness"
_K8S_MOD = "aragora.server.handlers.admin.health.kubernetes"
_DEGRADED_MOD = "aragora.server.degraded_mode"
_UNIFIED_SERVER_MOD = "aragora.server.unified_server"
_HANDLER_REGISTRY_MOD = "aragora.server.handler_registry.core"
_REDIS_CACHE_MOD = "aragora.utils.redis_config"
_PG_POOL_MOD = "aragora.storage.postgres_pool"
_LEADER_MOD = "aragora.control_plane.leader"
_STARTUP_MOD = "aragora.server.startup"


class MockHTTPHandler:
    """Mock HTTP handler for passing to handle()."""

    def __init__(self):
        self.command = "GET"
        self.client_address = ("127.0.0.1", 12345)
        self.headers = {"User-Agent": "test-agent", "Content-Length": "2"}
        self.rfile = MagicMock()
        self.rfile.read.return_value = b"{}"


def _make_handler_with_mocks(
    storage=MagicMock,
    elo=MagicMock,
    storage_exc=None,
    elo_exc=None,
):
    """Create a ReadinessHandler with get_storage and get_elo_system mocked."""
    h = ReadinessHandler(ctx={})
    if storage_exc:
        h.get_storage = MagicMock(side_effect=storage_exc)
    elif storage is None:
        h.get_storage = MagicMock(return_value=None)
    else:
        h.get_storage = MagicMock(return_value=MagicMock())
    if elo_exc:
        h.get_elo_system = MagicMock(side_effect=elo_exc)
    elif elo is None:
        h.get_elo_system = MagicMock(return_value=None)
    else:
        h.get_elo_system = MagicMock(return_value=MagicMock())
    return h


def _block_module_imports(*module_names):
    """Context manager that makes specified modules un-importable.

    This removes modules from sys.modules and patches builtins.__import__
    to raise ImportError for the specified module names.
    """
    import builtins

    original_import = builtins.__import__
    saved = {}
    for name in module_names:
        if name in sys.modules:
            saved[name] = sys.modules.pop(name)

    def _mock_import(name, *args, **kwargs):
        for blocked in module_names:
            if name == blocked or name.startswith(blocked + "."):
                raise ImportError(f"Mocked: {name}")
        return original_import(name, *args, **kwargs)

    return patch.object(builtins, "__import__", side_effect=_mock_import), saved


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Default ReadinessHandler with empty context."""
    return ReadinessHandler(ctx={})


@pytest.fixture
def handler_with_ctx():
    """ReadinessHandler with populated context."""
    ctx = {"storage": MagicMock(), "elo_system": MagicMock()}
    return ReadinessHandler(ctx=ctx)


@pytest.fixture
def http_handler():
    """Mock HTTP handler."""
    return MockHTTPHandler()


@pytest.fixture(autouse=True)
def _clear_health_cache():
    """Clear the health check cache before and after each test."""
    from aragora.server.handlers.admin.health import (
        _HEALTH_CACHE,
        _HEALTH_CACHE_TIMESTAMPS,
    )

    _HEALTH_CACHE.clear()
    _HEALTH_CACHE_TIMESTAMPS.clear()
    yield
    _HEALTH_CACHE.clear()
    _HEALTH_CACHE_TIMESTAMPS.clear()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure environment variables don't leak between tests."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("ARAGORA_REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ARAGORA_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("ARAGORA_REQUIRE_DATABASE", raising=False)
    for key in [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
        "GEMINI_API_KEY",
        "XAI_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# TestReadinessHandlerInit
# ---------------------------------------------------------------------------


class TestReadinessHandlerInit:
    """Tests for ReadinessHandler.__init__."""

    def test_init_with_empty_ctx(self):
        h = ReadinessHandler(ctx={})
        assert h.ctx == {}

    def test_init_with_none_ctx(self):
        h = ReadinessHandler(ctx=None)
        assert h.ctx == {}

    def test_init_no_args(self):
        h = ReadinessHandler()
        assert h.ctx == {}

    def test_init_with_populated_ctx(self):
        ctx = {"storage": "fake_storage", "debug": True}
        h = ReadinessHandler(ctx=ctx)
        assert h.ctx["storage"] == "fake_storage"
        assert h.ctx["debug"] is True


# ---------------------------------------------------------------------------
# TestClassAttributes
# ---------------------------------------------------------------------------


class TestClassAttributes:
    """Tests for class-level attributes."""

    def test_routes_contains_readyz(self):
        assert "/readyz" in ReadinessHandler.ROUTES

    def test_routes_contains_readyz_dependencies(self):
        assert "/readyz/dependencies" in ReadinessHandler.ROUTES

    def test_routes_has_exactly_two_entries(self):
        assert len(ReadinessHandler.ROUTES) == 2

    def test_public_routes_contains_readyz(self):
        assert "/readyz" in ReadinessHandler.PUBLIC_ROUTES

    def test_public_routes_contains_readyz_dependencies(self):
        assert "/readyz/dependencies" in ReadinessHandler.PUBLIC_ROUTES

    def test_public_routes_is_set(self):
        assert isinstance(ReadinessHandler.PUBLIC_ROUTES, set)

    def test_all_routes_are_public(self):
        """All routes on ReadinessHandler are public (K8s probes)."""
        for route in ReadinessHandler.ROUTES:
            assert route in ReadinessHandler.PUBLIC_ROUTES


# ---------------------------------------------------------------------------
# TestCanHandle
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for can_handle() route matching."""

    def test_can_handle_readyz(self, handler):
        assert handler.can_handle("/readyz") is True

    def test_can_handle_readyz_dependencies(self, handler):
        assert handler.can_handle("/readyz/dependencies") is True

    def test_cannot_handle_healthz(self, handler):
        assert handler.can_handle("/healthz") is False

    def test_cannot_handle_api_health(self, handler):
        assert handler.can_handle("/api/v1/health") is False

    def test_cannot_handle_empty_string(self, handler):
        assert handler.can_handle("") is False

    def test_cannot_handle_partial_match(self, handler):
        assert handler.can_handle("/readyz/") is False

    def test_cannot_handle_readyz_extra_path(self, handler):
        assert handler.can_handle("/readyz/dependencies/extra") is False

    def test_cannot_handle_readyz_prefix(self, handler):
        assert handler.can_handle("/api/readyz") is False

    def test_cannot_handle_none_like_string(self, handler):
        assert handler.can_handle("readyz") is False


# ---------------------------------------------------------------------------
# TestHandleRouting
# ---------------------------------------------------------------------------


class TestHandleRouting:
    """Tests for handle() path dispatch."""

    @pytest.mark.asyncio
    async def test_handle_readyz_dispatches_to_fast_probe(self, handler, http_handler):
        mock_result = HandlerResult(
            status_code=200,
            content_type="application/json",
            body=b'{"status":"ready"}',
        )
        with patch.object(handler, "_readiness_probe_fast", return_value=mock_result) as m:
            result = await handler.handle("/readyz", {}, http_handler)
            m.assert_called_once()
            assert result is mock_result

    @pytest.mark.asyncio
    async def test_handle_readyz_deps_dispatches_to_dependencies(self, handler, http_handler):
        mock_result = HandlerResult(
            status_code=200,
            content_type="application/json",
            body=b'{"status":"ready"}',
        )
        with patch.object(handler, "_readiness_dependencies", return_value=mock_result) as m:
            result = await handler.handle("/readyz/dependencies", {}, http_handler)
            m.assert_called_once()
            assert result is mock_result

    @pytest.mark.asyncio
    async def test_handle_unknown_path_returns_none(self, handler, http_handler):
        result = await handler.handle("/healthz", {}, http_handler)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_empty_path_returns_none(self, handler, http_handler):
        result = await handler.handle("", {}, http_handler)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_passes_with_empty_query_params(self, handler, http_handler):
        with patch.object(
            handler,
            "_readiness_probe_fast",
            return_value=HandlerResult(200, "application/json", b"{}"),
        ):
            result = await handler.handle("/readyz", {}, http_handler)
            assert result is not None

    @pytest.mark.asyncio
    async def test_handle_passes_with_nonempty_query_params(self, handler, http_handler):
        with patch.object(
            handler,
            "_readiness_probe_fast",
            return_value=HandlerResult(200, "application/json", b"{}"),
        ):
            result = await handler.handle("/readyz", {"verbose": "true"}, http_handler)
            assert result is not None


# ---------------------------------------------------------------------------
# TestReadinessProbesFastDelegate
# ---------------------------------------------------------------------------


class TestReadinessProbesFastDelegate:
    """Tests for _readiness_probe_fast() delegation to kubernetes module."""

    def test_delegates_to_kubernetes_readiness_probe_fast(self, handler):
        mock_result = HandlerResult(
            status_code=200,
            content_type="application/json",
            body=b'{"status":"ready"}',
        )
        with patch(
            f"{_READINESS_MOD}.readiness_probe_fast",
            return_value=mock_result,
        ) as m:
            result = handler._readiness_probe_fast()
            m.assert_called_once_with(handler)
            assert result is mock_result

    def test_passes_handler_self_as_argument(self, handler):
        with patch(
            f"{_READINESS_MOD}.readiness_probe_fast",
            return_value=HandlerResult(200, "application/json", b"{}"),
        ) as m:
            handler._readiness_probe_fast()
            args, _ = m.call_args
            assert args[0] is handler


# ---------------------------------------------------------------------------
# TestReadinessDependenciesDelegate
# ---------------------------------------------------------------------------


class TestReadinessDependenciesDelegate:
    """Tests for _readiness_dependencies() delegation to kubernetes module."""

    def test_delegates_to_kubernetes_readiness_dependencies(self, handler):
        mock_result = HandlerResult(
            status_code=200,
            content_type="application/json",
            body=b'{"status":"ready"}',
        )
        with patch(
            f"{_READINESS_MOD}.readiness_dependencies",
            return_value=mock_result,
        ) as m:
            result = handler._readiness_dependencies()
            m.assert_called_once_with(handler)
            assert result is mock_result

    def test_passes_handler_self_as_argument(self, handler):
        with patch(
            f"{_READINESS_MOD}.readiness_dependencies",
            return_value=HandlerResult(200, "application/json", b"{}"),
        ) as m:
            handler._readiness_dependencies()
            args, _ = m.call_args
            assert args[0] is handler


# ---------------------------------------------------------------------------
# TestHandleUnknownPaths
# ---------------------------------------------------------------------------


class TestHandleUnknownPaths:
    """Tests that handle() returns None for non-matching paths."""

    @pytest.mark.asyncio
    async def test_returns_none_for_healthz(self, handler, http_handler):
        result = await handler.handle("/healthz", {}, http_handler)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_api_v1_health(self, handler, http_handler):
        result = await handler.handle("/api/v1/health", {}, http_handler)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_api_health(self, handler, http_handler):
        result = await handler.handle("/api/health", {}, http_handler)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_random_path(self, handler, http_handler):
        result = await handler.handle("/foo/bar", {}, http_handler)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_readyz_with_trailing_slash(self, handler, http_handler):
        result = await handler.handle("/readyz/", {}, http_handler)
        assert result is None


# ---------------------------------------------------------------------------
# TestHandleEdgeCases
# ---------------------------------------------------------------------------


class TestHandleEdgeCases:
    """Edge cases for the handler."""

    def test_handler_with_none_ctx_still_functional(self):
        h = ReadinessHandler(ctx=None)
        assert h.can_handle("/readyz") is True

    @pytest.mark.asyncio
    async def test_handle_with_none_handler(self, handler):
        """handle() with None http_handler should still dispatch correctly."""
        mock_result = HandlerResult(200, "application/json", b'{"status":"ready"}')
        with patch.object(handler, "_readiness_probe_fast", return_value=mock_result):
            result = await handler.handle("/readyz", {}, None)
            assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_with_none_query_params(self, handler, http_handler):
        """handle() with None query_params should still work."""
        mock_result = HandlerResult(200, "application/json", b'{"status":"ready"}')
        with patch.object(handler, "_readiness_probe_fast", return_value=mock_result):
            result = await handler.handle("/readyz", None, http_handler)
            assert result is mock_result

    def test_handler_is_instance_of_secure_handler(self, handler):
        from aragora.server.handlers.secure import SecureHandler

        assert isinstance(handler, SecureHandler)

    def test_handler_module_all_export(self):
        import aragora.server.handlers.admin.health.readiness as mod

        assert "ReadinessHandler" in mod.__all__

    @pytest.mark.asyncio
    async def test_handle_returns_handler_result_type(self, handler, http_handler):
        """Confirm the returned object is a HandlerResult."""
        mock_result = HandlerResult(200, "application/json", b'{"ok":true}')
        with patch.object(handler, "_readiness_probe_fast", return_value=mock_result):
            result = await handler.handle("/readyz", {}, http_handler)
            assert isinstance(result, HandlerResult)


# ---------------------------------------------------------------------------
# TestFastProbeIntegration
# ---------------------------------------------------------------------------


class TestFastProbeIntegration:
    """Integration-style tests for the fast readiness probe via kubernetes module.

    These patch the source modules that kubernetes.py imports inline so that
    readiness_probe_fast exercises real code paths.
    """

    def _run_fast_probe(self, handler):
        """Run the fast probe with degraded_mode / unified_server / handler_registry
        made un-importable so the fast path skips those checks."""
        with (
            patch.dict(
                sys.modules,
                {
                    _DEGRADED_MOD: None,
                    _UNIFIED_SERVER_MOD: None,
                    _HANDLER_REGISTRY_MOD: None,
                    _REDIS_CACHE_MOD: None,
                    _PG_POOL_MOD: None,
                },
            ),
        ):
            return handler._readiness_probe_fast()

    def test_fast_probe_returns_ready_when_all_checks_pass(self):
        h = _make_handler_with_mocks()
        result = self._run_fast_probe(h)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "ready"
        assert body["fast_probe"] is True

    def test_fast_probe_returns_not_ready_when_storage_fails(self):
        h = _make_handler_with_mocks(storage_exc=RuntimeError("no storage"))
        result = self._run_fast_probe(h)
        assert _status(result) == 503
        body = _body(result)
        assert body["status"] == "not_ready"
        assert body["checks"]["storage_initialized"] is False

    def test_fast_probe_returns_not_ready_when_elo_fails(self):
        h = _make_handler_with_mocks(elo_exc=RuntimeError("no elo"))
        result = self._run_fast_probe(h)
        assert _status(result) == 503
        body = _body(result)
        assert body["status"] == "not_ready"
        assert body["checks"]["elo_initialized"] is False

    def test_fast_probe_includes_latency(self):
        h = _make_handler_with_mocks()
        result = self._run_fast_probe(h)
        body = _body(result)
        assert "latency_ms" in body
        assert isinstance(body["latency_ms"], (int, float))

    def test_fast_probe_full_validation_link(self):
        h = _make_handler_with_mocks()
        result = self._run_fast_probe(h)
        body = _body(result)
        assert body["full_validation"] == "/readyz/dependencies"

    def test_fast_probe_returns_cached_result(self, handler):
        """Second call returns cached result (5s cache TTL)."""
        from aragora.server.handlers.admin.health import _set_cached_health

        cached_data = {"status": "ready", "checks": {}, "cached": True}
        _set_cached_health("readiness_fast", cached_data)
        result = handler._readiness_probe_fast()
        body = _body(result)
        assert body.get("cached") is True
        assert _status(result) == 200

    def test_fast_probe_cached_not_ready_returns_503(self, handler):
        """Cached not_ready result returns 503."""
        from aragora.server.handlers.admin.health import _set_cached_health

        cached_data = {"status": "not_ready", "checks": {}}
        _set_cached_health("readiness_fast", cached_data)
        result = handler._readiness_probe_fast()
        assert _status(result) == 503

    def test_fast_probe_degraded_mode(self):
        """When degraded mode is active, fast probe returns 503 immediately."""
        mock_state = MagicMock()
        mock_state.error_code.value = "MISSING_API_KEY"
        mock_state.reason = "No API keys"
        mock_state.recovery_hint = "Set ANTHROPIC_API_KEY"

        mock_degraded_mod = MagicMock()
        mock_degraded_mod.is_degraded.return_value = True
        mock_degraded_mod.get_degraded_state.return_value = mock_state

        h = _make_handler_with_mocks()
        with patch.dict(
            sys.modules,
            {
                _DEGRADED_MOD: mock_degraded_mod,
                _UNIFIED_SERVER_MOD: None,
                _HANDLER_REGISTRY_MOD: None,
            },
        ):
            result = h._readiness_probe_fast()
            assert _status(result) == 503
            body = _body(result)
            assert body["status"] == "not_ready"
            assert "degraded" in body

    def test_fast_probe_storage_returns_none(self):
        """When get_storage returns None, storage_initialized is True (not configured is OK)."""
        h = _make_handler_with_mocks(storage=None)
        result = self._run_fast_probe(h)
        body = _body(result)
        assert body["checks"]["storage_initialized"] is True

    def test_fast_probe_elo_returns_none(self):
        """When get_elo_system returns None, elo_initialized is True (not configured is OK)."""
        h = _make_handler_with_mocks(elo=None)
        result = self._run_fast_probe(h)
        body = _body(result)
        assert body["checks"]["elo_initialized"] is True

    def test_fast_probe_checks_degraded_mode_key(self):
        """Degraded mode import error sets degraded_mode check to True."""
        h = _make_handler_with_mocks()
        result = self._run_fast_probe(h)
        body = _body(result)
        assert body["checks"]["degraded_mode"] is True

    def test_fast_probe_storage_oserror(self):
        """OSError from storage is handled."""
        h = _make_handler_with_mocks(storage_exc=OSError("disk full"))
        result = self._run_fast_probe(h)
        assert _status(result) == 503
        body = _body(result)
        assert body["checks"]["storage_initialized"] is False

    def test_fast_probe_elo_valueerror(self):
        """ValueError from ELO is handled."""
        h = _make_handler_with_mocks(elo_exc=ValueError("bad config"))
        result = self._run_fast_probe(h)
        assert _status(result) == 503
        body = _body(result)
        assert body["checks"]["elo_initialized"] is False


# ---------------------------------------------------------------------------
# TestDependenciesIntegration
# ---------------------------------------------------------------------------


class TestDependenciesIntegration:
    """Integration-style tests for the dependencies readiness probe."""

    def _run_deps_probe(self, handler):
        """Run the dependencies probe with external modules un-importable."""
        with patch.dict(
            sys.modules,
            {
                _DEGRADED_MOD: None,
                _LEADER_MOD: None,
                _STARTUP_MOD: None,
            },
        ):
            return handler._readiness_dependencies()

    def test_dependencies_returns_ready_when_all_pass(self):
        h = _make_handler_with_mocks()
        result = self._run_deps_probe(h)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "ready"

    def test_dependencies_storage_error_returns_503(self):
        h = _make_handler_with_mocks(storage_exc=RuntimeError("storage down"))
        result = self._run_deps_probe(h)
        assert _status(result) == 503
        body = _body(result)
        assert body["status"] == "not_ready"
        assert body["checks"]["storage"] is False

    def test_dependencies_elo_error_returns_503(self):
        h = _make_handler_with_mocks(elo_exc=ValueError("elo error"))
        result = self._run_deps_probe(h)
        assert _status(result) == 503
        body = _body(result)
        assert body["checks"]["elo_system"] is False

    def test_dependencies_includes_latency(self):
        h = _make_handler_with_mocks()
        result = self._run_deps_probe(h)
        body = _body(result)
        assert "latency_ms" in body

    def test_dependencies_api_keys_no_keys_configured(self):
        h = _make_handler_with_mocks()
        result = self._run_deps_probe(h)
        body = _body(result)
        assert body["checks"]["api_keys"]["configured_count"] == 0
        assert "warning" in body["checks"]["api_keys"]

    def test_dependencies_api_keys_with_key_configured(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        h = _make_handler_with_mocks()
        result = self._run_deps_probe(h)
        body = _body(result)
        assert body["checks"]["api_keys"]["configured_count"] == 1
        assert "anthropic" in body["checks"]["api_keys"]["providers"]

    def test_dependencies_api_keys_multiple_providers(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-mistral")
        h = _make_handler_with_mocks()
        result = self._run_deps_probe(h)
        body = _body(result)
        assert body["checks"]["api_keys"]["configured_count"] == 3
        assert "anthropic" in body["checks"]["api_keys"]["providers"]
        assert "openai" in body["checks"]["api_keys"]["providers"]
        assert "mistral" in body["checks"]["api_keys"]["providers"]

    def test_dependencies_cached_result(self):
        from aragora.server.handlers.admin.health import _set_cached_health

        cached = {"status": "ready", "checks": {}, "cached_marker": True}
        _set_cached_health("readiness", cached)
        h = ReadinessHandler(ctx={})
        result = h._readiness_dependencies()
        body = _body(result)
        assert body.get("cached_marker") is True
        assert _status(result) == 200

    def test_dependencies_cached_not_ready_returns_503(self):
        from aragora.server.handlers.admin.health import _set_cached_health

        cached = {"status": "not_ready", "checks": {}}
        _set_cached_health("readiness", cached)
        h = ReadinessHandler(ctx={})
        result = h._readiness_dependencies()
        assert _status(result) == 503

    def test_dependencies_degraded_mode(self):
        """Degraded mode causes immediate 503."""
        mock_state = MagicMock()
        mock_state.error_code.value = "STARTUP_ERROR"
        mock_state.reason = "Failed to start"
        mock_state.recovery_hint = "Check logs"

        mock_degraded_mod = MagicMock()
        mock_degraded_mod.is_degraded.return_value = True
        mock_degraded_mod.get_degraded_state.return_value = mock_state

        h = _make_handler_with_mocks()
        with patch.dict(
            sys.modules,
            {
                _DEGRADED_MOD: mock_degraded_mod,
                _LEADER_MOD: None,
                _STARTUP_MOD: None,
            },
        ):
            result = h._readiness_dependencies()
            assert _status(result) == 503
            body = _body(result)
            assert body["status"] == "not_ready"
            assert body["reason"] == "Server in degraded mode"

    def test_dependencies_storage_none_is_ok(self):
        """get_storage returning None is treated as OK (not configured)."""
        h = _make_handler_with_mocks(storage=None)
        result = self._run_deps_probe(h)
        body = _body(result)
        assert body["checks"]["storage"] is True
        assert _status(result) == 200

    def test_dependencies_elo_none_is_ok(self):
        """get_elo_system returning None is treated as OK (not configured)."""
        h = _make_handler_with_mocks(elo=None)
        result = self._run_deps_probe(h)
        body = _body(result)
        assert body["checks"]["elo_system"] is True
        assert _status(result) == 200

    def test_dependencies_redis_check_skipped(self):
        """When leader module is not importable, redis check is skipped."""
        h = _make_handler_with_mocks()
        result = self._run_deps_probe(h)
        body = _body(result)
        assert body["checks"]["redis"] == {"status": "check_skipped"}

    def test_dependencies_postgresql_check_skipped(self):
        """When startup module is not importable, postgresql check is skipped."""
        h = _make_handler_with_mocks()
        result = self._run_deps_probe(h)
        body = _body(result)
        assert body["checks"]["postgresql"] == {"status": "check_skipped"}

    def test_dependencies_storage_oserror(self):
        """OSError from storage marks it as failed."""
        h = _make_handler_with_mocks(storage_exc=OSError("permission denied"))
        result = self._run_deps_probe(h)
        assert _status(result) == 503
        body = _body(result)
        assert body["checks"]["storage"] is False
