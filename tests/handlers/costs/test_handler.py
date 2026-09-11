"""Comprehensive tests for CostHandler (aragora/server/handlers/costs/handler.py).

Covers all 20 API endpoints across these test classes:

  TestInit                   - Handler initialization
  TestRoutes                 - ROUTES list validation (versioned + legacy parity)
  TestGetCosts               - GET /api/v1/costs
  TestGetBreakdown           - GET /api/v1/costs/breakdown
  TestGetTimeline            - GET /api/v1/costs/timeline
  TestGetAlerts              - GET /api/v1/costs/alerts
  TestCreateAlert            - POST /api/v1/costs/alerts
  TestDismissAlert           - POST /api/v1/costs/alerts/{id}/dismiss
  TestSetBudget              - POST /api/v1/costs/budget
  TestListBudgets            - GET /api/v1/costs/budgets
  TestCreateBudget           - POST /api/v1/costs/budgets
  TestGetRecommendations     - GET /api/v1/costs/recommendations
  TestGetRecommendation      - GET /api/v1/costs/recommendations/{id}
  TestApplyRecommendation    - POST /api/v1/costs/recommendations/{id}/apply
  TestDismissRecommendation  - POST /api/v1/costs/recommendations/{id}/dismiss
  TestGetRecommendationsDetailed - GET /api/v1/costs/recommendations/detailed
  TestGetEfficiency           - GET /api/v1/costs/efficiency
  TestGetForecast             - GET /api/v1/costs/forecast
  TestGetForecastDetailed     - GET /api/v1/costs/forecast/detailed
  TestSimulateForecast        - POST /api/v1/costs/forecast/simulate
  TestExport                  - GET /api/v1/costs/export
  TestGetUsage                - GET /api/v1/costs/usage
  TestCheckConstraints        - POST /api/v1/costs/constraints/check
  TestEstimateCost            - POST /api/v1/costs/estimate
  TestErrorCategories         - Cross-endpoint error type coverage
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


def _req(
    method: str = "GET",
    path: str = "/api/v1/costs",
    query: str = "",
    body: dict[str, Any] | None = None,
    match_info: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock aiohttp request."""
    full_path = f"{path}?{query}" if query else path
    request = make_mocked_request(method, full_path)
    if match_info:
        request.match_info.update(match_info)
    if body is not None:
        request.json = AsyncMock(return_value=body)
        request.text = AsyncMock(return_value=json.dumps(body))
        request.read = AsyncMock(return_value=json.dumps(body).encode())
    return request


def _body(response) -> dict[str, Any]:
    """Parse JSON response body."""
    return json.loads(response.body)


def _status(response) -> int:
    """Get response HTTP status code."""
    return response.status


def _summary(**overrides) -> CostSummary:
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
            {"date": "2026-02-22", "cost": 16.00, "tokens": 400000},
        ],
        "alerts": [
            {
                "id": "1",
                "type": "budget_warning",
                "message": "80% usage",
                "severity": "warning",
                "timestamp": now.isoformat(),
            }
        ],
    }
    defaults.update(overrides)
    return CostSummary(**defaults)


def _patch_summary(summary=None, side_effect=None):
    """Patch get_cost_summary."""
    kwargs: dict[str, Any] = {"new_callable": AsyncMock}
    if side_effect:
        kwargs["side_effect"] = side_effect
    else:
        kwargs["return_value"] = summary or _summary()
    return patch("aragora.server.handlers.costs.handler._models.get_cost_summary", **kwargs)


def _patch_tracker(tracker):
    return patch(
        "aragora.server.handlers.costs.handler._models._get_cost_tracker",
        return_value=tracker,
    )


def _patch_parse_body(body_dict, err=None):
    return patch(
        "aragora.server.handlers.costs.handler.parse_json_body",
        new_callable=AsyncMock,
        return_value=(body_dict, err),
    )


def _patch_optimizer(optimizer):
    return patch(
        "aragora.billing.optimizer.get_cost_optimizer",
        return_value=optimizer,
    )


def _patch_forecaster(forecaster):
    return patch(
        "aragora.billing.forecaster.get_cost_forecaster",
        return_value=forecaster,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    return CostHandler(ctx={})


# ===========================================================================
# TestInit
# ===========================================================================


class TestInit:
    """Handler construction."""

    def test_default_ctx(self):
        h = CostHandler()
        assert h.ctx == {}

    def test_ctx_is_stored(self):
        ctx = {"db": "mock"}
        h = CostHandler(ctx=ctx)
        assert h.ctx is ctx

    def test_none_ctx_becomes_empty(self):
        h = CostHandler(ctx=None)
        assert h.ctx == {}


# ===========================================================================
# TestRoutes
# ===========================================================================


class TestRoutes:
    """ROUTES list completeness."""

    def test_total_count_matches_versioned_legacy_pairs(self):
        versioned = [r for r in CostHandler.ROUTES if r.startswith("/api/v1/")]
        legacy = [
            r for r in CostHandler.ROUTES if r.startswith("/api/") and not r.startswith("/api/v1/")
        ]
        assert len(CostHandler.ROUTES) == len(versioned) + len(legacy)
        assert len(versioned) == len(legacy)

    def test_versioned_routes_have_legacy_counterparts(self):
        versioned = [r for r in CostHandler.ROUTES if r.startswith("/api/v1/")]
        for v in versioned:
            legacy = v.replace("/api/v1/", "/api/")
            assert legacy in CostHandler.ROUTES, f"Missing legacy: {legacy}"

    def test_no_duplicates(self):
        assert len(CostHandler.ROUTES) == len(set(CostHandler.ROUTES))

    @pytest.mark.parametrize(
        "route",
        [
            "/api/v1/costs",
            "/api/v1/costs/alerts",
            "/api/v1/costs/alerts/*/dismiss",
            "/api/v1/costs/breakdown",
            "/api/v1/costs/budget",
            "/api/v1/costs/budgets",
            "/api/v1/costs/constraints/check",
            "/api/v1/costs/efficiency",
            "/api/v1/costs/estimate",
            "/api/v1/costs/export",
            "/api/v1/costs/forecast",
            "/api/v1/costs/forecast/detailed",
            "/api/v1/costs/forecast/simulate",
            "/api/v1/costs/recommendations",
            "/api/v1/costs/recommendations/detailed",
            "/api/v1/costs/recommendations/*",
            "/api/v1/costs/recommendations/*/apply",
            "/api/v1/costs/recommendations/*/dismiss",
            "/api/v1/costs/debates/{debate_id}",
            "/api/v1/costs/debates/{debate_id}/line-items",
            "/api/v1/costs/debates/{debate_id}/performance",
            "/api/v1/costs/timeline",
            "/api/v1/costs/usage",
        ],
    )
    def test_versioned_route_present(self, route):
        assert route in CostHandler.ROUTES


# ===========================================================================
# GET /api/v1/costs
# ===========================================================================


class TestGetCosts:
    @pytest.mark.asyncio
    async def test_success_returns_all_fields(self, handler):
        s = _summary()
        with _patch_summary(s):
            resp = await handler.handle_get_costs(_req())
        assert _status(resp) == 200
        d = _body(resp)
        data = d["data"]
        assert data["total_cost_usd"] == 125.50
        assert data["budget_usd"] == 500.00
        assert data["api_calls"] == 12_550

    @pytest.mark.asyncio
    async def test_default_params(self, handler):
        with _patch_summary() as mock:
            await handler.handle_get_costs(_req())
        mock.assert_awaited_once_with(workspace_id="default", time_range="7d")

    @pytest.mark.asyncio
    async def test_custom_range_24h(self, handler):
        with _patch_summary() as mock:
            await handler.handle_get_costs(_req(query="range=24h"))
        mock.assert_awaited_once_with(workspace_id="default", time_range="24h")

    @pytest.mark.asyncio
    async def test_custom_range_90d(self, handler):
        with _patch_summary() as mock:
            await handler.handle_get_costs(_req(query="range=90d&workspace_id=prod"))
        mock.assert_awaited_once_with(workspace_id="prod", time_range="90d")

    @pytest.mark.asyncio
    async def test_zero_cost_summary(self, handler):
        s = _summary(
            total_cost=0.0,
            tokens_used=0,
            api_calls=0,
            daily_costs=[],
            alerts=[],
            cost_by_provider=[],
            cost_by_feature=[],
        )
        with _patch_summary(s):
            resp = await handler.handle_get_costs(_req())
        assert _status(resp) == 200
        d = _body(resp)
        assert d["data"]["total_cost_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_value_error_returns_500(self, handler):
        with _patch_summary(side_effect=ValueError("bad")):
            resp = await handler.handle_get_costs(_req())
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_runtime_error_returns_500(self, handler):
        with _patch_summary(side_effect=RuntimeError("crash")):
            resp = await handler.handle_get_costs(_req())
        assert _status(resp) == 500


# ===========================================================================
# GET /api/v1/costs/breakdown
# ===========================================================================


class TestGetBreakdown:
    @pytest.mark.asyncio
    async def test_group_by_provider(self, handler):
        s = _summary()
        with _patch_summary(s):
            resp = await handler.handle_get_breakdown(_req(query="group_by=provider"))
        d = _body(resp)
        assert "data" in d
        assert "by_provider" in d["data"]

    @pytest.mark.asyncio
    async def test_group_by_feature(self, handler):
        s = _summary()
        with _patch_summary(s):
            resp = await handler.handle_get_breakdown(_req(query="group_by=feature"))
        d = _body(resp)
        assert "data" in d
        assert "by_feature" in d["data"]

    @pytest.mark.asyncio
    async def test_unknown_group_falls_back_to_provider(self, handler):
        s = _summary()
        with _patch_summary(s):
            resp = await handler.handle_get_breakdown(_req(query="group_by=model"))
        d = _body(resp)
        assert "data" in d
        assert "by_provider" in d["data"]

    @pytest.mark.asyncio
    async def test_default_group_is_provider(self, handler):
        s = _summary()
        with _patch_summary(s):
            resp = await handler.handle_get_breakdown(_req(path="/api/v1/costs/breakdown"))
        d = _body(resp)
        assert "data" in d
        assert "by_provider" in d["data"]

    @pytest.mark.asyncio
    async def test_custom_workspace_forwarded(self, handler):
        with _patch_summary() as mock:
            await handler.handle_get_breakdown(_req(query="workspace_id=team-a&range=30d"))
        mock.assert_awaited_once_with(workspace_id="team-a", time_range="30d")

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        with _patch_summary(side_effect=OSError("disk")):
            resp = await handler.handle_get_breakdown(_req())
        assert _status(resp) == 500


# ===========================================================================
# GET /api/v1/costs/timeline
# ===========================================================================


class TestGetTimeline:
    @pytest.mark.asyncio
    async def test_timeline_data(self, handler):
        s = _summary()
        with _patch_summary(s):
            resp = await handler.handle_get_timeline(_req())
        d = _body(resp)
        data = d["data"]
        assert len(data["data_points"]) == len(s.daily_costs)
        assert data["total_cost"] == 125.50
        assert data["average_daily_cost"] == pytest.approx(125.50 / 3, rel=1e-3)

    @pytest.mark.asyncio
    async def test_empty_daily_costs_average_zero(self, handler):
        s = _summary(daily_costs=[])
        with _patch_summary(s):
            resp = await handler.handle_get_timeline(_req())
        assert _body(resp)["data"]["average_daily_cost"] == 0

    @pytest.mark.asyncio
    async def test_single_day(self, handler):
        s = _summary(daily_costs=[{"date": "2026-02-22", "cost": 50.0, "tokens": 100}])
        with _patch_summary(s):
            resp = await handler.handle_get_timeline(_req())
        d = _body(resp)
        # total_cost comes from summary.total_cost (125.50), divided by 1 day
        assert d["data"]["average_daily_cost"] == pytest.approx(125.50, rel=1e-3)

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        with _patch_summary(side_effect=TypeError("bad type")):
            resp = await handler.handle_get_timeline(_req())
        assert _status(resp) == 500


# ===========================================================================
# GET /api/v1/costs/alerts
# ===========================================================================


class TestGetAlerts:
    @pytest.mark.asyncio
    async def test_no_tracker_returns_empty(self, handler):
        with _patch_tracker(None):
            resp = await handler.handle_get_alerts(_req())
        assert _status(resp) == 200
        assert _body(resp)["data"]["alerts"] == []

    @pytest.mark.asyncio
    async def test_active_alerts_returned(self, handler):
        tracker = MagicMock()
        tracker.query_km_workspace_alerts.return_value = []
        active = [{"id": "a1", "type": "warn", "message": "high", "severity": "warning"}]
        with (
            _patch_tracker(tracker),
            patch(
                "aragora.server.handlers.costs.handler._models._get_active_alerts",
                return_value=active,
            ),
        ):
            resp = await handler.handle_get_alerts(_req())
        d = _body(resp)["data"]
        assert len(d["alerts"]) == 1
        assert d["alerts"][0]["id"] == "a1"

    @pytest.mark.asyncio
    async def test_km_unacknowledged_alerts_included(self, handler):
        tracker = MagicMock()
        tracker.query_km_workspace_alerts.return_value = [
            {
                "id": "km-1",
                "level": "critical",
                "message": "over budget",
                "acknowledged": False,
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        with (
            _patch_tracker(tracker),
            patch(
                "aragora.server.handlers.costs.handler._models._get_active_alerts",
                return_value=[],
            ),
        ):
            resp = await handler.handle_get_alerts(_req())
        d = _body(resp)["data"]
        assert len(d["alerts"]) == 1
        assert d["alerts"][0]["type"] == "critical"
        assert d["alerts"][0]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_km_acknowledged_alerts_skipped(self, handler):
        tracker = MagicMock()
        tracker.query_km_workspace_alerts.return_value = [
            {"id": "km-2", "level": "info", "message": "ack", "acknowledged": True},
        ]
        with (
            _patch_tracker(tracker),
            patch(
                "aragora.server.handlers.costs.handler._models._get_active_alerts",
                return_value=[],
            ),
        ):
            resp = await handler.handle_get_alerts(_req())
        assert _body(resp)["data"]["alerts"] == []

    @pytest.mark.asyncio
    async def test_mixed_active_and_km_alerts(self, handler):
        tracker = MagicMock()
        tracker.query_km_workspace_alerts.return_value = [
            {
                "id": "km-a",
                "level": "warning",
                "message": "x",
                "acknowledged": False,
                "created_at": "",
            },
            {"id": "km-b", "level": "info", "message": "y", "acknowledged": True},
        ]
        active = [{"id": "active-1", "type": "budget", "message": "z", "severity": "warning"}]
        with (
            _patch_tracker(tracker),
            patch(
                "aragora.server.handlers.costs.handler._models._get_active_alerts",
                return_value=active,
            ),
        ):
            resp = await handler.handle_get_alerts(_req())
        d = _body(resp)["data"]
        assert len(d["alerts"]) == 2  # active-1 + km-a (km-b ack'd)

    @pytest.mark.asyncio
    async def test_custom_workspace(self, handler):
        tracker = MagicMock()
        tracker.query_km_workspace_alerts.return_value = []
        with (
            _patch_tracker(tracker),
            patch(
                "aragora.server.handlers.costs.handler._models._get_active_alerts",
                return_value=[],
            ) as mock_active,
        ):
            await handler.handle_get_alerts(_req(query="workspace_id=ws-custom"))
        mock_active.assert_called_once_with(tracker, "ws-custom")

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        with (
            _patch_tracker(None),
            patch(
                "aragora.server.handlers.costs.handler._models._get_cost_tracker",
                side_effect=AttributeError("broken"),
            ),
        ):
            resp = await handler.handle_get_alerts(_req())
        assert _status(resp) == 500


# ===========================================================================
# POST /api/v1/costs/alerts (create)
# ===========================================================================


class TestCreateAlert:
    @pytest.mark.asyncio
    async def test_create_budget_threshold(self, handler):
        body = {
            "name": "Alert1",
            "type": "budget_threshold",
            "threshold": 90,
            "notification_channels": ["slack"],
        }
        with _patch_parse_body(body):
            resp = await handler.handle_create_alert(_req("POST", body=body))
        assert _status(resp) == 201
        d = _body(resp)
        assert d["success"] is True
        assert d["alert"]["name"] == "Alert1"
        assert d["alert"]["type"] == "budget_threshold"
        assert d["alert"]["threshold"] == 90
        assert d["alert"]["active"] is True
        assert d["alert"]["id"].startswith("alert_")

    @pytest.mark.asyncio
    async def test_create_spike_detection(self, handler):
        body = {"name": "Spike", "type": "spike_detection", "threshold": 2.5}
        with _patch_parse_body(body):
            resp = await handler.handle_create_alert(_req("POST", body=body))
        assert _status(resp) == 201
        assert _body(resp)["alert"]["type"] == "spike_detection"

    @pytest.mark.asyncio
    async def test_create_daily_limit(self, handler):
        body = {"name": "Daily", "type": "daily_limit"}
        with _patch_parse_body(body):
            resp = await handler.handle_create_alert(_req("POST", body=body))
        assert _status(resp) == 201

    @pytest.mark.asyncio
    async def test_missing_name_returns_400(self, handler):
        body = {"type": "budget_threshold"}
        with _patch_parse_body(body):
            resp = await handler.handle_create_alert(_req("POST", body=body))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_invalid_type_returns_400(self, handler):
        body = {"name": "Bad", "type": "unknown_type"}
        with _patch_parse_body(body):
            resp = await handler.handle_create_alert(_req("POST", body=body))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_default_threshold_is_80(self, handler):
        body = {"name": "Defaults", "type": "budget_threshold"}
        with _patch_parse_body(body):
            resp = await handler.handle_create_alert(_req("POST", body=body))
        assert _body(resp)["alert"]["threshold"] == 80

    @pytest.mark.asyncio
    async def test_default_channels_is_email(self, handler):
        body = {"name": "Defaults", "type": "budget_threshold"}
        with _patch_parse_body(body):
            resp = await handler.handle_create_alert(_req("POST", body=body))
        assert _body(resp)["alert"]["notification_channels"] == ["email"]

    @pytest.mark.asyncio
    async def test_parse_error_forwarded(self, handler):
        from aiohttp import web

        err = web.json_response({"error": "bad json"}, status=400)
        with _patch_parse_body(None, err=err):
            resp = await handler.handle_create_alert(_req("POST"))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_workspace_id_default(self, handler):
        body = {"name": "X", "type": "budget_threshold"}
        with _patch_parse_body(body):
            resp = await handler.handle_create_alert(_req("POST", body=body))
        assert _body(resp)["alert"]["workspace_id"] == "default"

    @pytest.mark.asyncio
    async def test_created_at_is_iso_string(self, handler):
        body = {"name": "X", "type": "budget_threshold"}
        with _patch_parse_body(body):
            resp = await handler.handle_create_alert(_req("POST", body=body))
        # Should not raise
        datetime.fromisoformat(_body(resp)["alert"]["created_at"])


# ===========================================================================
# POST /api/v1/costs/alerts/{alert_id}/dismiss
# ===========================================================================


class TestDismissAlert:
    @pytest.mark.asyncio
    async def test_dismiss_success(self, handler):
        req = _req("POST", match_info={"alert_id": "a-123"})
        resp = await handler.handle_dismiss_alert(req)
        assert _status(resp) == 200
        d = _body(resp)
        assert d["success"] is True
        assert d["alert_id"] == "a-123"
        assert d["dismissed"] is True

    @pytest.mark.asyncio
    async def test_dismiss_with_workspace(self, handler):
        req = _req("POST", query="workspace_id=ws-99", match_info={"alert_id": "a-456"})
        resp = await handler.handle_dismiss_alert(req)
        assert _body(resp)["alert_id"] == "a-456"

    @pytest.mark.asyncio
    async def test_dismiss_none_alert_id(self, handler):
        """match_info not set -> alert_id is None, still returns 200."""
        req = _req("POST")
        resp = await handler.handle_dismiss_alert(req)
        assert _status(resp) == 200
        assert _body(resp)["alert_id"] is None


# ===========================================================================
# POST /api/v1/costs/budget
# ===========================================================================


class TestSetBudget:
    @pytest.mark.asyncio
    async def test_set_budget_with_tracker(self, handler):
        body = {"budget": 1000, "workspace_id": "ws-1", "daily_limit": 50, "name": "Prod"}
        tracker = MagicMock()
        with _patch_tracker(tracker), _patch_parse_body(body):
            resp = await handler.handle_set_budget(_req("POST", body=body))
        assert _status(resp) == 200
        d = _body(resp)
        assert d["success"] is True
        assert d["budget"] == 1000
        assert d["workspace_id"] == "ws-1"
        assert d["daily_limit"] == 50
        tracker.set_budget.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_budget_no_tracker(self, handler):
        body = {"budget": 500}
        with _patch_tracker(None), _patch_parse_body(body):
            resp = await handler.handle_set_budget(_req("POST", body=body))
        assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_negative_budget_returns_400(self, handler):
        body = {"budget": -10}
        with _patch_parse_body(body):
            resp = await handler.handle_set_budget(_req("POST", body=body))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_missing_budget_returns_400(self, handler):
        body = {"workspace_id": "ws"}
        with _patch_parse_body(body):
            resp = await handler.handle_set_budget(_req("POST", body=body))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_zero_budget_is_valid(self, handler):
        body = {"budget": 0}
        with _patch_tracker(None), _patch_parse_body(body):
            resp = await handler.handle_set_budget(_req("POST", body=body))
        assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_parse_error_forwarded(self, handler):
        from aiohttp import web

        err = web.json_response({"error": "nope"}, status=400)
        with _patch_parse_body(None, err=err):
            resp = await handler.handle_set_budget(_req("POST"))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_default_workspace_and_name(self, handler):
        body = {"budget": 200}
        with _patch_tracker(None), _patch_parse_body(body):
            resp = await handler.handle_set_budget(_req("POST", body=body))
        d = _body(resp)
        assert d["workspace_id"] == "default"

    @pytest.mark.asyncio
    async def test_no_daily_limit(self, handler):
        body = {"budget": 300}
        with _patch_tracker(None), _patch_parse_body(body):
            resp = await handler.handle_set_budget(_req("POST", body=body))
        assert _body(resp)["daily_limit"] is None


# ===========================================================================
# GET /api/v1/costs/budgets
# ===========================================================================


class TestListBudgets:
    @pytest.mark.asyncio
    async def test_with_budget(self, handler):
        budget = MagicMock()
        budget.name = "Main"
        budget.monthly_limit_usd = Decimal("1000")
        budget.daily_limit_usd = Decimal("50")
        budget.current_monthly_spend = Decimal("250")
        budget.current_daily_spend = Decimal("10")
        tracker = MagicMock()
        tracker.get_budget.return_value = budget
        with _patch_tracker(tracker):
            resp = await handler.handle_list_budgets(_req(query="workspace_id=ws-1"))
        assert _status(resp) == 200
        d = _body(resp)
        assert d["count"] == 1
        b = d["budgets"][0]
        assert b["name"] == "Main"
        assert b["monthly_limit_usd"] == 1000.0
        assert b["daily_limit_usd"] == 50.0
        assert b["current_monthly_spend"] == 250.0
        assert b["current_daily_spend"] == 10.0
        assert b["active"] is True
        assert b["id"] == "budget_ws-1"

    @pytest.mark.asyncio
    async def test_no_budget(self, handler):
        tracker = MagicMock()
        tracker.get_budget.return_value = None
        with _patch_tracker(tracker):
            resp = await handler.handle_list_budgets(_req())
        assert _body(resp)["count"] == 0
        assert _body(resp)["budgets"] == []

    @pytest.mark.asyncio
    async def test_no_tracker_returns_503(self, handler):
        with _patch_tracker(None):
            resp = await handler.handle_list_budgets(_req())
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_budget_without_daily_limit(self, handler):
        budget = MagicMock()
        budget.name = "NoDailyLimit"
        budget.monthly_limit_usd = Decimal("500")
        budget.daily_limit_usd = None
        budget.current_monthly_spend = Decimal("0")
        budget.current_daily_spend = Decimal("0")
        tracker = MagicMock()
        tracker.get_budget.return_value = budget
        with _patch_tracker(tracker):
            resp = await handler.handle_list_budgets(_req())
        b = _body(resp)["budgets"][0]
        assert b["daily_limit_usd"] is None

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            side_effect=KeyError("fail"),
        ):
            resp = await handler.handle_list_budgets(_req())
        assert _status(resp) == 500


# ===========================================================================
# POST /api/v1/costs/budgets
# ===========================================================================


class TestCreateBudget:
    @pytest.mark.asyncio
    async def test_create_success(self, handler):
        body = {
            "workspace_id": "ws-1",
            "name": "Eng Budget",
            "monthly_limit_usd": 2000,
            "daily_limit_usd": 100,
            "alert_thresholds": [50, 75, 90],
        }
        tracker = MagicMock()
        with _patch_tracker(tracker), _patch_parse_body(body):
            resp = await handler.handle_create_budget(_req("POST", body=body))
        assert _status(resp) == 201
        d = _body(resp)
        assert d["success"] is True
        assert d["budget"]["name"] == "Eng Budget"
        assert d["budget"]["monthly_limit_usd"] == 2000
        assert d["budget"]["daily_limit_usd"] == 100
        assert d["budget"]["alert_thresholds"] == [50, 75, 90]
        tracker.set_budget.assert_called_once()

    @pytest.mark.asyncio
    async def test_negative_limit_returns_400(self, handler):
        body = {"monthly_limit_usd": -1}
        with _patch_parse_body(body):
            resp = await handler.handle_create_budget(_req("POST", body=body))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_missing_limit_returns_400(self, handler):
        body = {"name": "NoBudget"}
        with _patch_parse_body(body):
            resp = await handler.handle_create_budget(_req("POST", body=body))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_zero_limit_is_valid(self, handler):
        body = {"monthly_limit_usd": 0}
        with _patch_tracker(None), _patch_parse_body(body):
            resp = await handler.handle_create_budget(_req("POST", body=body))
        assert _status(resp) == 201

    @pytest.mark.asyncio
    async def test_default_alert_thresholds(self, handler):
        body = {"monthly_limit_usd": 100}
        with _patch_tracker(None), _patch_parse_body(body):
            resp = await handler.handle_create_budget(_req("POST", body=body))
        d = _body(resp)
        assert d["budget"]["alert_thresholds"] == [50, 75, 90, 100]

    @pytest.mark.asyncio
    async def test_no_tracker_still_succeeds(self, handler):
        body = {"monthly_limit_usd": 500}
        with _patch_tracker(None), _patch_parse_body(body):
            resp = await handler.handle_create_budget(_req("POST", body=body))
        assert _status(resp) == 201

    @pytest.mark.asyncio
    async def test_default_name_uses_workspace(self, handler):
        body = {"monthly_limit_usd": 100, "workspace_id": "team-x"}
        with _patch_tracker(None), _patch_parse_body(body):
            resp = await handler.handle_create_budget(_req("POST", body=body))
        assert _body(resp)["budget"]["name"] == "Budget for team-x"

    @pytest.mark.asyncio
    async def test_parse_error_forwarded(self, handler):
        from aiohttp import web

        err = web.json_response({"error": "oops"}, status=400)
        with _patch_parse_body(None, err=err):
            resp = await handler.handle_create_budget(_req("POST"))
        assert _status(resp) == 400


# ===========================================================================
# GET /api/v1/costs/recommendations
# ===========================================================================


class TestGetRecommendations:
    def _mock_optimizer(self, recs=None, summary_dict=None):
        rec = MagicMock()
        rec.to_dict.return_value = {"id": "r-1", "type": "caching", "estimated_savings_usd": 50}
        summary = MagicMock()
        summary.to_dict.return_value = summary_dict or {"total_savings": 50}
        opt = MagicMock()
        opt.get_workspace_recommendations.return_value = recs or [rec]
        opt.get_summary.return_value = summary
        return opt

    @pytest.mark.asyncio
    async def test_success(self, handler):
        opt = self._mock_optimizer()
        with (
            _patch_optimizer(opt),
            patch("aragora.billing.recommendations.RecommendationStatus"),
            patch("aragora.billing.recommendations.RecommendationType"),
        ):
            resp = await handler.handle_get_recommendations(_req())
        assert _status(resp) == 200
        d = _body(resp)
        assert "recommendations" in d["data"]
        assert "summary" in d["data"]

    @pytest.mark.asyncio
    async def test_empty_recommendations_triggers_analyze(self, handler):
        opt = MagicMock()
        # First call returns empty, second call returns results
        opt.get_workspace_recommendations.side_effect = [[], []]
        opt.analyze_workspace = AsyncMock()
        summary = MagicMock()
        summary.to_dict.return_value = {}
        opt.get_summary.return_value = summary
        with (
            _patch_optimizer(opt),
            patch("aragora.billing.recommendations.RecommendationStatus"),
            patch("aragora.billing.recommendations.RecommendationType"),
        ):
            resp = await handler.handle_get_recommendations(_req())
        assert _status(resp) == 200
        opt.analyze_workspace.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_import_error_returns_500(self, handler):
        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            side_effect=ImportError("missing"),
        ):
            resp = await handler.handle_get_recommendations(_req())
        assert _status(resp) == 500


# ===========================================================================
# GET /api/v1/costs/recommendations/{recommendation_id}
# ===========================================================================


class TestGetRecommendation:
    @pytest.mark.asyncio
    async def test_found(self, handler):
        rec = MagicMock()
        rec.to_dict.return_value = {"id": "r-1", "type": "caching"}
        opt = MagicMock()
        opt.get_recommendation.return_value = rec
        req = _req(match_info={"recommendation_id": "r-1"})
        with _patch_optimizer(opt):
            resp = await handler.handle_get_recommendation(req)
        assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_not_found(self, handler):
        opt = MagicMock()
        opt.get_recommendation.return_value = None
        req = _req(match_info={"recommendation_id": "missing"})
        with _patch_optimizer(opt):
            resp = await handler.handle_get_recommendation(req)
        assert _status(resp) == 404

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        req = _req(match_info={"recommendation_id": "r-1"})
        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            side_effect=RuntimeError("broken"),
        ):
            resp = await handler.handle_get_recommendation(req)
        assert _status(resp) == 500


# ===========================================================================
# POST /api/v1/costs/recommendations/{id}/apply
# ===========================================================================


class TestApplyRecommendation:
    @pytest.mark.asyncio
    async def test_apply_success(self, handler):
        rec = MagicMock()
        rec.to_dict.return_value = {"id": "r-1", "status": "applied"}
        opt = MagicMock()
        opt.apply_recommendation.return_value = True
        opt.get_recommendation.return_value = rec
        body = {"user_id": "user-1"}
        req = _req("POST", body=body, match_info={"recommendation_id": "r-1"})
        with _patch_optimizer(opt), _patch_parse_body(body):
            resp = await handler.handle_apply_recommendation(req)
        assert _status(resp) == 200
        d = _body(resp)
        assert d["success"] is True
        assert d["recommendation"]["status"] == "applied"

    @pytest.mark.asyncio
    async def test_apply_not_found(self, handler):
        opt = MagicMock()
        opt.apply_recommendation.return_value = False
        body = {"user_id": "u"}
        req = _req("POST", body=body, match_info={"recommendation_id": "missing"})
        with _patch_optimizer(opt), _patch_parse_body(body):
            resp = await handler.handle_apply_recommendation(req)
        assert _status(resp) == 404

    @pytest.mark.asyncio
    async def test_apply_default_user_id(self, handler):
        rec = MagicMock()
        rec.to_dict.return_value = {"id": "r-1"}
        opt = MagicMock()
        opt.apply_recommendation.return_value = True
        opt.get_recommendation.return_value = rec
        body = {}
        req = _req("POST", body=body, match_info={"recommendation_id": "r-1"})
        with _patch_optimizer(opt), _patch_parse_body(body):
            resp = await handler.handle_apply_recommendation(req)
        opt.apply_recommendation.assert_called_once_with("r-1", "unknown")

    @pytest.mark.asyncio
    async def test_apply_parse_error(self, handler):
        from aiohttp import web

        err = web.json_response({"error": "bad"}, status=400)
        req = _req("POST", match_info={"recommendation_id": "r-1"})
        with _patch_parse_body(None, err=err):
            resp = await handler.handle_apply_recommendation(req)
        assert _status(resp) == 400


# ===========================================================================
# POST /api/v1/costs/recommendations/{id}/dismiss
# ===========================================================================


class TestDismissRecommendation:
    @pytest.mark.asyncio
    async def test_dismiss_success(self, handler):
        opt = MagicMock()
        opt.dismiss_recommendation.return_value = True
        req = _req("POST", match_info={"recommendation_id": "r-1"})
        with _patch_optimizer(opt):
            resp = await handler.handle_dismiss_recommendation(req)
        assert _status(resp) == 200
        d = _body(resp)
        assert d["success"] is True
        assert d["dismissed"] is True

    @pytest.mark.asyncio
    async def test_dismiss_not_found(self, handler):
        opt = MagicMock()
        opt.dismiss_recommendation.return_value = False
        req = _req("POST", match_info={"recommendation_id": "x"})
        with _patch_optimizer(opt):
            resp = await handler.handle_dismiss_recommendation(req)
        assert _status(resp) == 404

    @pytest.mark.asyncio
    async def test_dismiss_error_returns_500(self, handler):
        req = _req("POST", match_info={"recommendation_id": "r-1"})
        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            side_effect=ValueError("err"),
        ):
            resp = await handler.handle_dismiss_recommendation(req)
        assert _status(resp) == 500


# ===========================================================================
# GET /api/v1/costs/recommendations/detailed
# ===========================================================================


class TestGetRecommendationsDetailed:
    def _make_rec(self, rec_id, rec_type, savings):
        r = MagicMock()
        r.to_dict.return_value = {
            "id": rec_id,
            "type": rec_type,
            "estimated_savings_usd": savings,
        }
        return r

    def _mock_opt(self, recs):
        opt = MagicMock()
        opt.get_workspace_recommendations.return_value = recs
        summary = MagicMock()
        summary.to_dict.return_value = {
            "total_savings": sum(r.to_dict()["estimated_savings_usd"] for r in recs)
        }
        opt.get_summary.return_value = summary
        return opt

    @pytest.mark.asyncio
    async def test_with_implementation(self, handler):
        rec = self._make_rec("r-1", "model_downgrade", 100)
        opt = self._mock_opt([rec])
        with _patch_optimizer(opt):
            resp = await handler.handle_get_recommendations_detailed(
                _req(query="include_implementation=true")
            )
        d = _body(resp)
        assert d["count"] == 1
        r = d["recommendations"][0]
        assert "implementation_steps" in r
        assert r["difficulty"] == "easy"
        assert r["time_to_implement"] == "< 1 hour"

    @pytest.mark.asyncio
    async def test_without_implementation(self, handler):
        rec = self._make_rec("r-1", "caching", 50)
        opt = self._mock_opt([rec])
        with _patch_optimizer(opt):
            resp = await handler.handle_get_recommendations_detailed(
                _req(query="include_implementation=false")
            )
        r = _body(resp)["recommendations"][0]
        assert "implementation_steps" not in r
        assert "difficulty" not in r

    @pytest.mark.asyncio
    async def test_min_savings_filter(self, handler):
        r1 = self._make_rec("r-1", "caching", 10)
        r2 = self._make_rec("r-2", "batching", 100)
        opt = self._mock_opt([r1, r2])
        with _patch_optimizer(opt):
            resp = await handler.handle_get_recommendations_detailed(_req(query="min_savings=50"))
        d = _body(resp)
        assert d["count"] == 1
        assert d["recommendations"][0]["id"] == "r-2"

    @pytest.mark.asyncio
    async def test_sorted_by_savings_descending(self, handler):
        r1 = self._make_rec("r-1", "caching", 20)
        r2 = self._make_rec("r-2", "batching", 100)
        r3 = self._make_rec("r-3", "model_downgrade", 50)
        opt = self._mock_opt([r1, r2, r3])
        with _patch_optimizer(opt):
            resp = await handler.handle_get_recommendations_detailed(_req())
        recs = _body(resp)["recommendations"]
        assert [r["estimated_savings_usd"] for r in recs] == [100, 50, 20]

    @pytest.mark.asyncio
    async def test_total_potential_savings(self, handler):
        r1 = self._make_rec("r-1", "caching", 30)
        r2 = self._make_rec("r-2", "batching", 70)
        opt = self._mock_opt([r1, r2])
        with _patch_optimizer(opt):
            resp = await handler.handle_get_recommendations_detailed(_req())
        assert _body(resp)["total_potential_savings_usd"] == 100

    @pytest.mark.asyncio
    async def test_rate_limiting_type(self, handler):
        rec = self._make_rec("r-1", "rate_limiting", 40)
        opt = self._mock_opt([rec])
        with _patch_optimizer(opt):
            resp = await handler.handle_get_recommendations_detailed(
                _req(query="include_implementation=true")
            )
        r = _body(resp)["recommendations"][0]
        assert r["difficulty"] == "easy"
        assert r["time_to_implement"] == "1-2 hours"

    @pytest.mark.asyncio
    async def test_unknown_type_gets_defaults(self, handler):
        rec = self._make_rec("r-1", "some_unknown_type", 25)
        opt = self._mock_opt([rec])
        with _patch_optimizer(opt):
            resp = await handler.handle_get_recommendations_detailed(
                _req(query="include_implementation=true")
            )
        r = _body(resp)["recommendations"][0]
        assert r["difficulty"] == "medium"
        assert r["time_to_implement"] == "2-4 hours"
        assert len(r["implementation_steps"]) == 4

    @pytest.mark.asyncio
    async def test_analyze_called_when_empty(self, handler):
        opt = MagicMock()
        opt.get_workspace_recommendations.side_effect = [[], []]
        opt.analyze_workspace = AsyncMock()
        summary = MagicMock()
        summary.to_dict.return_value = {}
        opt.get_summary.return_value = summary
        with _patch_optimizer(opt):
            resp = await handler.handle_get_recommendations_detailed(_req())
        opt.analyze_workspace.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        with patch(
            "aragora.billing.optimizer.get_cost_optimizer",
            side_effect=ImportError("no module"),
        ):
            resp = await handler.handle_get_recommendations_detailed(_req())
        assert _status(resp) == 500


# ===========================================================================
# GET /api/v1/costs/efficiency
# ===========================================================================


class TestGetEfficiency:
    def _tracker(self, stats):
        t = MagicMock()
        t.get_workspace_stats.return_value = stats
        return t

    @pytest.mark.asyncio
    async def test_metrics_calculated(self, handler):
        t = self._tracker(
            {
                "total_tokens_in": 500_000,
                "total_tokens_out": 200_000,
                "total_api_calls": 1000,
                "total_cost_usd": "70.00",
                "cost_by_model": {"claude-3-opus": Decimal("50"), "gpt-4": Decimal("20")},
            }
        )
        with _patch_tracker(t):
            resp = await handler.handle_get_efficiency(_req(query="workspace_id=ws&range=30d"))
        assert _status(resp) == 200
        d = _body(resp)
        data = d["data"]
        assert data["cost_per_1k_tokens"] == pytest.approx(0.1, abs=0.001)
        assert data["avg_tokens_per_call"] == 700.0
        assert data["cost_per_call"] == pytest.approx(0.07, abs=0.001)

    @pytest.mark.asyncio
    async def test_zero_everything(self, handler):
        t = self._tracker(
            {
                "total_tokens_in": 0,
                "total_tokens_out": 0,
                "total_api_calls": 0,
                "total_cost_usd": "0",
                "cost_by_model": {},
            }
        )
        with _patch_tracker(t):
            resp = await handler.handle_get_efficiency(_req())
        data = _body(resp)["data"]
        assert data["cost_per_1k_tokens"] == 0
        assert data["avg_tokens_per_call"] == 0
        assert data["cost_per_call"] == 0

    @pytest.mark.asyncio
    async def test_model_utilization_sorted(self, handler):
        t = self._tracker(
            {
                "total_tokens_in": 100,
                "total_tokens_out": 0,
                "total_api_calls": 1,
                "total_cost_usd": "100",
                "cost_by_model": {"small": Decimal("20"), "large": Decimal("80")},
            }
        )
        with _patch_tracker(t):
            resp = await handler.handle_get_efficiency(_req())
        data = _body(resp)["data"]
        # Handler returns efficiency metrics; cost_per_1k_tokens = 100/100*1000 = 1000
        assert data["cost_per_1k_tokens"] == pytest.approx(1000.0, rel=1e-2)
        assert data["avg_tokens_per_call"] == 100.0
        assert data["cost_per_call"] == pytest.approx(100.0, rel=1e-2)

    @pytest.mark.asyncio
    async def test_no_tracker_returns_503(self, handler):
        with _patch_tracker(None):
            resp = await handler.handle_get_efficiency(_req())
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            side_effect=RuntimeError("oops"),
        ):
            resp = await handler.handle_get_efficiency(_req())
        assert _status(resp) == 500


# ===========================================================================
# GET /api/v1/costs/forecast
# ===========================================================================


class TestGetForecast:
    def _forecaster(self, report_dict):
        report = MagicMock()
        report.to_dict.return_value = report_dict
        f = MagicMock()
        f.generate_forecast = AsyncMock(return_value=report)
        return f

    @pytest.mark.asyncio
    async def test_success(self, handler):
        f = self._forecaster(
            {"projected_cost": 300.0, "confidence": 0.85, "projected_monthly_cost": 300.0}
        )
        with _patch_forecaster(f):
            resp = await handler.handle_get_forecast(_req(query="workspace_id=ws&days=60"))
        assert _status(resp) == 200
        assert _body(resp)["data"]["projected_monthly_cost"] == 300.0

    @pytest.mark.asyncio
    async def test_default_days_30(self, handler):
        f = self._forecaster({"projected_cost": 100})
        with _patch_forecaster(f):
            await handler.handle_get_forecast(_req())
        call_kwargs = f.generate_forecast.call_args.kwargs
        assert call_kwargs["forecast_days"] == 30

    @pytest.mark.asyncio
    async def test_import_error_returns_500(self, handler):
        with patch(
            "aragora.billing.forecaster.get_cost_forecaster",
            side_effect=ImportError("no forecaster"),
        ):
            resp = await handler.handle_get_forecast(_req())
        assert _status(resp) == 500


# ===========================================================================
# GET /api/v1/costs/forecast/detailed
# ===========================================================================


class TestGetForecastDetailed:
    def _forecaster(self, projected_cost=150.0):
        report = MagicMock()
        report.to_dict.return_value = {"projected_cost": projected_cost}
        f = MagicMock()
        f.generate_forecast = AsyncMock(return_value=report)
        return f

    @pytest.mark.asyncio
    async def test_with_confidence(self, handler):
        f = self._forecaster(210.0)
        with _patch_forecaster(f):
            resp = await handler.handle_get_forecast_detailed(
                _req(query="days=7&include_confidence=true")
            )
        d = _body(resp)
        assert d["forecast_days"] == 7
        assert len(d["daily_forecasts"]) == 7
        day0 = d["daily_forecasts"][0]
        assert "confidence_low" in day0
        assert "confidence_high" in day0
        assert day0["confidence_low"] < day0["projected_cost_usd"] < day0["confidence_high"]
        assert d["confidence_level"] == 0.80

    @pytest.mark.asyncio
    async def test_without_confidence(self, handler):
        f = self._forecaster(90.0)
        with _patch_forecaster(f):
            resp = await handler.handle_get_forecast_detailed(
                _req(query="days=3&include_confidence=false")
            )
        d = _body(resp)
        assert len(d["daily_forecasts"]) == 3
        assert "confidence_low" not in d["daily_forecasts"][0]
        assert "confidence_level" not in d

    @pytest.mark.asyncio
    async def test_daily_cost_proportional(self, handler):
        f = self._forecaster(100.0)
        with _patch_forecaster(f):
            resp = await handler.handle_get_forecast_detailed(_req(query="days=10"))
        d = _body(resp)
        for day in d["daily_forecasts"]:
            assert day["projected_cost_usd"] == pytest.approx(10.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_zero_projected_cost(self, handler):
        f = self._forecaster(0.0)
        with _patch_forecaster(f):
            resp = await handler.handle_get_forecast_detailed(_req(query="days=5"))
        d = _body(resp)
        assert all(day["projected_cost_usd"] == 0.0 for day in d["daily_forecasts"])

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        with patch(
            "aragora.billing.forecaster.get_cost_forecaster",
            side_effect=RuntimeError("fail"),
        ):
            resp = await handler.handle_get_forecast_detailed(_req())
        assert _status(resp) == 500


# ===========================================================================
# POST /api/v1/costs/forecast/simulate
# ===========================================================================


class TestSimulateForecast:
    @pytest.mark.asyncio
    async def test_simulate_success(self, handler):
        result = MagicMock()
        result.to_dict.return_value = {"scenario": "Double", "projected_cost": 200}
        f = MagicMock()
        f.simulate_scenario = AsyncMock(return_value=result)
        body = {
            "workspace_id": "ws",
            "scenario": {"name": "Double", "description": "2x", "changes": {"mult": 2}},
            "days": 30,
        }
        with (
            _patch_forecaster(f),
            _patch_parse_body(body),
            patch(
                "aragora.billing.forecaster.SimulationScenario",
            ),
        ):
            resp = await handler.handle_simulate_forecast(_req("POST", body=body))
        assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_default_scenario_fields(self, handler):
        result = MagicMock()
        result.to_dict.return_value = {"projected_cost": 50}
        f = MagicMock()
        f.simulate_scenario = AsyncMock(return_value=result)
        body = {}  # All defaults
        with (
            _patch_forecaster(f),
            _patch_parse_body(body),
            patch(
                "aragora.billing.forecaster.SimulationScenario",
            ) as mock_scenario,
        ):
            await handler.handle_simulate_forecast(_req("POST", body=body))
        mock_scenario.assert_called_once_with(name="Custom Scenario", description="", changes={})

    @pytest.mark.asyncio
    async def test_parse_error(self, handler):
        from aiohttp import web

        err = web.json_response({"error": "bad"}, status=400)
        with _patch_parse_body(None, err=err):
            resp = await handler.handle_simulate_forecast(_req("POST"))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        body = {"scenario": {}}
        with (
            _patch_parse_body(body),
            patch(
                "aragora.billing.forecaster.get_cost_forecaster",
                side_effect=ImportError("missing"),
            ),
        ):
            resp = await handler.handle_simulate_forecast(_req("POST", body=body))
        assert _status(resp) == 500


# ===========================================================================
# GET /api/v1/costs/export
# ===========================================================================


class TestExport:
    @pytest.mark.asyncio
    async def test_json_export(self, handler):
        s = _summary()
        with _patch_summary(s):
            resp = await handler.handle_export(_req(query="format=json&range=30d&group_by=daily"))
        assert _status(resp) == 200
        d = _body(resp)
        assert d["workspace_id"] == "default"
        assert d["time_range"] == "30d"
        assert d["group_by"] == "daily"
        assert "exported_at" in d
        assert "rows" in d
        assert d["total_cost"] == 125.50
        assert d["total_tokens"] == 3_125_000
        assert d["total_api_calls"] == 12_550

    @pytest.mark.asyncio
    async def test_csv_export(self, handler):
        with _patch_summary():
            resp = await handler.handle_export(_req(query="format=csv"))
        assert _status(resp) == 200
        assert resp.content_type == "text/csv"

    @pytest.mark.asyncio
    async def test_invalid_format_returns_400(self, handler):
        resp = await handler.handle_export(_req(query="format=xml"))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_provider_grouping(self, handler):
        s = _summary()
        with _patch_summary(s):
            resp = await handler.handle_export(_req(query="format=json&group_by=provider"))
        d = _body(resp)
        assert len(d["rows"]) == len(s.cost_by_provider)

    @pytest.mark.asyncio
    async def test_feature_grouping(self, handler):
        s = _summary()
        with _patch_summary(s):
            resp = await handler.handle_export(_req(query="format=json&group_by=feature"))
        d = _body(resp)
        assert len(d["rows"]) == len(s.cost_by_feature)

    @pytest.mark.asyncio
    async def test_daily_grouping_default(self, handler):
        s = _summary()
        with _patch_summary(s):
            resp = await handler.handle_export(_req(query="format=json"))
        d = _body(resp)
        assert len(d["rows"]) == len(s.daily_costs)

    @pytest.mark.asyncio
    async def test_default_format_is_json(self, handler):
        with _patch_summary():
            resp = await handler.handle_export(_req())
        assert _status(resp) == 200
        _body(resp)  # Should parse as JSON

    @pytest.mark.asyncio
    async def test_csv_has_content_disposition(self, handler):
        with _patch_summary():
            resp = await handler.handle_export(_req(query="format=csv&workspace_id=ws1&range=7d"))
        headers = resp.headers
        assert "attachment" in headers.get("Content-Disposition", "")
        assert "ws1" in headers.get("Content-Disposition", "")

    @pytest.mark.asyncio
    async def test_export_error_returns_500(self, handler):
        with _patch_summary(side_effect=KeyError("missing")):
            resp = await handler.handle_export(_req(query="format=json"))
        assert _status(resp) == 500


# ===========================================================================
# GET /api/v1/costs/usage
# ===========================================================================


class TestGetUsage:
    def _mock_report(self, **kwargs):
        report = MagicMock()
        report.total_cost_usd = kwargs.get("total_cost_usd", Decimal("100"))
        report.total_tokens_in = kwargs.get("total_tokens_in", 400_000)
        report.total_tokens_out = kwargs.get("total_tokens_out", 150_000)
        report.total_api_calls = kwargs.get("total_api_calls", 800)
        report.cost_by_provider = kwargs.get(
            "cost_by_provider", {"Anthropic": Decimal("70"), "OpenAI": Decimal("30")}
        )
        report.cost_by_operation = kwargs.get("cost_by_operation", {})
        report.cost_by_model = kwargs.get("cost_by_model", {})
        report.calls_by_provider = kwargs.get(
            "calls_by_provider", {"Anthropic": 600, "OpenAI": 200}
        )
        return report

    def _tracker(self, report):
        t = MagicMock()
        t.generate_report = AsyncMock(return_value=report)
        return t

    @pytest.mark.asyncio
    async def test_usage_by_provider(self, handler):
        report = self._mock_report()
        t = self._tracker(report)
        with _patch_tracker(t):
            resp = await handler.handle_get_usage(
                _req(query="workspace_id=ws&range=7d&group_by=provider")
            )
        assert _status(resp) == 200
        d = _body(resp)
        assert d["workspace_id"] == "ws"
        assert d["time_range"] == "7d"
        assert d["total_cost_usd"] == 100.0
        assert d["total_tokens_in"] == 400_000
        assert d["total_api_calls"] == 800
        assert len(d["usage"]) == 2

    @pytest.mark.asyncio
    async def test_usage_by_operation(self, handler):
        report = self._mock_report(
            cost_by_provider={},
            cost_by_operation={"debate": Decimal("60"), "review": Decimal("40")},
        )
        t = self._tracker(report)
        with _patch_tracker(t):
            resp = await handler.handle_get_usage(_req(query="group_by=operation"))
        d = _body(resp)
        assert len(d["usage"]) == 2

    @pytest.mark.asyncio
    async def test_usage_by_model(self, handler):
        report = self._mock_report(
            cost_by_provider={},
            cost_by_model={"claude-opus": Decimal("80"), "gpt-4o": Decimal("20")},
        )
        t = self._tracker(report)
        with _patch_tracker(t):
            resp = await handler.handle_get_usage(_req(query="group_by=model"))
        d = _body(resp)
        assert len(d["usage"]) == 2

    @pytest.mark.asyncio
    async def test_no_tracker_returns_503(self, handler):
        with _patch_tracker(None):
            resp = await handler.handle_get_usage(_req())
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_period_start_and_end_present(self, handler):
        report = self._mock_report()
        t = self._tracker(report)
        with _patch_tracker(t):
            resp = await handler.handle_get_usage(_req())
        d = _body(resp)
        assert "period_start" in d
        assert "period_end" in d

    @pytest.mark.asyncio
    async def test_range_days_mapping(self, handler):
        """Different range values produce different period_start dates."""
        for rng in ("24h", "7d", "30d", "90d"):
            report = self._mock_report()
            t = self._tracker(report)
            with _patch_tracker(t):
                resp = await handler.handle_get_usage(_req(query=f"range={rng}"))
            assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            side_effect=TypeError("bad"),
        ):
            resp = await handler.handle_get_usage(_req())
        assert _status(resp) == 500


# ===========================================================================
# POST /api/v1/costs/constraints/check
# ===========================================================================


class TestCheckConstraints:
    def _budget(
        self,
        monthly=Decimal("1000"),
        monthly_spend=Decimal("200"),
        daily=None,
        daily_spend=Decimal("0"),
    ):
        b = MagicMock()
        b.monthly_limit_usd = monthly
        b.current_monthly_spend = monthly_spend
        b.daily_limit_usd = daily
        b.current_daily_spend = daily_spend
        return b

    @pytest.mark.asyncio
    async def test_allowed(self, handler):
        tracker = MagicMock()
        tracker.get_budget.return_value = self._budget()
        body = {"workspace_id": "ws", "estimated_cost_usd": 50, "operation": "debate"}
        with _patch_tracker(tracker), _patch_parse_body(body):
            resp = await handler.handle_check_constraints(_req("POST", body=body))
        d = _body(resp)
        assert d["allowed"] is True
        assert d["reason"] == "OK"
        assert d["remaining_monthly_budget"] == 800.0

    @pytest.mark.asyncio
    async def test_exceed_monthly(self, handler):
        tracker = MagicMock()
        tracker.get_budget.return_value = self._budget(
            monthly=Decimal("100"), monthly_spend=Decimal("95")
        )
        body = {"estimated_cost_usd": 10}
        with _patch_tracker(tracker), _patch_parse_body(body):
            resp = await handler.handle_check_constraints(_req("POST", body=body))
        d = _body(resp)
        assert d["allowed"] is False
        assert "monthly budget" in d["reason"]

    @pytest.mark.asyncio
    async def test_exceed_daily(self, handler):
        tracker = MagicMock()
        tracker.get_budget.return_value = self._budget(
            daily=Decimal("20"), daily_spend=Decimal("18")
        )
        body = {"estimated_cost_usd": 5}
        with _patch_tracker(tracker), _patch_parse_body(body):
            resp = await handler.handle_check_constraints(_req("POST", body=body))
        d = _body(resp)
        assert d["allowed"] is False
        assert "daily budget" in d["reason"]

    @pytest.mark.asyncio
    async def test_negative_cost_returns_400(self, handler):
        body = {"estimated_cost_usd": -1}
        with _patch_parse_body(body):
            resp = await handler.handle_check_constraints(_req("POST", body=body))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_no_tracker_allowed(self, handler):
        body = {"estimated_cost_usd": 100}
        with _patch_tracker(None), _patch_parse_body(body):
            resp = await handler.handle_check_constraints(_req("POST", body=body))
        d = _body(resp)
        assert d["allowed"] is True
        assert d["remaining_monthly_budget"] is None

    @pytest.mark.asyncio
    async def test_no_budget_allowed(self, handler):
        tracker = MagicMock()
        tracker.get_budget.return_value = None
        body = {"estimated_cost_usd": 50}
        with _patch_tracker(tracker), _patch_parse_body(body):
            resp = await handler.handle_check_constraints(_req("POST", body=body))
        d = _body(resp)
        assert d["allowed"] is True

    @pytest.mark.asyncio
    async def test_zero_cost_allowed(self, handler):
        tracker = MagicMock()
        tracker.get_budget.return_value = self._budget(
            monthly=Decimal("10"), monthly_spend=Decimal("10")
        )
        body = {"estimated_cost_usd": 0}
        with _patch_tracker(tracker), _patch_parse_body(body):
            resp = await handler.handle_check_constraints(_req("POST", body=body))
        d = _body(resp)
        assert d["allowed"] is True

    @pytest.mark.asyncio
    async def test_monthly_not_exceeded_daily_checked(self, handler):
        """When monthly is OK but daily is over, result is denied."""
        tracker = MagicMock()
        tracker.get_budget.return_value = self._budget(
            monthly=Decimal("1000"),
            monthly_spend=Decimal("100"),
            daily=Decimal("10"),
            daily_spend=Decimal("8"),
        )
        body = {"estimated_cost_usd": 5}
        with _patch_tracker(tracker), _patch_parse_body(body):
            resp = await handler.handle_check_constraints(_req("POST", body=body))
        d = _body(resp)
        assert d["allowed"] is False
        assert "daily" in d["reason"]

    @pytest.mark.asyncio
    async def test_parse_error_forwarded(self, handler):
        from aiohttp import web

        err = web.json_response({"error": "bad"}, status=400)
        with _patch_parse_body(None, err=err):
            resp = await handler.handle_check_constraints(_req("POST"))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_operation_field_echoed(self, handler):
        body = {"estimated_cost_usd": 1, "operation": "analysis"}
        with _patch_tracker(None), _patch_parse_body(body):
            resp = await handler.handle_check_constraints(_req("POST", body=body))
        assert _body(resp)["operation"] == "analysis"


# ===========================================================================
# POST /api/v1/costs/estimate
# ===========================================================================


class TestEstimateCost:
    @pytest.mark.asyncio
    async def test_default_model_provider(self, handler):
        body = {"tokens_input": 1_000_000, "tokens_output": 500_000}
        with _patch_parse_body(body):
            resp = await handler.handle_estimate_cost(_req("POST", body=body))
        assert _status(resp) == 200
        d = _body(resp)
        assert d["pricing"]["model"] == "claude-opus-4"
        assert d["pricing"]["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_zero_tokens(self, handler):
        body = {"tokens_input": 0, "tokens_output": 0}
        with _patch_parse_body(body):
            resp = await handler.handle_estimate_cost(_req("POST", body=body))
        d = _body(resp)
        assert d["estimated_cost_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_operation_echoed(self, handler):
        body = {"tokens_input": 100, "tokens_output": 100, "operation": "debate"}
        with _patch_parse_body(body):
            resp = await handler.handle_estimate_cost(_req("POST", body=body))
        assert _body(resp)["operation"] == "debate"

    @pytest.mark.asyncio
    async def test_unknown_provider_and_model_uses_openrouter_default(self, handler):
        """The $2/$8 default is reached only when the MODEL has no row
        anywhere -- not merely when the provider label is unrecognised.

        This test used to omit ``model``, so it exercised the default
        ``claude-opus-4``, which has a real priced row that
        ``calculate_token_cost`` finds by exact spelling regardless of the
        label; it therefore charged $30 and had been failing on main. Naming
        a genuinely uncataloged model tests what the name claims.
        """
        body = {
            "tokens_input": 1_000_000,
            "tokens_output": 1_000_000,
            "provider": "xyzzy",
            "model": "totally-unknown-model-v0",
        }
        with _patch_parse_body(body):
            resp = await handler.handle_estimate_cost(_req("POST", body=body))
        d = _body(resp)
        # openrouter default: $2/M in + $8/M out = $10
        assert d["estimated_cost_usd"] == pytest.approx(10.0, abs=0.1)
        assert d["pricing"]["input_per_1m"] == pytest.approx(2.0)
        assert d["pricing"]["output_per_1m"] == pytest.approx(8.0)

    @pytest.mark.asyncio
    async def test_unrecognised_label_still_bills_the_model_real_rate(self, handler):
        """A provider label is not information about a model's price."""
        body = {
            "tokens_input": 1_000_000,
            "tokens_output": 1_000_000,
            "provider": "xyzzy",
            "model": "claude-opus-4",
        }
        with _patch_parse_body(body):
            resp = await handler.handle_estimate_cost(_req("POST", body=body))
        d = _body(resp)
        assert d["estimated_cost_usd"] == pytest.approx(30.0)
        # The reported per-1M figures are the EFFECTIVE rates actually
        # charged, so they can no longer contradict the total.
        assert d["pricing"]["input_per_1m"] == pytest.approx(5.0)
        assert d["pricing"]["output_per_1m"] == pytest.approx(25.0)

    @pytest.mark.asyncio
    async def test_breakdown_sums_to_the_total_at_a_long_context_input(self, handler):
        """Above a documented long-context threshold the two halves used to
        be quoted at the FLAT rate and stopped adding up (gpt-6-astra, 300k
        in / 10k out: 6.00 + 0.50 against a real 6.75)."""
        body = {
            "tokens_input": 300_000,
            "tokens_output": 10_000,
            "provider": "openai",
            "model": "gpt-6-astra",
        }
        with _patch_parse_body(body):
            resp = await handler.handle_estimate_cost(_req("POST", body=body))
        d = _body(resp)
        total = d["estimated_cost_usd"]
        assert total == pytest.approx(6.75)
        assert d["breakdown"]["input_cost_usd"] + d["breakdown"]["output_cost_usd"] == (
            pytest.approx(total, abs=1e-6)
        )
        # And the reported rates are the tiered ones actually applied.
        assert d["pricing"]["input_per_1m"] == pytest.approx(20.0)
        assert d["pricing"]["output_per_1m"] == pytest.approx(75.0)

    @pytest.mark.asyncio
    async def test_breakdown_present(self, handler):
        body = {"tokens_input": 500_000, "tokens_output": 250_000}
        with _patch_parse_body(body):
            resp = await handler.handle_estimate_cost(_req("POST", body=body))
        d = _body(resp)
        assert d["breakdown"]["input_tokens"] == 500_000
        assert d["breakdown"]["output_tokens"] == 250_000
        assert "input_cost_usd" in d["breakdown"]
        assert "output_cost_usd" in d["breakdown"]

    @pytest.mark.asyncio
    async def test_pricing_info_present(self, handler):
        body = {"tokens_input": 100, "tokens_output": 100, "model": "gpt-4o", "provider": "openai"}
        with _patch_parse_body(body):
            resp = await handler.handle_estimate_cost(_req("POST", body=body))
        d = _body(resp)
        assert "input_per_1m" in d["pricing"]
        assert "output_per_1m" in d["pricing"]

    @pytest.mark.asyncio
    async def test_parse_error_forwarded(self, handler):
        from aiohttp import web

        err = web.json_response({"error": "bad"}, status=400)
        with _patch_parse_body(None, err=err):
            resp = await handler.handle_estimate_cost(_req("POST"))
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_error_returns_500(self, handler):
        body = {"tokens_input": 100}
        with (
            _patch_parse_body(body),
            patch(
                "aragora.server.handlers.costs.handler.calculate_token_cost",
                side_effect=ValueError("bad"),
            ),
        ):
            resp = await handler.handle_estimate_cost(_req("POST", body=body))
        assert _status(resp) == 500


# ===========================================================================
# Cross-Endpoint Error Categories
# ===========================================================================


class TestErrorCategories:
    """Ensure every caught exception type produces 500 for sample endpoints."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc_type",
        [ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError, ImportError],
    )
    async def test_get_costs_catches_all_types(self, handler, exc_type):
        with _patch_summary(side_effect=exc_type("test")):
            resp = await handler.handle_get_costs(_req())
        assert _status(resp) == 500

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc_type",
        [ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError, ImportError],
    )
    async def test_set_budget_catches_all_types(self, handler, exc_type):
        body = {"budget": 100}
        with (
            _patch_parse_body(body),
            _patch_tracker(MagicMock()),
            patch(
                "aragora.server.handlers.costs.handler.Decimal",
                side_effect=exc_type("test"),
            ),
        ):
            resp = await handler.handle_set_budget(_req("POST", body=body))
        assert _status(resp) == 500

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc_type",
        [ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError, ImportError],
    )
    async def test_efficiency_catches_all_types(self, handler, exc_type):
        with patch(
            "aragora.server.handlers.costs.handler._models._get_cost_tracker",
            side_effect=exc_type("test"),
        ):
            resp = await handler.handle_get_efficiency(_req())
        assert _status(resp) == 500
