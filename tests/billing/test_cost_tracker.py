"""
Comprehensive tests for aragora.billing.cost_tracker module.

Tests cover:
- TokenUsage dataclass: creation, cost calculation, serialization, deserialization
- Budget dataclass: alert levels, threshold checking, serialization
- BudgetAlert and CostReport dataclasses
- CostTracker: recording, batch recording, buffer flushing, workspace stats
- Budget management: set/get budget, alert callbacks, alert deduplication
- Debate budget enforcement: limits, checks, recording, clearing
- Cost reporting and aggregation: generate_report, get_agent_costs, get_debate_cost
- KM adapter integration: cost patterns, workspace alerts, anomaly detection
- Reset operations: daily and monthly budget resets
- Global singleton: get_cost_tracker, record_usage convenience function
- Error handling: adapter failures, callback exceptions, edge cases
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest

from aragora.billing.cost_tracker import (
    Budget,
    BudgetAlert,
    BudgetAlertLevel,
    CostGranularity,
    CostReport,
    CostTracker,
    DebateBudgetExceededError,
    TokenUsage,
    get_cost_tracker,
    record_usage,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tracker():
    """Fresh CostTracker with no external dependencies."""
    return CostTracker()


@pytest.fixture
def sample_usage():
    """Standard TokenUsage for recording tests."""
    return TokenUsage(
        workspace_id="ws-100",
        agent_id="agent-1",
        agent_name="claude",
        debate_id="debate-42",
        provider="anthropic",
        model="claude-3-opus",
        tokens_in=1000,
        tokens_out=500,
        latency_ms=200.0,
        operation="debate_round",
        metadata={"user_id": "user-1", "org_id": "org-1"},
    )


@pytest.fixture
def sample_budget():
    """Standard Budget with workspace binding."""
    return Budget(
        id="budget-abc",
        name="Team Budget",
        workspace_id="ws-100",
        monthly_limit_usd=Decimal("100.00"),
        daily_limit_usd=Decimal("10.00"),
        per_debate_limit_usd=Decimal("1.00"),
    )


# =============================================================================
# 1. TokenUsage dataclass
# =============================================================================


class TestTokenUsage:
    """Tests for the TokenUsage dataclass."""

    def test_defaults(self):
        """TokenUsage fields default to sensible zero/empty values."""
        usage = TokenUsage()
        assert usage.workspace_id == ""
        assert usage.tokens_in == 0
        assert usage.tokens_out == 0
        assert usage.tokens_cached == 0
        assert usage.cost_usd == Decimal("0")
        assert usage.latency_ms == 0.0
        assert usage.operation == ""
        assert usage.metadata == {}
        assert usage.id  # auto-generated UUID

    def test_calculate_cost_returns_decimal(self):
        """calculate_cost delegates to calculate_token_cost and stores result."""
        usage = TokenUsage(
            provider="anthropic", model="claude-3-opus", tokens_in=500, tokens_out=100
        )
        cost = usage.calculate_cost()
        assert isinstance(cost, Decimal)
        assert usage.cost_usd == cost

    def test_to_dict_keys(self, sample_usage):
        """to_dict includes all expected fields."""
        data = sample_usage.to_dict()
        expected_keys = {
            "id",
            "workspace_id",
            "agent_id",
            "agent_name",
            "debate_id",
            "session_id",
            "provider",
            "model",
            "tokens_in",
            "tokens_out",
            "tokens_cached",
            "cost_usd",
            "latency_ms",
            "timestamp",
            "operation",
            "metadata",
        }
        assert set(data.keys()) == expected_keys

    def test_to_dict_values(self, sample_usage):
        """to_dict serializes values correctly."""
        data = sample_usage.to_dict()
        assert data["workspace_id"] == "ws-100"
        assert data["agent_name"] == "claude"
        assert data["tokens_in"] == 1000
        assert isinstance(data["cost_usd"], str)
        assert isinstance(data["timestamp"], str)

    def test_from_dict_round_trip(self, sample_usage):
        """from_dict can recreate a TokenUsage from to_dict output."""
        data = sample_usage.to_dict()
        restored = TokenUsage.from_dict(data)
        assert restored.workspace_id == sample_usage.workspace_id
        assert restored.agent_name == sample_usage.agent_name
        assert restored.tokens_in == sample_usage.tokens_in
        assert restored.tokens_out == sample_usage.tokens_out

    def test_from_dict_with_datetime_object(self):
        """from_dict handles datetime objects in the timestamp field."""
        ts = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        data = {"timestamp": ts, "tokens_in": 10}
        usage = TokenUsage.from_dict(data)
        assert usage.timestamp == ts

    def test_from_dict_missing_fields(self):
        """from_dict gracefully handles missing optional fields."""
        usage = TokenUsage.from_dict({})
        assert usage.workspace_id == ""
        assert usage.tokens_in == 0
        assert usage.cost_usd == Decimal("0")


# =============================================================================
# 2. Budget dataclass and alert levels
# =============================================================================


class TestBudget:
    """Tests for Budget dataclass and alert level checking."""

    def test_alert_level_no_limit(self):
        """No alert when monthly_limit_usd is None."""
        budget = Budget(name="Open")
        assert budget.check_alert_level() is None

    def test_alert_level_zero_limit(self):
        """No alert when monthly_limit_usd is zero."""
        budget = Budget(monthly_limit_usd=Decimal("0"))
        assert budget.check_alert_level() is None

    @pytest.mark.parametrize(
        "spend, expected_level",
        [
            (Decimal("49.99"), None),
            (Decimal("50.00"), BudgetAlertLevel.INFO),
            (Decimal("74.99"), BudgetAlertLevel.INFO),
            (Decimal("75.00"), BudgetAlertLevel.WARNING),
            (Decimal("89.99"), BudgetAlertLevel.WARNING),
            (Decimal("90.00"), BudgetAlertLevel.CRITICAL),
            (Decimal("99.99"), BudgetAlertLevel.CRITICAL),
            (Decimal("100.00"), BudgetAlertLevel.EXCEEDED),
            (Decimal("150.00"), BudgetAlertLevel.EXCEEDED),
        ],
    )
    def test_alert_thresholds(self, spend, expected_level):
        """Alert level matches the spend percentage bracket."""
        budget = Budget(monthly_limit_usd=Decimal("100.00"), current_monthly_spend=spend)
        assert budget.check_alert_level() == expected_level

    def test_disabled_thresholds_still_allow_exceeded(self):
        """EXCEEDED fires even when all percentage thresholds are disabled."""
        budget = Budget(
            monthly_limit_usd=Decimal("100.00"),
            current_monthly_spend=Decimal("100.00"),
            alert_threshold_50=False,
            alert_threshold_75=False,
            alert_threshold_90=False,
        )
        assert budget.check_alert_level() == BudgetAlertLevel.EXCEEDED

    def test_to_dict_includes_alert_level(self, sample_budget):
        """to_dict includes the computed alert_level."""
        sample_budget.current_monthly_spend = Decimal("80.00")
        data = sample_budget.to_dict()
        assert data["alert_level"] == "warning"

    def test_to_dict_no_alert(self, sample_budget):
        """to_dict shows None alert_level when under threshold."""
        sample_budget.current_monthly_spend = Decimal("0")
        data = sample_budget.to_dict()
        assert data["alert_level"] is None


# =============================================================================
# 3. DebateBudgetExceededError
# =============================================================================


class TestDebateBudgetExceededError:
    """Tests for the custom exception."""

    def test_default_message(self):
        err = DebateBudgetExceededError("d-1", Decimal("2.00"), Decimal("1.00"))
        assert "d-1" in str(err)
        assert err.debate_id == "d-1"
        assert err.current_cost == Decimal("2.00")
        assert err.limit == Decimal("1.00")

    def test_custom_message(self):
        err = DebateBudgetExceededError("d-1", Decimal("2"), Decimal("1"), message="boom")
        assert str(err) == "boom"


# =============================================================================
# 4. CostTracker - recording usage
# =============================================================================


@pytest.mark.asyncio
class TestCostTrackerRecording:
    """Tests for CostTracker.record and record_batch."""

    async def test_record_updates_workspace_stats(self, tracker, sample_usage):
        """A single record updates tokens, cost, api_calls for the workspace."""
        await tracker.record(sample_usage)
        stats = tracker.get_workspace_stats("ws-100")
        assert stats["total_tokens_in"] == 1000
        assert stats["total_tokens_out"] == 500
        assert stats["total_api_calls"] == 1
        assert Decimal(stats["total_cost_usd"]) >= Decimal("0")

    async def test_record_tracks_debate_cost(self, tracker, sample_usage):
        """Recording with debate_id populates _debate_costs."""
        await tracker.record(sample_usage)
        assert "debate-42" in tracker._debate_costs

    async def test_record_no_debate_id(self, tracker):
        """Recording without debate_id does not create a debate cost entry."""
        usage = TokenUsage(workspace_id="ws-1", agent_name="x", provider="p", model="m")
        await tracker.record(usage)
        assert len(tracker._debate_costs) == 0

    async def test_record_persists_to_usage_tracker(self, tracker, sample_usage):
        """If a UsageTracker is provided, record calls its .record method."""
        mock_ut = MagicMock()
        tracker._usage_tracker = mock_ut
        await tracker.record(sample_usage)
        mock_ut.record.assert_called_once()

    async def test_record_batch(self, tracker):
        """record_batch records each usage in sequence."""
        usages = [
            TokenUsage(
                workspace_id="ws-1", agent_name=f"a{i}", provider="p", model="m", tokens_in=100
            )
            for i in range(4)
        ]
        await tracker.record_batch(usages)
        stats = tracker.get_workspace_stats("ws-1")
        assert stats["total_api_calls"] == 4
        assert stats["total_tokens_in"] == 400

    async def test_buffer_flush_on_overflow(self, tracker):
        """Buffer is flushed once it reaches _buffer_max_size."""
        tracker._buffer_max_size = 5
        for i in range(6):
            usage = TokenUsage(workspace_id="ws-1", agent_name="a", provider="p", model="m")
            await tracker.record(usage)
        # After flush, buffer should have only the record added after flush
        assert len(tracker._usage_buffer) < 5

    async def test_record_calculates_cost_when_zero(self, tracker):
        """If cost_usd is zero, record calls calculate_cost."""
        usage = TokenUsage(
            workspace_id="ws-1",
            agent_name="c",
            provider="anthropic",
            model="claude-3-opus",
            tokens_in=500,
            tokens_out=100,
        )
        assert usage.cost_usd == Decimal("0")
        await tracker.record(usage)
        # cost_usd should have been calculated (may still be 0 if model not in pricing)
        # The important thing is it didn't raise
        assert isinstance(usage.cost_usd, Decimal)

    async def test_record_skips_cost_calc_when_nonzero(self, tracker):
        """If cost_usd is already set, record does not recalculate."""
        usage = TokenUsage(
            workspace_id="ws-1",
            agent_name="c",
            provider="p",
            model="m",
            tokens_in=100,
            tokens_out=50,
            cost_usd=Decimal("0.42"),
        )
        await tracker.record(usage)
        assert usage.cost_usd == Decimal("0.42")


# =============================================================================
# 5. Budget management
# =============================================================================


@pytest.mark.asyncio
class TestBudgetManagement:
    """Tests for set_budget, get_budget, and alert callbacks."""

    async def test_set_and_get_by_workspace(self, tracker, sample_budget):
        tracker.set_budget(sample_budget)
        retrieved = tracker.get_budget(workspace_id="ws-100")
        assert retrieved is not None
        assert retrieved.id == "budget-abc"

    async def test_set_and_get_by_org(self, tracker):
        budget = Budget(id="ob-1", name="Org", org_id="org-55", monthly_limit_usd=Decimal("500"))
        tracker.set_budget(budget)
        assert tracker.get_budget(org_id="org-55") is not None

    async def test_get_budget_returns_none_for_unknown(self, tracker):
        assert tracker.get_budget(workspace_id="unknown") is None
        assert tracker.get_budget(org_id="unknown") is None

    async def test_alert_callback_fires_on_threshold(self, tracker, sample_budget):
        """Alert callbacks fire when a budget threshold is crossed."""
        alerts = []
        tracker.add_alert_callback(lambda a: alerts.append(a))
        tracker.set_budget(sample_budget)

        # Push spend over 50% with a single large record
        usage = TokenUsage(
            workspace_id="ws-100",
            agent_name="c",
            provider="p",
            model="m",
            cost_usd=Decimal("55.00"),
        )
        await tracker.record(usage)
        assert len(alerts) >= 1
        assert alerts[0].budget_id == "budget-abc"

    async def test_alert_deduplication(self, tracker, sample_budget):
        """Same alert level on the same day is not sent twice."""
        alerts = []
        tracker.add_alert_callback(lambda a: alerts.append(a))
        tracker.set_budget(sample_budget)

        for _ in range(3):
            usage = TokenUsage(
                workspace_id="ws-100",
                agent_name="c",
                provider="p",
                model="m",
                cost_usd=Decimal("20.00"),
            )
            await tracker.record(usage)

        # Although multiple records pushed spend further, each level only triggers once per day
        unique_levels = {a.level for a in alerts}
        # Each unique level should appear at most once
        for level in unique_levels:
            count = sum(1 for a in alerts if a.level == level)
            assert count == 1, f"Alert level {level} fired {count} times"

    async def test_remove_alert_callback(self, tracker):
        cb = Mock()
        tracker.add_alert_callback(cb)
        tracker.remove_alert_callback(cb)
        assert cb not in tracker._alert_callbacks

    async def test_callback_exception_does_not_propagate(self, tracker, sample_budget):
        """A failing callback does not prevent other processing."""

        def bad_callback(alert):
            raise RuntimeError("callback crash")

        tracker.add_alert_callback(bad_callback)
        tracker.set_budget(sample_budget)

        usage = TokenUsage(
            workspace_id="ws-100",
            agent_name="c",
            provider="p",
            model="m",
            cost_usd=Decimal("55.00"),
        )
        # Should not raise despite bad callback
        await tracker.record(usage)

    async def test_km_adapter_alert_storage(self, tracker, sample_budget):
        """When KM adapter is set, budget alerts are stored to KM."""
        mock_adapter = MagicMock()
        tracker.set_km_adapter(mock_adapter)
        tracker.set_budget(sample_budget)

        usage = TokenUsage(
            workspace_id="ws-100",
            agent_name="c",
            provider="p",
            model="m",
            cost_usd=Decimal("55.00"),
        )
        await tracker.record(usage)
        mock_adapter.store_alert.assert_called()

    async def test_km_adapter_alert_storage_exception(self, tracker, sample_budget):
        """KM adapter exceptions on alert storage are logged, not raised."""
        mock_adapter = MagicMock()
        mock_adapter.store_alert.side_effect = RuntimeError("KM down")
        tracker.set_km_adapter(mock_adapter)
        tracker.set_budget(sample_budget)

        usage = TokenUsage(
            workspace_id="ws-100",
            agent_name="c",
            provider="p",
            model="m",
            cost_usd=Decimal("55.00"),
        )
        # Should not raise
        await tracker.record(usage)


# =============================================================================
# 6. Debate budget enforcement
# =============================================================================


class TestDebateBudget:
    """Tests for per-debate budget limits and checks."""

    def test_set_debate_limit(self, tracker):
        tracker.set_debate_limit("d-1", Decimal("5.00"))
        assert tracker._debate_limits["d-1"] == Decimal("5.00")
        assert tracker._debate_costs["d-1"] == Decimal("0")

    def test_check_no_limit(self, tracker):
        status = tracker.check_debate_budget("d-no-limit")
        assert status["allowed"] is True
        assert status["limit"] == "unlimited"
        assert status["remaining"] == "unlimited"

    def test_check_within_budget(self, tracker):
        tracker.set_debate_limit("d-1", Decimal("10.00"))
        tracker.record_debate_cost("d-1", Decimal("3.00"))
        status = tracker.check_debate_budget("d-1")
        assert status["allowed"] is True
        assert status["remaining"] == "7.00"

    def test_check_exceeded(self, tracker):
        tracker.set_debate_limit("d-1", Decimal("5.00"))
        tracker.record_debate_cost("d-1", Decimal("6.00"))
        status = tracker.check_debate_budget("d-1")
        assert status["allowed"] is False
        assert "exceeded" in status["message"].lower()

    def test_check_with_estimate_blocks(self, tracker):
        tracker.set_debate_limit("d-1", Decimal("5.00"))
        tracker.record_debate_cost("d-1", Decimal("4.50"))
        status = tracker.check_debate_budget("d-1", estimated_cost_usd=Decimal("1.00"))
        assert status["allowed"] is False

    def test_check_with_estimate_allows(self, tracker):
        tracker.set_debate_limit("d-1", Decimal("5.00"))
        tracker.record_debate_cost("d-1", Decimal("4.50"))
        status = tracker.check_debate_budget("d-1", estimated_cost_usd=Decimal("0.30"))
        assert status["allowed"] is True

    def test_record_debate_cost_cumulative(self, tracker):
        tracker.set_debate_limit("d-1", Decimal("10.00"))
        tracker.record_debate_cost("d-1", Decimal("2.00"))
        tracker.record_debate_cost("d-1", Decimal("3.00"))
        assert tracker._debate_costs["d-1"] == Decimal("5.00")

    def test_record_debate_cost_no_prior_limit(self, tracker):
        """record_debate_cost works even without set_debate_limit."""
        status = tracker.record_debate_cost("d-new", Decimal("1.00"))
        assert status["allowed"] is True
        assert status["limit"] == "unlimited"

    def test_get_debate_budget_status_delegates(self, tracker):
        tracker.set_debate_limit("d-1", Decimal("5.00"))
        status = tracker.get_debate_budget_status("d-1")
        assert status["limit"] == "5.00"

    def test_clear_debate_budget(self, tracker):
        tracker.set_debate_limit("d-1", Decimal("5.00"))
        tracker.record_debate_cost("d-1", Decimal("2.00"))
        tracker.clear_debate_budget("d-1")
        assert "d-1" not in tracker._debate_costs
        assert "d-1" not in tracker._debate_limits

    def test_clear_nonexistent_is_safe(self, tracker):
        tracker.clear_debate_budget("nonexistent")  # must not raise


# =============================================================================
# 7. Reporting and aggregation
# =============================================================================


@pytest.mark.asyncio
class TestReporting:
    """Tests for generate_report, get_agent_costs, get_debate_cost."""

    async def test_generate_report_empty_workspace(self, tracker):
        report = await tracker.generate_report(workspace_id="ws-empty")
        assert report.workspace_id == "ws-empty"
        assert report.total_cost_usd == Decimal("0")
        assert report.total_api_calls == 0

    async def test_generate_report_with_data(self, tracker):
        for name in ["claude", "gemini", "claude"]:
            usage = TokenUsage(
                workspace_id="ws-1",
                agent_name=name,
                provider="p",
                model="m",
                tokens_in=1000,
                tokens_out=500,
                cost_usd=Decimal("1.00"),
            )
            await tracker.record(usage)

        report = await tracker.generate_report(workspace_id="ws-1")
        assert report.total_api_calls == 3
        assert report.total_tokens_in == 3000
        assert report.total_tokens_out == 1500
        assert report.total_cost_usd == Decimal("3.00")
        assert "claude" in report.cost_by_agent
        assert "gemini" in report.cost_by_agent

    async def test_generate_report_averages(self, tracker):
        for _ in range(4):
            usage = TokenUsage(
                workspace_id="ws-1",
                agent_name="a",
                provider="p",
                model="m",
                tokens_in=200,
                tokens_out=100,
                cost_usd=Decimal("2.00"),
            )
            await tracker.record(usage)

        report = await tracker.generate_report(workspace_id="ws-1")
        assert report.avg_cost_per_call == Decimal("2.00")
        assert report.avg_tokens_per_call == 300.0

    async def test_generate_report_projections(self, tracker):
        for _ in range(5):
            usage = TokenUsage(
                workspace_id="ws-1",
                agent_name="a",
                provider="p",
                model="m",
                tokens_in=100,
                tokens_out=50,
                cost_usd=Decimal("1.00"),
            )
            await tracker.record(usage)

        report = await tracker.generate_report(workspace_id="ws-1")
        assert report.projected_daily_rate is not None
        assert report.projected_monthly_cost is not None
        assert report.projected_monthly_cost > Decimal("0")

    async def test_generate_report_top_agents(self, tracker):
        for name, cost in [("claude", "3.00"), ("gemini", "1.00")]:
            usage = TokenUsage(
                workspace_id="ws-1",
                agent_name=name,
                provider="p",
                model="m",
                tokens_in=100,
                tokens_out=50,
                cost_usd=Decimal(cost),
            )
            await tracker.record(usage)

        report = await tracker.generate_report(workspace_id="ws-1")
        assert len(report.top_agents_by_cost) == 2
        assert report.top_agents_by_cost[0]["agent"] == "claude"

    async def test_generate_report_default_period(self, tracker):
        """Default period is last 30 days when no dates given."""
        report = await tracker.generate_report(workspace_id="ws-1")
        delta = report.period_end - report.period_start
        assert 29 <= delta.days <= 31

    async def test_get_agent_costs(self, tracker):
        for name, cost in [("claude", "3.00"), ("gemini", "2.00")]:
            usage = TokenUsage(
                workspace_id="ws-1",
                agent_name=name,
                provider="p",
                model="m",
                cost_usd=Decimal(cost),
            )
            await tracker.record(usage)

        costs = await tracker.get_agent_costs("ws-1")
        assert "claude" in costs
        assert "gemini" in costs
        assert costs["claude"]["percentage"] == 60.0
        assert costs["gemini"]["percentage"] == 40.0

    async def test_get_agent_costs_empty(self, tracker):
        costs = await tracker.get_agent_costs("ws-empty")
        assert costs == {}

    async def test_get_debate_cost_from_buffer(self, tracker):
        usage = TokenUsage(
            workspace_id="ws-1",
            agent_name="claude",
            debate_id="d-1",
            provider="p",
            model="m",
            tokens_in=800,
            tokens_out=200,
            cost_usd=Decimal("0.50"),
        )
        await tracker.record(usage)
        result = await tracker.get_debate_cost("d-1")
        assert result["debate_id"] == "d-1"
        assert result["total_tokens_in"] == 800
        assert result["total_tokens_out"] == 200
        assert Decimal(result["total_cost_usd"]) == Decimal("0.50")

    async def test_get_debate_cost_empty(self, tracker):
        result = await tracker.get_debate_cost("nonexistent")
        assert Decimal(result["total_cost_usd"]) == Decimal("0")


# =============================================================================
# 8. KM adapter integration
# =============================================================================


class TestKMIntegration:
    """Tests for Knowledge Mound adapter queries and anomaly detection."""

    def test_set_km_adapter(self, tracker):
        adapter = MagicMock()
        tracker.set_km_adapter(adapter)
        assert tracker._km_adapter is adapter

    def test_query_cost_patterns_no_adapter(self, tracker):
        assert tracker.query_km_cost_patterns("ws-1") == {}

    def test_query_cost_patterns_with_adapter(self, tracker):
        adapter = MagicMock()
        adapter.get_cost_patterns.return_value = {"avg": 0.05}
        tracker.set_km_adapter(adapter)
        result = tracker.query_km_cost_patterns("ws-1", agent_id="a1")
        assert result == {"avg": 0.05}
        adapter.get_cost_patterns.assert_called_once_with("ws-1", "a1")

    def test_query_cost_patterns_adapter_error(self, tracker):
        adapter = MagicMock()
        adapter.get_cost_patterns.side_effect = RuntimeError("fail")
        tracker.set_km_adapter(adapter)
        assert tracker.query_km_cost_patterns("ws-1") == {}

    def test_query_workspace_alerts_no_adapter(self, tracker):
        assert tracker.query_km_workspace_alerts("ws-1") == []

    def test_query_workspace_alerts_with_adapter(self, tracker):
        adapter = MagicMock()
        adapter.get_workspace_alerts.return_value = [{"level": "warning"}]
        tracker.set_km_adapter(adapter)
        result = tracker.query_km_workspace_alerts("ws-1", min_level="warning", limit=10)
        assert len(result) == 1
        adapter.get_workspace_alerts.assert_called_once_with("ws-1", "warning", 10)

    def test_query_workspace_alerts_adapter_error(self, tracker):
        adapter = MagicMock()
        adapter.get_workspace_alerts.side_effect = RuntimeError("fail")
        tracker.set_km_adapter(adapter)
        assert tracker.query_km_workspace_alerts("ws-1") == []

    @pytest.mark.asyncio
    async def test_detect_anomalies_no_adapter(self, tracker):
        anomalies, advisory = await tracker.detect_and_store_anomalies("ws-1")
        assert anomalies == []
        assert advisory.recommended_action == "none"

    @pytest.mark.asyncio
    async def test_detect_anomalies_no_stats(self, tracker):
        adapter = MagicMock()
        tracker.set_km_adapter(adapter)
        anomalies, advisory = await tracker.detect_and_store_anomalies("ws-unknown")
        assert anomalies == []
        assert advisory.recommended_action == "none"

    @pytest.mark.asyncio
    async def test_detect_anomalies_stores_results(self, tracker):
        adapter = MagicMock()
        anomaly = MagicMock()
        anomaly.to_dict.return_value = {"type": "spike"}
        adapter.detect_anomalies.return_value = [anomaly]
        adapter.store_anomaly.return_value = "anomaly-id-1"
        tracker.set_km_adapter(adapter)

        # Populate workspace stats
        usage = TokenUsage(
            workspace_id="ws-1",
            agent_name="a",
            provider="p",
            model="m",
            tokens_in=100,
            tokens_out=50,
            cost_usd=Decimal("1.00"),
        )
        await tracker.record(usage)

        results, advisory = await tracker.detect_and_store_anomalies("ws-1")
        assert len(results) == 1
        assert results[0]["type"] == "spike"

    @pytest.mark.asyncio
    async def test_detect_anomalies_error_handling(self, tracker):
        adapter = MagicMock()
        adapter.detect_anomalies.side_effect = RuntimeError("boom")
        tracker.set_km_adapter(adapter)

        usage = TokenUsage(
            workspace_id="ws-1",
            agent_name="a",
            provider="p",
            model="m",
            cost_usd=Decimal("1.00"),
        )
        await tracker.record(usage)

        results, advisory = await tracker.detect_and_store_anomalies("ws-1")
        assert results == []
        assert advisory.recommended_action == "none"


# =============================================================================
# 9. Reset operations
# =============================================================================


class TestResets:
    """Tests for daily and monthly budget resets."""

    def test_reset_daily_budgets(self, tracker, sample_budget):
        sample_budget.current_daily_spend = Decimal("8.00")
        tracker.set_budget(sample_budget)
        tracker.reset_daily_budgets()
        b = tracker.get_budget(workspace_id="ws-100")
        assert b.current_daily_spend == Decimal("0")

    def test_reset_daily_clears_daily_alert_keys(self, tracker):
        tracker._sent_alerts.add("b1:info:daily:2025-01-01")
        tracker._sent_alerts.add("b1:warning:2025-01-01")
        tracker.reset_daily_budgets()
        # Only the key containing "daily" should have been removed
        assert "b1:info:daily:2025-01-01" not in tracker._sent_alerts

    def test_reset_monthly_budgets(self, tracker, sample_budget):
        sample_budget.current_monthly_spend = Decimal("80.00")
        sample_budget.current_daily_spend = Decimal("5.00")
        tracker.set_budget(sample_budget)
        tracker.reset_monthly_budgets()
        b = tracker.get_budget(workspace_id="ws-100")
        assert b.current_monthly_spend == Decimal("0")
        assert b.current_daily_spend == Decimal("0")

    def test_reset_monthly_clears_all_alerts(self, tracker):
        tracker._sent_alerts = {"a", "b", "c"}
        tracker.reset_monthly_budgets()
        assert len(tracker._sent_alerts) == 0

    def test_reset_monthly_clears_workspace_stats(self, tracker):
        tracker._workspace_stats["ws-1"]["total_cost"] = Decimal("50")
        tracker.reset_monthly_budgets()
        assert len(tracker._workspace_stats) == 0


# =============================================================================
# 10. Global singleton and convenience function
# =============================================================================


class TestGlobalSingleton:
    """Tests for get_cost_tracker and record_usage."""

    def test_get_cost_tracker_does_not_import_knowledge(self, monkeypatch):
        """Billing singleton creation must not auto-import the KM adapter."""
        import builtins
        import aragora.billing.cost_tracker as ct

        real_import = builtins.__import__

        def reject_knowledge(name, *args, **kwargs):
            if name.startswith("aragora.knowledge"):
                raise AssertionError(f"unexpected upward import: {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(ct, "_cost_tracker", None)
        with (
            patch.object(ct, "UsageTracker", side_effect=ImportError),
            patch("builtins.__import__", side_effect=reject_knowledge),
        ):
            tracker = get_cost_tracker()

        assert isinstance(tracker, CostTracker)

    def test_get_cost_tracker_creates_instance(self):
        import aragora.billing.cost_tracker as ct

        ct._cost_tracker = None
        with patch.object(ct, "UsageTracker", side_effect=ImportError):
            tracker = get_cost_tracker()
            assert isinstance(tracker, CostTracker)

    def test_get_cost_tracker_returns_same_instance(self):
        import aragora.billing.cost_tracker as ct

        ct._cost_tracker = None
        with patch.object(ct, "UsageTracker", side_effect=ImportError):
            t1 = get_cost_tracker()
            t2 = get_cost_tracker()
            assert t1 is t2

    @pytest.mark.asyncio
    async def test_record_usage_convenience(self):
        """The record_usage convenience function creates a TokenUsage and records it."""
        import aragora.billing.cost_tracker as ct

        mock_tracker = MagicMock()
        mock_tracker.record = AsyncMock()
        ct._cost_tracker = mock_tracker

        try:
            result = await record_usage(
                workspace_id="ws-1",
                agent_name="claude",
                provider="anthropic",
                model="claude-3",
                tokens_in=100,
                tokens_out=50,
                debate_id="d-1",
                operation="test",
                latency_ms=42.0,
            )
            assert isinstance(result, TokenUsage)
            assert result.workspace_id == "ws-1"
            mock_tracker.record.assert_awaited_once()
        finally:
            ct._cost_tracker = None


# =============================================================================
# 11. CostReport and CostGranularity dataclasses
# =============================================================================


class TestCostReportDataclass:
    """Tests for CostReport serialization."""

    def test_to_dict_keys(self):
        report = CostReport(workspace_id="ws-1", total_cost_usd=Decimal("10.00"))
        data = report.to_dict()
        assert data["workspace_id"] == "ws-1"
        assert data["total_cost_usd"] == "10.00"
        assert "cost_by_agent" in data
        assert "projected_monthly_cost" in data

    def test_to_dict_projected_values(self):
        report = CostReport(
            projected_monthly_cost=Decimal("30.00"),
            projected_daily_rate=Decimal("1.00"),
        )
        data = report.to_dict()
        assert data["projected_monthly_cost"] == "30.00"
        assert data["projected_daily_rate"] == "1.00"


class TestCostGranularity:
    def test_values(self):
        assert CostGranularity.HOURLY.value == "hourly"
        assert CostGranularity.DAILY.value == "daily"
        assert CostGranularity.WEEKLY.value == "weekly"
        assert CostGranularity.MONTHLY.value == "monthly"


class TestBudgetAlertDataclass:
    def test_defaults(self):
        alert = BudgetAlert()
        assert alert.acknowledged is False
        assert alert.acknowledged_at is None
        assert alert.level == BudgetAlertLevel.INFO


# =============================================================================
# 12. Workspace stats for unknown workspace
# =============================================================================


class TestWorkspaceStats:
    def test_get_stats_unknown_workspace(self, tracker):
        """get_workspace_stats returns zeros for unknown workspace."""
        stats = tracker.get_workspace_stats("nonexistent")
        assert stats["workspace_id"] == "nonexistent"
        assert Decimal(stats["total_cost_usd"]) == Decimal("0")
        assert stats["total_api_calls"] == 0


# =============================================================================
# 13. Multiple workspace isolation
# =============================================================================


@pytest.mark.asyncio
class TestMultiWorkspace:
    async def test_workspaces_are_isolated(self, tracker):
        """Usage in one workspace does not affect another."""
        for ws in ["ws-a", "ws-b"]:
            usage = TokenUsage(
                workspace_id=ws,
                agent_name="a",
                provider="p",
                model="m",
                tokens_in=100,
                tokens_out=50,
                cost_usd=Decimal("1.00"),
            )
            await tracker.record(usage)

        stats_a = tracker.get_workspace_stats("ws-a")
        stats_b = tracker.get_workspace_stats("ws-b")
        assert stats_a["total_api_calls"] == 1
        assert stats_b["total_api_calls"] == 1
        assert Decimal(stats_a["total_cost_usd"]) == Decimal("1.00")
        assert Decimal(stats_b["total_cost_usd"]) == Decimal("1.00")
