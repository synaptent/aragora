"""Tests for parallel init connectivity gate (Gap 2).

Verifies that _check_connectivity_gate() in ParallelInitializer correctly
gates Phase 2 based on ARAGORA_REQUIRE_DATABASE / ARAGORA_REQUIRE_REDIS
environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest


@dataclass
class FakeInitTask:
    name: str
    error: Exception | None = None
    result: Any = None


@dataclass
class FakePhaseResult:
    name: str = "connections"
    tasks: list[Any] = field(default_factory=list)
    success: bool = True
    duration_ms: float = 100.0


@pytest.fixture
def initializer():
    """Create a ParallelInitializer with default config."""
    from aragora.server.startup.parallel import ParallelInitializer

    return ParallelInitializer(
        nomic_dir="/tmp/nomic",
        stream_emitter=None,
        graceful_degradation=True,
    )


class TestConnectivityGate:
    """Test _check_connectivity_gate behavior."""

    def test_gate_passes_with_no_requirements(self, initializer):
        """No env vars set = gate passes regardless of task results."""
        phase1 = FakePhaseResult(
            tasks=[
                FakeInitTask(name="postgres_pool", error=RuntimeError("down")),
                FakeInitTask(name="redis", error=RuntimeError("down")),
            ]
        )
        with patch.dict("os.environ", {}, clear=True):
            assert initializer._check_connectivity_gate(phase1) is True

    def test_gate_fails_when_db_required_and_failed(self, initializer):
        """ARAGORA_REQUIRE_DATABASE=true + DB failure = gate fails."""
        phase1 = FakePhaseResult(
            tasks=[
                FakeInitTask(name="postgres_pool", error=RuntimeError("connection refused")),
                FakeInitTask(name="redis"),
            ]
        )
        with patch.dict("os.environ", {"ARAGORA_REQUIRE_DATABASE": "true"}, clear=True):
            assert initializer._check_connectivity_gate(phase1) is False

    def test_gate_passes_when_db_required_and_succeeded(self, initializer):
        """ARAGORA_REQUIRE_DATABASE=true + DB success = gate passes."""
        phase1 = FakePhaseResult(
            tasks=[
                FakeInitTask(name="postgres_pool", error=None),
                FakeInitTask(name="redis"),
            ]
        )
        with patch.dict("os.environ", {"ARAGORA_REQUIRE_DATABASE": "true"}, clear=True):
            assert initializer._check_connectivity_gate(phase1) is True

    def test_gate_fails_when_redis_required_and_failed(self, initializer):
        """ARAGORA_REQUIRE_REDIS=true + Redis failure = gate fails."""
        phase1 = FakePhaseResult(
            tasks=[
                FakeInitTask(name="postgres_pool"),
                FakeInitTask(name="redis", error=ConnectionError("refused")),
            ]
        )
        with patch.dict("os.environ", {"ARAGORA_REQUIRE_REDIS": "true"}, clear=True):
            assert initializer._check_connectivity_gate(phase1) is False

    def test_gate_passes_when_redis_required_and_succeeded(self, initializer):
        """ARAGORA_REQUIRE_REDIS=true + Redis success = gate passes."""
        phase1 = FakePhaseResult(
            tasks=[
                FakeInitTask(name="postgres_pool"),
                FakeInitTask(name="redis", error=None),
            ]
        )
        with patch.dict("os.environ", {"ARAGORA_REQUIRE_REDIS": "true"}, clear=True):
            assert initializer._check_connectivity_gate(phase1) is True

    def test_gate_both_required_both_failed(self, initializer):
        """Both backends required and both failed = gate fails."""
        phase1 = FakePhaseResult(
            tasks=[
                FakeInitTask(name="postgres_pool", error=RuntimeError("down")),
                FakeInitTask(name="redis", error=ConnectionError("down")),
            ]
        )
        env = {"ARAGORA_REQUIRE_DATABASE": "true", "ARAGORA_REQUIRE_REDIS": "true"}
        with patch.dict("os.environ", env, clear=True):
            assert initializer._check_connectivity_gate(phase1) is False

    def test_gate_enters_degraded_mode_on_failure(self, initializer):
        """When graceful_degradation=True, gate failure calls set_degraded."""
        phase1 = FakePhaseResult(
            tasks=[
                FakeInitTask(name="postgres_pool", error=RuntimeError("refused")),
            ]
        )
        with patch.dict("os.environ", {"ARAGORA_REQUIRE_DATABASE": "true"}, clear=True):
            with patch("aragora.server.degraded_mode.set_degraded") as mock_degrade:
                result = initializer._check_connectivity_gate(phase1)
                assert result is False
                mock_degrade.assert_called_once_with(
                    "Required backend(s) failed: postgres_pool: refused",
                    error_code="DATABASE_UNAVAILABLE",
                    recovery_hint="Check database/Redis connectivity and restart.",
                )

    def test_gate_sets_redis_error_code_when_only_redis_failed(self, initializer):
        """Redis-only failures should expose a Redis-specific degraded code."""
        phase1 = FakePhaseResult(
            tasks=[
                FakeInitTask(name="postgres_pool"),
                FakeInitTask(name="redis", error=ConnectionError("refused")),
            ]
        )
        with patch.dict("os.environ", {"ARAGORA_REQUIRE_REDIS": "true"}, clear=True):
            with patch("aragora.server.degraded_mode.set_degraded") as mock_degrade:
                result = initializer._check_connectivity_gate(phase1)
                assert result is False
                mock_degrade.assert_called_once_with(
                    "Required backend(s) failed: redis: refused",
                    error_code="REDIS_UNAVAILABLE",
                    recovery_hint="Check database/Redis connectivity and restart.",
                )

    def test_strict_mode_raises_on_failure(self):
        """When graceful_degradation=False, parallel init returns failure."""
        from aragora.server.startup.parallel import ParallelInitializer

        init = ParallelInitializer(
            nomic_dir="/tmp",
            stream_emitter=None,
            graceful_degradation=False,
        )
        phase1 = FakePhaseResult(
            tasks=[
                FakeInitTask(name="postgres_pool", error=RuntimeError("down")),
            ]
        )
        with patch.dict("os.environ", {"ARAGORA_REQUIRE_DATABASE": "true"}, clear=True):
            assert init._check_connectivity_gate(phase1) is False

    def test_distributed_state_implicitly_requires_redis(self, initializer):
        """is_distributed_state_required() implicitly requires Redis."""
        phase1 = FakePhaseResult(
            tasks=[
                FakeInitTask(name="postgres_pool"),
                FakeInitTask(name="redis", error=ConnectionError("refused")),
            ]
        )
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=True,
            ):
                assert initializer._check_connectivity_gate(phase1) is False
