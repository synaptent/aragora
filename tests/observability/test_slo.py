"""
Tests for SLO (Service Level Objective) module.

Tests SLO definitions, compliance calculations, and alerting.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import os

import pytest

from aragora.observability import slo as slo_module
from aragora.observability.slo import (
    DEFAULT_AVAILABILITY_TARGET,
    DEFAULT_DEBATE_SUCCESS_TARGET,
    DEFAULT_LATENCY_P99_MS,
    SLOBreach,
    SLOResult,
    SLOStatus,
    SLOTarget,
    create_notification_callback,
    get_slo_targets,
    _calculate_error_budget,
)


class TestSLOTarget:
    """Tests for SLOTarget dataclass."""

    def test_target_creation(self):
        """SLO targets are created correctly."""
        target = SLOTarget(
            name="Test SLO",
            target=0.99,
            unit="ratio",
            description="Test description",
        )

        assert target.name == "Test SLO"
        assert target.target == 0.99
        assert target.unit == "ratio"
        assert target.comparison == "gte"  # Default

    def test_target_with_lte_comparison(self):
        """SLO targets can use lte comparison."""
        target = SLOTarget(
            name="Latency",
            target=0.5,
            unit="seconds",
            description="Latency target",
            comparison="lte",
        )

        assert target.comparison == "lte"


class TestSLOResult:
    """Tests for SLOResult dataclass."""

    def test_result_compliant(self):
        """Compliant SLO result is created correctly."""
        now = datetime.now(timezone.utc)
        result = SLOResult(
            name="Availability",
            target=0.999,
            current=0.9995,
            compliant=True,
            compliance_percentage=99.95,
            window_start=now - timedelta(hours=24),
            window_end=now,
            error_budget_remaining=50.0,
            burn_rate=0.5,
        )

        assert result.compliant is True
        assert result.compliance_percentage == 99.95
        assert result.error_budget_remaining == 50.0

    def test_result_non_compliant(self):
        """Non-compliant SLO result is created correctly."""
        now = datetime.now(timezone.utc)
        result = SLOResult(
            name="Availability",
            target=0.999,
            current=0.99,
            compliant=False,
            compliance_percentage=99.0,
            window_start=now - timedelta(hours=24),
            window_end=now,
            error_budget_remaining=-100.0,
            burn_rate=2.0,
        )

        assert result.compliant is False
        assert result.error_budget_remaining < 0


class TestSLOStatus:
    """Tests for SLOStatus dataclass."""

    def _create_result(self, name: str, compliant: bool) -> SLOResult:
        """Helper to create test results."""
        now = datetime.now(timezone.utc)
        return SLOResult(
            name=name,
            target=0.99,
            current=0.995 if compliant else 0.95,
            compliant=compliant,
            compliance_percentage=99.5 if compliant else 95.0,
            window_start=now - timedelta(hours=24),
            window_end=now,
            error_budget_remaining=50.0 if compliant else -50.0,
            burn_rate=0.5 if compliant else 2.0,
        )

    def test_status_all_healthy(self):
        """Status is healthy when all SLOs are compliant."""
        status = SLOStatus(
            availability=self._create_result("availability", True),
            latency_p99=self._create_result("latency", True),
            debate_success=self._create_result("debate", True),
        )

        assert status.overall_healthy is True

    def test_status_unhealthy_availability(self):
        """Status is unhealthy when availability fails."""
        status = SLOStatus(
            availability=self._create_result("availability", False),
            latency_p99=self._create_result("latency", True),
            debate_success=self._create_result("debate", True),
        )

        assert status.overall_healthy is False

    def test_status_unhealthy_latency(self):
        """Status is unhealthy when latency fails."""
        status = SLOStatus(
            availability=self._create_result("availability", True),
            latency_p99=self._create_result("latency", False),
            debate_success=self._create_result("debate", True),
        )

        assert status.overall_healthy is False

    def test_status_unhealthy_debate_success(self):
        """Status is unhealthy when debate success fails."""
        status = SLOStatus(
            availability=self._create_result("availability", True),
            latency_p99=self._create_result("latency", True),
            debate_success=self._create_result("debate", False),
        )

        assert status.overall_healthy is False


class TestDefaultTargets:
    """Tests for default SLO target values."""

    def test_default_availability_target(self):
        """Default availability is 99.9%."""
        assert DEFAULT_AVAILABILITY_TARGET == 0.999

    def test_default_latency_target(self):
        """Default p99 latency is 2000ms."""
        assert DEFAULT_LATENCY_P99_MS == 2000

    def test_default_debate_success_target(self):
        """Default debate success is 95%."""
        assert DEFAULT_DEBATE_SUCCESS_TARGET == 0.95


class TestGetSLOTargets:
    """Tests for get_slo_targets function."""

    def test_returns_default_targets(self):
        """Returns default targets when no env vars set."""
        with patch.dict(os.environ, {}, clear=True):
            targets = get_slo_targets()

            assert "availability" in targets
            assert "latency_p99" in targets
            assert "debate_success" in targets

            assert targets["availability"].target == 0.999
            assert targets["latency_p99"].target == 2.0  # 2000ms in seconds
            assert targets["debate_success"].target == 0.95

    def test_overrides_from_env(self):
        """Environment variables override defaults."""
        env = {
            "SLO_AVAILABILITY_TARGET": "0.9999",
            "SLO_LATENCY_P99_TARGET_MS": "250",
            "SLO_DEBATE_SUCCESS_TARGET": "0.99",
        }

        with patch.dict(os.environ, env, clear=False):
            targets = get_slo_targets()

            assert targets["availability"].target == 0.9999
            assert targets["latency_p99"].target == 0.25  # 250ms in seconds
            assert targets["debate_success"].target == 0.99

    def test_target_descriptions(self):
        """Targets have appropriate descriptions."""
        targets = get_slo_targets()

        assert "successful requests" in targets["availability"].description.lower()
        assert "latency" in targets["latency_p99"].description.lower()
        assert "debate" in targets["debate_success"].description.lower()

    def test_target_units(self):
        """Targets have correct units."""
        targets = get_slo_targets()

        assert targets["availability"].unit == "ratio"
        assert targets["latency_p99"].unit == "seconds"
        assert targets["debate_success"].unit == "ratio"

    def test_target_comparisons(self):
        """Targets use correct comparisons."""
        targets = get_slo_targets()

        # Availability and success rate should be >= target
        assert targets["availability"].comparison == "gte"
        assert targets["debate_success"].comparison == "gte"

        # Latency should be <= target
        assert targets["latency_p99"].comparison == "lte"


class TestCalculateErrorBudget:
    """Tests for error budget calculation."""

    def test_error_budget_healthy(self):
        """Error budget is positive when meeting target."""
        remaining, burn_rate = _calculate_error_budget(
            target=0.999,
            current=0.9995,
            comparison="gte",
        )

        assert remaining > 0
        assert burn_rate < 1.0

    def test_error_budget_at_target(self):
        """Error budget at edge of target."""
        remaining, burn_rate = _calculate_error_budget(
            target=0.999,
            current=0.999,
            comparison="gte",
        )

        # Should be approximately 0% remaining
        assert remaining >= 0

    def test_error_budget_exceeded(self):
        """Error budget is zero when exceeding target."""
        remaining, burn_rate = _calculate_error_budget(
            target=0.999,
            current=0.99,
            comparison="gte",
        )

        # Budget is exhausted (clamped to 0, never negative)
        assert remaining == 0
        assert burn_rate > 1.0

    def test_error_budget_lte_comparison(self):
        """Error budget works for LTE comparisons (latency)."""
        # Good latency (below target)
        remaining, burn_rate = _calculate_error_budget(
            target=0.5,
            current=0.3,
            comparison="lte",
        )

        assert remaining > 0

        # Slightly bad latency (above target but within 50% error budget)
        remaining, burn_rate = _calculate_error_budget(
            target=0.5,
            current=0.7,
            comparison="lte",
        )

        # Budget partially consumed but not exhausted (error budget = 50% of target = 0.25)
        assert remaining > 0
        assert remaining < 100  # Some budget consumed

        # Very bad latency (exhausts error budget - overage >= 50% of target)
        remaining, burn_rate = _calculate_error_budget(
            target=0.5,
            current=0.8,  # Overage of 0.3 > error budget of 0.25
            comparison="lte",
        )

        # Budget is exhausted (clamped to 0, never negative)
        assert remaining == 0


class _RecordingNotificationSink:
    def __init__(self) -> None:
        self.breaches: list[SLOBreach] = []

    async def notify(self, breach: SLOBreach) -> None:
        self.breaches.append(breach)


def _make_breach() -> SLOBreach:
    return SLOBreach(
        slo_name="API Availability",
        severity="critical",
        current_value=0.975,
        target_value=0.999,
        error_budget_remaining=12.3,
        burn_rate=4.56,
        message="Availability below target",
    )


class TestNotificationCallback:
    """Tests for the observability-owned SLO notification contract."""

    @pytest.fixture(autouse=True)
    def _reset_notification_provider(self):
        register = getattr(slo_module, "register_slo_notification_sink_provider", None)
        if register is not None:
            register(None)
        yield
        if register is not None:
            register(None)

    def test_slo_module_has_no_control_plane_imports(self) -> None:
        source = Path(slo_module.__file__).read_text(encoding="utf-8")

        assert "aragora.control_plane.channels" not in source
        assert "aragora.control_plane.notifications" not in source

    @pytest.mark.asyncio
    async def test_resolves_registered_provider_on_every_invocation(self) -> None:
        first_sink = _RecordingNotificationSink()
        second_sink = _RecordingNotificationSink()
        sinks = iter((first_sink, second_sink))
        provider_calls = 0

        def provider():
            nonlocal provider_calls
            provider_calls += 1
            return next(sinks)

        slo_module.register_slo_notification_sink_provider(provider)
        callback = create_notification_callback()
        breach = _make_breach()

        await callback(breach)
        await callback(breach)

        assert provider_calls == 2
        assert first_sink.breaches == [breach]
        assert second_sink.breaches == [breach]

    @pytest.mark.asyncio
    async def test_missing_provider_is_fail_soft(self, caplog: pytest.LogCaptureFixture) -> None:
        slo_module.register_slo_notification_sink_provider(None)

        await create_notification_callback()(_make_breach())

        assert "Notification dispatcher not configured" in caplog.text

    @pytest.mark.asyncio
    async def test_provider_failure_is_fail_soft(self, caplog: pytest.LogCaptureFixture) -> None:
        def failing_provider():
            raise RuntimeError("dispatcher unavailable")

        slo_module.register_slo_notification_sink_provider(failing_provider)

        await create_notification_callback()(_make_breach())

        assert "Failed to dispatch notification" in caplog.text
