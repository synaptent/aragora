"""
Tests for cost forecaster budget runway alerts.

Tests:
- check_budget_runway() method
  - No cost tracker
  - No budget configured
  - Budget healthy (> 7 days)
  - Budget warning (<= 7 days)
  - Budget critical (<= 3 days)
  - Budget exhausted (0 days)
  - Insufficient data
- run_budget_runway_check() background task
  - Multiple workspaces
  - Notification triggers on warning/critical
  - Error handling per workspace
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.billing.forecaster import (
    AlertSeverity,
    BudgetRunwayResult,
    CostForecaster,
    run_budget_runway_check,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _make_tracker(monthly_limit=100.0, current_spend=50.0, daily_costs=None):
    """Create a mock cost tracker."""
    tracker = MagicMock()

    budget = MagicMock()
    budget.monthly_limit_usd = Decimal(str(monthly_limit)) if monthly_limit else None
    budget.current_monthly_spend = Decimal(str(current_spend))
    tracker.get_budget.return_value = budget

    # Mock usage buffer for _get_daily_costs
    tracker._buffer_lock = AsyncMock()
    tracker._buffer_lock.__aenter__ = AsyncMock()
    tracker._buffer_lock.__aexit__ = AsyncMock(return_value=False)
    tracker._usage_buffer = []

    return tracker


# ===========================================================================
# BudgetRunwayResult
# ===========================================================================


class TestBudgetRunwayResult:
    def test_to_dict(self):
        result = BudgetRunwayResult(
            workspace_id="ws-001",
            days_remaining=5,
            alert_level=AlertSeverity.WARNING,
            budget_limit=Decimal("100.00"),
            current_spend=Decimal("65.00"),
            daily_burn_rate=Decimal("7.00"),
            message="Budget running low",
        )
        d = result.to_dict()
        assert d["workspace_id"] == "ws-001"
        assert d["days_remaining"] == 5
        assert d["alert_level"] == "warning"
        assert d["budget_limit"] == "100.00"
        assert d["daily_burn_rate"] == "7.00"

    def test_to_dict_with_nones(self):
        result = BudgetRunwayResult(
            workspace_id="ws-001",
            days_remaining=None,
            alert_level=AlertSeverity.INFO,
        )
        d = result.to_dict()
        assert d["days_remaining"] is None
        assert d["budget_limit"] is None


# ===========================================================================
# check_budget_runway
# ===========================================================================


class TestCheckBudgetRunway:
    @pytest.mark.asyncio
    async def test_no_cost_tracker(self):
        forecaster = CostForecaster(cost_tracker=None)
        result = await forecaster.check_budget_runway("ws-001")
        assert result.alert_level == AlertSeverity.INFO
        assert result.days_remaining is None
        assert "No cost tracker" in result.message

    @pytest.mark.asyncio
    async def test_no_budget_limit(self):
        tracker = _make_tracker(monthly_limit=None)
        tracker.get_budget.return_value = MagicMock(monthly_limit_usd=None)
        forecaster = CostForecaster(cost_tracker=tracker)
        result = await forecaster.check_budget_runway("ws-001")
        assert result.alert_level == AlertSeverity.INFO
        assert "No budget limit" in result.message

    @pytest.mark.asyncio
    async def test_healthy_budget(self):
        tracker = _make_tracker(monthly_limit=1000, current_spend=100)
        forecaster = CostForecaster(cost_tracker=tracker)

        # Mock _get_daily_costs to return 7 days of $10/day
        now = datetime.now(timezone.utc)
        daily = [(now - timedelta(days=i), Decimal("10")) for i in range(7)]
        daily.reverse()

        with patch.object(forecaster, "_get_daily_costs", new_callable=AsyncMock) as mock_costs:
            mock_costs.return_value = daily
            result = await forecaster.check_budget_runway("ws-001")

        assert result.alert_level == AlertSeverity.INFO
        assert result.days_remaining is not None
        assert result.days_remaining > 7
        assert "healthy" in result.message

    @pytest.mark.asyncio
    async def test_warning_budget(self):
        tracker = _make_tracker(monthly_limit=100, current_spend=60)
        forecaster = CostForecaster(cost_tracker=tracker)

        now = datetime.now(timezone.utc)
        # $8/day burn rate -> ~5 days of $40 remaining
        daily = [(now - timedelta(days=i), Decimal("8")) for i in range(7)]
        daily.reverse()

        with patch.object(forecaster, "_get_daily_costs", new_callable=AsyncMock) as mock_costs:
            mock_costs.return_value = daily
            result = await forecaster.check_budget_runway("ws-001")

        assert result.alert_level == AlertSeverity.WARNING
        assert result.days_remaining is not None
        assert result.days_remaining <= 7
        assert "running low" in result.message

    @pytest.mark.asyncio
    async def test_critical_budget(self):
        tracker = _make_tracker(monthly_limit=100, current_spend=85)
        forecaster = CostForecaster(cost_tracker=tracker)

        now = datetime.now(timezone.utc)
        # $10/day burn rate -> ~1.5 days remaining
        daily = [(now - timedelta(days=i), Decimal("10")) for i in range(7)]
        daily.reverse()

        with patch.object(forecaster, "_get_daily_costs", new_callable=AsyncMock) as mock_costs:
            mock_costs.return_value = daily
            result = await forecaster.check_budget_runway("ws-001")

        assert result.alert_level == AlertSeverity.CRITICAL
        assert result.days_remaining is not None
        assert result.days_remaining <= 3

    @pytest.mark.asyncio
    async def test_budget_exhausted(self):
        tracker = _make_tracker(monthly_limit=100, current_spend=110)
        forecaster = CostForecaster(cost_tracker=tracker)

        now = datetime.now(timezone.utc)
        daily = [(now - timedelta(days=i), Decimal("10")) for i in range(7)]
        daily.reverse()

        with patch.object(forecaster, "_get_daily_costs", new_callable=AsyncMock) as mock_costs:
            mock_costs.return_value = daily
            result = await forecaster.check_budget_runway("ws-001")

        assert result.alert_level == AlertSeverity.CRITICAL
        assert result.days_remaining == 0
        assert "exhausted" in result.message.lower()

    @pytest.mark.asyncio
    async def test_custom_threshold(self):
        tracker = _make_tracker(monthly_limit=100, current_spend=50)
        forecaster = CostForecaster(cost_tracker=tracker)

        now = datetime.now(timezone.utc)
        # $5/day -> 10 days remaining
        daily = [(now - timedelta(days=i), Decimal("5")) for i in range(7)]
        daily.reverse()

        with patch.object(forecaster, "_get_daily_costs", new_callable=AsyncMock) as mock_costs:
            mock_costs.return_value = daily
            result = await forecaster.check_budget_runway("ws-001", warning_threshold_days=14)

        # 10 days remaining < 14 day threshold -> warning
        assert result.alert_level == AlertSeverity.WARNING

    @pytest.mark.asyncio
    async def test_includes_burn_rate(self):
        tracker = _make_tracker(monthly_limit=1000, current_spend=100)
        forecaster = CostForecaster(cost_tracker=tracker)

        now = datetime.now(timezone.utc)
        daily = [(now - timedelta(days=i), Decimal("15")) for i in range(7)]
        daily.reverse()

        with patch.object(forecaster, "_get_daily_costs", new_callable=AsyncMock) as mock_costs:
            mock_costs.return_value = daily
            result = await forecaster.check_budget_runway("ws-001")

        assert result.daily_burn_rate is not None
        assert result.daily_burn_rate == Decimal("15.00")


# ===========================================================================
# run_budget_runway_check background task
# ===========================================================================


class TestRunBudgetRunwayCheck:
    @pytest.mark.asyncio
    async def test_checks_all_workspaces(self):
        with patch("aragora.billing.forecaster.get_cost_forecaster") as mock_get:
            forecaster = MagicMock()
            mock_get.return_value = forecaster
            forecaster._cost_tracker = None

            runway_result = BudgetRunwayResult(
                workspace_id="ws-001",
                days_remaining=30,
                alert_level=AlertSeverity.INFO,
                message="Healthy",
            )
            forecaster.check_budget_runway = AsyncMock(return_value=runway_result)

            results = await run_budget_runway_check(workspace_ids=["ws-001", "ws-002"])

        assert len(results) == 2
        assert forecaster.check_budget_runway.call_count == 2

    @pytest.mark.asyncio
    async def test_sends_notification_on_warning(self):
        with patch("aragora.billing.forecaster.get_cost_forecaster") as mock_get:
            forecaster = MagicMock()
            mock_get.return_value = forecaster
            forecaster._cost_tracker = None

            runway_result = BudgetRunwayResult(
                workspace_id="ws-001",
                days_remaining=5,
                alert_level=AlertSeverity.WARNING,
                budget_limit=Decimal("100"),
                daily_burn_rate=Decimal("10"),
                message="Budget running low",
            )
            forecaster.check_budget_runway = AsyncMock(return_value=runway_result)

            with patch(
                "aragora.billing.forecaster.notify_budget_runway",
                new_callable=AsyncMock,
            ) as mock_notify:
                results = await run_budget_runway_check(workspace_ids=["ws-001"])

            assert len(results) == 1
            assert results[0].alert_level == AlertSeverity.WARNING
            mock_notify.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_workspace_error(self):
        with patch("aragora.billing.forecaster.get_cost_forecaster") as mock_get:
            forecaster = MagicMock()
            mock_get.return_value = forecaster
            forecaster._cost_tracker = None

            forecaster.check_budget_runway = AsyncMock(side_effect=RuntimeError("db error"))

            results = await run_budget_runway_check(workspace_ids=["ws-001"])

        assert len(results) == 0  # Error is caught, no result added

    @pytest.mark.asyncio
    async def test_empty_workspace_list(self):
        with patch("aragora.billing.forecaster.get_cost_forecaster") as mock_get:
            forecaster = MagicMock()
            mock_get.return_value = forecaster
            forecaster._cost_tracker = None

            results = await run_budget_runway_check(workspace_ids=[])

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_no_notification_on_info(self):
        with patch("aragora.billing.forecaster.get_cost_forecaster") as mock_get:
            forecaster = MagicMock()
            mock_get.return_value = forecaster
            forecaster._cost_tracker = None

            runway_result = BudgetRunwayResult(
                workspace_id="ws-001",
                days_remaining=30,
                alert_level=AlertSeverity.INFO,
                message="Healthy",
            )
            forecaster.check_budget_runway = AsyncMock(return_value=runway_result)

            with patch(
                "aragora.billing.forecaster.notify_budget_runway",
                new_callable=AsyncMock,
            ) as mock_notify:
                results = await run_budget_runway_check(workspace_ids=["ws-001"])

            assert len(results) == 1
            # notify should NOT have been called since alert_level is INFO
            mock_notify.assert_not_awaited()
