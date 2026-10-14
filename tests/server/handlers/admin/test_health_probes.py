"""
Tests for Kubernetes probe implementations.

Tests cover:
- Liveness probe behavior (always returns 200)
- Readiness probe behavior (returns 200 or 503 based on checks)
- Cache behavior for readiness probe
- Degraded mode handling
- Storage and ELO system checks
- Redis and PostgreSQL connectivity checks
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.admin.health.probes import ProbesMixin


class TestProbeHandler(ProbesMixin):
    """Test handler implementing ProbesMixin."""

    def __init__(
        self,
        storage: Any = None,
        elo_system: Any = None,
        storage_error: Exception | None = None,
        elo_error: Exception | None = None,
    ):
        self._storage = storage
        self._elo_system = elo_system
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


class TestLivenessProbe:
    """Tests for liveness_probe method."""

    def test_liveness_probe_returns_ok(self):
        """Liveness probe returns 200 with status: ok."""
        handler = TestProbeHandler()

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": None}):
            # Force ImportError for degraded_mode
            with patch.object(
                handler, "liveness_probe", wraps=handler.liveness_probe
            ) as mock_probe:
                # Direct call bypassing the import check
                result = handler.liveness_probe()

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "ok"

    def test_liveness_probe_in_degraded_mode(self):
        """Liveness probe returns 200 with degraded info when in degraded mode."""
        handler = TestProbeHandler()

        mock_degraded_module = MagicMock()
        mock_degraded_module.is_degraded.return_value = True
        mock_degraded_module.get_degraded_reason.return_value = "Missing API key"

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded_module}):
            result = handler.liveness_probe()

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "ok"
        assert body["degraded"] is True
        assert "Missing API key" in body["degraded_reason"]

    def test_liveness_probe_not_degraded(self):
        """Liveness probe returns simple ok when not degraded."""
        handler = TestProbeHandler()

        mock_degraded_module = MagicMock()
        mock_degraded_module.is_degraded.return_value = False

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded_module}):
            result = handler.liveness_probe()

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "ok"
        assert "degraded" not in body


class TestReadinessProbe:
    """Tests for readiness_probe method."""

    def setup_method(self):
        """Set up test cache."""
        self.cache: dict[str, Any] = {}

    def cache_get(self, key: str) -> Any:
        return self.cache.get(key)

    def cache_set(self, key: str, value: Any) -> None:
        self.cache[key] = value

    def test_readiness_probe_ready(self):
        """Readiness probe returns 200 when all checks pass."""
        handler = TestProbeHandler(
            storage=MagicMock(),
            elo_system=MagicMock(),
        )

        # Mock degraded mode to be inactive
        mock_degraded_module = MagicMock()
        mock_degraded_module.is_degraded.return_value = False

        # Mock Redis/PostgreSQL checks to pass through existing checks and add their own
        def mock_redis_check(ready: bool, checks: dict) -> tuple:
            checks["redis"] = {"configured": False}
            return ready, checks

        def mock_pg_check(ready: bool, checks: dict) -> tuple:
            checks["postgresql"] = {"configured": False}
            return ready, checks

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded_module}):
            with patch.object(handler, "_check_redis_readiness", side_effect=mock_redis_check):
                with patch.object(
                    handler, "_check_postgresql_readiness", side_effect=mock_pg_check
                ):
                    result = handler.readiness_probe(self.cache_get, self.cache_set)

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "ready"
        assert body["checks"]["storage"] is True
        assert body["checks"]["elo_system"] is True

    def test_readiness_probe_in_degraded_mode(self):
        """Readiness probe returns 503 when in degraded mode."""
        handler = TestProbeHandler()

        mock_state = MagicMock()
        mock_state.error_code.value = "MISSING_API_KEY"
        mock_state.reason = "No Anthropic API key configured"
        mock_state.recovery_hint = "Set ANTHROPIC_API_KEY"

        mock_degraded_module = MagicMock()
        mock_degraded_module.is_degraded.return_value = True
        mock_degraded_module.get_degraded_state.return_value = mock_state

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded_module}):
            result = handler.readiness_probe(self.cache_get, self.cache_set)

        assert result.status_code == 503
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "not_ready"
        assert "degraded" in body
        assert body["degraded"]["error_code"] == "MISSING_API_KEY"

    def test_readiness_probe_storage_failure(self):
        """Readiness probe returns 503 when storage check fails."""
        handler = TestProbeHandler(
            storage_error=RuntimeError("Storage unavailable"),
            elo_system=MagicMock(),
        )

        mock_degraded_module = MagicMock()
        mock_degraded_module.is_degraded.return_value = False

        # Mock Redis/PostgreSQL checks to pass through existing checks
        def mock_redis_check(ready: bool, checks: dict) -> tuple:
            checks["redis"] = {"configured": False}
            return ready, checks

        def mock_pg_check(ready: bool, checks: dict) -> tuple:
            checks["postgresql"] = {"configured": False}
            return ready, checks

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded_module}):
            with patch.object(handler, "_check_redis_readiness", side_effect=mock_redis_check):
                with patch.object(
                    handler, "_check_postgresql_readiness", side_effect=mock_pg_check
                ):
                    result = handler.readiness_probe(self.cache_get, self.cache_set)

        assert result.status_code == 503
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "not_ready"
        assert body["checks"]["storage"] is False

    def test_readiness_probe_elo_failure(self):
        """Readiness probe returns 503 when ELO system check fails."""
        handler = TestProbeHandler(
            storage=MagicMock(),
            elo_error=ValueError("ELO system not initialized"),
        )

        mock_degraded_module = MagicMock()
        mock_degraded_module.is_degraded.return_value = False

        # Mock Redis/PostgreSQL checks to pass through existing checks
        def mock_redis_check(ready: bool, checks: dict) -> tuple:
            checks["redis"] = {"configured": False}
            return ready, checks

        def mock_pg_check(ready: bool, checks: dict) -> tuple:
            checks["postgresql"] = {"configured": False}
            return ready, checks

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded_module}):
            with patch.object(handler, "_check_redis_readiness", side_effect=mock_redis_check):
                with patch.object(
                    handler, "_check_postgresql_readiness", side_effect=mock_pg_check
                ):
                    result = handler.readiness_probe(self.cache_get, self.cache_set)

        assert result.status_code == 503
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "not_ready"
        assert body["checks"]["elo_system"] is False

    def test_readiness_probe_cache_hit(self):
        """Readiness probe returns cached result when available."""
        handler = TestProbeHandler()

        # Pre-populate cache with ready result
        self.cache["readiness"] = {
            "status": "ready",
            "checks": {"storage": True, "elo_system": True},
            "latency_ms": 5.0,
        }

        result = handler.readiness_probe(self.cache_get, self.cache_set)

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "ready"
        assert body["latency_ms"] == 5.0

    def test_readiness_probe_cache_hit_not_ready(self):
        """Readiness probe returns 503 for cached not_ready result."""
        handler = TestProbeHandler()

        # Pre-populate cache with not_ready result
        self.cache["readiness"] = {
            "status": "not_ready",
            "checks": {"storage": False},
            "latency_ms": 10.0,
        }

        result = handler.readiness_probe(self.cache_get, self.cache_set)

        assert result.status_code == 503
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "not_ready"

    def test_readiness_probe_no_storage_configured_is_ok(self):
        """Readiness probe treats no storage as OK."""
        handler = TestProbeHandler(
            storage=None,  # Not configured
            elo_system=MagicMock(),
        )

        mock_degraded_module = MagicMock()
        mock_degraded_module.is_degraded.return_value = False

        # Mock Redis/PostgreSQL checks to pass through existing checks
        def mock_redis_check(ready: bool, checks: dict) -> tuple:
            checks["redis"] = {"configured": False}
            return ready, checks

        def mock_pg_check(ready: bool, checks: dict) -> tuple:
            checks["postgresql"] = {"configured": False}
            return ready, checks

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded_module}):
            with patch.object(handler, "_check_redis_readiness", side_effect=mock_redis_check):
                with patch.object(
                    handler, "_check_postgresql_readiness", side_effect=mock_pg_check
                ):
                    result = handler.readiness_probe(self.cache_get, self.cache_set)

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert body["status"] == "ready"
        # Storage check passes because None is treated as "not configured = OK"
        assert body["checks"]["storage"] is True


class TestRedisReadinessCheck:
    """Tests for _check_redis_readiness method."""

    def test_redis_not_configured(self):
        """Redis check passes when not configured."""
        handler = TestProbeHandler()

        with patch.dict("os.environ", {}, clear=True):
            with patch.dict("sys.modules", {"aragora.config.distributed": None}):
                ready, checks = handler._check_redis_readiness(True, {})

        assert ready is True
        # When import fails, returns {"status": "check_skipped"}
        # When Redis URL is not set, returns {"configured": False}
        redis_check = checks.get("redis", {})
        assert (
            redis_check.get("configured") is False
            or redis_check.get("status") == "check_skipped"
            or "redis" not in checks
        )

    def test_redis_configured_but_not_required(self):
        """Redis check passes when configured but not required for distributed state."""
        handler = TestProbeHandler()

        mock_distributed = MagicMock()
        mock_distributed.is_distributed_state_required.return_value = False

        with patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"}):
            with patch.dict("sys.modules", {"aragora.config.distributed": mock_distributed}):
                ready, checks = handler._check_redis_readiness(True, {})

        assert ready is True
        # When not required, should indicate configured but not required
        assert "redis" in checks


class TestPostgreSQLReadinessCheck:
    """Tests for _check_postgresql_readiness method."""

    def test_postgresql_not_configured(self):
        """PostgreSQL check passes when not configured."""
        handler = TestProbeHandler()

        with patch.dict("os.environ", {}, clear=True):
            ready, checks = handler._check_postgresql_readiness(True, {})

        # Should pass or skip when not configured
        assert ready is True

    def test_postgresql_configured_but_not_required(self):
        """PostgreSQL check passes when configured but not required."""
        handler = TestProbeHandler()

        with patch.dict(
            "os.environ",
            {"DATABASE_URL": "postgresql://localhost/test", "ARAGORA_REQUIRE_DATABASE": "false"},
        ):
            ready, checks = handler._check_postgresql_readiness(True, {})

        assert ready is True
        assert "postgresql" in checks


class TestProbeIntegration:
    """Integration tests for probe behavior."""

    def test_liveness_always_returns_200(self):
        """Liveness should always return 200, even with errors."""
        # Test with various error conditions
        handlers = [
            TestProbeHandler(storage_error=RuntimeError("Error")),
            TestProbeHandler(elo_error=ValueError("Error")),
            TestProbeHandler(),
        ]

        for handler in handlers:
            result = handler.liveness_probe()
            assert result.status_code == 200

    def test_readiness_respects_all_checks(self):
        """Readiness should check all dependencies."""
        handler = TestProbeHandler(
            storage=MagicMock(),
            elo_system=MagicMock(),
        )

        cache: dict[str, Any] = {}

        def cache_get(key: str) -> Any:
            return cache.get(key)

        def cache_set(key: str, value: Any) -> None:
            cache[key] = value

        mock_degraded_module = MagicMock()
        mock_degraded_module.is_degraded.return_value = False

        # Mock Redis/PostgreSQL checks to pass through existing checks
        def mock_redis_check(ready: bool, checks: dict) -> tuple:
            checks["redis"] = {"configured": False}
            return ready, checks

        def mock_pg_check(ready: bool, checks: dict) -> tuple:
            checks["postgresql"] = {"configured": False}
            return ready, checks

        with patch.dict("sys.modules", {"aragora.server.degraded_mode": mock_degraded_module}):
            with patch.object(handler, "_check_redis_readiness", side_effect=mock_redis_check):
                with patch.object(
                    handler, "_check_postgresql_readiness", side_effect=mock_pg_check
                ):
                    result = handler.readiness_probe(cache_get, cache_set)

        assert result.status_code == 200
        body = json.loads(result.body.decode("utf-8"))
        assert "latency_ms" in body
        assert body["latency_ms"] >= 0
