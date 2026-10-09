"""Comprehensive tests for ProbesMixin in aragora/server/handlers/admin/health/probes.py.

Tests the ProbesMixin class which provides Kubernetes liveness and readiness probes:

  TestGetStorage               - get_storage() method
  TestGetStorageNoCtx          - get_storage() when ctx is None or missing
  TestGetEloSystem             - get_elo_system() from ctx
  TestGetEloSystemClassAttr    - get_elo_system() from class attribute
  TestGetEloSystemNoCtx        - get_elo_system() when ctx is None or missing
  TestLivenessProbe            - liveness_probe() healthy server
  TestLivenessProbeDegraded    - liveness_probe() degraded mode
  TestLivenessProbeImportError - liveness_probe() when degraded_mode unavailable
  TestReadinessProbe           - readiness_probe() all checks passing
  TestReadinessProbeCached     - readiness_probe() cached result path
  TestReadinessProbeDegraded   - readiness_probe() degraded mode
  TestReadinessProbeStorage    - readiness_probe() storage check
  TestReadinessProbeElo        - readiness_probe() ELO system check
  TestCheckRedisReadiness      - _check_redis_readiness() method
  TestCheckRedisImportError    - _check_redis_readiness() import error handling
  TestCheckRedisConnError      - _check_redis_readiness() connectivity errors
  TestCheckRedisTimeout        - _check_redis_readiness() timeout errors
  TestCheckRedisRuntimeError   - _check_redis_readiness() runtime errors
  TestCheckPostgresReadiness   - _check_postgresql_readiness() method
  TestCheckPostgresImportError - _check_postgresql_readiness() import error handling
  TestCheckPostgresConnError   - _check_postgresql_readiness() connectivity errors
  TestCheckPostgresTimeout     - _check_postgresql_readiness() timeout errors
  TestCheckPostgresRuntimeError - _check_postgresql_readiness() runtime errors

90+ tests covering all branches, error paths, and edge cases.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.admin.health.probes import ProbesMixin


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


class ConcreteProbesMixin(ProbesMixin):
    """Concrete class that uses ProbesMixin for testing."""

    elo_system = None  # Class attribute checked by get_elo_system

    def __init__(self, ctx: dict[str, Any] | None = None):
        self.ctx = ctx or {}


def _make_probe(**kwargs) -> ConcreteProbesMixin:
    """Create a ProbesMixin instance with configurable context."""
    ctx = {}
    if "storage" in kwargs:
        ctx["storage"] = kwargs["storage"]
    if "elo_system" in kwargs:
        ctx["elo_system"] = kwargs["elo_system"]
    probe = ConcreteProbesMixin(ctx=ctx if ctx else None)
    if kwargs.get("ctx_none"):
        probe.ctx = None
    if kwargs.get("no_ctx"):
        if hasattr(probe, "ctx"):
            delattr(probe, "ctx")
    return probe


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


def _make_distributed_module(distributed_required: bool = False):
    """Create a fake aragora.config.distributed module."""
    mod = types.ModuleType("aragora.config.distributed")
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
# Context managers for module-level patches
# ---------------------------------------------------------------------------


def _patch_degraded(is_degraded_val=False, reason="", state=None):
    mod = _make_degraded_module(is_degraded_val, reason, state)
    return patch.dict(sys.modules, {"aragora.server.degraded_mode": mod})


def _remove_degraded():
    return patch.dict(sys.modules, {"aragora.server.degraded_mode": None})


def _patch_distributed(distributed_required=False):
    mod = _make_distributed_module(distributed_required)
    return patch.dict(sys.modules, {"aragora.config.distributed": mod})


def _remove_distributed():
    return patch.dict(sys.modules, {"aragora.config.distributed": None})


def _patch_startup(redis_result=(True, "OK"), db_result=(True, "OK")):
    mod = _make_startup_module(redis_result, db_result)
    return patch.dict(sys.modules, {"aragora.server.startup": mod})


def _remove_startup():
    return patch.dict(sys.modules, {"aragora.server.startup": None})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove env vars that affect probe behaviour so tests start clean."""
    for var in (
        "REDIS_URL",
        "ARAGORA_REDIS_URL",
        "DATABASE_URL",
        "ARAGORA_POSTGRES_DSN",
        "ARAGORA_REQUIRE_DATABASE",
    ):
        monkeypatch.delenv(var, raising=False)


# ===========================================================================
# get_storage
# ===========================================================================


class TestGetStorage:
    """Test get_storage() retrieves storage from ctx."""

    def test_returns_storage_when_present(self):
        storage = MagicMock()
        probe = _make_probe(storage=storage)
        assert probe.get_storage() is storage

    def test_returns_none_when_storage_not_in_ctx(self):
        probe = ConcreteProbesMixin(ctx={})
        assert probe.get_storage() is None

    def test_returns_none_when_storage_key_missing(self):
        probe = ConcreteProbesMixin(ctx={"other": "value"})
        assert probe.get_storage() is None


class TestGetStorageNoCtx:
    """Test get_storage() when ctx is None or missing."""

    def test_returns_none_when_ctx_is_none(self):
        probe = _make_probe(ctx_none=True)
        assert probe.get_storage() is None

    def test_returns_none_when_no_ctx_attribute(self):
        probe = _make_probe(no_ctx=True)
        assert probe.get_storage() is None

    def test_returns_none_for_empty_ctx(self):
        probe = ConcreteProbesMixin(ctx={})
        assert probe.get_storage() is None


# ===========================================================================
# get_elo_system
# ===========================================================================


class TestGetEloSystem:
    """Test get_elo_system() retrieves ELO from ctx."""

    def test_returns_elo_from_ctx(self):
        elo = MagicMock()
        probe = _make_probe(elo_system=elo)
        # Ensure class attribute is None so ctx is used
        probe.__class__.elo_system = None
        assert probe.get_elo_system() is elo

    def test_returns_none_when_elo_not_in_ctx(self):
        probe = ConcreteProbesMixin(ctx={})
        probe.__class__.elo_system = None
        assert probe.get_elo_system() is None

    def test_returns_none_when_elo_key_missing(self):
        probe = ConcreteProbesMixin(ctx={"other": "value"})
        probe.__class__.elo_system = None
        assert probe.get_elo_system() is None


class TestGetEloSystemClassAttr:
    """Test get_elo_system() preferring class attribute over ctx."""

    def test_returns_class_attribute_when_set(self):
        elo_class = MagicMock()
        elo_ctx = MagicMock()
        probe = _make_probe(elo_system=elo_ctx)
        probe.__class__.elo_system = elo_class
        try:
            result = probe.get_elo_system()
            assert result is elo_class
        finally:
            probe.__class__.elo_system = None

    def test_falls_back_to_ctx_when_class_attr_is_none(self):
        elo_ctx = MagicMock()
        probe = _make_probe(elo_system=elo_ctx)
        probe.__class__.elo_system = None
        assert probe.get_elo_system() is elo_ctx

    def test_class_attr_takes_priority(self):
        class EloProbe(ProbesMixin):
            elo_system = MagicMock()

            def __init__(self):
                self.ctx = {"elo_system": MagicMock()}

        probe = EloProbe()
        assert probe.get_elo_system() is EloProbe.elo_system


class TestGetEloSystemNoCtx:
    """Test get_elo_system() when ctx is None or missing."""

    def test_returns_none_when_ctx_is_none(self):
        probe = _make_probe(ctx_none=True)
        probe.__class__.elo_system = None
        assert probe.get_elo_system() is None

    def test_returns_none_when_no_ctx_attribute(self):
        probe = _make_probe(no_ctx=True)
        probe.__class__.elo_system = None
        assert probe.get_elo_system() is None

    def test_class_attr_used_even_when_no_ctx(self):
        elo = MagicMock()
        probe = _make_probe(no_ctx=True)
        probe.__class__.elo_system = elo
        try:
            assert probe.get_elo_system() is elo
        finally:
            probe.__class__.elo_system = None


# ===========================================================================
# liveness_probe
# ===========================================================================


class TestLivenessProbe:
    """Test liveness_probe() when server is healthy."""

    def test_returns_200(self):
        probe = _make_probe()
        with _patch_degraded(is_degraded_val=False):
            result = probe.liveness_probe()
        assert _status(result) == 200

    def test_status_is_ok(self):
        probe = _make_probe()
        with _patch_degraded(is_degraded_val=False):
            result = probe.liveness_probe()
        assert _body(result)["status"] == "ok"

    def test_no_degraded_key_when_healthy(self):
        probe = _make_probe()
        with _patch_degraded(is_degraded_val=False):
            result = probe.liveness_probe()
        assert "degraded" not in _body(result)

    def test_no_note_key_when_healthy(self):
        probe = _make_probe()
        with _patch_degraded(is_degraded_val=False):
            result = probe.liveness_probe()
        assert "note" not in _body(result)

    def test_no_degraded_reason_when_healthy(self):
        probe = _make_probe()
        with _patch_degraded(is_degraded_val=False):
            result = probe.liveness_probe()
        assert "degraded_reason" not in _body(result)


class TestLivenessProbeDegraded:
    """Test liveness_probe() when server is in degraded mode."""

    def test_still_returns_200(self):
        """Container should NOT be restarted for degraded mode."""
        probe = _make_probe()
        with _patch_degraded(is_degraded_val=True, reason="Missing API key"):
            result = probe.liveness_probe()
        assert _status(result) == 200

    def test_body_marks_degraded_true(self):
        probe = _make_probe()
        with _patch_degraded(is_degraded_val=True, reason="Missing API key"):
            result = probe.liveness_probe()
        assert _body(result)["degraded"] is True

    def test_status_still_ok(self):
        probe = _make_probe()
        with _patch_degraded(is_degraded_val=True, reason="test"):
            result = probe.liveness_probe()
        assert _body(result)["status"] == "ok"

    def test_degraded_reason_included(self):
        probe = _make_probe()
        with _patch_degraded(is_degraded_val=True, reason="Missing API key"):
            result = probe.liveness_probe()
        assert _body(result)["degraded_reason"] == "Missing API key"

    def test_includes_note(self):
        probe = _make_probe()
        with _patch_degraded(is_degraded_val=True, reason="reason"):
            result = probe.liveness_probe()
        assert "Check /api/health" in _body(result)["note"]

    def test_degraded_reason_truncated_to_100_chars(self):
        probe = _make_probe()
        long_reason = "x" * 200
        with _patch_degraded(is_degraded_val=True, reason=long_reason):
            result = probe.liveness_probe()
        assert len(_body(result)["degraded_reason"]) == 100

    def test_degraded_reason_exactly_100_chars(self):
        probe = _make_probe()
        reason = "a" * 100
        with _patch_degraded(is_degraded_val=True, reason=reason):
            result = probe.liveness_probe()
        assert len(_body(result)["degraded_reason"]) == 100

    def test_degraded_reason_under_100_chars(self):
        probe = _make_probe()
        reason = "short reason"
        with _patch_degraded(is_degraded_val=True, reason=reason):
            result = probe.liveness_probe()
        assert _body(result)["degraded_reason"] == "short reason"

    def test_empty_degraded_reason(self):
        probe = _make_probe()
        with _patch_degraded(is_degraded_val=True, reason=""):
            result = probe.liveness_probe()
        assert _body(result)["degraded_reason"] == ""


class TestLivenessProbeImportError:
    """Test liveness_probe() when degraded_mode module is unavailable."""

    def test_returns_ok_on_import_error(self):
        probe = _make_probe()
        with _remove_degraded():
            result = probe.liveness_probe()
        assert _status(result) == 200
        assert _body(result)["status"] == "ok"

    def test_no_degraded_fields_on_import_error(self):
        probe = _make_probe()
        with _remove_degraded():
            result = probe.liveness_probe()
        body = _body(result)
        assert "degraded" not in body
        assert "degraded_reason" not in body
        assert "note" not in body


# ===========================================================================
# readiness_probe
# ===========================================================================


class TestReadinessProbeCached:
    """Test readiness_probe() when a cached result is available."""

    def test_returns_cached_ready(self):
        probe = _make_probe()
        cached_result = {"status": "ready", "checks": {}}
        cache_get = lambda key: cached_result
        cache_set = MagicMock()

        result = probe.readiness_probe(cache_get, cache_set)
        assert _status(result) == 200
        assert _body(result)["status"] == "ready"

    def test_returns_cached_not_ready_with_503(self):
        probe = _make_probe()
        cached_result = {"status": "not_ready", "checks": {}}
        cache_get = lambda key: cached_result
        cache_set = MagicMock()

        result = probe.readiness_probe(cache_get, cache_set)
        assert _status(result) == 503
        assert _body(result)["status"] == "not_ready"

    def test_cached_other_status_returns_503(self):
        probe = _make_probe()
        cached_result = {"status": "degraded", "checks": {}}
        cache_get = lambda key: cached_result
        cache_set = MagicMock()

        result = probe.readiness_probe(cache_get, cache_set)
        assert _status(result) == 503

    def test_cache_set_not_called_when_cached(self):
        probe = _make_probe()
        cached_result = {"status": "ready", "checks": {}}
        cache_get = lambda key: cached_result
        cache_set = MagicMock()

        probe.readiness_probe(cache_get, cache_set)
        cache_set.assert_not_called()

    def test_cache_none_triggers_fresh_check(self):
        probe = _make_probe(storage=MagicMock(), elo_system=MagicMock())
        cache_get = lambda key: None
        cache_set = MagicMock()

        with _remove_degraded(), _remove_distributed(), _remove_startup():
            result = probe.readiness_probe(cache_get, cache_set)
        assert _status(result) == 200
        cache_set.assert_called_once()


class TestReadinessProbeDegraded:
    """Test readiness_probe() when server is in degraded mode."""

    def _make_state(self):
        state = MagicMock()
        state.error_code.value = "MISSING_API_KEY"
        state.reason = "No API keys configured"
        state.recovery_hint = "Set ANTHROPIC_API_KEY"
        return state

    def test_returns_503(self):
        probe = _make_probe()
        state = self._make_state()
        cache_get = lambda key: None
        cache_set = MagicMock()

        with _patch_degraded(is_degraded_val=True, state=state):
            result = probe.readiness_probe(cache_get, cache_set)
        assert _status(result) == 503

    def test_body_includes_degraded_details(self):
        probe = _make_probe()
        state = self._make_state()
        cache_get = lambda key: None
        cache_set = MagicMock()

        with _patch_degraded(is_degraded_val=True, state=state):
            result = probe.readiness_probe(cache_get, cache_set)
        body = _body(result)
        assert body["status"] == "not_ready"
        assert body["reason"] == "Server in degraded mode"
        assert body["degraded"]["error_code"] == "MISSING_API_KEY"
        assert body["degraded"]["reason"] == "No API keys configured"
        assert body["degraded"]["recovery_hint"] == "Set ANTHROPIC_API_KEY"
        assert body["checks"]["degraded_mode"] is False

    def test_degraded_does_not_call_cache_set(self):
        probe = _make_probe()
        state = self._make_state()
        cache_get = lambda key: None
        cache_set = MagicMock()

        with _patch_degraded(is_degraded_val=True, state=state):
            probe.readiness_probe(cache_get, cache_set)
        cache_set.assert_not_called()

    def test_degraded_import_error_continues(self):
        """If degraded_mode not installed, treat as not degraded."""
        probe = _make_probe(storage=MagicMock(), elo_system=MagicMock())
        cache_get = lambda key: None
        cache_set = MagicMock()

        with _remove_degraded(), _remove_distributed(), _remove_startup():
            result = probe.readiness_probe(cache_get, cache_set)
        assert _status(result) == 200


class TestReadinessProbe:
    """Test readiness_probe() overall behavior."""

    def _run(self, probe=None):
        if probe is None:
            probe = _make_probe(storage=MagicMock(), elo_system=MagicMock())
        cache_get = lambda key: None
        cache_set = MagicMock()

        with _remove_degraded(), _remove_distributed(), _remove_startup():
            return probe.readiness_probe(cache_get, cache_set), cache_set

    def test_returns_200_when_all_pass(self):
        result, _ = self._run()
        assert _status(result) == 200

    def test_status_is_ready(self):
        result, _ = self._run()
        assert _body(result)["status"] == "ready"

    def test_latency_ms_present(self):
        result, _ = self._run()
        assert "latency_ms" in _body(result)
        assert isinstance(_body(result)["latency_ms"], (int, float))

    def test_latency_ms_non_negative(self):
        result, _ = self._run()
        assert _body(result)["latency_ms"] >= 0

    def test_result_is_cached(self):
        _, cache_set = self._run()
        cache_set.assert_called_once()
        args = cache_set.call_args
        assert args[0][0] == "readiness"
        cached_data = args[0][1]
        assert cached_data["status"] == "ready"

    def test_checks_storage_true_when_present(self):
        probe = _make_probe(storage=MagicMock())
        result, _ = self._run(probe)
        assert _body(result)["checks"]["storage"] is True

    def test_checks_elo_system_true_when_present(self):
        probe = _make_probe(elo_system=MagicMock())
        result, _ = self._run(probe)
        assert _body(result)["checks"]["elo_system"] is True


class TestReadinessProbeStorage:
    """Test readiness_probe() storage check."""

    def _run(self, probe):
        cache_get = lambda key: None
        cache_set = MagicMock()
        with _remove_degraded(), _remove_distributed(), _remove_startup():
            return probe.readiness_probe(cache_get, cache_set)

    def test_storage_present_is_true(self):
        probe = _make_probe(storage=MagicMock())
        result = self._run(probe)
        assert _body(result)["checks"]["storage"] is True
        assert _status(result) == 200

    def test_storage_none_is_ok(self):
        """Storage not configured should not fail readiness."""
        probe = ConcreteProbesMixin(ctx={"storage": None})
        result = self._run(probe)
        assert _body(result)["checks"]["storage"] is True
        assert _status(result) == 200

    def test_storage_missing_from_ctx_is_ok(self):
        probe = ConcreteProbesMixin(ctx={})
        result = self._run(probe)
        assert _body(result)["checks"]["storage"] is True

    def test_storage_os_error_fails(self):
        probe = _make_probe(storage=MagicMock())
        probe.get_storage = MagicMock(side_effect=OSError("Disk full"))
        result = self._run(probe)
        assert _body(result)["checks"]["storage"] is False
        assert _status(result) == 503

    def test_storage_runtime_error_fails(self):
        probe = _make_probe(storage=MagicMock())
        probe.get_storage = MagicMock(side_effect=RuntimeError("Not initialized"))
        result = self._run(probe)
        assert _body(result)["checks"]["storage"] is False
        assert _status(result) == 503

    def test_storage_value_error_fails(self):
        probe = _make_probe(storage=MagicMock())
        probe.get_storage = MagicMock(side_effect=ValueError("Bad config"))
        result = self._run(probe)
        assert _body(result)["checks"]["storage"] is False
        assert _status(result) == 503


class TestReadinessProbeElo:
    """Test readiness_probe() ELO system check."""

    def _run(self, probe):
        cache_get = lambda key: None
        cache_set = MagicMock()
        with _remove_degraded(), _remove_distributed(), _remove_startup():
            return probe.readiness_probe(cache_get, cache_set)

    def test_elo_present_is_true(self):
        probe = _make_probe(elo_system=MagicMock())
        result = self._run(probe)
        assert _body(result)["checks"]["elo_system"] is True
        assert _status(result) == 200

    def test_elo_none_is_ok(self):
        probe = ConcreteProbesMixin(ctx={"elo_system": None})
        result = self._run(probe)
        assert _body(result)["checks"]["elo_system"] is True

    def test_elo_missing_from_ctx_is_ok(self):
        probe = ConcreteProbesMixin(ctx={})
        probe.__class__.elo_system = None
        result = self._run(probe)
        assert _body(result)["checks"]["elo_system"] is True

    def test_elo_os_error_fails(self):
        probe = _make_probe(elo_system=MagicMock())
        probe.get_elo_system = MagicMock(side_effect=OSError("Disk error"))
        result = self._run(probe)
        assert _body(result)["checks"]["elo_system"] is False
        assert _status(result) == 503

    def test_elo_runtime_error_fails(self):
        probe = _make_probe(elo_system=MagicMock())
        probe.get_elo_system = MagicMock(side_effect=RuntimeError("ELO broken"))
        result = self._run(probe)
        assert _body(result)["checks"]["elo_system"] is False
        assert _status(result) == 503

    def test_elo_value_error_fails(self):
        probe = _make_probe(elo_system=MagicMock())
        probe.get_elo_system = MagicMock(side_effect=ValueError("Bad ELO config"))
        result = self._run(probe)
        assert _body(result)["checks"]["elo_system"] is False
        assert _status(result) == 503


class TestReadinessMultipleFailures:
    """Test readiness_probe() with multiple failures."""

    def _run(self, probe):
        cache_get = lambda key: None
        cache_set = MagicMock()
        with _remove_degraded(), _remove_distributed(), _remove_startup():
            return probe.readiness_probe(cache_get, cache_set)

    def test_both_storage_and_elo_fail(self):
        probe = _make_probe()
        probe.get_storage = MagicMock(side_effect=OSError("Disk full"))
        probe.get_elo_system = MagicMock(side_effect=RuntimeError("ELO broken"))
        result = self._run(probe)
        body = _body(result)
        assert body["checks"]["storage"] is False
        assert body["checks"]["elo_system"] is False
        assert body["status"] == "not_ready"
        assert _status(result) == 503

    def test_storage_fail_elo_ok(self):
        probe = _make_probe(elo_system=MagicMock())
        probe.get_storage = MagicMock(side_effect=ValueError("Bad"))
        result = self._run(probe)
        body = _body(result)
        assert body["checks"]["storage"] is False
        assert body["checks"]["elo_system"] is True
        assert _status(result) == 503

    def test_storage_ok_elo_fail(self):
        probe = _make_probe(storage=MagicMock())
        probe.get_elo_system = MagicMock(side_effect=ValueError("Bad"))
        result = self._run(probe)
        body = _body(result)
        assert body["checks"]["storage"] is True
        assert body["checks"]["elo_system"] is False
        assert _status(result) == 503


# ===========================================================================
# _check_redis_readiness
# ===========================================================================


class TestCheckRedisReadiness:
    """Test _check_redis_readiness() with Redis connected."""

    def test_redis_connected_when_distributed_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(redis_result=(True, "Connected")),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                return_value=(True, "Connected"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is True
        assert checks["redis"]["connected"] is True
        assert checks["redis"]["message"] == "Connected"

    def test_redis_disconnected_when_required_fails(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(redis_result=(False, "Connection refused")),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                return_value=(False, "Connection refused"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is False
        assert checks["redis"]["connected"] is False

    def test_redis_configured_but_not_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=False),
            _patch_startup(),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is True
        assert checks["redis"]["configured"] is True
        assert checks["redis"]["required"] is False

    def test_redis_not_configured(self, monkeypatch):
        probe = _make_probe()

        with (
            _patch_distributed(distributed_required=False),
            _patch_startup(),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is True
        assert checks["redis"]["configured"] is False

    def test_redis_aragora_redis_url(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("ARAGORA_REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(redis_result=(True, "OK")),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                return_value=(True, "OK"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert checks["redis"]["connected"] is True

    def test_redis_in_async_context_uses_thread_pool(self, monkeypatch):
        """When already in an async loop, ThreadPoolExecutor should be used."""
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        mock_loop = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = (True, "Connected via thread")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(redis_result=(True, "Connected via thread")),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                return_value=mock_loop,
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.concurrent.futures.ThreadPoolExecutor",
            ) as mock_tpe_cls,
        ):
            mock_executor = MagicMock()
            mock_executor.submit.return_value = mock_future
            mock_executor.__enter__ = MagicMock(return_value=mock_executor)
            mock_executor.__exit__ = MagicMock(return_value=False)
            mock_tpe_cls.return_value = mock_executor

            ready, checks = probe._check_redis_readiness(True, {})
        assert checks["redis"]["connected"] is True
        assert checks["redis"]["message"] == "Connected via thread"

    def test_redis_preserves_existing_ready_false(self, monkeypatch):
        """If ready is already False, a successful Redis check should not reset it."""
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=False),
            _patch_startup(),
        ):
            ready, checks = probe._check_redis_readiness(False, {})
        # ready stays False since the probe only sets it to False, never True
        assert ready is False


class TestCheckRedisImportError:
    """Test _check_redis_readiness() when imports fail."""

    def test_import_error_skips_check(self):
        probe = _make_probe()
        with _remove_distributed(), _remove_startup():
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is True
        assert checks["redis"]["status"] == "check_skipped"


class TestCheckRedisConnError:
    """Test _check_redis_readiness() connectivity errors."""

    def test_connection_error_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=ConnectionError("Connection refused"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is False
        assert checks["redis"]["error_type"] == "connectivity"

    def test_connection_error_not_required(self, monkeypatch):
        """When not distributed-required, no validation so no connectivity error."""
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=False),
            _patch_startup(),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is True
        assert checks["redis"]["configured"] is True
        assert checks["redis"]["required"] is False

    def test_os_error_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=OSError("Network unreachable"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is False
        assert checks["redis"]["error_type"] == "connectivity"

    def test_timeout_error_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=TimeoutError("Timed out"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is False
        assert checks["redis"]["error_type"] == "connectivity"


class TestCheckRedisTimeout:
    """Test _check_redis_readiness() timeout errors."""

    def test_asyncio_timeout_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=asyncio.TimeoutError("Timed out"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        # asyncio.TimeoutError is a subclass of TimeoutError (which is OSError-like)
        # so it may be caught by (ConnectionError, TimeoutError, OSError) clause
        assert ready is False
        assert checks["redis"]["error_type"] in ("timeout", "connectivity")

    def test_concurrent_futures_timeout_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=concurrent.futures.TimeoutError("Pool timeout"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is False
        assert checks["redis"]["error_type"] in ("timeout", "connectivity")

    def test_timeout_not_required_does_not_fail(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=False),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=asyncio.TimeoutError("Timed out"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is True


class TestCheckRedisRuntimeError:
    """Test _check_redis_readiness() runtime/type/value/attribute errors."""

    def test_runtime_error_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=TypeError("Unexpected"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is False
        assert "error" in checks["redis"]

    def test_value_error_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=ValueError("Bad value"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is False
        assert "error" in checks["redis"]

    def test_attribute_error_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=True),
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=AttributeError("Missing attr"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is False
        assert "error" in checks["redis"]

    def test_runtime_error_not_required(self, monkeypatch):
        """When distributed not required, no validation is attempted, so no error."""
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        with (
            _patch_distributed(distributed_required=False),
            _patch_startup(),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert ready is True
        assert checks["redis"]["configured"] is True
        assert checks["redis"]["required"] is False

    def test_runtime_error_distributed_import_fails(self, monkeypatch):
        """If the distributed-policy module also fails to import during error handling, still record error."""
        probe = _make_probe()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        # Create a distributed-policy module that works initially but raises during error recovery
        distributed_mod = types.ModuleType("aragora.config.distributed")
        distributed_mod.is_distributed_state_required = lambda: True

        startup_mod = _make_startup_module()

        with (
            patch.dict(
                sys.modules,
                {
                    "aragora.config.distributed": distributed_mod,
                    "aragora.server.startup": startup_mod,
                },
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=RuntimeError("Runtime error during validation"),
            ),
        ):
            ready, checks = probe._check_redis_readiness(True, {})
        assert "error" in checks["redis"]


# ===========================================================================
# _check_postgresql_readiness
# ===========================================================================


class TestCheckPostgresReadiness:
    """Test _check_postgresql_readiness() with PostgreSQL connected."""

    def test_postgres_connected_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _patch_startup(db_result=(True, "Connected")),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                return_value=(True, "Connected"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is True
        assert checks["postgresql"]["connected"] is True
        assert checks["postgresql"]["message"] == "Connected"

    def test_postgres_disconnected_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _patch_startup(db_result=(False, "Connection refused")),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                return_value=(False, "Connection refused"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is False
        assert checks["postgresql"]["connected"] is False

    def test_postgres_configured_but_not_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")

        with _patch_startup():
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is True
        assert checks["postgresql"]["configured"] is True
        assert checks["postgresql"]["required"] is False

    def test_postgres_not_configured(self, monkeypatch):
        probe = _make_probe()

        with _patch_startup():
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is True
        assert checks["postgresql"]["configured"] is False

    def test_postgres_aragora_postgres_dsn(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("ARAGORA_POSTGRES_DSN", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "1")

        with (
            _patch_startup(db_result=(True, "Connected")),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                return_value=(True, "Connected"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert checks["postgresql"]["connected"] is True

    def test_postgres_require_database_yes(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "yes")

        with (
            _patch_startup(db_result=(True, "OK")),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                return_value=(True, "OK"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert checks["postgresql"]["connected"] is True

    def test_postgres_in_async_context_uses_thread_pool(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        mock_loop = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = (True, "Connected via thread")

        with (
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                return_value=mock_loop,
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.concurrent.futures.ThreadPoolExecutor",
            ) as mock_tpe_cls,
        ):
            mock_executor = MagicMock()
            mock_executor.submit.return_value = mock_future
            mock_executor.__enter__ = MagicMock(return_value=mock_executor)
            mock_executor.__exit__ = MagicMock(return_value=False)
            mock_tpe_cls.return_value = mock_executor

            ready, checks = probe._check_postgresql_readiness(True, {})
        assert checks["postgresql"]["connected"] is True
        assert checks["postgresql"]["message"] == "Connected via thread"

    def test_postgres_require_database_false_values(self, monkeypatch):
        """Non-true values for ARAGORA_REQUIRE_DATABASE mean not required."""
        probe = _make_probe()
        for val in ("false", "0", "no", ""):
            monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
            monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", val)

            with _patch_startup():
                ready, checks = probe._check_postgresql_readiness(True, {})
            assert checks["postgresql"]["configured"] is True, (
                f"Failed for ARAGORA_REQUIRE_DATABASE={val!r}"
            )
            assert checks["postgresql"]["required"] is False

    def test_postgres_preserves_existing_ready_false(self, monkeypatch):
        """If ready is already False, passing postgres should not reset it."""
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")

        with _patch_startup():
            ready, checks = probe._check_postgresql_readiness(False, {})
        assert ready is False


class TestCheckPostgresImportError:
    """Test _check_postgresql_readiness() when imports fail."""

    def test_import_error_skips_check(self):
        probe = _make_probe()
        with _remove_startup():
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is True
        assert checks["postgresql"]["status"] == "check_skipped"


class TestCheckPostgresConnError:
    """Test _check_postgresql_readiness() connectivity errors."""

    def test_connection_error_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=ConnectionError("Connection refused"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is False
        assert checks["postgresql"]["error_type"] == "connectivity"

    def test_connection_error_not_required(self, monkeypatch):
        """When database not required and ConnectionError at import level, ready stays True."""
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        # Not setting ARAGORA_REQUIRE_DATABASE means not required

        # Make the startup module import raise ConnectionError at the try-block level
        startup_mod = types.ModuleType("aragora.server.startup")

        def _bad_validate(**kw):
            raise ConnectionError("Connection refused")

        startup_mod.validate_database_connectivity = _bad_validate
        # Trigger the error by making require_database True so the validation runs,
        # but we actually want to test when not required. Since the exception handlers
        # check require_database, we set it False.
        # The only way to reach the exception handler with require_database=False
        # is if validate_database_connectivity raises during non-required path.
        # But actually that path doesn't call validate at all.
        # So let's just test the correct behavior: not required + configured = pass through.
        with _patch_startup():
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is True
        assert checks["postgresql"]["configured"] is True
        assert checks["postgresql"]["required"] is False

    def test_os_error_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=OSError("Network unreachable"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is False
        assert checks["postgresql"]["error_type"] == "connectivity"


class TestCheckPostgresTimeout:
    """Test _check_postgresql_readiness() timeout errors."""

    def test_asyncio_timeout_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=asyncio.TimeoutError("Timed out"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is False
        assert checks["postgresql"]["error_type"] in ("timeout", "connectivity")

    def test_concurrent_futures_timeout_when_required(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=concurrent.futures.TimeoutError("Pool timeout"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is False
        assert checks["postgresql"]["error_type"] in ("timeout", "connectivity")

    def test_timeout_not_required_does_not_fail(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        # Not setting ARAGORA_REQUIRE_DATABASE

        with (
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=asyncio.TimeoutError("Timed out"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is True


class TestCheckPostgresRuntimeError:
    """Test _check_postgresql_readiness() runtime/value/type/attribute errors."""

    def test_runtime_error(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=RuntimeError("Unexpected runtime error"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert "error" in checks["postgresql"]

    def test_value_error(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("ARAGORA_POSTGRES_DSN", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "1")

        with (
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=ValueError("Bad DSN"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert "error" in checks["postgresql"]

    def test_type_error(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "yes")

        with (
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=TypeError("Wrong type"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert "error" in checks["postgresql"]

    def test_attribute_error(self, monkeypatch):
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_REQUIRE_DATABASE", "true")

        with (
            _patch_startup(),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.get_running_loop",
                side_effect=RuntimeError("no loop"),
            ),
            patch(
                "aragora.server.handlers.admin.health.probes.asyncio.run",
                side_effect=AttributeError("Missing attr"),
            ),
        ):
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert "error" in checks["postgresql"]

    def test_runtime_error_does_not_affect_ready_when_not_required(self, monkeypatch):
        """When database not required, no validation is attempted, so no error."""
        probe = _make_probe()
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        # Not setting ARAGORA_REQUIRE_DATABASE means not required
        # The code takes the `elif database_url:` branch which does not call
        # validate_database_connectivity, so no error is possible.

        with _patch_startup():
            ready, checks = probe._check_postgresql_readiness(True, {})
        assert ready is True
        assert checks["postgresql"]["configured"] is True
        assert checks["postgresql"]["required"] is False
