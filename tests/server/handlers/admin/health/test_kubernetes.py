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

    @staticmethod
    def _run_ready_probe_with_redis_pool(pool: Any) -> tuple[int, dict[str, Any]]:
        """Run the fast probe on an otherwise-ready server with the real shared
        pool global set to ``pool``.

        Fails if the probe tries to build the pool or changes the Redis
        availability latch.
        """
        import aragora.server.unified_server as usrv
        import aragora.utils.redis_config as redis_config
        from aragora.server.handlers.admin.health.kubernetes import readiness_probe_fast

        handler = MockHandler(storage=MagicMock(), elo_system=MagicMock())
        mock_degraded = MagicMock()
        mock_degraded.is_degraded.return_value = False
        route_index_mock = MagicMock()
        route_index_mock._exact_routes = {"/health": ("_h", None)}
        latch = object()

        def _must_not_be_called():
            raise AssertionError("readiness_probe_fast called get_redis_pool")

        with (
            patch.object(usrv, "_server_ready", True),
            patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded}),
            patch(
                "aragora.server.handler_registry.core.get_route_index",
                return_value=route_index_mock,
            ),
            patch.object(redis_config, "_redis_pool", pool),
            patch.object(redis_config, "_redis_available", latch),
            patch.object(redis_config, "get_redis_pool", side_effect=_must_not_be_called),
        ):
            result = readiness_probe_fast(handler)
            assert redis_config._redis_available is latch

        return result.status_code, json.loads(result.body.decode("utf-8"))

    @pytest.mark.parametrize(
        ("redis_url", "aragora_redis_url", "pool_built", "expected"),
        [
            (None, None, False, "not_configured"),
            (None, None, True, "not_configured"),
            ("redis://legacy:6379/0", None, False, "not_configured"),
            ("redis://legacy:6379/0", None, True, "not_configured"),
            (None, "redis://shared:6379/0", False, False),
            (None, "redis://shared:6379/0", True, True),
            ("redis://legacy:6379/0", "redis://shared:6379/0", False, False),
            ("redis://legacy:6379/0", "redis://shared:6379/0", True, True),
        ],
        ids=[
            "neither-no-pool",
            "neither-pool-built",
            "redis_url_only-no-pool",
            "redis_url_only-pool-built",
            "aragora_redis_url_only-no-pool",
            "aragora_redis_url_only-pool-built",
            "both-no-pool",
            "both-pool-built",
        ],
    )
    def test_readiness_fast_redis_pool_url_matrix(
        self, monkeypatch, redis_url, aragora_redis_url, pool_built, expected
    ):
        """Only ARAGORA_REDIS_URL configures the shared pool, so REDIS_URL alone
        reports "not_configured" instead of a False that looks like a broken pool.
        When configured, the value says whether the pool is built yet; it never
        affects readiness."""
        for name, value in (("REDIS_URL", redis_url), ("ARAGORA_REDIS_URL", aragora_redis_url)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)

        status, body = self._run_ready_probe_with_redis_pool(object() if pool_built else None)

        actual = body["checks"]["redis_pool"]
        assert (type(actual), actual) == (type(expected), expected)
        assert status == 200
        assert body["status"] == "ready"

    def test_readiness_fast_never_builds_redis_pool(self, monkeypatch):
        """With the shared pool configured but not built, the fast probe reports
        False without calling get_redis_pool (which pings the network on first
        use) or touching the availability latch."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.setenv("ARAGORA_REDIS_URL", "redis://localhost:6379/0")

        status, body = self._run_ready_probe_with_redis_pool(None)

        assert body["checks"]["redis_pool"] is False
        assert status == 200


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
