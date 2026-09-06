"""Tests for Kubernetes liveness and readiness probe implementations."""

import sys
import types as _types_mod

# Pre-stub Slack modules to prevent import chain failures
_SLACK_ATTRS = [
    "SlackHandler",
    "get_slack_handler",
    "get_slack_integration",
    "get_workspace_store",
    "resolve_workspace",
    "create_tracked_task",
    "_validate_slack_url",
    "SLACK_SIGNING_SECRET",
    "SLACK_BOT_TOKEN",
    "SLACK_WEBHOOK_URL",
    "SLACK_ALLOWED_DOMAINS",
    "SignatureVerifierMixin",
    "CommandsMixin",
    "EventsMixin",
    "init_slack_handler",
]
for _mod_name in (
    "aragora.server.handlers.social.slack.handler",
    "aragora.server.handlers.social.slack",
    "aragora.server.handlers.social._slack_impl",
):
    if _mod_name not in sys.modules:
        _m = _types_mod.ModuleType(_mod_name)
        for _a in _SLACK_ATTRS:
            setattr(_m, _a, None)
        sys.modules[_mod_name] = _m

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class MockHandler:
    """Mock handler for testing Kubernetes probe functions."""

    def __init__(
        self,
        storage: Any = None,
        elo_system: Any = None,
        nomic_dir: Path | None = None,
        storage_error: Exception | None = None,
        elo_error: Exception | None = None,
    ):
        self._storage = storage
        self._elo_system = elo_system
        self._nomic_dir = nomic_dir
        self._storage_error = storage_error
        self._elo_error = elo_error

    def get_storage(self) -> Any:
        if self._storage_error:
            raise self._storage_error
        return self._storage

    def get_elo_system(self) -> Any:
        if self._elo_error:
            raise self._elo_error
        return self._elo_system

    def get_nomic_dir(self) -> Path | None:
        return self._nomic_dir


@pytest.fixture(autouse=True)
def clear_module_state():
    """Clear any module-level state between tests."""
    import aragora.server.handlers.admin.health as health_mod

    health_mod._HEALTH_CACHE.clear()
    health_mod._HEALTH_CACHE_TIMESTAMPS.clear()
    yield


class TestLivenessProbe:
    """Tests for liveness_probe function."""

    def test_liveness_returns_ok(self):
        """Liveness probe returns 200 with status ok."""
        from aragora.server.handlers.admin.health.kubernetes import liveness_probe

        handler = MockHandler()

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": None}):
            result = liveness_probe(handler)

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "ok"

    def test_liveness_returns_ok_in_degraded_mode(self):
        """Liveness probe returns 200 even in degraded mode."""
        from aragora.server.handlers.admin.health.kubernetes import liveness_probe

        handler = MockHandler()

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = True
        mock_degraded.get_degraded_reason.return_value = "Missing API key"

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}):
            result = liveness_probe(handler)

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "ok"
        assert body.get("degraded") is True

    def test_liveness_no_degraded_info_when_not_degraded(self):
        """Liveness probe returns simple ok when not degraded."""
        from aragora.server.handlers.admin.health.kubernetes import liveness_probe

        handler = MockHandler()

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = False

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}):
            result = liveness_probe(handler)

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "ok"
        assert "degraded" not in body


class TestReadinessProbeFast:
    """Tests for readiness_probe_fast function."""

    def test_readiness_fast_returns_ready(self):
        """Fast readiness probe returns 200 when ready."""
        import aragora.server.unified_server as usrv
        from aragora.server.handlers.admin.health.kubernetes import readiness_probe_fast

        handler = MockHandler(
            storage=MagicMock(),
            elo_system=MagicMock(),
        )

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = False

        route_index_mock = MagicMock()
        route_index_mock._exact_routes = {"/health": ("_h", None)}

        old_ready = usrv._server_ready
        usrv._server_ready = True
        try:
            with (
                patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}),
                patch(
                    "aragora.server.handler_registry.core.get_route_index",
                    return_value=route_index_mock,
                ),
            ):
                result = readiness_probe_fast(handler)
        finally:
            usrv._server_ready = old_ready

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "ready"
        assert body.get("fast_probe") is True

    def test_readiness_fast_returns_not_ready_in_degraded(self):
        """Fast readiness probe returns 503 in degraded mode."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_probe_fast

        handler = MockHandler()

        mock_state = MagicMock()
        mock_state.error_code.value = "MISSING_API_KEY"
        mock_state.reason = "No API key"
        mock_state.recovery_hint = "Set ANTHROPIC_API_KEY"

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = True
        mock_degraded.get_degraded_state.return_value = mock_state

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}):
            result = readiness_probe_fast(handler)

        assert result.status_code == 503
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "not_ready"

    def test_readiness_fast_storage_error(self):
        """Fast readiness probe returns 503 on storage error."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_probe_fast

        handler = MockHandler(
            storage_error=RuntimeError("Storage unavailable"),
        )

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = False

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}):
            result = readiness_probe_fast(handler)

        assert result.status_code == 503
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "not_ready"
        assert body["checks"]["storage_initialized"] is False

    def test_readiness_fast_uses_cache(self):
        """Fast readiness probe uses cached result."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_probe_fast
        import aragora.server.handlers.admin.health as health_mod

        handler = MockHandler()

        # Pre-populate cache
        health_mod._HEALTH_CACHE["readiness_fast"] = {
            "status": "ready",
            "checks": {"storage_initialized": True},
            "latency_ms": 1.0,
            "fast_probe": True,
        }
        health_mod._HEALTH_CACHE_TIMESTAMPS["readiness_fast"] = __import__("time").time()

        result = readiness_probe_fast(handler)

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["latency_ms"] == 1.0

    def test_readiness_fast_latency_tracked(self):
        """Fast readiness probe tracks latency."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_probe_fast

        handler = MockHandler(storage=MagicMock())

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = False

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}):
            result = readiness_probe_fast(handler)

        body = json.loads(result.body.decode("utf-8"))
        assert "latency_ms" in body
        assert body["latency_ms"] >= 0

    def test_readiness_fast_reports_redis_pool_when_url_set(self, monkeypatch):
        """With REDIS_URL set, the fast probe reports a live pool as True."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_probe_fast

        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.delenv("ARAGORA_REDIS_URL", raising=False)
        handler = MockHandler(storage=MagicMock(), elo_system=MagicMock())

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = False

        with (
            patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}),
            patch("aragora.utils.redis_config.get_redis_pool", return_value=object()),
        ):
            result = readiness_probe_fast(handler)

        body = json.loads(result.body.decode("utf-8"))
        assert body["checks"]["redis_pool"] is True

    def test_readiness_fast_reports_missing_redis_pool_when_url_set(self, monkeypatch):
        """With REDIS_URL set but no pool built yet, the fast probe reports False."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_probe_fast

        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.delenv("ARAGORA_REDIS_URL", raising=False)
        handler = MockHandler(storage=MagicMock(), elo_system=MagicMock())

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = False

        with (
            patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}),
            patch("aragora.utils.redis_config.get_redis_pool", return_value=None),
        ):
            result = readiness_probe_fast(handler)

        body = json.loads(result.body.decode("utf-8"))
        assert body["checks"]["redis_pool"] is False


class TestReadinessDependencies:
    """Tests for readiness_dependencies function."""

    def test_readiness_deps_returns_ready(self):
        """Full readiness probe returns 200 when all deps ready."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_dependencies

        handler = MockHandler(
            storage=MagicMock(),
            elo_system=MagicMock(),
        )

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = False

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}):
            with patch.dict("os.environ", {}, clear=True):
                result = readiness_dependencies(handler)

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "ready"

    def test_readiness_deps_returns_not_ready_in_degraded(self):
        """Full readiness probe returns 503 in degraded mode."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_dependencies

        handler = MockHandler()

        mock_state = MagicMock()
        mock_state.error_code.value = "STARTUP_ERROR"
        mock_state.reason = "Failed to start"
        mock_state.recovery_hint = "Check logs"

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = True
        mock_degraded.get_degraded_state.return_value = mock_state

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}):
            result = readiness_dependencies(handler)

        assert result.status_code == 503
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "not_ready"

    def test_readiness_deps_storage_failure(self):
        """Full readiness probe returns 503 on storage failure."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_dependencies

        handler = MockHandler(
            storage_error=RuntimeError("Storage error"),
        )

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = False

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}):
            with patch.dict("os.environ", {}, clear=True):
                result = readiness_dependencies(handler)

        assert result.status_code == 503
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "not_ready"
        assert body["checks"]["storage"] is False

    def test_readiness_deps_elo_failure(self):
        """Full readiness probe returns 503 on ELO failure."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_dependencies

        handler = MockHandler(
            storage=MagicMock(),
            elo_error=ValueError("ELO error"),
        )

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = False

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}):
            with patch.dict("os.environ", {}, clear=True):
                result = readiness_dependencies(handler)

        assert result.status_code == 503
        body = json.loads(result.body.decode("utf-8"))
        assert body["checks"]["elo_system"] is False

    def test_readiness_deps_uses_cache(self):
        """Full readiness probe uses cached result."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_dependencies
        import aragora.server.handlers.admin.health as health_mod

        handler = MockHandler()

        # Pre-populate cache
        health_mod._HEALTH_CACHE["readiness"] = {
            "status": "ready",
            "checks": {"storage": True, "elo_system": True},
            "latency_ms": 50.0,
        }
        health_mod._HEALTH_CACHE_TIMESTAMPS["readiness"] = __import__("time").time()

        result = readiness_dependencies(handler)

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["latency_ms"] == 50.0

    def test_readiness_deps_null_storage_ok(self):
        """Full readiness treats null storage as OK."""
        from aragora.server.handlers.admin.health.kubernetes import readiness_dependencies

        handler = MockHandler(
            storage=None,
            elo_system=MagicMock(),
        )

        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = False

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}):
            with patch.dict("os.environ", {}, clear=True):
                result = readiness_dependencies(handler)

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["checks"]["storage"] is True
