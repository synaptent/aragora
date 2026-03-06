"""Tests for aragora.nomic.cost_forecast module.

Covers:
- NomicCostEstimate / BudgetCheckResult dataclasses
- NomicCostForecaster.estimate_run_cost with/without historical data
- NomicCostForecaster.check_mid_run_budget at ok/warning/critical thresholds
- Budget overrun detection and warning messages
- AutonomousOrchestrator integration (opt-in wiring)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aragora.nomic.cost_forecast import (
    BudgetCheckResult,
    NomicCostEstimate,
    NomicCostForecaster,
)


# -----------------------------------------------------------------------
# Dataclass sanity
# -----------------------------------------------------------------------


class TestNomicCostEstimate:
    def test_defaults(self) -> None:
        est = NomicCostEstimate(
            estimated_total_usd=1.50,
            per_subtask_estimates={"s0": 0.75, "s1": 0.75},
        )
        assert est.estimated_total_usd == 1.50
        assert est.budget_limit is None
        assert est.projected_utilization_pct is None
        assert est.will_exceed_budget is False
        assert est.confidence == 0.5
        assert est.warning_message is None

    def test_with_budget_overrun(self) -> None:
        est = NomicCostEstimate(
            estimated_total_usd=3.0,
            per_subtask_estimates={"s0": 1.5, "s1": 1.5},
            budget_limit=2.0,
            projected_utilization_pct=150.0,
            will_exceed_budget=True,
            confidence=0.8,
            warning_message="over budget",
        )
        assert est.will_exceed_budget is True
        assert est.warning_message == "over budget"


class TestBudgetCheckResult:
    def test_ok_status(self) -> None:
        r = BudgetCheckResult(
            status="ok",
            spent_usd=0.5,
            projected_total_usd=1.0,
            budget_limit_usd=5.0,
            utilization_pct=20.0,
            message="healthy",
        )
        assert r.status == "ok"
        assert r.utilization_pct == 20.0


# -----------------------------------------------------------------------
# NomicCostForecaster — estimate_run_cost
# -----------------------------------------------------------------------


class TestEstimateRunCost:
    def test_basic_estimate_no_tracks(self) -> None:
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.10)
        est = forecaster.estimate_run_cost(subtask_count=5)
        # 5 subtasks * 0.10 * cycle_factor(sqrt(5) ~ 2.236)
        assert est.estimated_total_usd > 0
        assert len(est.per_subtask_estimates) == 5
        assert est.confidence == 0.5
        assert est.will_exceed_budget is False

    def test_estimate_with_tracks(self) -> None:
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.10)
        est = forecaster.estimate_run_cost(
            subtask_count=4,
            tracks=["sme", "core"],
        )
        # sme=0.8x, core=1.5x alternating
        assert len(est.per_subtask_estimates) == 4
        keys = list(est.per_subtask_estimates.keys())
        assert "sme" in keys[0]
        assert "core" in keys[1]

    def test_estimate_budget_exceeded(self) -> None:
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=1.00)
        est = forecaster.estimate_run_cost(
            subtask_count=10,
            budget_limit=2.0,
        )
        assert est.will_exceed_budget is True
        assert est.warning_message is not None
        assert "exceeds" in est.warning_message.lower()
        assert est.projected_utilization_pct is not None
        assert est.projected_utilization_pct > 100.0

    def test_estimate_budget_not_exceeded(self) -> None:
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.01)
        est = forecaster.estimate_run_cost(
            subtask_count=3,
            budget_limit=10.0,
        )
        assert est.will_exceed_budget is False
        assert est.projected_utilization_pct is not None
        assert est.projected_utilization_pct < 100.0

    def test_estimate_no_budget_limit(self) -> None:
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.20)
        est = forecaster.estimate_run_cost(subtask_count=5)
        assert est.budget_limit is None
        assert est.projected_utilization_pct is None
        assert est.will_exceed_budget is False

    def test_estimate_with_max_cycles_scaling(self) -> None:
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.10)
        est_1 = forecaster.estimate_run_cost(subtask_count=3, max_cycles=1)
        est_5 = forecaster.estimate_run_cost(subtask_count=3, max_cycles=5)
        # Higher max_cycles -> higher estimate (dampened via sqrt)
        assert est_5.estimated_total_usd > est_1.estimated_total_usd

    def test_estimate_zero_subtasks(self) -> None:
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.50)
        est = forecaster.estimate_run_cost(subtask_count=0)
        assert est.estimated_total_usd == 0.0
        assert len(est.per_subtask_estimates) == 0

    def test_estimate_with_historical_telemetry(self) -> None:
        """When telemetry has historical data, use it instead of default."""
        telemetry = MagicMock()
        telemetry.get_avg_cost_per_improvement.return_value = 0.25
        forecaster = NomicCostForecaster(
            cost_per_subtask_estimate=0.10,
            telemetry=telemetry,
        )
        est = forecaster.estimate_run_cost(subtask_count=4, max_cycles=1)
        # Should use 0.25 from telemetry, not 0.10 default
        assert est.estimated_total_usd == pytest.approx(4 * 0.25, abs=0.01)
        assert est.confidence == 0.8  # higher confidence with telemetry

    def test_estimate_telemetry_returns_zero_falls_back(self) -> None:
        """Telemetry returning 0 falls back to default."""
        telemetry = MagicMock()
        telemetry.get_avg_cost_per_improvement.return_value = 0.0
        forecaster = NomicCostForecaster(
            cost_per_subtask_estimate=0.15,
            telemetry=telemetry,
        )
        est = forecaster.estimate_run_cost(subtask_count=2, max_cycles=1)
        assert est.estimated_total_usd == pytest.approx(2 * 0.15, abs=0.01)
        assert est.confidence == 0.5

    def test_estimate_telemetry_raises_falls_back(self) -> None:
        """Telemetry raising an error falls back to default."""
        telemetry = MagicMock()
        telemetry.get_avg_cost_per_improvement.side_effect = RuntimeError("db error")
        forecaster = NomicCostForecaster(
            cost_per_subtask_estimate=0.15,
            telemetry=telemetry,
        )
        est = forecaster.estimate_run_cost(subtask_count=2, max_cycles=1)
        assert est.estimated_total_usd == pytest.approx(2 * 0.15, abs=0.01)
        assert est.confidence == 0.5

    def test_negative_cost_per_subtask_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            NomicCostForecaster(cost_per_subtask_estimate=-0.05)

    def test_budget_warning_zone(self) -> None:
        """When projected cost is 80-100% of budget, warn but don't mark exceeded."""
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.10)
        est = forecaster.estimate_run_cost(
            subtask_count=1,
            max_cycles=1,
            budget_limit=0.11,
        )
        # 0.10 / 0.11 ~ 90.9% — warning zone
        assert est.will_exceed_budget is False
        assert est.warning_message is not None
        assert est.projected_utilization_pct is not None
        assert est.projected_utilization_pct >= 80.0


# -----------------------------------------------------------------------
# NomicCostForecaster — check_mid_run_budget
# -----------------------------------------------------------------------


class TestCheckMidRunBudget:
    def test_ok_status(self) -> None:
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.10)
        result = forecaster.check_mid_run_budget(
            spent_so_far=0.20,
            remaining_subtasks=3,
            budget_limit=5.0,
        )
        assert result.status == "ok"
        assert result.spent_usd == 0.20
        assert result.budget_limit_usd == 5.0
        assert "healthy" in result.message.lower()

    def test_warning_threshold(self) -> None:
        """Trigger warning at >= 80% utilization."""
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.50)
        result = forecaster.check_mid_run_budget(
            spent_so_far=3.50,
            remaining_subtasks=2,
            budget_limit=5.0,
        )
        # projected = 3.50 + 2 * 0.50 = 4.50 => 90%
        assert result.status == "warning"
        assert result.utilization_pct >= 80.0
        assert "warning" in result.message.lower()

    def test_critical_threshold(self) -> None:
        """Trigger critical at >= 95% utilization."""
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.10)
        result = forecaster.check_mid_run_budget(
            spent_so_far=4.80,
            remaining_subtasks=2,
            budget_limit=5.0,
        )
        # projected = 4.80 + 2 * 0.10 = 5.00 => 100%
        assert result.status == "critical"
        assert result.utilization_pct >= 95.0
        assert "critical" in result.message.lower()

    def test_no_remaining_subtasks(self) -> None:
        """With 0 remaining, projected == spent."""
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.10)
        result = forecaster.check_mid_run_budget(
            spent_so_far=1.0,
            remaining_subtasks=0,
            budget_limit=5.0,
        )
        assert result.status == "ok"
        assert result.projected_total_usd == 1.0

    def test_zero_budget_limit(self) -> None:
        """Budget limit of 0 is treated as no limit."""
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.10)
        result = forecaster.check_mid_run_budget(
            spent_so_far=1.0,
            remaining_subtasks=5,
            budget_limit=0.0,
        )
        assert result.status == "ok"
        assert result.utilization_pct == 0.0

    def test_negative_budget_limit(self) -> None:
        """Negative budget limit is treated as no limit."""
        forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.10)
        result = forecaster.check_mid_run_budget(
            spent_so_far=0.5,
            remaining_subtasks=3,
            budget_limit=-1.0,
        )
        assert result.status == "ok"

    def test_mid_run_uses_telemetry_cost(self) -> None:
        """Mid-run check uses historical cost from telemetry for projections."""
        telemetry = MagicMock()
        telemetry.get_avg_cost_per_improvement.return_value = 0.50
        forecaster = NomicCostForecaster(
            cost_per_subtask_estimate=0.10,
            telemetry=telemetry,
        )
        result = forecaster.check_mid_run_budget(
            spent_so_far=3.0,
            remaining_subtasks=4,
            budget_limit=5.0,
        )
        # projected = 3.0 + 4 * 0.50 = 5.0 => 100% => critical
        assert result.status == "critical"
        assert result.projected_total_usd == pytest.approx(5.0, abs=0.01)


# -----------------------------------------------------------------------
# AutonomousOrchestrator integration
# -----------------------------------------------------------------------


class TestOrchestratorIntegration:
    """Verify that the cost forecast opt-in params wire correctly."""

    def test_init_default_disabled(self) -> None:
        """By default cost forecasting is disabled."""
        from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

        orch = AutonomousOrchestrator(require_human_approval=False)
        assert orch.enable_cost_forecast is False
        assert orch._cost_forecaster is None
        assert orch._cost_alert_callback is None

    def test_init_enabled_auto_creates_forecaster(self) -> None:
        """Enabling cost forecast auto-creates a NomicCostForecaster."""
        from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

        orch = AutonomousOrchestrator(
            require_human_approval=False,
            enable_cost_forecast=True,
        )
        assert orch.enable_cost_forecast is True
        assert orch._cost_forecaster is not None
        assert isinstance(orch._cost_forecaster, NomicCostForecaster)

    def test_init_custom_forecaster(self) -> None:
        """A custom forecaster is preserved."""
        from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

        custom = NomicCostForecaster(cost_per_subtask_estimate=0.50)
        orch = AutonomousOrchestrator(
            require_human_approval=False,
            enable_cost_forecast=True,
            cost_forecaster=custom,
        )
        assert orch._cost_forecaster is custom

    def test_init_alert_callback(self) -> None:
        """Alert callback is stored."""
        from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

        cb = MagicMock()
        orch = AutonomousOrchestrator(
            require_human_approval=False,
            enable_cost_forecast=True,
            cost_alert_callback=cb,
        )
        assert orch._cost_alert_callback is cb
