"""
Cost Forecasting Engine.

Provides cost prediction and budget forecasting capabilities:
- Time series analysis of historical costs
- Seasonal pattern detection
- Growth rate modeling
- Anomaly detection
- Budget threshold alerts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from statistics import mean, stdev
from typing import TYPE_CHECKING, Any, cast

from aragora.billing.notification_sink import notify_budget_runway

if TYPE_CHECKING:
    from aragora.billing.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class TrendDirection(str, Enum):
    """Direction of cost trend."""

    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"


class SeasonalPattern(str, Enum):
    """Seasonal patterns in cost data."""

    DAILY = "daily"  # Intra-day patterns
    WEEKLY = "weekly"  # Day-of-week patterns
    MONTHLY = "monthly"  # Time-of-month patterns
    NONE = "none"  # No clear pattern


class AlertSeverity(str, Enum):
    """Severity of forecast alerts."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class DailyForecast:
    """Forecast for a single day."""

    date: datetime
    predicted_cost: Decimal
    lower_bound: Decimal  # 95% confidence interval
    upper_bound: Decimal
    confidence: float  # 0-1


@dataclass
class ForecastAlert:
    """An alert from forecasting analysis."""

    id: str
    severity: AlertSeverity
    title: str
    message: str
    metric: str  # e.g., "daily_cost", "monthly_projection"
    current_value: Decimal
    threshold_value: Decimal
    projected_date: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "metric": self.metric,
            "current_value": str(self.current_value),
            "threshold_value": str(self.threshold_value),
            "projected_date": self.projected_date.isoformat() if self.projected_date else None,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class TrendAnalysis:
    """Analysis of cost trends."""

    direction: TrendDirection
    change_rate: float  # Daily change rate (percentage)
    change_rate_weekly: float  # Weekly change rate
    r_squared: float  # Fit quality (0-1)
    description: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "direction": self.direction.value,
            "change_rate_daily": round(self.change_rate, 2),
            "change_rate_weekly": round(self.change_rate_weekly, 2),
            "r_squared": round(self.r_squared, 3),
            "description": self.description,
        }


@dataclass
class ForecastReport:
    """Complete forecast report for a workspace."""

    workspace_id: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Historical data used
    history_start: datetime | None = None
    history_end: datetime | None = None
    data_points: int = 0

    # Forecast period
    forecast_start: datetime | None = None
    forecast_end: datetime | None = None
    forecast_days: int = 30

    # Aggregate predictions
    predicted_monthly_cost: Decimal = Decimal("0")
    predicted_daily_average: Decimal = Decimal("0")
    confidence_interval: float = 0.95

    # Trend analysis
    trend: TrendAnalysis | None = None
    seasonal_pattern: SeasonalPattern = SeasonalPattern.NONE

    # Daily forecasts
    daily_forecasts: list[DailyForecast] = field(default_factory=list)

    # Alerts
    alerts: list[ForecastAlert] = field(default_factory=list)

    # Budget comparison
    budget_limit: Decimal | None = None
    projected_budget_usage: float | None = None  # Percentage
    days_until_budget_exceeded: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "workspace_id": self.workspace_id,
            "generated_at": self.generated_at.isoformat(),
            "history": {
                "start": self.history_start.isoformat() if self.history_start else None,
                "end": self.history_end.isoformat() if self.history_end else None,
                "data_points": self.data_points,
            },
            "forecast_period": {
                "start": self.forecast_start.isoformat() if self.forecast_start else None,
                "end": self.forecast_end.isoformat() if self.forecast_end else None,
                "days": self.forecast_days,
            },
            "predictions": {
                "monthly_cost": str(self.predicted_monthly_cost),
                "daily_average": str(self.predicted_daily_average),
                "confidence_interval": self.confidence_interval,
            },
            "trend": self.trend.to_dict() if self.trend else None,
            "seasonal_pattern": self.seasonal_pattern.value,
            "daily_forecasts": [
                {
                    "date": f.date.strftime("%Y-%m-%d"),
                    "predicted_cost": str(f.predicted_cost),
                    "lower_bound": str(f.lower_bound),
                    "upper_bound": str(f.upper_bound),
                    "confidence": round(f.confidence, 2),
                }
                for f in self.daily_forecasts
            ],
            "alerts": [a.to_dict() for a in self.alerts],
            "budget": {
                "limit": str(self.budget_limit) if self.budget_limit else None,
                "projected_usage_percent": (
                    round(self.projected_budget_usage, 1)
                    if self.projected_budget_usage is not None
                    else None
                ),
                "days_until_exceeded": self.days_until_budget_exceeded,
            },
        }


@dataclass
class BudgetRunwayResult:
    """Result of a budget runway check."""

    workspace_id: str
    days_remaining: int | None = None  # None if no budget set
    alert_level: AlertSeverity = AlertSeverity.INFO
    budget_limit: Decimal | None = None
    current_spend: Decimal = Decimal("0")
    daily_burn_rate: Decimal = Decimal("0")
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "workspace_id": self.workspace_id,
            "days_remaining": self.days_remaining,
            "alert_level": self.alert_level.value,
            "budget_limit": str(self.budget_limit) if self.budget_limit else None,
            "current_spend": str(self.current_spend),
            "daily_burn_rate": str(self.daily_burn_rate),
            "message": self.message,
        }


@dataclass
class SimulationScenario:
    """A what-if simulation scenario."""

    name: str
    description: str
    changes: dict[str, Any]  # e.g., {"model_change": "haiku", "request_reduction": 0.2}


@dataclass
class SimulationResult:
    """Result of a cost simulation."""

    scenario: SimulationScenario
    baseline_cost: Decimal
    simulated_cost: Decimal
    cost_difference: Decimal
    percentage_change: float
    daily_breakdown: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "scenario": {
                "name": self.scenario.name,
                "description": self.scenario.description,
                "changes": self.scenario.changes,
            },
            "baseline_cost": str(self.baseline_cost),
            "simulated_cost": str(self.simulated_cost),
            "cost_difference": str(self.cost_difference),
            "percentage_change": round(self.percentage_change, 1),
            "daily_breakdown": self.daily_breakdown,
        }


class CostForecaster:
    """
    Cost forecasting engine.

    Uses simple statistical methods for cost prediction:
    - Moving averages for smoothing
    - Linear regression for trend detection
    - Standard deviation for confidence intervals
    """

    def __init__(
        self,
        cost_tracker: CostTracker | None = None,
    ):
        """
        Initialize forecaster.

        Args:
            cost_tracker: CostTracker instance for data access
        """
        self._cost_tracker = cost_tracker

    def set_cost_tracker(self, tracker: CostTracker) -> None:
        """Set the cost tracker instance."""
        self._cost_tracker = tracker

    async def generate_forecast(
        self,
        workspace_id: str,
        forecast_days: int = 30,
        history_days: int = 30,
    ) -> ForecastReport:
        """
        Generate a cost forecast report.

        Args:
            workspace_id: Workspace to forecast
            forecast_days: Days to forecast ahead
            history_days: Days of history to use

        Returns:
            ForecastReport with predictions
        """
        now = datetime.now(timezone.utc)
        history_start = now - timedelta(days=history_days)

        # Get historical data
        daily_costs = await self._get_daily_costs(workspace_id, history_start, now)

        report = ForecastReport(
            workspace_id=workspace_id,
            history_start=history_start,
            history_end=now,
            data_points=len(daily_costs),
            forecast_start=now,
            forecast_end=now + timedelta(days=forecast_days),
            forecast_days=forecast_days,
        )

        if len(daily_costs) < 3:
            logger.warning("Insufficient data for forecast: %s points", len(daily_costs))
            return report

        # Analyze trend
        report.trend = self._analyze_trend(daily_costs)

        # Detect seasonal pattern
        report.seasonal_pattern = self._detect_seasonality(daily_costs)

        # Generate daily forecasts
        report.daily_forecasts = self._forecast_daily(daily_costs, forecast_days, report.trend)

        # Calculate aggregates
        if report.daily_forecasts:
            total = sum(f.predicted_cost for f in report.daily_forecasts)
            report.predicted_monthly_cost = Decimal(str(total))
            report.predicted_daily_average = Decimal(str(total)) / len(report.daily_forecasts)

        # Check budget
        if self._cost_tracker:
            budget = self._cost_tracker.get_budget(workspace_id=workspace_id)
            if budget and budget.monthly_limit_usd:
                report.budget_limit = budget.monthly_limit_usd
                report.projected_budget_usage = float(
                    (report.predicted_monthly_cost / budget.monthly_limit_usd) * 100
                )
                report.days_until_budget_exceeded = self._calculate_budget_runway(
                    daily_costs, budget.monthly_limit_usd, budget.current_monthly_spend
                )

                # Generate budget alerts
                report.alerts.extend(self._generate_budget_alerts(report, budget.monthly_limit_usd))

        # Generate anomaly alerts
        report.alerts.extend(self._detect_anomalies(daily_costs))

        return report

    async def _get_daily_costs(
        self,
        workspace_id: str,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, Decimal]]:
        """Get daily cost totals from cost tracker."""
        daily_costs: dict[str, Decimal] = {}

        if self._cost_tracker:
            # Get from tracker's buffer
            async with self._cost_tracker._buffer_lock:
                for usage in self._cost_tracker._usage_buffer:
                    if usage.workspace_id != workspace_id:
                        continue
                    if usage.timestamp < start or usage.timestamp > end:
                        continue

                    day_key = usage.timestamp.strftime("%Y-%m-%d")
                    daily_costs[day_key] = daily_costs.get(day_key, Decimal("0")) + usage.cost_usd

        # Fill in missing days with zero (or could interpolate)
        result = []
        current = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= end:
            day_key = current.strftime("%Y-%m-%d")
            cost = daily_costs.get(day_key, Decimal("0"))
            result.append((current, cost))
            current += timedelta(days=1)

        return result

    def _analyze_trend(
        self,
        daily_costs: list[tuple[datetime, Decimal]],
    ) -> TrendAnalysis:
        """Analyze trend using simple linear regression."""
        if len(daily_costs) < 2:
            return TrendAnalysis(
                direction=TrendDirection.STABLE,
                change_rate=0.0,
                change_rate_weekly=0.0,
                r_squared=0.0,
                description="Insufficient data for trend analysis",
            )

        # Extract values
        costs = [float(c[1]) for c in daily_costs]
        n = len(costs)

        # Calculate means
        x_mean = (n - 1) / 2  # Days from start
        y_mean = mean(costs)

        # Calculate slope using least squares
        numerator = sum((i - x_mean) * (costs[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            slope = 0.0
        else:
            slope = numerator / denominator

        # Calculate R-squared
        y_pred = [y_mean + slope * (i - x_mean) for i in range(n)]
        ss_res = sum((costs[i] - y_pred[i]) ** 2 for i in range(n))
        ss_tot = sum((costs[i] - y_mean) ** 2 for i in range(n))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        # Determine direction
        if y_mean > 0:
            daily_rate = (slope / y_mean) * 100  # Percentage
        else:
            daily_rate = 0.0

        weekly_rate = daily_rate * 7

        if abs(daily_rate) < 1:  # Less than 1% daily change
            direction = TrendDirection.STABLE
            desc = "Costs are relatively stable"
        elif daily_rate > 0:
            direction = TrendDirection.INCREASING
            desc = f"Costs increasing at {abs(daily_rate):.1f}% per day"
        else:
            direction = TrendDirection.DECREASING
            desc = f"Costs decreasing at {abs(daily_rate):.1f}% per day"

        return TrendAnalysis(
            direction=direction,
            change_rate=daily_rate,
            change_rate_weekly=weekly_rate,
            r_squared=max(0, min(1, r_squared)),
            description=desc,
        )

    def _detect_seasonality(
        self,
        daily_costs: list[tuple[datetime, Decimal]],
    ) -> SeasonalPattern:
        """Detect seasonal patterns in cost data."""
        if len(daily_costs) < 14:
            return SeasonalPattern.NONE

        # Check for weekly pattern (day-of-week effects)
        by_weekday: dict[int, list[float]] = {i: [] for i in range(7)}
        for date, cost in daily_costs:
            by_weekday[date.weekday()].append(float(cost))

        # Calculate variance between weekdays
        weekday_means = [mean(costs) if costs else 0 for costs in by_weekday.values()]
        overall_mean = mean([float(c[1]) for c in daily_costs])

        if overall_mean > 0:
            weekday_variance = stdev(weekday_means) / overall_mean if len(weekday_means) > 1 else 0
        else:
            weekday_variance = 0

        if weekday_variance > 0.2:  # More than 20% variance
            return SeasonalPattern.WEEKLY

        return SeasonalPattern.NONE

    def _forecast_daily(
        self,
        daily_costs: list[tuple[datetime, Decimal]],
        forecast_days: int,
        trend: TrendAnalysis,
    ) -> list[DailyForecast]:
        """Generate daily forecasts."""
        if not daily_costs:
            return []

        costs = [float(c[1]) for c in daily_costs]
        last_date = daily_costs[-1][0]

        # Use exponential moving average as base
        alpha = 0.3  # Smoothing factor
        ema = costs[0]
        for cost in costs[1:]:
            ema = alpha * cost + (1 - alpha) * ema

        # Calculate standard deviation for confidence intervals
        if len(costs) > 1:
            std_dev = stdev(costs)
        else:
            std_dev = ema * 0.2  # Default 20% uncertainty

        # Daily growth factor from trend
        daily_growth = 1 + (trend.change_rate / 100) if trend else 1.0

        forecasts = []
        base_value = ema

        for i in range(forecast_days):
            forecast_date = last_date + timedelta(days=i + 1)

            # Apply trend
            predicted = Decimal(str(base_value * (daily_growth**i)))

            # Confidence decreases over time
            confidence = max(0.5, 0.95 - (i * 0.01))

            # Wider intervals for further predictions
            interval_width = std_dev * (1 + i * 0.05) * 1.96  # 95% CI

            lower = max(Decimal("0"), predicted - Decimal(str(interval_width)))
            upper = predicted + Decimal(str(interval_width))

            forecasts.append(
                DailyForecast(
                    date=forecast_date,
                    predicted_cost=predicted.quantize(Decimal("0.01")),
                    lower_bound=lower.quantize(Decimal("0.01")),
                    upper_bound=upper.quantize(Decimal("0.01")),
                    confidence=confidence,
                )
            )

        return forecasts

    def _calculate_budget_runway(
        self,
        daily_costs: list[tuple[datetime, Decimal]],
        monthly_limit: Decimal,
        current_spend: Decimal,
    ) -> int | None:
        """Calculate days until budget is exhausted."""
        if not daily_costs:
            return None

        recent_costs = [float(c[1]) for c in daily_costs[-7:]]  # Last 7 days
        if not recent_costs:
            return None

        avg_daily = mean(recent_costs)
        if avg_daily <= 0:
            return None

        remaining = float(monthly_limit - current_spend)
        if remaining <= 0:
            return 0

        days = int(remaining / avg_daily)
        return max(0, days)

    def _generate_budget_alerts(
        self,
        report: ForecastReport,
        budget_limit: Decimal,
    ) -> list[ForecastAlert]:
        """Generate alerts based on budget projections."""
        alerts = []

        if report.projected_budget_usage and report.projected_budget_usage >= 100:
            alerts.append(
                ForecastAlert(
                    id=f"budget_exceed_{report.workspace_id}",
                    severity=AlertSeverity.CRITICAL,
                    title="Budget Projected to be Exceeded",
                    message=(
                        f"Forecast shows {report.projected_budget_usage:.0f}% of monthly "
                        f"budget will be used (${report.predicted_monthly_cost:.2f} of "
                        f"${budget_limit:.2f})"
                    ),
                    metric="monthly_projection",
                    current_value=report.predicted_monthly_cost,
                    threshold_value=budget_limit,
                )
            )
        elif report.projected_budget_usage and report.projected_budget_usage >= 80:
            alerts.append(
                ForecastAlert(
                    id=f"budget_warning_{report.workspace_id}",
                    severity=AlertSeverity.WARNING,
                    title="Approaching Budget Limit",
                    message=(
                        f"Forecast shows {report.projected_budget_usage:.0f}% of monthly "
                        f"budget will be used"
                    ),
                    metric="monthly_projection",
                    current_value=report.predicted_monthly_cost,
                    threshold_value=budget_limit,
                )
            )

        if report.days_until_budget_exceeded is not None:
            if report.days_until_budget_exceeded <= 5:
                alerts.append(
                    ForecastAlert(
                        id=f"budget_runway_{report.workspace_id}",
                        severity=AlertSeverity.CRITICAL,
                        title="Budget Running Out",
                        message=(
                            f"At current rate, budget will be exhausted in "
                            f"{report.days_until_budget_exceeded} days"
                        ),
                        metric="budget_runway",
                        current_value=Decimal(str(report.days_until_budget_exceeded)),
                        threshold_value=Decimal("5"),
                        projected_date=(
                            datetime.now(timezone.utc)
                            + timedelta(days=report.days_until_budget_exceeded)
                        ),
                    )
                )

        return alerts

    def _detect_anomalies(
        self,
        daily_costs: list[tuple[datetime, Decimal]],
    ) -> list[ForecastAlert]:
        """Detect cost anomalies (spikes)."""
        alerts: list[ForecastAlert] = []

        if len(daily_costs) < 7:
            return alerts

        costs = [float(c[1]) for c in daily_costs]
        recent = costs[-7:]
        historical = costs[:-7] if len(costs) > 7 else costs

        if not historical:
            return alerts

        historical_mean = mean(historical)
        historical_std = stdev(historical) if len(historical) > 1 else historical_mean * 0.2

        # Check for recent spikes
        for i, cost in enumerate(recent):
            if historical_std > 0:
                z_score = (cost - historical_mean) / historical_std
            else:
                z_score = 0

            if z_score > 2.5:  # More than 2.5 std deviations
                date = daily_costs[-(7 - i)][0]
                alerts.append(
                    ForecastAlert(
                        id=f"spike_{date.strftime('%Y%m%d')}",
                        severity=AlertSeverity.WARNING,
                        title="Cost Spike Detected",
                        message=(
                            f"Cost on {date.strftime('%Y-%m-%d')} (${cost:.2f}) was "
                            f"{((cost / historical_mean) - 1) * 100:.0f}% above average"
                        ),
                        metric="daily_cost",
                        current_value=Decimal(str(cost)),
                        threshold_value=Decimal(str(historical_mean + 2 * historical_std)),
                    )
                )

        return alerts

    async def simulate_scenario(
        self,
        workspace_id: str,
        scenario: SimulationScenario,
        days: int = 30,
    ) -> SimulationResult:
        """
        Simulate a what-if scenario.

        Args:
            workspace_id: Workspace to simulate
            scenario: Scenario to apply
            days: Days to simulate

        Returns:
            SimulationResult with comparison
        """
        # Get baseline forecast
        baseline = await self.generate_forecast(workspace_id, forecast_days=days)

        # Apply scenario changes
        baseline_cost = baseline.predicted_monthly_cost
        multiplier = Decimal("1.0")

        changes = scenario.changes
        if "cost_reduction" in changes:
            multiplier *= Decimal(str(1 - changes["cost_reduction"]))
        if "model_change" in changes:
            # Map model changes to cost multipliers
            model_multipliers = {
                "haiku": Decimal("0.3"),  # 70% cheaper
                "mini": Decimal("0.2"),  # 80% cheaper
                "sonnet": Decimal("0.6"),  # 40% cheaper
            }
            multiplier *= model_multipliers.get(changes["model_change"], Decimal("1.0"))
        if "request_reduction" in changes:
            multiplier *= Decimal(str(1 - changes["request_reduction"]))

        simulated_cost = baseline_cost * multiplier
        difference = baseline_cost - simulated_cost
        pct_change = float((difference / baseline_cost) * 100) if baseline_cost > 0 else 0

        return SimulationResult(
            scenario=scenario,
            baseline_cost=baseline_cost,
            simulated_cost=simulated_cost.quantize(Decimal("0.01")),
            cost_difference=difference.quantize(Decimal("0.01")),
            percentage_change=pct_change,
            daily_breakdown=[
                {
                    "date": f.date.strftime("%Y-%m-%d"),
                    "baseline": str(f.predicted_cost),
                    "simulated": str((f.predicted_cost * multiplier).quantize(Decimal("0.01"))),
                }
                for f in baseline.daily_forecasts
            ],
        )

    async def check_budget_runway(
        self,
        workspace_id: str,
        warning_threshold_days: int = 7,
        critical_threshold_days: int = 3,
    ) -> BudgetRunwayResult:
        """Check how many days until budget is exhausted.

        Args:
            workspace_id: Workspace to check
            warning_threshold_days: Days threshold for WARNING alert (default 7)
            critical_threshold_days: Days threshold for CRITICAL alert (default 3)

        Returns:
            BudgetRunwayResult with days remaining and alert level.
        """
        if not self._cost_tracker:
            return BudgetRunwayResult(
                workspace_id=workspace_id,
                message="No cost tracker configured",
            )

        try:
            budget = self._cost_tracker.get_budget()
        except (AttributeError, KeyError, TypeError, ValueError):
            budget = None

        if not budget or not getattr(budget, "monthly_limit_usd", None):
            return BudgetRunwayResult(
                workspace_id=workspace_id,
                message="No budget limit configured",
            )

        monthly_limit = cast(Decimal, budget.monthly_limit_usd)
        current_spend = cast(
            Decimal,
            getattr(budget, "current_monthly_spend", Decimal("0")),
        )
        remaining = monthly_limit - current_spend

        # Calculate daily burn rate from recent history
        now = datetime.now(timezone.utc)
        history_start = now - timedelta(days=7)
        try:
            daily_costs = await self._get_daily_costs(workspace_id, history_start, now)
        except (AttributeError, KeyError, TypeError, ValueError, OSError):
            daily_costs = []

        if daily_costs and len(daily_costs) > 0:
            # daily_costs may be list of (datetime, Decimal) tuples or plain Decimals
            costs = []
            for c in daily_costs:
                if isinstance(c, (tuple, list)):
                    costs.append(float(c[1]))
                else:
                    costs.append(float(c))
            daily_burn = mean(costs)
        else:
            # Estimate from current spend and days elapsed
            days_elapsed = now.day or 1
            daily_burn = float(current_spend) / days_elapsed

        daily_burn_rate = Decimal(str(round(daily_burn, 2)))

        if daily_burn <= 0:
            return BudgetRunwayResult(
                workspace_id=workspace_id,
                budget_limit=monthly_limit,
                current_spend=current_spend,
                daily_burn_rate=daily_burn_rate,
                message="No significant spending detected",
            )

        days_remaining = int(float(remaining) / daily_burn)
        if days_remaining <= 0:
            days_remaining = 0
            alert_level = AlertSeverity.CRITICAL
            message = f"Budget exhausted — spent ${current_spend} of ${monthly_limit}"
        elif days_remaining <= critical_threshold_days:
            alert_level = AlertSeverity.CRITICAL
            message = f"Budget critically low — {days_remaining} days remaining"
        elif days_remaining <= warning_threshold_days:
            alert_level = AlertSeverity.WARNING
            message = f"Budget running low — {days_remaining} days remaining"
        else:
            alert_level = AlertSeverity.INFO
            message = f"Budget healthy — {days_remaining} days remaining"

        return BudgetRunwayResult(
            workspace_id=workspace_id,
            days_remaining=days_remaining,
            alert_level=alert_level,
            budget_limit=monthly_limit,
            current_spend=current_spend,
            daily_burn_rate=daily_burn_rate,
            message=message,
        )


async def run_budget_runway_check(
    forecaster: CostForecaster | None = None,
    workspace_ids: list[str] | None = None,
) -> list[BudgetRunwayResult]:
    """Run budget runway checks across workspaces and trigger notifications.

    Args:
        forecaster: CostForecaster instance (uses global if None)
        workspace_ids: Workspaces to check (defaults to ["default"])

    Returns:
        List of BudgetRunwayResult for each workspace
    """
    if forecaster is None:
        forecaster = get_cost_forecaster()

    if workspace_ids is None:
        workspace_ids = ["default"]

    results: list[BudgetRunwayResult] = []
    for ws_id in workspace_ids:
        try:
            result = await forecaster.check_budget_runway(ws_id)
            results.append(result)

            # Trigger notification for warning/critical
            if result.alert_level in (AlertSeverity.WARNING, AlertSeverity.CRITICAL):
                try:
                    await notify_budget_runway(
                        title=f"Budget Alert: {result.alert_level.value.upper()}",
                        message=result.message,
                        severity=result.alert_level.value,
                        workspace_id=ws_id,
                    )
                except (
                    RuntimeError,
                    OSError,
                    ConnectionError,
                    ValueError,
                ) as notify_err:
                    logger.warning("Failed to send budget alert for %s: %s", ws_id, notify_err)
        except (RuntimeError, OSError, ConnectionError, ValueError, TypeError, KeyError) as e:
            logger.error("Budget runway check failed for %s: %s", ws_id, e)

    return results


async def send_forecast_notifications(
    report: ForecastReport,
    org_id: str,
    org_name: str,
    email: str,
    budget_name: str = "Monthly Budget",
) -> bool:
    """
    Send notifications for forecast alerts.

    Args:
        report: ForecastReport with predictions
        org_id: Organization ID
        org_name: Organization name
        email: Email address to notify
        budget_name: Name of the budget

    Returns:
        True if notifications were sent successfully
    """
    from aragora.billing.notifications import get_billing_notifier

    notifier = get_billing_notifier()

    # Check if budget will be exceeded
    if report.days_until_budget_exceeded is not None and report.days_until_budget_exceeded > 0:
        if report.budget_limit and report.predicted_monthly_cost:
            projected_date = datetime.now(timezone.utc) + timedelta(
                days=report.days_until_budget_exceeded
            )

            # Get current spend from the sum of historical data or from daily_forecasts
            current_spent = float(report.predicted_daily_average * report.data_points)

            result = notifier.notify_forecast_overage(
                org_id=org_id,
                email=email,
                org_name=org_name,
                budget_name=budget_name,
                current_spent=current_spent,
                budget_limit=float(report.budget_limit),
                projected_date=projected_date,
                projected_amount=float(report.predicted_monthly_cost),
            )
            return result.success

    return True


# Global forecaster instance
_forecaster: CostForecaster | None = None


def get_cost_forecaster() -> CostForecaster:
    """Get or create the global cost forecaster."""
    global _forecaster
    if _forecaster is None:
        try:
            from aragora.billing.cost_tracker import get_cost_tracker

            tracker = get_cost_tracker()
            _forecaster = CostForecaster(cost_tracker=tracker)
        except ImportError:
            _forecaster = CostForecaster()
    return _forecaster


__all__ = [
    "CostForecaster",
    "ForecastReport",
    "DailyForecast",
    "ForecastAlert",
    "TrendAnalysis",
    "TrendDirection",
    "SeasonalPattern",
    "AlertSeverity",
    "BudgetRunwayResult",
    "SimulationScenario",
    "SimulationResult",
    "get_cost_forecaster",
    "send_forecast_notifications",
    "run_budget_runway_check",
]
