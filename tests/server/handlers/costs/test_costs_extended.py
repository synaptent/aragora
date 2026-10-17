"""
Extended tests for cost visibility API handler.

Covers endpoints and edge cases not in the original test file:
- Export (JSON/CSV, invalid format)
- Usage tracking (group_by variants, no tracker)
- Budget listing and creation (validation, thresholds)
- Constraint checking (monthly/daily limits, negative cost)
- Cost estimation (different providers/models, defaults)
- Detailed forecast (confidence intervals, daily breakdowns)
- Detailed recommendations (implementation steps, min_savings filter)
- Alert creation (validation, invalid type)
- Edge cases (zero division, unknown group_by, empty data)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from aragora.server.handlers.costs import CostHandler, CostSummary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    return CostHandler()


@pytest.fixture
def mock_request():
    request = MagicMock(spec=web.Request)
    request.query = {}
    request.match_info = {}
    return request


def _make_summary(**overrides):
    """Build a CostSummary with sensible defaults, overriding as needed."""
    defaults = dict(
        total_cost=100.0,
        budget=500.0,
        tokens_used=1_000_000,
        api_calls=5000,
        last_updated=datetime.now(timezone.utc),
        cost_by_provider=[{"name": "Anthropic", "cost": 70.0, "percentage": 70.0}],
        cost_by_feature=[{"name": "Debates", "cost": 60.0, "percentage": 60.0}],
        daily_costs=[{"date": "2026-01-20", "cost": 20.0, "tokens": 500000}],
        alerts=[],
    )
    defaults.update(overrides)
    return CostSummary(**defaults)


# ===========================================================================
# Export endpoint tests
# ===========================================================================


class TestExportHandler:
    """Tests for GET /api/v1/costs/export."""

    @pytest.mark.asyncio
    async def test_export_json(self, handler, mock_request):
        """JSON export includes rows and metadata."""
        mock_request.query = {"format": "json", "range": "7d", "group_by": "daily"}

        with patch("aragora.server.handlers.costs.models.get_cost_summary") as m:
            m.return_value = _make_summary()
            response = await handler.handle_export(mock_request)

        assert response.status == 200
        data = json.loads(response.body)
        assert "rows" in data
        assert data["workspace_id"] == "default"
        assert data["group_by"] == "daily"

    @pytest.mark.asyncio
    async def test_export_csv(self, handler, mock_request):
        """CSV export returns text/csv content type."""
        mock_request.query = {"format": "csv", "range": "30d"}

        with patch("aragora.server.handlers.costs.models.get_cost_summary") as m:
            m.return_value = _make_summary()
            response = await handler.handle_export(mock_request)

        assert response.status == 200
        assert response.content_type == "text/csv"

    @pytest.mark.asyncio
    async def test_export_invalid_format(self, handler, mock_request):
        """Invalid export format returns 400."""
        mock_request.query = {"format": "xml"}

        response = await handler.handle_export(mock_request)

        assert response.status == 400
        assert "error" in json.loads(response.body)

    @pytest.mark.asyncio
    async def test_export_by_provider(self, handler, mock_request):
        """Export grouped by provider returns provider rows."""
        mock_request.query = {"format": "json", "group_by": "provider"}

        with patch("aragora.server.handlers.costs.models.get_cost_summary") as m:
            m.return_value = _make_summary()
            response = await handler.handle_export(mock_request)

        data = json.loads(response.body)
        assert data["rows"][0]["name"] == "Anthropic"


# ===========================================================================
# Usage endpoint tests
# ===========================================================================


class TestUsageHandler:
    """Tests for GET /api/v1/costs/usage."""

    @pytest.mark.asyncio
    async def test_usage_no_tracker(self, handler, mock_request):
        """Returns 503 when tracker is unavailable."""
        with patch("aragora.server.handlers.costs.models._get_cost_tracker", return_value=None):
            response = await handler.handle_get_usage(mock_request)

        assert response.status == 503

    @pytest.mark.asyncio
    async def test_usage_group_by_provider(self, handler, mock_request):
        """Usage grouped by provider returns provider breakdown."""
        mock_request.query = {"group_by": "provider"}
        mock_report = MagicMock()
        mock_report.total_cost_usd = Decimal("200")
        mock_report.total_tokens_in = 500000
        mock_report.total_tokens_out = 250000
        mock_report.total_api_calls = 3000
        mock_report.cost_by_provider = {"anthropic": Decimal("120"), "openai": Decimal("80")}
        mock_report.calls_by_provider = {"anthropic": 2000, "openai": 1000}
        mock_report.cost_by_operation = {}

        mock_tracker = MagicMock()
        mock_tracker.generate_report = AsyncMock(return_value=mock_report)

        with patch(
            "aragora.server.handlers.costs.models._get_cost_tracker", return_value=mock_tracker
        ):
            response = await handler.handle_get_usage(mock_request)

        assert response.status == 200
        data = json.loads(response.body)
        assert len(data["usage"]) == 2

    @pytest.mark.asyncio
    async def test_usage_group_by_operation(self, handler, mock_request):
        """Usage grouped by operation returns operation breakdown."""
        mock_request.query = {"group_by": "operation"}
        mock_report = MagicMock()
        mock_report.total_cost_usd = Decimal("100")
        mock_report.total_tokens_in = 100000
        mock_report.total_tokens_out = 50000
        mock_report.total_api_calls = 1000
        mock_report.cost_by_provider = {}
        mock_report.cost_by_operation = {"debate": Decimal("60"), "review": Decimal("40")}

        mock_tracker = MagicMock()
        mock_tracker.generate_report = AsyncMock(return_value=mock_report)

        with patch(
            "aragora.server.handlers.costs.models._get_cost_tracker", return_value=mock_tracker
        ):
            response = await handler.handle_get_usage(mock_request)

        data = json.loads(response.body)
        assert data["group_by"] == "operation"
        assert len(data["usage"]) == 2


# ===========================================================================
# Budget listing and creation tests
# ===========================================================================


class TestBudgetEndpoints:
    """Tests for budget list and create endpoints."""

    @pytest.mark.asyncio
    async def test_list_budgets_no_tracker(self, handler, mock_request):
        """List budgets returns 503 when tracker unavailable."""
        with patch("aragora.server.handlers.costs.models._get_cost_tracker", return_value=None):
            response = await handler.handle_list_budgets(mock_request)

        assert response.status == 503

    @pytest.mark.asyncio
    async def test_list_budgets_with_budget(self, handler, mock_request):
        """List budgets returns budget details when one exists."""
        mock_budget = MagicMock()
        mock_budget.name = "Main Budget"
        mock_budget.monthly_limit_usd = Decimal("1000")
        mock_budget.daily_limit_usd = Decimal("50")
        mock_budget.current_monthly_spend = Decimal("300")
        mock_budget.current_daily_spend = Decimal("15")

        mock_tracker = MagicMock()
        mock_tracker.get_budget = MagicMock(return_value=mock_budget)

        with patch(
            "aragora.server.handlers.costs.models._get_cost_tracker", return_value=mock_tracker
        ):
            response = await handler.handle_list_budgets(mock_request)

        assert response.status == 200
        data = json.loads(response.body)
        assert data["count"] == 1
        assert data["budgets"][0]["monthly_limit_usd"] == 1000.0

    @pytest.mark.asyncio
    async def test_list_budgets_none(self, handler, mock_request):
        """List budgets returns empty list when no budget set."""
        mock_tracker = MagicMock()
        mock_tracker.get_budget = MagicMock(return_value=None)

        with patch(
            "aragora.server.handlers.costs.models._get_cost_tracker", return_value=mock_tracker
        ):
            response = await handler.handle_list_budgets(mock_request)

        data = json.loads(response.body)
        assert data["count"] == 0
        assert data["budgets"] == []

    @pytest.mark.asyncio
    async def test_create_budget_success(self, handler, mock_request):
        """Create budget returns 201 on success."""
        mock_request.json = AsyncMock(
            return_value={
                "workspace_id": "ws1",
                "name": "Test Budget",
                "monthly_limit_usd": 500,
                "daily_limit_usd": 25,
                "alert_thresholds": [50, 75, 90],
            }
        )
        mock_tracker = MagicMock()
        mock_tracker.set_budget = MagicMock()

        with patch(
            "aragora.server.handlers.costs.models._get_cost_tracker", return_value=mock_tracker
        ):
            response = await handler.handle_create_budget(mock_request)

        assert response.status == 201
        data = json.loads(response.body)
        assert data["success"] is True
        assert data["budget"]["name"] == "Test Budget"

    @pytest.mark.asyncio
    async def test_create_budget_negative_limit(self, handler, mock_request):
        """Create budget rejects negative monthly limit."""
        mock_request.json = AsyncMock(return_value={"monthly_limit_usd": -100})

        response = await handler.handle_create_budget(mock_request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_create_budget_missing_limit(self, handler, mock_request):
        """Create budget rejects missing monthly limit."""
        mock_request.json = AsyncMock(return_value={"name": "No limit"})

        response = await handler.handle_create_budget(mock_request)

        assert response.status == 400


# ===========================================================================
# Constraint checking tests
# ===========================================================================


class TestConstraintHandler:
    """Tests for POST /api/v1/costs/constraints/check."""

    @pytest.mark.asyncio
    async def test_constraints_allowed(self, handler, mock_request):
        """Constraint check allows operation within budget."""
        mock_request.json = AsyncMock(
            return_value={"estimated_cost_usd": 10, "workspace_id": "ws1"}
        )
        mock_budget = MagicMock()
        mock_budget.monthly_limit_usd = Decimal("1000")
        mock_budget.current_monthly_spend = Decimal("100")
        mock_budget.daily_limit_usd = None

        mock_tracker = MagicMock()
        mock_tracker.get_budget = MagicMock(return_value=mock_budget)

        with patch(
            "aragora.server.handlers.costs.models._get_cost_tracker", return_value=mock_tracker
        ):
            response = await handler.handle_check_constraints(mock_request)

        data = json.loads(response.body)
        assert data["allowed"] is True
        assert data["remaining_monthly_budget"] == 900.0

    @pytest.mark.asyncio
    async def test_constraints_exceeds_monthly(self, handler, mock_request):
        """Constraint check blocks operation exceeding monthly budget."""
        mock_request.json = AsyncMock(
            return_value={"estimated_cost_usd": 500, "workspace_id": "ws1"}
        )
        mock_budget = MagicMock()
        mock_budget.monthly_limit_usd = Decimal("1000")
        mock_budget.current_monthly_spend = Decimal("800")
        mock_budget.daily_limit_usd = None

        mock_tracker = MagicMock()
        mock_tracker.get_budget = MagicMock(return_value=mock_budget)

        with patch(
            "aragora.server.handlers.costs.models._get_cost_tracker", return_value=mock_tracker
        ):
            response = await handler.handle_check_constraints(mock_request)

        data = json.loads(response.body)
        assert data["allowed"] is False
        assert "monthly budget" in data["reason"]

    @pytest.mark.asyncio
    async def test_constraints_exceeds_daily(self, handler, mock_request):
        """Constraint check blocks operation exceeding daily limit."""
        mock_request.json = AsyncMock(
            return_value={"estimated_cost_usd": 20, "workspace_id": "ws1"}
        )
        mock_budget = MagicMock()
        mock_budget.monthly_limit_usd = Decimal("10000")
        mock_budget.current_monthly_spend = Decimal("100")
        mock_budget.daily_limit_usd = Decimal("30")
        mock_budget.current_daily_spend = Decimal("25")

        mock_tracker = MagicMock()
        mock_tracker.get_budget = MagicMock(return_value=mock_budget)

        with patch(
            "aragora.server.handlers.costs.models._get_cost_tracker", return_value=mock_tracker
        ):
            response = await handler.handle_check_constraints(mock_request)

        data = json.loads(response.body)
        assert data["allowed"] is False
        assert "daily budget" in data["reason"]

    @pytest.mark.asyncio
    async def test_constraints_negative_cost(self, handler, mock_request):
        """Constraint check rejects negative estimated cost."""
        mock_request.json = AsyncMock(return_value={"estimated_cost_usd": -5})

        response = await handler.handle_check_constraints(mock_request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_constraints_no_tracker(self, handler, mock_request):
        """Constraint check allows by default when no tracker available."""
        mock_request.json = AsyncMock(return_value={"estimated_cost_usd": 100})

        with patch("aragora.server.handlers.costs.models._get_cost_tracker", return_value=None):
            response = await handler.handle_check_constraints(mock_request)

        data = json.loads(response.body)
        assert data["allowed"] is True


# ===========================================================================
# Cost estimation tests
# ===========================================================================


class TestEstimateCostHandler:
    """Tests for POST /api/v1/costs/estimate."""

    @pytest.mark.asyncio
    async def test_estimate_anthropic_opus(self, handler, mock_request):
        """Estimate cost for claude-opus-4 returns correct pricing."""
        mock_request.json = AsyncMock(
            return_value={
                "tokens_input": 1_000_000,
                "tokens_output": 1_000_000,
                "model": "claude-opus-4",
                "provider": "anthropic",
            }
        )

        response = await handler.handle_estimate_cost(mock_request)

        data = json.loads(response.body)
        assert data["estimated_cost_usd"] == 30.0  # 5 + 25
        assert data["pricing"]["input_per_1m"] == 5.00
        assert data["pricing"]["output_per_1m"] == 25.00

    @pytest.mark.asyncio
    async def test_estimate_unknown_provider_and_model(self, handler, mock_request):
        """The openrouter $2/$8 default is reached when the MODEL has no row
        anywhere, not merely when the provider label is unrecognised.

        This test used to omit ``model`` and so exercised the default
        ``claude-opus-4``, whose real $5/M row ``calculate_token_cost`` finds
        by exact spelling under any label -- the reported $2/M contradicted
        the cost the same response quoted (2026-09-05 wave-2 re-review).
        """
        mock_request.json = AsyncMock(
            return_value={
                "tokens_input": 1_000_000,
                "tokens_output": 0,
                "provider": "some_new_provider",
                "model": "totally-unknown-model-v0",
            }
        )

        response = await handler.handle_estimate_cost(mock_request)

        data = json.loads(response.body)
        assert data["pricing"]["input_per_1m"] == 2.00
        assert data["estimated_cost_usd"] == 2.00

    @pytest.mark.asyncio
    async def test_estimate_zero_tokens(self, handler, mock_request):
        """Zero tokens produces zero cost."""
        mock_request.json = AsyncMock(return_value={"tokens_input": 0, "tokens_output": 0})

        response = await handler.handle_estimate_cost(mock_request)

        data = json.loads(response.body)
        assert data["estimated_cost_usd"] == 0.0


# ===========================================================================
# Detailed forecast tests
# ===========================================================================


class TestDetailedForecastHandler:
    """Tests for GET /api/v1/costs/forecast/detailed."""

    @pytest.mark.asyncio
    async def test_detailed_forecast_with_confidence(self, handler, mock_request):
        """Detailed forecast includes confidence intervals by default."""
        mock_request.query = {"workspace_id": "test", "days": "7"}

        mock_report = MagicMock()
        mock_report.to_dict = MagicMock(return_value={"projected_cost": 700.0})

        mock_forecaster = MagicMock()
        mock_forecaster.generate_forecast = AsyncMock(return_value=mock_report)

        with patch("aragora.billing.forecaster.get_cost_forecaster", return_value=mock_forecaster):
            response = await handler.handle_get_forecast_detailed(mock_request)

        assert response.status == 200
        data = json.loads(response.body)
        assert len(data["daily_forecasts"]) == 7
        assert "confidence_low" in data["daily_forecasts"][0]
        assert "confidence_high" in data["daily_forecasts"][0]
        assert data["confidence_level"] == 0.80

    @pytest.mark.asyncio
    async def test_detailed_forecast_without_confidence(self, handler, mock_request):
        """Detailed forecast omits confidence when disabled."""
        mock_request.query = {"days": "3", "include_confidence": "false"}

        mock_report = MagicMock()
        mock_report.to_dict = MagicMock(return_value={"projected_cost": 300.0})

        mock_forecaster = MagicMock()
        mock_forecaster.generate_forecast = AsyncMock(return_value=mock_report)

        with patch("aragora.billing.forecaster.get_cost_forecaster", return_value=mock_forecaster):
            response = await handler.handle_get_forecast_detailed(mock_request)

        data = json.loads(response.body)
        assert "confidence_level" not in data
        assert "confidence_low" not in data["daily_forecasts"][0]


# ===========================================================================
# Detailed recommendations tests
# ===========================================================================


class TestDetailedRecommendationsHandler:
    """Tests for GET /api/v1/costs/recommendations/detailed."""

    @pytest.mark.asyncio
    async def test_detailed_recommendations_with_steps(self, handler, mock_request):
        """Detailed recommendations include implementation steps."""
        mock_request.query = {"workspace_id": "test"}

        mock_rec = MagicMock()
        mock_rec.to_dict = MagicMock(
            return_value={
                "id": "rec_1",
                "type": "model_downgrade",
                "estimated_savings_usd": 50.0,
            }
        )
        mock_summary = MagicMock()
        mock_summary.to_dict = MagicMock(return_value={"total": 50.0})

        mock_optimizer = MagicMock()
        mock_optimizer.get_workspace_recommendations = MagicMock(return_value=[mock_rec])
        mock_optimizer.get_summary = MagicMock(return_value=mock_summary)

        with patch("aragora.billing.optimizer.get_cost_optimizer", return_value=mock_optimizer):
            response = await handler.handle_get_recommendations_detailed(mock_request)

        data = json.loads(response.body)
        assert data["count"] == 1
        rec = data["recommendations"][0]
        assert "implementation_steps" in rec
        assert rec["difficulty"] == "easy"  # model_downgrade is easy

    @pytest.mark.asyncio
    async def test_detailed_recommendations_min_savings_filter(self, handler, mock_request):
        """Min savings filter excludes low-value recommendations."""
        mock_request.query = {"min_savings": "100"}

        mock_rec_low = MagicMock()
        mock_rec_low.to_dict = MagicMock(
            return_value={"type": "caching", "estimated_savings_usd": 20.0}
        )
        mock_rec_high = MagicMock()
        mock_rec_high.to_dict = MagicMock(
            return_value={"type": "batching", "estimated_savings_usd": 200.0}
        )
        mock_summary = MagicMock()
        mock_summary.to_dict = MagicMock(return_value={})

        mock_optimizer = MagicMock()
        mock_optimizer.get_workspace_recommendations = MagicMock(
            return_value=[mock_rec_low, mock_rec_high]
        )
        mock_optimizer.get_summary = MagicMock(return_value=mock_summary)

        with patch("aragora.billing.optimizer.get_cost_optimizer", return_value=mock_optimizer):
            response = await handler.handle_get_recommendations_detailed(mock_request)

        data = json.loads(response.body)
        assert data["count"] == 1
        assert data["recommendations"][0]["estimated_savings_usd"] == 200.0


# ===========================================================================
# Alert creation tests
# ===========================================================================


class TestCreateAlertHandler:
    """Tests for POST /api/v1/costs/alerts."""

    @pytest.mark.asyncio
    async def test_create_alert_success(self, handler, mock_request):
        """Creating alert returns 201 with alert details."""
        mock_request.json = AsyncMock(
            return_value={
                "name": "High spend alert",
                "type": "budget_threshold",
                "threshold": 90,
                "notification_channels": ["email", "slack"],
            }
        )

        response = await handler.handle_create_alert(mock_request)

        assert response.status == 201
        data = json.loads(response.body)
        assert data["success"] is True
        assert data["alert"]["name"] == "High spend alert"
        assert data["alert"]["type"] == "budget_threshold"
        assert data["alert"]["active"] is True

    @pytest.mark.asyncio
    async def test_create_alert_missing_name(self, handler, mock_request):
        """Creating alert without name returns 400."""
        mock_request.json = AsyncMock(return_value={"type": "budget_threshold", "threshold": 80})

        response = await handler.handle_create_alert(mock_request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_create_alert_invalid_type(self, handler, mock_request):
        """Creating alert with invalid type returns 400."""
        mock_request.json = AsyncMock(
            return_value={"name": "Bad alert", "type": "nonexistent_type"}
        )

        response = await handler.handle_create_alert(mock_request)

        assert response.status == 400
        data = json.loads(response.body)
        assert "Invalid alert type" in data["error"]


# ===========================================================================
# Edge case tests
# ===========================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_timeline_empty_daily_costs(self, handler, mock_request):
        """Timeline with empty daily costs returns zero average."""
        with patch("aragora.server.handlers.costs.models.get_cost_summary") as m:
            m.return_value = _make_summary(total_cost=0.0, daily_costs=[])
            response = await handler.handle_get_timeline(mock_request)

        data = json.loads(response.body)
        assert data["data"]["average_daily_cost"] == 0

    @pytest.mark.asyncio
    async def test_breakdown_unknown_group_by(self, handler, mock_request):
        """Unknown group_by falls back to provider breakdown."""
        mock_request.query = {"group_by": "unknown_field"}

        with patch("aragora.server.handlers.costs.models.get_cost_summary") as m:
            m.return_value = _make_summary()
            response = await handler.handle_get_breakdown(mock_request)

        data = json.loads(response.body)
        assert data["data"]["by_provider"][0]["name"] == "Anthropic"

    @pytest.mark.asyncio
    async def test_efficiency_zero_tokens_and_calls(self, handler, mock_request):
        """Efficiency with zero tokens and calls avoids division by zero."""
        mock_tracker = MagicMock()
        mock_tracker.get_workspace_stats = MagicMock(
            return_value={
                "total_tokens_in": 0,
                "total_tokens_out": 0,
                "total_api_calls": 0,
                "total_cost_usd": Decimal("0"),
                "cost_by_model": {},
            }
        )

        with patch(
            "aragora.server.handlers.costs.models._get_cost_tracker", return_value=mock_tracker
        ):
            response = await handler.handle_get_efficiency(mock_request)

        assert response.status == 200
        data = json.loads(response.body)
        assert data["data"]["cost_per_1k_tokens"] == 0
        assert data["data"]["avg_tokens_per_call"] == 0
        assert data["data"]["cost_per_call"] == 0

    @pytest.mark.asyncio
    async def test_handler_init_default_context(self):
        """Handler initializes with empty dict when no context given."""
        h = CostHandler()
        assert h.ctx == {}

    @pytest.mark.asyncio
    async def test_handler_init_custom_context(self):
        """Handler stores provided context."""
        ctx = {"storage": MagicMock()}
        h = CostHandler(ctx=ctx)
        assert h.ctx is ctx
