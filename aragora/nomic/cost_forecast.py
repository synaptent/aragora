"""Cost forecasting and budget alerts for Nomic Loop self-improvement runs.

Provides pre-run cost estimation and mid-run budget monitoring with
configurable warning/critical thresholds. Integrates with CycleTelemetryCollector
to leverage historical cost data for more accurate predictions.

Usage:
    from aragora.nomic.cost_forecast import NomicCostForecaster

    forecaster = NomicCostForecaster(cost_per_subtask_estimate=0.15)

    # Pre-run: estimate total cost before spending budget
    estimate = forecaster.estimate_run_cost(
        subtask_count=10,
        tracks=["sme", "developer"],
        max_cycles=5,
        budget_limit=2.0,
    )
    if estimate.will_exceed_budget:
        print(estimate.warning_message)

    # Mid-run: check budget health after each subtask
    check = forecaster.check_mid_run_budget(
        spent_so_far=1.20,
        remaining_subtasks=4,
        budget_limit=2.0,
    )
    if check.status == "critical":
        print(check.message)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NomicCostEstimate:
    """Pre-run cost estimate for a Nomic Loop execution."""

    estimated_total_usd: float
    per_subtask_estimates: dict[str, float]
    budget_limit: float | None = None
    projected_utilization_pct: float | None = None
    will_exceed_budget: bool = False
    confidence: float = 0.5
    warning_message: str | None = None


@dataclass
class BudgetCheckResult:
    """Mid-run budget health check after subtask completion."""

    status: str  # "ok", "warning", "critical"
    spent_usd: float
    projected_total_usd: float
    budget_limit_usd: float
    utilization_pct: float
    message: str


# Per-track cost multipliers relative to baseline cost per subtask.
# Security and core tracks tend to involve heavier model usage (longer
# prompts, more revision rounds) while QA and SME tracks are lighter.
_TRACK_COST_MULTIPLIERS: dict[str, float] = {
    "sme": 0.8,
    "developer": 1.0,
    "self_hosted": 0.9,
    "qa": 0.7,
    "core": 1.5,
    "security": 1.3,
}

# Thresholds for mid-run budget status transitions.
_WARNING_THRESHOLD_PCT = 80.0
_CRITICAL_THRESHOLD_PCT = 95.0


class NomicCostForecaster:
    """Estimates and monitors costs for Nomic Loop self-improvement runs.

    Args:
        cost_per_subtask_estimate: Default cost per subtask in USD when no
            historical data is available. Defaults to $0.15.
        telemetry: Optional ``CycleTelemetryCollector`` instance.  When
            provided, the forecaster uses historical average cost data to
            produce more accurate estimates.
    """

    def __init__(
        self,
        cost_per_subtask_estimate: float = 0.15,
        telemetry: Any | None = None,
    ) -> None:
        if cost_per_subtask_estimate < 0:
            raise ValueError("cost_per_subtask_estimate must be non-negative")

        self._default_cost = cost_per_subtask_estimate
        self._telemetry = telemetry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate_run_cost(
        self,
        subtask_count: int,
        tracks: list[str] | None = None,
        max_cycles: int = 5,
        budget_limit: float | None = None,
    ) -> NomicCostEstimate:
        """Produce a pre-run cost estimate.

        Uses historical average cost from telemetry when available;
        otherwise falls back to ``cost_per_subtask_estimate``.

        The ``max_cycles`` parameter acts as a linear multiplier on the
        per-subtask cost to account for multi-cycle retry overhead.  A
        dampening factor (sqrt) is applied because not every subtask uses
        all available cycles.

        Args:
            subtask_count: Number of subtasks in the decomposition.
            tracks: Optional list of track names for per-track weighting.
            max_cycles: Maximum improvement cycles per subtask.
            budget_limit: Budget cap in USD (optional).

        Returns:
            A ``NomicCostEstimate`` with projected totals and warnings.
        """
        base_cost = self._resolve_base_cost()
        confidence = self._resolve_confidence()

        # Apply a dampened cycle multiplier: most subtasks don't exhaust
        # max_cycles, so we use sqrt to approximate average utilization.
        cycle_factor = max(1.0, max_cycles**0.5)

        per_subtask: dict[str, float] = {}

        if tracks:
            for i in range(subtask_count):
                track = tracks[i % len(tracks)]
                multiplier = _TRACK_COST_MULTIPLIERS.get(track, 1.0)
                key = f"subtask_{i}_{track}"
                per_subtask[key] = base_cost * multiplier * cycle_factor
        else:
            for i in range(subtask_count):
                key = f"subtask_{i}"
                per_subtask[key] = base_cost * cycle_factor

        estimated_total = sum(per_subtask.values())

        # Budget analysis
        will_exceed = False
        utilization_pct: float | None = None
        warning_message: str | None = None

        if budget_limit is not None and budget_limit > 0:
            utilization_pct = (estimated_total / budget_limit) * 100.0
            will_exceed = estimated_total > budget_limit

            if will_exceed:
                overage = estimated_total - budget_limit
                warning_message = (
                    f"Projected cost ${estimated_total:.2f} exceeds budget "
                    f"${budget_limit:.2f} by ${overage:.2f} "
                    f"({utilization_pct:.0f}% utilization)"
                )
                logger.warning(
                    "cost_forecast_budget_exceeded projected=%.2f limit=%.2f",
                    estimated_total,
                    budget_limit,
                )
            elif utilization_pct >= _WARNING_THRESHOLD_PCT:
                warning_message = (
                    f"Projected cost ${estimated_total:.2f} is "
                    f"{utilization_pct:.0f}% of budget ${budget_limit:.2f}"
                )

        return NomicCostEstimate(
            estimated_total_usd=estimated_total,
            per_subtask_estimates=per_subtask,
            budget_limit=budget_limit,
            projected_utilization_pct=utilization_pct,
            will_exceed_budget=will_exceed,
            confidence=confidence,
            warning_message=warning_message,
        )

    def check_mid_run_budget(
        self,
        spent_so_far: float,
        remaining_subtasks: int,
        budget_limit: float,
    ) -> BudgetCheckResult:
        """Check budget health during execution.

        Extrapolates the burn rate from completed subtasks to project
        the total run cost.  Returns a ``BudgetCheckResult`` with status
        set to ``"ok"``, ``"warning"`` (>=80% utilization), or
        ``"critical"`` (>=95% utilization).

        Args:
            spent_so_far: USD spent on completed subtasks.
            remaining_subtasks: Number of subtasks still pending.
            budget_limit: Budget cap in USD.

        Returns:
            A ``BudgetCheckResult`` with projected totals and status.
        """
        if budget_limit <= 0:
            return BudgetCheckResult(
                status="ok",
                spent_usd=spent_so_far,
                projected_total_usd=spent_so_far,
                budget_limit_usd=budget_limit,
                utilization_pct=0.0,
                message="No budget limit set",
            )

        # Project total cost from current burn rate
        if remaining_subtasks > 0:
            avg_cost_per_subtask = self._resolve_base_cost()
            projected_remaining = avg_cost_per_subtask * remaining_subtasks
            projected_total = spent_so_far + projected_remaining
        else:
            projected_total = spent_so_far

        utilization_pct = (projected_total / budget_limit) * 100.0

        if utilization_pct >= _CRITICAL_THRESHOLD_PCT:
            status = "critical"
            message = (
                f"Budget critical: projected ${projected_total:.2f} is "
                f"{utilization_pct:.0f}% of ${budget_limit:.2f} limit "
                f"(${spent_so_far:.2f} spent, {remaining_subtasks} remaining)"
            )
            logger.warning(
                "cost_forecast_critical projected=%.2f limit=%.2f spent=%.2f",
                projected_total,
                budget_limit,
                spent_so_far,
            )
        elif utilization_pct >= _WARNING_THRESHOLD_PCT:
            status = "warning"
            message = (
                f"Budget warning: projected ${projected_total:.2f} is "
                f"{utilization_pct:.0f}% of ${budget_limit:.2f} limit "
                f"(${spent_so_far:.2f} spent, {remaining_subtasks} remaining)"
            )
            logger.info(
                "cost_forecast_warning projected=%.2f limit=%.2f spent=%.2f",
                projected_total,
                budget_limit,
                spent_so_far,
            )
        else:
            status = "ok"
            message = (
                f"Budget healthy: projected ${projected_total:.2f} is "
                f"{utilization_pct:.0f}% of ${budget_limit:.2f} limit"
            )

        return BudgetCheckResult(
            status=status,
            spent_usd=spent_so_far,
            projected_total_usd=projected_total,
            budget_limit_usd=budget_limit,
            utilization_pct=utilization_pct,
            message=message,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_base_cost(self) -> float:
        """Return the best available per-subtask cost estimate.

        Prefers historical average from telemetry; falls back to the
        configured default.
        """
        if self._telemetry is not None:
            try:
                avg = self._telemetry.get_avg_cost_per_improvement()
                if avg and avg > 0:
                    return avg
            except (AttributeError, RuntimeError, OSError, ValueError) as exc:
                logger.debug("telemetry cost lookup failed: %s", exc)

        return self._default_cost

    def _resolve_confidence(self) -> float:
        """Return confidence level based on data availability.

        Returns 0.8 when historical telemetry is available (more data
        means better predictions), 0.5 otherwise.
        """
        if self._telemetry is not None:
            try:
                avg = self._telemetry.get_avg_cost_per_improvement()
                if avg and avg > 0:
                    return 0.8
            except (AttributeError, RuntimeError, OSError, ValueError):
                pass
        return 0.5
