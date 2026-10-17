"""Tests for cost visibility handler (aragora/server/handlers/costs/handler.py).

Covers all routes and behavior of the CostHandler class:
- ROUTES list coverage for route matching
- GET /api/v1/costs - Cost summary dashboard
- GET /api/v1/costs/breakdown - Cost breakdown by provider/feature
- GET /api/v1/costs/timeline - Cost timeline data
- GET /api/v1/costs/alerts - Budget alerts
- POST /api/v1/costs/alerts - Create cost alert
- POST /api/v1/costs/alerts/{alert_id}/dismiss - Dismiss alert
- POST /api/v1/costs/budget - Set budget
- GET /api/v1/costs/budgets - List budgets
- POST /api/v1/costs/budgets - Create budget
- GET /api/v1/costs/recommendations - Get recommendations
- GET /api/v1/costs/recommendations/detailed - Detailed recommendations
- GET /api/v1/costs/recommendations/{id} - Get single recommendation
- POST /api/v1/costs/recommendations/{id}/apply - Apply recommendation
- POST /api/v1/costs/recommendations/{id}/dismiss - Dismiss recommendation
- GET /api/v1/costs/efficiency - Efficiency metrics
- GET /api/v1/costs/forecast - Cost forecast
- GET /api/v1/costs/forecast/detailed - Detailed forecast
- POST /api/v1/costs/forecast/simulate - Simulate cost scenario
- GET /api/v1/costs/export - Export cost data (CSV/JSON)
- GET /api/v1/costs/usage - Usage tracking
- POST /api/v1/costs/constraints/check - Check budget constraints
- POST /api/v1/costs/estimate - Estimate operation cost
- Error handling and edge cases
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp.test_utils import make_mocked_request

from aragora.server.handlers.costs.handler import CostHandler
from aragora.server.handlers.costs.models import CostSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    method: str = "GET",
    path: str = "/api/v1/costs",
    query: str = "",
    body: dict[str, Any] | None = None,
    match_info: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock aiohttp request with given parameters."""
    full_path = f"{path}?{query}" if query else path
    request = make_mocked_request(method, full_path)

    if match_info:
        request.match_info.update(match_info)

    if body is not None:
        request.json = AsyncMock(return_value=body)
        request.text = AsyncMock(return_value=json.dumps(body))
        request.read = AsyncMock(return_value=json.dumps(body).encode())

    return request


def _parse_response(response) -> dict[str, Any]:
    """Parse response body as JSON."""
    return json.loads(response.body)


def _parse_data(response) -> dict[str, Any]:
    """Parse response body and unwrap the 'data' envelope."""
    body = json.loads(response.body)
    return body.get("data", body)


def _make_cost_summary(**overrides) -> CostSummary:
    """Create a CostSummary with sensible defaults."""
    now = datetime.now(timezone.utc)
    defaults = {
        "total_cost": 125.50,
        "budget": 500.00,
        "tokens_used": 3_125_000,
        "api_calls": 12_550,
        "last_updated": now,
        "cost_by_provider": [
            {"name": "Anthropic", "cost": 77.31, "percentage": 61.6},
            {"name": "OpenAI", "cost": 34.64, "percentage": 27.6},
        ],
        "cost_by_feature": [
            {"name": "Debates", "cost": 54.22, "percentage": 43.2},
            {"name": "Code Review", "cost": 22.46, "percentage": 17.9},
        ],
        "daily_costs": [
            {"date": "2026-02-20", "cost": 18.50, "tokens": 462500},
            {"date": "2026-02-21", "cost": 21.00, "tokens": 525000},
        ],
        "alerts": [
            {
                "id": "1",
                "type": "budget_warning",
                "message": "Projected to reach 80% of budget",
                "severity": "warning",
                "timestamp": now.isoformat(),
            }
        ],
    }
    defaults.update(overrides)
    return CostSummary(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a CostHandler instance."""
    return CostHandler(ctx={})


# ---------------------------------------------------------------------------
# ROUTES list coverage
# ---------------------------------------------------------------------------


class TestRoutes:
    """Verify ROUTES list contains all expected paths."""

    def test_routes_contains_versioned_costs(self, handler):
        assert "/api/v1/costs" in CostHandler.ROUTES

    def test_routes_contains_legacy_costs(self, handler):
        assert "/api/costs" in CostHandler.ROUTES

    def test_routes_contains_versioned_alerts(self, handler):
        assert "/api/v1/costs/alerts" in CostHandler.ROUTES

    def test_routes_contains_versioned_breakdown(self, handler):
        assert "/api/v1/costs/breakdown" in CostHandler.ROUTES

    def test_routes_contains_versioned_budget(self, handler):
        assert "/api/v1/costs/budget" in CostHandler.ROUTES

    def test_routes_contains_versioned_budgets(self, handler):
        assert "/api/v1/costs/budgets" in CostHandler.ROUTES

    def test_routes_contains_versioned_constraints_check(self, handler):
        assert "/api/v1/costs/constraints/check" in CostHandler.ROUTES

    def test_routes_contains_versioned_efficiency(self, handler):
        assert "/api/v1/costs/efficiency" in CostHandler.ROUTES

    def test_routes_contains_versioned_estimate(self, handler):
        assert "/api/v1/costs/estimate" in CostHandler.ROUTES

    def test_routes_contains_versioned_export(self, handler):
        assert "/api/v1/costs/export" in CostHandler.ROUTES

    def test_routes_contains_versioned_forecast(self, handler):
        assert "/api/v1/costs/forecast" in CostHandler.ROUTES

    def test_routes_contains_versioned_forecast_detailed(self, handler):
        assert "/api/v1/costs/forecast/detailed" in CostHandler.ROUTES

    def test_routes_contains_versioned_forecast_simulate(self, handler):
        assert "/api/v1/costs/forecast/simulate" in CostHandler.ROUTES

    def test_routes_contains_versioned_recommendations(self, handler):
        assert "/api/v1/costs/recommendations" in CostHandler.ROUTES

    def test_routes_contains_versioned_recommendations_detailed(self, handler):
        assert "/api/v1/costs/recommendations/detailed" in CostHandler.ROUTES

    def test_routes_contains_versioned_recommendations_wildcard(self, handler):
        assert "/api/v1/costs/recommendations/*" in CostHandler.ROUTES

    def test_routes_contains_versioned_recommendations_apply(self, handler):
        assert "/api/v1/costs/recommendations/*/apply" in CostHandler.ROUTES

    def test_routes_contains_versioned_recommendations_dismiss(self, handler):
        assert "/api/v1/costs/recommendations/*/dismiss" in CostHandler.ROUTES

    def test_routes_contains_versioned_timeline(self, handler):
        assert "/api/v1/costs/timeline" in CostHandler.ROUTES

    def test_routes_contains_versioned_usage(self, handler):
        assert "/api/v1/costs/usage" in CostHandler.ROUTES

    def test_routes_contains_versioned_alerts_dismiss(self, handler):
        assert "/api/v1/costs/alerts/*/dismiss" in CostHandler.ROUTES

    def test_routes_has_expected_count(self, handler):
        """Both versioned and legacy routes should exist."""
        assert len(CostHandler.ROUTES) == 56  # 28 versioned + 28 legacy

    def test_every_versioned_route_has_legacy_counterpart(self, handler):
        """Each /api/v1/costs/... route should have a /api/costs/... counterpart."""
        versioned = [r for r in CostHandler.ROUTES if r.startswith("/api/v1/")]
        for route in versioned:
            legacy = route.replace("/api/v1/", "/api/")
            assert legacy in CostHandler.ROUTES, f"Missing legacy route for {route}"


# ---------------------------------------------------------------------------
# GET /api/v1/costs
# ---------------------------------------------------------------------------


class TestGetCosts:
    """Tests for cost summary endpoint."""

    @pytest.mark.asyncio
    async def test_returns_cost_summary(self, handler):
        request = _make_request("GET", "/api/v1/costs")
        summary = _make_cost_summary()

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            response = await handler.handle_get_costs(request)

        assert response.status == 200
        data = _parse_data(response)
        assert data["total_cost_usd"] == 125.50
        assert data["budget_usd"] == 500.00
        assert "tokens_in" in data
        assert "api_calls" in data
        assert "period_start" in data
        assert "period_end" in data

    @pytest.mark.asyncio
    async def test_default_query_params(self, handler):
        """Default range=7d and workspace_id=default."""
        request = _make_request("GET", "/api/v1/costs")
        summary = _make_cost_summary()

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ) as mock_get:
            await handler.handle_get_costs(request)

        mock_get.assert_called_once_with(workspace_id="default", time_range="7d")

    @pytest.mark.asyncio
    async def test_custom_query_params(self, handler):
        """Custom range and workspace_id are forwarded."""
        request = _make_request("GET", "/api/v1/costs", query="range=30d&workspace_id=ws-123")
        summary = _make_cost_summary()

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ) as mock_get:
            await handler.handle_get_costs(request)

        mock_get.assert_called_once_with(workspace_id="ws-123", time_range="30d")

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        request = _make_request("GET", "/api/v1/costs")

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            side_effect=ValueError("broken"),
        ):
            response = await handler.handle_get_costs(request)

        assert response.status == 500

    @pytest.mark.asyncio
    async def test_empty_cost_summary(self, handler):
        """Zero-cost summary is returned correctly."""
        request = _make_request("GET", "/api/v1/costs")
        summary = _make_cost_summary(
            total_cost=0.0,
            tokens_used=0,
            api_calls=0,
            cost_by_provider=[],
            cost_by_feature=[],
            daily_costs=[],
            alerts=[],
        )

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            response = await handler.handle_get_costs(request)

        assert response.status == 200
        data = _parse_data(response)
        assert data["total_cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# GET /api/v1/costs/breakdown
# ---------------------------------------------------------------------------


class TestGetBreakdown:
    """Tests for cost breakdown endpoint."""

    @pytest.mark.asyncio
    async def test_breakdown_by_provider(self, handler):
        request = _make_request("GET", "/api/v1/costs/breakdown", query="group_by=provider")
        summary = _make_cost_summary()

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            response = await handler.handle_get_breakdown(request)

        assert response.status == 200
        data = _parse_data(response)
        assert "by_provider" in data
        assert isinstance(data["by_provider"], list)

    @pytest.mark.asyncio
    async def test_breakdown_by_feature(self, handler):
        request = _make_request("GET", "/api/v1/costs/breakdown", query="group_by=feature")
        summary = _make_cost_summary()

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            response = await handler.handle_get_breakdown(request)

        data = _parse_data(response)
        assert "by_feature" in data
        assert isinstance(data["by_feature"], list)

    @pytest.mark.asyncio
    async def test_breakdown_unknown_group_defaults_to_provider(self, handler):
        request = _make_request("GET", "/api/v1/costs/breakdown", query="group_by=unknown")
        summary = _make_cost_summary()

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            response = await handler.handle_get_breakdown(request)

        data = _parse_data(response)
        assert "by_provider" in data

    @pytest.mark.asyncio
    async def test_breakdown_error_returns_500(self, handler):
        request = _make_request("GET", "/api/v1/costs/breakdown")

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ):
            response = await handler.handle_get_breakdown(request)

        assert response.status == 500


# ---------------------------------------------------------------------------
# GET /api/v1/costs/timeline
# ---------------------------------------------------------------------------


class TestGetTimeline:
    """Tests for cost timeline endpoint."""

    @pytest.mark.asyncio
    async def test_timeline_returns_data(self, handler):
        request = _make_request("GET", "/api/v1/costs/timeline")
        summary = _make_cost_summary()

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            response = await handler.handle_get_timeline(request)

        assert response.status == 200
        data = _parse_data(response)
        assert "data_points" in data
        assert data["total_cost"] == 125.50
        # average = 125.50 / 2 daily_costs entries
        assert data["average_daily_cost"] == pytest.approx(62.75)

    @pytest.mark.asyncio
    async def test_timeline_empty_daily_costs_average_zero(self, handler):
        request = _make_request("GET", "/api/v1/costs/timeline")
        summary = _make_cost_summary(daily_costs=[])

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            response = await handler.handle_get_timeline(request)

        data = _parse_data(response)
        assert data["average_daily_cost"] == 0

    @pytest.mark.asyncio
    async def test_timeline_error_returns_500(self, handler):
        request = _make_request("GET", "/api/v1/costs/timeline")

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            side_effect=TypeError("bad"),
        ):
            response = await handler.handle_get_timeline(request)

        assert response.status == 500


# ---------------------------------------------------------------------------
# GET /api/v1/costs/alerts
# ---------------------------------------------------------------------------


class TestGetAlerts:
    """Tests for budget alerts endpoint."""

    @pytest.mark.asyncio
    async def test_alerts_with_tracker(self, handler):
        mock_tracker = MagicMock()
        mock_tracker.query_km_workspace_alerts.return_value = []

        with (
            patch(
                "aragora.server.handlers.costs.handler._models._get_cost_tracker",
                return_value=mock_tracker,
            ),
            patch(
                "aragora.server.handlers.costs.handler._models._get_active_alerts",
                return_value=[
                    {
                        "id": "alert-1",
                        "type": "budget_warning",
                        "message": "80% usage",
                        "severity": "warning",
                    }
                ],
            ),
        ):
            request = _make_request("GET", "/api/v1/costs/alerts")
            response = await handler.handle_get_alerts(request)

        assert response.status == 200
        data = _parse_data(response)
        assert "alerts" in data
        assert len(data["alerts"]) == 1
        assert data["alerts"][0]["id"] == "alert-1"

    @pytest.mark.asyncio
    async def test_alerts_without_tracker(self, handler):
        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            return_value=None,
        ):
            request = _make_request("GET", "/api/v1/costs/alerts")
            response = await handler.handle_get_alerts(request)

        assert response.status == 200
        data = _parse_data(response)
        assert data["alerts"] == []

    @pytest.mark.asyncio
    async def test_alerts_includes_km_alerts(self, handler):
        mock_tracker = MagicMock()
        mock_tracker.query_km_workspace_alerts.return_value = [
            {
                "id": "km-1",
                "level": "warning",
                "message": "KM alert",
                "acknowledged": False,
                "created_at": "2026-02-20T00:00:00Z",
            },
        ]

        with (
            patch(
                "aragora.server.handlers.costs.handler._models._get_cost_tracker",
                return_value=mock_tracker,
            ),
            patch(
                "aragora.server.handlers.costs.handler._models._get_active_alerts",
                return_value=[],
            ),
        ):
            request = _make_request("GET", "/api/v1/costs/alerts")
            response = await handler.handle_get_alerts(request)

        data = _parse_data(response)
        assert len(data["alerts"]) == 1
        assert data["alerts"][0]["id"] == "km-1"
        assert data["alerts"][0]["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_alerts_skips_acknowledged_km_alerts(self, handler):
        mock_tracker = MagicMock()
        mock_tracker.query_km_workspace_alerts.return_value = [
            {"id": "km-1", "level": "warning", "message": "acknowledged", "acknowledged": True},
        ]

        with (
            patch(
                "aragora.server.handlers.costs.handler._models._get_cost_tracker",
                return_value=mock_tracker,
            ),
            patch(
                "aragora.server.handlers.costs.handler._models._get_active_alerts",
                return_value=[],
            ),
        ):
            request = _make_request("GET", "/api/v1/costs/alerts")
            response = await handler.handle_get_alerts(request)

        data = _parse_data(response)
        assert data["alerts"] == []

    @pytest.mark.asyncio
    async def test_alerts_error_returns_500(self, handler):
        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            side_effect=AttributeError("fail"),
        ):
            request = _make_request("GET", "/api/v1/costs/alerts")
            response = await handler.handle_get_alerts(request)

        assert response.status == 500


# ---------------------------------------------------------------------------
# POST /api/v1/costs/budget
# ---------------------------------------------------------------------------


class TestSetBudget:
    """Tests for setting budget endpoint."""

    @pytest.mark.asyncio
    async def test_set_budget_success(self, handler):
        body = {"budget": 1000, "workspace_id": "ws-1", "daily_limit": 50, "name": "My Budget"}
        request = _make_request("POST", "/api/v1/costs/budget", body=body)
        mock_tracker = MagicMock()

        with (
            patch(
                "aragora.server.handlers.costs.handler._models._get_cost_tracker",
                return_value=mock_tracker,
            ),
            patch(
                "aragora.server.handlers.costs.handler.parse_json_body",
                new_callable=AsyncMock,
                return_value=(body, None),
            ),
        ):
            response = await handler.handle_set_budget(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["success"] is True
        assert data["budget"] == 1000
        assert data["workspace_id"] == "ws-1"
        assert data["daily_limit"] == 50

    @pytest.mark.asyncio
    async def test_set_budget_negative_amount(self, handler):
        body = {"budget": -100}
        request = _make_request("POST", "/api/v1/costs/budget", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_set_budget(request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_set_budget_missing_amount(self, handler):
        body = {"workspace_id": "ws-1"}
        request = _make_request("POST", "/api/v1/costs/budget", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_set_budget(request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_set_budget_no_tracker(self, handler):
        """Budget is accepted even without tracker (just logs)."""
        body = {"budget": 500}
        request = _make_request("POST", "/api/v1/costs/budget", body=body)

        with (
            patch(
                "aragora.server.handlers.costs.handler._models._get_cost_tracker",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.costs.handler.parse_json_body",
                new_callable=AsyncMock,
                return_value=(body, None),
            ),
        ):
            response = await handler.handle_set_budget(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_set_budget_parse_error(self, handler):
        """When parse_json_body returns an error, return that error."""
        from aiohttp import web

        err_response = web.json_response({"error": "Invalid JSON"}, status=400)
        request = _make_request("POST", "/api/v1/costs/budget", body={})

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(None, err_response),
        ):
            response = await handler.handle_set_budget(request)

        assert response.status == 400


# ---------------------------------------------------------------------------
# POST /api/v1/costs/alerts/{alert_id}/dismiss
# ---------------------------------------------------------------------------


class TestDismissAlert:
    """Tests for dismissing alerts."""

    @pytest.mark.asyncio
    async def test_dismiss_alert_success(self, handler):
        request = _make_request(
            "POST",
            "/api/v1/costs/alerts/alert-123/dismiss",
            match_info={"alert_id": "alert-123"},
        )

        response = await handler.handle_dismiss_alert(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["success"] is True
        assert data["alert_id"] == "alert-123"
        assert data["dismissed"] is True

    @pytest.mark.asyncio
    async def test_dismiss_alert_with_workspace(self, handler):
        request = _make_request(
            "POST",
            "/api/v1/costs/alerts/alert-456/dismiss",
            query="workspace_id=ws-custom",
            match_info={"alert_id": "alert-456"},
        )

        response = await handler.handle_dismiss_alert(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["alert_id"] == "alert-456"


# ---------------------------------------------------------------------------
# POST /api/v1/costs/alerts (create)
# ---------------------------------------------------------------------------


class TestCreateAlert:
    """Tests for creating cost alerts."""

    @pytest.mark.asyncio
    async def test_create_alert_success(self, handler):
        body = {
            "workspace_id": "ws-1",
            "name": "High Spend Alert",
            "type": "budget_threshold",
            "threshold": 90,
            "notification_channels": ["email", "slack"],
        }
        request = _make_request("POST", "/api/v1/costs/alerts", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_create_alert(request)

        assert response.status == 201
        data = _parse_response(response)
        assert data["success"] is True
        assert data["alert"]["name"] == "High Spend Alert"
        assert data["alert"]["type"] == "budget_threshold"
        assert data["alert"]["threshold"] == 90
        assert data["alert"]["active"] is True
        assert data["alert"]["id"].startswith("alert_")

    @pytest.mark.asyncio
    async def test_create_alert_missing_name(self, handler):
        body = {"type": "budget_threshold", "threshold": 80}
        request = _make_request("POST", "/api/v1/costs/alerts", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_create_alert(request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_create_alert_invalid_type(self, handler):
        body = {"name": "My Alert", "type": "invalid_type"}
        request = _make_request("POST", "/api/v1/costs/alerts", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_create_alert(request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_create_alert_spike_detection_type(self, handler):
        body = {"name": "Spike Alert", "type": "spike_detection", "threshold": 2.0}
        request = _make_request("POST", "/api/v1/costs/alerts", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_create_alert(request)

        assert response.status == 201
        data = _parse_response(response)
        assert data["alert"]["type"] == "spike_detection"

    @pytest.mark.asyncio
    async def test_create_alert_daily_limit_type(self, handler):
        body = {"name": "Daily Limit Alert", "type": "daily_limit"}
        request = _make_request("POST", "/api/v1/costs/alerts", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_create_alert(request)

        assert response.status == 201


# ---------------------------------------------------------------------------
# GET /api/v1/costs/recommendations
# ---------------------------------------------------------------------------


class TestGetRecommendations:
    """Tests for recommendations endpoint."""

    @pytest.mark.asyncio
    async def test_get_recommendations(self, handler):
        mock_rec = MagicMock()
        mock_rec.to_dict.return_value = {
            "id": "rec-1",
            "type": "model_downgrade",
            "estimated_savings_usd": 50.0,
            "status": "pending",
        }

        mock_summary = MagicMock()
        mock_summary.to_dict.return_value = {"total_savings": 50.0, "count": 1}

        mock_optimizer = MagicMock()
        mock_optimizer.get_workspace_recommendations.return_value = [mock_rec]
        mock_optimizer.get_summary.return_value = mock_summary

        request = _make_request("GET", "/api/v1/costs/recommendations")

        with (
            patch(
                "aragora.billing.optimizer.get_cost_optimizer",
                return_value=mock_optimizer,
            ),
            patch(
                "aragora.billing.recommendations.RecommendationStatus",
            ),
            patch(
                "aragora.billing.recommendations.RecommendationType",
            ),
        ):
            response = await handler.handle_get_recommendations(request)

        assert response.status == 200
        data = _parse_data(response)
        assert "recommendations" in data
        assert "summary" in data

    @pytest.mark.asyncio
    async def test_get_recommendations_error(self, handler):
        request = _make_request("GET", "/api/v1/costs/recommendations")

        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            side_effect=ImportError("no optimizer"),
        ):
            response = await handler.handle_get_recommendations(request)

        assert response.status == 500


# ---------------------------------------------------------------------------
# GET /api/v1/costs/recommendations/{recommendation_id}
# ---------------------------------------------------------------------------


class TestGetRecommendation:
    """Tests for single recommendation endpoint."""

    @pytest.mark.asyncio
    async def test_get_recommendation_found(self, handler):
        mock_rec = MagicMock()
        mock_rec.to_dict.return_value = {"id": "rec-1", "type": "caching"}

        mock_optimizer = MagicMock()
        mock_optimizer.get_recommendation.return_value = mock_rec

        request = _make_request(
            "GET",
            "/api/v1/costs/recommendations/rec-1",
            match_info={"recommendation_id": "rec-1"},
        )

        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            return_value=mock_optimizer,
        ):
            response = await handler.handle_get_recommendation(request)

        assert response.status == 200

    @pytest.mark.asyncio
    async def test_get_recommendation_not_found(self, handler):
        mock_optimizer = MagicMock()
        mock_optimizer.get_recommendation.return_value = None

        request = _make_request(
            "GET",
            "/api/v1/costs/recommendations/rec-nonexistent",
            match_info={"recommendation_id": "rec-nonexistent"},
        )

        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            return_value=mock_optimizer,
        ):
            response = await handler.handle_get_recommendation(request)

        assert response.status == 404

    @pytest.mark.asyncio
    async def test_get_recommendation_error(self, handler):
        request = _make_request(
            "GET",
            "/api/v1/costs/recommendations/rec-1",
            match_info={"recommendation_id": "rec-1"},
        )

        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            side_effect=RuntimeError("failed"),
        ):
            response = await handler.handle_get_recommendation(request)

        assert response.status == 500


# ---------------------------------------------------------------------------
# POST /api/v1/costs/recommendations/{recommendation_id}/apply
# ---------------------------------------------------------------------------


class TestApplyRecommendation:
    """Tests for applying a recommendation."""

    @pytest.mark.asyncio
    async def test_apply_recommendation_success(self, handler):
        mock_rec = MagicMock()
        mock_rec.to_dict.return_value = {"id": "rec-1", "status": "applied"}

        mock_optimizer = MagicMock()
        mock_optimizer.apply_recommendation.return_value = True
        mock_optimizer.get_recommendation.return_value = mock_rec

        body = {"user_id": "user-1"}
        request = _make_request(
            "POST",
            "/api/v1/costs/recommendations/rec-1/apply",
            body=body,
            match_info={"recommendation_id": "rec-1"},
        )

        with (
            patch(
                "aragora.billing.optimizer.get_cost_optimizer",
                return_value=mock_optimizer,
            ),
            patch(
                "aragora.server.handlers.costs.handler.parse_json_body",
                new_callable=AsyncMock,
                return_value=(body, None),
            ),
        ):
            response = await handler.handle_apply_recommendation(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_apply_recommendation_not_found(self, handler):
        mock_optimizer = MagicMock()
        mock_optimizer.apply_recommendation.return_value = False

        body = {"user_id": "user-1"}
        request = _make_request(
            "POST",
            "/api/v1/costs/recommendations/rec-missing/apply",
            body=body,
            match_info={"recommendation_id": "rec-missing"},
        )

        with (
            patch(
                "aragora.billing.optimizer.get_cost_optimizer",
                return_value=mock_optimizer,
            ),
            patch(
                "aragora.server.handlers.costs.handler.parse_json_body",
                new_callable=AsyncMock,
                return_value=(body, None),
            ),
        ):
            response = await handler.handle_apply_recommendation(request)

        assert response.status == 404


# ---------------------------------------------------------------------------
# POST /api/v1/costs/recommendations/{recommendation_id}/dismiss
# ---------------------------------------------------------------------------


class TestDismissRecommendation:
    """Tests for dismissing a recommendation."""

    @pytest.mark.asyncio
    async def test_dismiss_recommendation_success(self, handler):
        mock_optimizer = MagicMock()
        mock_optimizer.dismiss_recommendation.return_value = True

        request = _make_request(
            "POST",
            "/api/v1/costs/recommendations/rec-1/dismiss",
            match_info={"recommendation_id": "rec-1"},
        )

        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            return_value=mock_optimizer,
        ):
            response = await handler.handle_dismiss_recommendation(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["success"] is True
        assert data["dismissed"] is True

    @pytest.mark.asyncio
    async def test_dismiss_recommendation_not_found(self, handler):
        mock_optimizer = MagicMock()
        mock_optimizer.dismiss_recommendation.return_value = False

        request = _make_request(
            "POST",
            "/api/v1/costs/recommendations/rec-missing/dismiss",
            match_info={"recommendation_id": "rec-missing"},
        )

        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            return_value=mock_optimizer,
        ):
            response = await handler.handle_dismiss_recommendation(request)

        assert response.status == 404


# ---------------------------------------------------------------------------
# GET /api/v1/costs/efficiency
# ---------------------------------------------------------------------------


class TestGetEfficiency:
    """Tests for efficiency metrics endpoint."""

    @pytest.mark.asyncio
    async def test_efficiency_metrics(self, handler):
        mock_tracker = MagicMock()
        mock_tracker.get_workspace_stats.return_value = {
            "total_tokens_in": 500_000,
            "total_tokens_out": 200_000,
            "total_api_calls": 1000,
            "total_cost_usd": "70.00",
            "cost_by_model": {
                "claude-3-opus": Decimal("50.00"),
                "gpt-4": Decimal("20.00"),
            },
        }

        request = _make_request(
            "GET", "/api/v1/costs/efficiency", query="workspace_id=ws-1&range=30d"
        )

        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            return_value=mock_tracker,
        ):
            response = await handler.handle_get_efficiency(request)

        assert response.status == 200
        data = _parse_data(response)
        assert data["cost_per_1k_tokens"] == pytest.approx(0.1, abs=0.001)
        assert data["avg_tokens_per_call"] == 700.0
        assert data["cost_per_call"] == 0.07
        assert "efficiency_score" in data
        assert "cache_hit_rate" in data

    @pytest.mark.asyncio
    async def test_efficiency_no_tracker(self, handler):
        request = _make_request("GET", "/api/v1/costs/efficiency")

        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            return_value=None,
        ):
            response = await handler.handle_get_efficiency(request)

        assert response.status == 503

    @pytest.mark.asyncio
    async def test_efficiency_zero_tokens(self, handler):
        mock_tracker = MagicMock()
        mock_tracker.get_workspace_stats.return_value = {
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_api_calls": 0,
            "total_cost_usd": "0",
            "cost_by_model": {},
        }

        request = _make_request("GET", "/api/v1/costs/efficiency")

        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            return_value=mock_tracker,
        ):
            response = await handler.handle_get_efficiency(request)

        assert response.status == 200
        data = _parse_data(response)
        assert data["cost_per_1k_tokens"] == 0
        assert data["avg_tokens_per_call"] == 0
        assert data["cost_per_call"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/costs/forecast
# ---------------------------------------------------------------------------


class TestGetForecast:
    """Tests for cost forecast endpoint."""

    @pytest.mark.asyncio
    async def test_get_forecast(self, handler):
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {
            "projected_monthly_cost": 300.0,
            "projected_end_of_month": 280.0,
            "trend": "increasing",
            "confidence": 0.85,
        }

        mock_forecaster = MagicMock()
        mock_forecaster.generate_forecast = AsyncMock(return_value=mock_report)

        request = _make_request("GET", "/api/v1/costs/forecast", query="workspace_id=ws-1&days=60")

        with patch(
            "aragora.billing.forecaster.get_cost_forecaster",
            return_value=mock_forecaster,
        ):
            response = await handler.handle_get_forecast(request)

        assert response.status == 200
        data = _parse_data(response)
        assert data["projected_monthly_cost"] == 300.0
        assert data["confidence"] == 0.85
        assert data["trend"] == "increasing"

    @pytest.mark.asyncio
    async def test_get_forecast_error(self, handler):
        request = _make_request("GET", "/api/v1/costs/forecast")

        with patch(
            "aragora.billing.forecaster.get_cost_forecaster",
            side_effect=ImportError("no forecaster"),
        ):
            response = await handler.handle_get_forecast(request)

        assert response.status == 500


# ---------------------------------------------------------------------------
# GET /api/v1/costs/forecast/detailed
# ---------------------------------------------------------------------------


class TestGetForecastDetailed:
    """Tests for detailed forecast endpoint."""

    @pytest.mark.asyncio
    async def test_detailed_forecast_with_confidence(self, handler):
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {
            "projected_cost": 150.0,
            "confidence": 0.80,
        }

        mock_forecaster = MagicMock()
        mock_forecaster.generate_forecast = AsyncMock(return_value=mock_report)

        request = _make_request(
            "GET",
            "/api/v1/costs/forecast/detailed",
            query="days=7&include_confidence=true",
        )

        with patch(
            "aragora.billing.forecaster.get_cost_forecaster",
            return_value=mock_forecaster,
        ):
            response = await handler.handle_get_forecast_detailed(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["forecast_days"] == 7
        assert "daily_forecasts" in data
        assert len(data["daily_forecasts"]) == 7
        assert "confidence_low" in data["daily_forecasts"][0]
        assert "confidence_high" in data["daily_forecasts"][0]
        assert data["confidence_level"] == 0.80

    @pytest.mark.asyncio
    async def test_detailed_forecast_without_confidence(self, handler):
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {"projected_cost": 100.0}

        mock_forecaster = MagicMock()
        mock_forecaster.generate_forecast = AsyncMock(return_value=mock_report)

        request = _make_request(
            "GET",
            "/api/v1/costs/forecast/detailed",
            query="days=3&include_confidence=false",
        )

        with patch(
            "aragora.billing.forecaster.get_cost_forecaster",
            return_value=mock_forecaster,
        ):
            response = await handler.handle_get_forecast_detailed(request)

        assert response.status == 200
        data = _parse_response(response)
        assert len(data["daily_forecasts"]) == 3
        assert "confidence_low" not in data["daily_forecasts"][0]
        assert "confidence_level" not in data


# ---------------------------------------------------------------------------
# POST /api/v1/costs/forecast/simulate
# ---------------------------------------------------------------------------


class TestSimulateForecast:
    """Tests for forecast simulation endpoint."""

    @pytest.mark.asyncio
    async def test_simulate_forecast(self, handler):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "scenario": "Custom Scenario",
            "projected_cost": 200.0,
        }

        mock_forecaster = MagicMock()
        mock_forecaster.simulate_scenario = AsyncMock(return_value=mock_result)

        body = {
            "workspace_id": "ws-1",
            "scenario": {
                "name": "Double usage",
                "description": "What if usage doubles",
                "changes": {"multiplier": 2.0},
            },
            "days": 30,
        }
        request = _make_request("POST", "/api/v1/costs/forecast/simulate", body=body)

        with (
            patch(
                "aragora.billing.forecaster.get_cost_forecaster",
                return_value=mock_forecaster,
            ),
            patch(
                "aragora.billing.forecaster.SimulationScenario",
            ) as mock_scenario_cls,
            patch(
                "aragora.server.handlers.costs.handler.parse_json_body",
                new_callable=AsyncMock,
                return_value=(body, None),
            ),
        ):
            response = await handler.handle_simulate_forecast(request)

        assert response.status == 200

    @pytest.mark.asyncio
    async def test_simulate_forecast_error(self, handler):
        body = {"scenario": {}}
        request = _make_request("POST", "/api/v1/costs/forecast/simulate", body=body)

        with (
            patch(
                "aragora.server.handlers.costs.handler.parse_json_body",
                new_callable=AsyncMock,
                return_value=(body, None),
            ),
            patch(
                "aragora.billing.forecaster.get_cost_forecaster",
                side_effect=ImportError("no forecaster"),
            ),
        ):
            response = await handler.handle_simulate_forecast(request)

        assert response.status == 500


# ---------------------------------------------------------------------------
# GET /api/v1/costs/export
# ---------------------------------------------------------------------------


class TestExport:
    """Tests for cost data export endpoint."""

    @pytest.mark.asyncio
    async def test_export_json(self, handler):
        summary = _make_cost_summary()
        request = _make_request(
            "GET", "/api/v1/costs/export", query="format=json&range=30d&group_by=daily"
        )

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            response = await handler.handle_export(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["workspace_id"] == "default"
        assert data["time_range"] == "30d"
        assert data["group_by"] == "daily"
        assert "exported_at" in data
        assert "rows" in data

    @pytest.mark.asyncio
    async def test_export_csv(self, handler):
        summary = _make_cost_summary()
        request = _make_request("GET", "/api/v1/costs/export", query="format=csv&range=7d")

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            response = await handler.handle_export(request)

        assert response.status == 200
        assert response.content_type == "text/csv"

    @pytest.mark.asyncio
    async def test_export_invalid_format(self, handler):
        request = _make_request("GET", "/api/v1/costs/export", query="format=xml")

        response = await handler.handle_export(request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_export_provider_grouping(self, handler):
        summary = _make_cost_summary()
        request = _make_request(
            "GET", "/api/v1/costs/export", query="format=json&group_by=provider"
        )

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ):
            response = await handler.handle_export(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["group_by"] == "provider"
        # Rows should be provider breakdown
        assert len(data["rows"]) == len(summary.cost_by_provider)


# ---------------------------------------------------------------------------
# GET /api/v1/costs/usage
# ---------------------------------------------------------------------------


class TestGetUsage:
    """Tests for usage tracking endpoint."""

    @pytest.mark.asyncio
    async def test_usage_by_provider(self, handler):
        mock_report = MagicMock()
        mock_report.total_cost_usd = Decimal("100.00")
        mock_report.total_tokens_in = 400_000
        mock_report.total_tokens_out = 150_000
        mock_report.total_api_calls = 800
        mock_report.cost_by_provider = {"Anthropic": Decimal("70.00"), "OpenAI": Decimal("30.00")}
        mock_report.cost_by_operation = {}
        mock_report.calls_by_provider = {"Anthropic": 600, "OpenAI": 200}

        mock_tracker = MagicMock()
        mock_tracker.generate_report = AsyncMock(return_value=mock_report)

        request = _make_request(
            "GET", "/api/v1/costs/usage", query="workspace_id=ws-1&range=7d&group_by=provider"
        )

        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            return_value=mock_tracker,
        ):
            response = await handler.handle_get_usage(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["workspace_id"] == "ws-1"
        assert data["time_range"] == "7d"
        assert data["total_cost_usd"] == 100.0
        assert data["total_tokens_in"] == 400_000
        assert data["total_api_calls"] == 800
        assert len(data["usage"]) == 2

    @pytest.mark.asyncio
    async def test_usage_no_tracker(self, handler):
        request = _make_request("GET", "/api/v1/costs/usage")

        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            return_value=None,
        ):
            response = await handler.handle_get_usage(request)

        assert response.status == 503

    @pytest.mark.asyncio
    async def test_usage_by_operation(self, handler):
        mock_report = MagicMock()
        mock_report.total_cost_usd = Decimal("50.00")
        mock_report.total_tokens_in = 200_000
        mock_report.total_tokens_out = 80_000
        mock_report.total_api_calls = 300
        mock_report.cost_by_provider = {}
        mock_report.cost_by_operation = {"debate": Decimal("30.00"), "review": Decimal("20.00")}
        mock_report.cost_by_model = {}

        mock_tracker = MagicMock()
        mock_tracker.generate_report = AsyncMock(return_value=mock_report)

        request = _make_request("GET", "/api/v1/costs/usage", query="group_by=operation")

        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            return_value=mock_tracker,
        ):
            response = await handler.handle_get_usage(request)

        assert response.status == 200
        data = _parse_response(response)
        assert len(data["usage"]) == 2


# ---------------------------------------------------------------------------
# GET /api/v1/costs/budgets
# ---------------------------------------------------------------------------


class TestListBudgets:
    """Tests for listing budgets endpoint."""

    @pytest.mark.asyncio
    async def test_list_budgets_with_budget(self, handler):
        mock_budget = MagicMock()
        mock_budget.name = "Production Budget"
        mock_budget.monthly_limit_usd = Decimal("1000.00")
        mock_budget.daily_limit_usd = Decimal("50.00")
        mock_budget.current_monthly_spend = Decimal("250.00")
        mock_budget.current_daily_spend = Decimal("10.00")

        mock_tracker = MagicMock()
        mock_tracker.get_budget.return_value = mock_budget

        request = _make_request("GET", "/api/v1/costs/budgets", query="workspace_id=ws-1")

        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            return_value=mock_tracker,
        ):
            response = await handler.handle_list_budgets(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["count"] == 1
        assert data["workspace_id"] == "ws-1"
        budget = data["budgets"][0]
        assert budget["name"] == "Production Budget"
        assert budget["monthly_limit_usd"] == 1000.0
        assert budget["daily_limit_usd"] == 50.0
        assert budget["active"] is True

    @pytest.mark.asyncio
    async def test_list_budgets_no_budget(self, handler):
        mock_tracker = MagicMock()
        mock_tracker.get_budget.return_value = None

        request = _make_request("GET", "/api/v1/costs/budgets")

        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            return_value=mock_tracker,
        ):
            response = await handler.handle_list_budgets(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["count"] == 0
        assert data["budgets"] == []

    @pytest.mark.asyncio
    async def test_list_budgets_no_tracker(self, handler):
        request = _make_request("GET", "/api/v1/costs/budgets")

        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            return_value=None,
        ):
            response = await handler.handle_list_budgets(request)

        assert response.status == 503


# ---------------------------------------------------------------------------
# POST /api/v1/costs/budgets
# ---------------------------------------------------------------------------


class TestCreateBudget:
    """Tests for creating a budget."""

    @pytest.mark.asyncio
    async def test_create_budget_success(self, handler):
        body = {
            "workspace_id": "ws-1",
            "name": "Engineering Budget",
            "monthly_limit_usd": 2000,
            "daily_limit_usd": 100,
            "alert_thresholds": [50, 75, 90],
        }
        request = _make_request("POST", "/api/v1/costs/budgets", body=body)
        mock_tracker = MagicMock()

        with (
            patch(
                "aragora.server.handlers.costs.handler._models._get_cost_tracker",
                return_value=mock_tracker,
            ),
            patch(
                "aragora.server.handlers.costs.handler.parse_json_body",
                new_callable=AsyncMock,
                return_value=(body, None),
            ),
        ):
            response = await handler.handle_create_budget(request)

        assert response.status == 201
        data = _parse_response(response)
        assert data["success"] is True
        assert data["budget"]["name"] == "Engineering Budget"
        assert data["budget"]["monthly_limit_usd"] == 2000

    @pytest.mark.asyncio
    async def test_create_budget_negative_limit(self, handler):
        body = {"monthly_limit_usd": -100}
        request = _make_request("POST", "/api/v1/costs/budgets", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_create_budget(request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_create_budget_missing_limit(self, handler):
        body = {"name": "No Limit Budget"}
        request = _make_request("POST", "/api/v1/costs/budgets", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_create_budget(request)

        assert response.status == 400


# ---------------------------------------------------------------------------
# POST /api/v1/costs/constraints/check
# ---------------------------------------------------------------------------


class TestCheckConstraints:
    """Tests for budget constraint checking."""

    @pytest.mark.asyncio
    async def test_constraints_allowed(self, handler):
        mock_budget = MagicMock()
        mock_budget.monthly_limit_usd = Decimal("1000.00")
        mock_budget.current_monthly_spend = Decimal("200.00")
        mock_budget.daily_limit_usd = None

        mock_tracker = MagicMock()
        mock_tracker.get_budget.return_value = mock_budget

        body = {"workspace_id": "ws-1", "estimated_cost_usd": 50, "operation": "debate"}
        request = _make_request("POST", "/api/v1/costs/constraints/check", body=body)

        with (
            patch(
                "aragora.server.handlers.costs.handler._models._get_cost_tracker",
                return_value=mock_tracker,
            ),
            patch(
                "aragora.server.handlers.costs.handler.parse_json_body",
                new_callable=AsyncMock,
                return_value=(body, None),
            ),
        ):
            response = await handler.handle_check_constraints(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["allowed"] is True
        assert data["reason"] == "OK"
        assert data["remaining_monthly_budget"] == 800.0

    @pytest.mark.asyncio
    async def test_constraints_exceed_monthly(self, handler):
        mock_budget = MagicMock()
        mock_budget.monthly_limit_usd = Decimal("100.00")
        mock_budget.current_monthly_spend = Decimal("95.00")
        mock_budget.daily_limit_usd = None

        mock_tracker = MagicMock()
        mock_tracker.get_budget.return_value = mock_budget

        body = {"workspace_id": "ws-1", "estimated_cost_usd": 10}
        request = _make_request("POST", "/api/v1/costs/constraints/check", body=body)

        with (
            patch(
                "aragora.server.handlers.costs.handler._models._get_cost_tracker",
                return_value=mock_tracker,
            ),
            patch(
                "aragora.server.handlers.costs.handler.parse_json_body",
                new_callable=AsyncMock,
                return_value=(body, None),
            ),
        ):
            response = await handler.handle_check_constraints(request)

        data = _parse_response(response)
        assert data["allowed"] is False
        assert "monthly budget" in data["reason"]

    @pytest.mark.asyncio
    async def test_constraints_exceed_daily(self, handler):
        mock_budget = MagicMock()
        mock_budget.monthly_limit_usd = Decimal("1000.00")
        mock_budget.current_monthly_spend = Decimal("100.00")
        mock_budget.daily_limit_usd = Decimal("20.00")
        mock_budget.current_daily_spend = Decimal("18.00")

        mock_tracker = MagicMock()
        mock_tracker.get_budget.return_value = mock_budget

        body = {"estimated_cost_usd": 5}
        request = _make_request("POST", "/api/v1/costs/constraints/check", body=body)

        with (
            patch(
                "aragora.server.handlers.costs.handler._models._get_cost_tracker",
                return_value=mock_tracker,
            ),
            patch(
                "aragora.server.handlers.costs.handler.parse_json_body",
                new_callable=AsyncMock,
                return_value=(body, None),
            ),
        ):
            response = await handler.handle_check_constraints(request)

        data = _parse_response(response)
        assert data["allowed"] is False
        assert "daily budget" in data["reason"]

    @pytest.mark.asyncio
    async def test_constraints_negative_cost(self, handler):
        body = {"estimated_cost_usd": -5}
        request = _make_request("POST", "/api/v1/costs/constraints/check", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_check_constraints(request)

        assert response.status == 400

    @pytest.mark.asyncio
    async def test_constraints_no_tracker(self, handler):
        """Without tracker, operation is allowed (no constraints to check)."""
        body = {"estimated_cost_usd": 100}
        request = _make_request("POST", "/api/v1/costs/constraints/check", body=body)

        with (
            patch(
                "aragora.server.handlers.costs.handler._models._get_cost_tracker",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.costs.handler.parse_json_body",
                new_callable=AsyncMock,
                return_value=(body, None),
            ),
        ):
            response = await handler.handle_check_constraints(request)

        data = _parse_response(response)
        assert data["allowed"] is True
        assert data["remaining_monthly_budget"] is None


# ---------------------------------------------------------------------------
# POST /api/v1/costs/estimate
# ---------------------------------------------------------------------------


class TestEstimateCost:
    """Tests for cost estimation endpoint."""

    @pytest.mark.asyncio
    async def test_estimate_anthropic_opus(self, handler):
        body = {
            "operation": "debate",
            "tokens_input": 1_000_000,
            "tokens_output": 500_000,
            "model": "claude-3-opus",
            "provider": "anthropic",
        }
        request = _make_request("POST", "/api/v1/costs/estimate", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_estimate_cost(request)

        assert response.status == 200
        data = _parse_response(response)
        # claude-3-opus not in pricing table, falls back to default $2/M input, $8/M output
        # 1M @ $2 + 500K @ $8 = $2 + $4 = $6
        assert data["estimated_cost_usd"] == pytest.approx(6.0, abs=0.01)
        assert data["breakdown"]["input_tokens"] == 1_000_000
        assert data["breakdown"]["output_tokens"] == 500_000
        assert data["pricing"]["model"] == "claude-3-opus"
        assert data["pricing"]["provider"] == "anthropic"
        assert data["operation"] == "debate"

    @pytest.mark.asyncio
    async def test_estimate_openai_gpt4(self, handler):
        body = {
            "tokens_input": 500_000,
            "tokens_output": 200_000,
            "model": "gpt-4",
            "provider": "openai",
        }
        request = _make_request("POST", "/api/v1/costs/estimate", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_estimate_cost(request)

        assert response.status == 200
        data = _parse_response(response)
        # 500K input @ $30/M + 200K output @ $60/M = $15 + $12 = $27
        # gpt-4 not in pricing table (only gpt-4o), falls back to default $2/M input, $8/M output
        # 500K @ $2 + 200K @ $8 = $1 + $1.6 = $2.6
        assert data["estimated_cost_usd"] == pytest.approx(2.6, abs=0.01)

    @pytest.mark.asyncio
    async def test_estimate_unknown_provider_uses_default(self, handler):
        # The $2/$8 default is reached when the MODEL has no priced row
        # anywhere, not merely when the provider label is unrecognised: a
        # spelling has one price and the caller's label is not information
        # about it. Omitting "model" exercised the default "claude-opus-4",
        # which HAS a real $5/$25 row, so this assertion had been failing on
        # main; naming an uncataloged model tests what the name claims
        # (2026-09-05 wave-2 re-review).
        body = {
            "tokens_input": 1_000_000,
            "tokens_output": 1_000_000,
            "provider": "unknown_provider",
            "model": "totally-unknown-model-v0",
        }
        request = _make_request("POST", "/api/v1/costs/estimate", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_estimate_cost(request)

        assert response.status == 200
        data = _parse_response(response)
        # unknown provider falls back to openrouter defaults: $2/M input + $8/M output
        # 1M @ $2 + 1M @ $8 = $2 + $8 = $10
        assert data["estimated_cost_usd"] == pytest.approx(10.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_estimate_zero_tokens(self, handler):
        body = {"tokens_input": 0, "tokens_output": 0}
        request = _make_request("POST", "/api/v1/costs/estimate", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_estimate_cost(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["estimated_cost_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_estimate_haiku_pricing(self, handler):
        body = {
            "tokens_input": 1_000_000,
            "tokens_output": 1_000_000,
            "model": "claude-3-haiku",
            "provider": "anthropic",
        }
        request = _make_request("POST", "/api/v1/costs/estimate", body=body)

        with patch(
            "aragora.server.handlers.costs.handler.parse_json_body",
            new_callable=AsyncMock,
            return_value=(body, None),
        ):
            response = await handler.handle_estimate_cost(request)

        data = _parse_response(response)
        # claude-3-haiku not in pricing table, falls back to default $2/M input, $8/M output
        # 1M @ $2 + 1M @ $8 = $2 + $8 = $10
        assert data["estimated_cost_usd"] == pytest.approx(10.0, abs=0.01)


# ---------------------------------------------------------------------------
# GET /api/v1/costs/recommendations/detailed
# ---------------------------------------------------------------------------


class TestGetRecommendationsDetailed:
    """Tests for detailed recommendations endpoint."""

    @pytest.mark.asyncio
    async def test_detailed_recommendations(self, handler):
        mock_rec = MagicMock()
        mock_rec.to_dict.return_value = {
            "id": "rec-1",
            "type": "model_downgrade",
            "estimated_savings_usd": 100.0,
            "status": "pending",
        }

        mock_summary = MagicMock()
        mock_summary.to_dict.return_value = {"total_savings": 100.0}

        mock_optimizer = MagicMock()
        mock_optimizer.get_workspace_recommendations.return_value = [mock_rec]
        mock_optimizer.get_summary.return_value = mock_summary

        request = _make_request(
            "GET",
            "/api/v1/costs/recommendations/detailed",
            query="include_implementation=true",
        )

        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            return_value=mock_optimizer,
        ):
            response = await handler.handle_get_recommendations_detailed(request)

        assert response.status == 200
        data = _parse_response(response)
        assert data["count"] == 1
        rec = data["recommendations"][0]
        assert "implementation_steps" in rec
        assert rec["difficulty"] == "easy"
        assert rec["time_to_implement"] == "< 1 hour"

    @pytest.mark.asyncio
    async def test_detailed_recommendations_min_savings_filter(self, handler):
        mock_rec1 = MagicMock()
        mock_rec1.to_dict.return_value = {
            "id": "rec-1",
            "type": "model_downgrade",
            "estimated_savings_usd": 10.0,
        }
        mock_rec2 = MagicMock()
        mock_rec2.to_dict.return_value = {
            "id": "rec-2",
            "type": "caching",
            "estimated_savings_usd": 100.0,
        }

        mock_summary = MagicMock()
        mock_summary.to_dict.return_value = {"total_savings": 110.0}

        mock_optimizer = MagicMock()
        mock_optimizer.get_workspace_recommendations.return_value = [mock_rec1, mock_rec2]
        mock_optimizer.get_summary.return_value = mock_summary

        request = _make_request(
            "GET",
            "/api/v1/costs/recommendations/detailed",
            query="min_savings=50",
        )

        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            return_value=mock_optimizer,
        ):
            response = await handler.handle_get_recommendations_detailed(request)

        data = _parse_response(response)
        # Only rec-2 has savings >= 50
        assert data["count"] == 1
        assert data["recommendations"][0]["id"] == "rec-2"

    @pytest.mark.asyncio
    async def test_detailed_recommendations_without_implementation(self, handler):
        mock_rec = MagicMock()
        mock_rec.to_dict.return_value = {
            "id": "rec-1",
            "type": "batching",
            "estimated_savings_usd": 50.0,
        }

        mock_summary = MagicMock()
        mock_summary.to_dict.return_value = {}

        mock_optimizer = MagicMock()
        mock_optimizer.get_workspace_recommendations.return_value = [mock_rec]
        mock_optimizer.get_summary.return_value = mock_summary

        request = _make_request(
            "GET",
            "/api/v1/costs/recommendations/detailed",
            query="include_implementation=false",
        )

        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            return_value=mock_optimizer,
        ):
            response = await handler.handle_get_recommendations_detailed(request)

        data = _parse_response(response)
        rec = data["recommendations"][0]
        assert "implementation_steps" not in rec
        assert "difficulty" not in rec


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling across endpoints."""

    @pytest.mark.asyncio
    async def test_key_error_returns_500(self, handler):
        request = _make_request("GET", "/api/v1/costs")

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            side_effect=KeyError("missing"),
        ):
            response = await handler.handle_get_costs(request)

        assert response.status == 500

    @pytest.mark.asyncio
    async def test_attribute_error_returns_500(self, handler):
        request = _make_request("GET", "/api/v1/costs/timeline")

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            side_effect=AttributeError("no attr"),
        ):
            response = await handler.handle_get_timeline(request)

        assert response.status == 500

    @pytest.mark.asyncio
    async def test_os_error_returns_500(self, handler):
        request = _make_request("GET", "/api/v1/costs/breakdown")

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            side_effect=OSError("disk full"),
        ):
            response = await handler.handle_get_breakdown(request)

        assert response.status == 500

    @pytest.mark.asyncio
    async def test_import_error_returns_500(self, handler):
        request = _make_request("GET", "/api/v1/costs")

        with patch(
            "aragora.server.handlers.costs.handler._models.get_cost_summary",
            new_callable=AsyncMock,
            side_effect=ImportError("module missing"),
        ):
            response = await handler.handle_get_costs(request)

        assert response.status == 500


# ---------------------------------------------------------------------------
# Handler initialization
# ---------------------------------------------------------------------------


class TestHandlerInit:
    """Tests for CostHandler initialization."""

    def test_default_context(self):
        handler = CostHandler()
        assert handler.ctx == {}

    def test_custom_context(self):
        ctx = {"key": "value"}
        handler = CostHandler(ctx=ctx)
        assert handler.ctx == ctx

    def test_none_context_becomes_empty_dict(self):
        handler = CostHandler(ctx=None)
        assert handler.ctx == {}
