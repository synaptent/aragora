"""
Cost visibility HTTP handler class.

Provides the CostHandler class with all API endpoint methods for cost
tracking, budgets, alerts, recommendations, forecasting, and exports.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from aiohttp import web

from aragora.server.handlers.utils import parse_json_body
from aragora.server.handlers.utils.aiohttp_responses import web_error_response
from aragora.server.handlers.utils.responses import HandlerResult
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.handlers.api_decorators import api_endpoint
from aragora.server.validation.query_params import safe_query_int

from aragora.billing.usage import PROVIDER_PRICING, calculate_token_cost

from .helpers import (
    _build_export_rows,
    _export_csv_response,
    _get_implementation_difficulty,
    _get_implementation_steps,
    _get_implementation_time,
)
from . import models as _models
from aragora.server.handlers.utils.decorators import handle_errors

logger = logging.getLogger(__name__)


class CostHandler:
    """Handler for cost visibility API endpoints."""

    ROUTES = [
        # Versioned paths (canonical)
        "/api/v1/costs",
        "/api/v1/costs/alerts",
        "/api/v1/costs/alerts/*/dismiss",
        "/api/v1/costs/analytics/budget-utilization",
        "/api/v1/costs/analytics/by-agent",
        "/api/v1/costs/analytics/by-debate",
        "/api/v1/costs/analytics/by-model",
        "/api/v1/costs/analytics/trend",
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
        "/api/v1/costs/timeline",
        "/api/v1/costs/usage",
        # Debate session cost endpoints (v1 canonical)
        "/api/v1/costs/debates/{debate_id}",
        "/api/v1/costs/debates/{debate_id}/line-items",
        "/api/v1/costs/debates/{debate_id}/performance",
        # Legacy paths (unversioned)
        "/api/costs",
        "/api/costs/alerts",
        "/api/costs/alerts/*/dismiss",
        "/api/costs/analytics/budget-utilization",
        "/api/costs/analytics/by-agent",
        "/api/costs/analytics/by-debate",
        "/api/costs/analytics/by-model",
        "/api/costs/analytics/trend",
        "/api/costs/breakdown",
        "/api/costs/budget",
        "/api/costs/budgets",
        "/api/costs/constraints/check",
        "/api/costs/efficiency",
        "/api/costs/estimate",
        "/api/costs/export",
        "/api/costs/forecast",
        "/api/costs/forecast/detailed",
        "/api/costs/forecast/simulate",
        "/api/costs/recommendations",
        "/api/costs/recommendations/detailed",
        "/api/costs/recommendations/*",
        "/api/costs/recommendations/*/apply",
        "/api/costs/recommendations/*/dismiss",
        "/api/costs/timeline",
        "/api/costs/usage",
        # Debate session cost endpoints (legacy)
        "/api/costs/debates/{debate_id}",
        "/api/costs/debates/{debate_id}/line-items",
        "/api/costs/debates/{debate_id}/performance",
    ]

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        """Return whether this handler owns the given cost path."""
        return (
            self._resolve_registry_target(path, "GET") is not None
            or self._resolve_registry_target(path, "POST") is not None
        )

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests through the aiohttp-style handlers used by direct routes."""
        return self._run_async(self._dispatch_registry_request("GET", path, query_params, handler))

    @handle_errors
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route POST requests through the aiohttp-style handlers used by direct routes."""
        return self._run_async(self._dispatch_registry_request("POST", path, query_params, handler))

    @staticmethod
    def _run_async(coro: Any) -> HandlerResult | None:
        """Synchronously resolve async route helpers inside modular dispatch."""
        from aragora.server.handler_registry.core import _run_handler_coroutine

        return _run_handler_coroutine(coro)

    @staticmethod
    def _read_request_body(handler: Any) -> bytes:
        """Read the raw request body from the HTTP handler when needed."""
        try:
            content_length = int((getattr(handler, "headers", {}) or {}).get("Content-Length", "0"))
        except (TypeError, ValueError, AttributeError):
            content_length = 0
        if content_length <= 0 or not hasattr(handler, "rfile"):
            return b""
        body = handler.rfile.read(content_length)
        if isinstance(body, bytes):
            return body
        if isinstance(body, bytearray):
            return bytes(body)
        return b""

    @staticmethod
    def _match_dynamic(
        path: str,
        *,
        prefix: str,
        suffix: str = "",
        param_name: str,
    ) -> tuple[dict[str, str], ...] | None:
        """Match a single path-segment dynamic route and return extracted params."""
        if not path.startswith(prefix):
            return None
        remainder = path[len(prefix) :]
        if suffix:
            if not remainder.endswith(suffix):
                return None
            remainder = remainder[: -len(suffix)]
        token = remainder.strip("/")
        if not token or "/" in token:
            return None
        return ({param_name: token},)

    @classmethod
    def _resolve_registry_target(cls, path: str, method: str) -> tuple[str, dict[str, str]] | None:
        """Resolve a modular-dispatch path to the underlying aiohttp handler method."""
        get_routes = {
            "/api/v1/costs": "handle_get_costs",
            "/api/costs": "handle_get_costs",
            "/api/v1/costs/breakdown": "handle_get_breakdown",
            "/api/costs/breakdown": "handle_get_breakdown",
            "/api/v1/costs/timeline": "handle_get_timeline",
            "/api/costs/timeline": "handle_get_timeline",
            "/api/v1/costs/alerts": "handle_get_alerts",
            "/api/costs/alerts": "handle_get_alerts",
            "/api/v1/costs/recommendations": "handle_get_recommendations",
            "/api/costs/recommendations": "handle_get_recommendations",
            "/api/v1/costs/recommendations/detailed": "handle_get_recommendations_detailed",
            "/api/costs/recommendations/detailed": "handle_get_recommendations_detailed",
            "/api/v1/costs/export": "handle_export",
            "/api/costs/export": "handle_export",
            "/api/v1/costs/efficiency": "handle_get_efficiency",
            "/api/costs/efficiency": "handle_get_efficiency",
            "/api/v1/costs/forecast": "handle_get_forecast",
            "/api/costs/forecast": "handle_get_forecast",
            "/api/v1/costs/forecast/detailed": "handle_get_forecast_detailed",
            "/api/costs/forecast/detailed": "handle_get_forecast_detailed",
            "/api/v1/costs/usage": "handle_get_usage",
            "/api/costs/usage": "handle_get_usage",
            "/api/v1/costs/budgets": "handle_list_budgets",
            "/api/costs/budgets": "handle_list_budgets",
            "/api/v1/costs/analytics/trend": "handle_get_spend_trend",
            "/api/costs/analytics/trend": "handle_get_spend_trend",
            "/api/v1/costs/analytics/by-agent": "handle_get_spend_by_agent",
            "/api/costs/analytics/by-agent": "handle_get_spend_by_agent",
            "/api/v1/costs/analytics/by-model": "handle_get_spend_by_model",
            "/api/costs/analytics/by-model": "handle_get_spend_by_model",
            "/api/v1/costs/analytics/by-debate": "handle_get_spend_by_debate",
            "/api/costs/analytics/by-debate": "handle_get_spend_by_debate",
            "/api/v1/costs/analytics/budget-utilization": "handle_get_budget_utilization",
            "/api/costs/analytics/budget-utilization": "handle_get_budget_utilization",
        }
        post_routes = {
            "/api/v1/costs/budget": "handle_set_budget",
            "/api/costs/budget": "handle_set_budget",
            "/api/v1/costs/forecast/simulate": "handle_simulate_forecast",
            "/api/costs/forecast/simulate": "handle_simulate_forecast",
            "/api/v1/costs/budgets": "handle_create_budget",
            "/api/costs/budgets": "handle_create_budget",
            "/api/v1/costs/constraints/check": "handle_check_constraints",
            "/api/costs/constraints/check": "handle_check_constraints",
            "/api/v1/costs/estimate": "handle_estimate_cost",
            "/api/costs/estimate": "handle_estimate_cost",
            "/api/v1/costs/alerts": "handle_create_alert",
            "/api/costs/alerts": "handle_create_alert",
        }
        dynamic_routes = {
            "GET": [
                (
                    "/api/v1/costs/debates/",
                    "/line-items",
                    "debate_id",
                    "handle_get_debate_line_items",
                ),
                (
                    "/api/costs/debates/",
                    "/line-items",
                    "debate_id",
                    "handle_get_debate_line_items",
                ),
                (
                    "/api/v1/costs/debates/",
                    "/performance",
                    "debate_id",
                    "handle_get_debate_performance",
                ),
                (
                    "/api/costs/debates/",
                    "/performance",
                    "debate_id",
                    "handle_get_debate_performance",
                ),
                (
                    "/api/v1/costs/debates/",
                    "",
                    "debate_id",
                    "handle_get_debate_costs",
                ),
                (
                    "/api/costs/debates/",
                    "",
                    "debate_id",
                    "handle_get_debate_costs",
                ),
                (
                    "/api/v1/costs/recommendations/",
                    "",
                    "recommendation_id",
                    "handle_get_recommendation",
                ),
                (
                    "/api/costs/recommendations/",
                    "",
                    "recommendation_id",
                    "handle_get_recommendation",
                ),
            ],
            "POST": [
                ("/api/v1/costs/alerts/", "/dismiss", "alert_id", "handle_dismiss_alert"),
                ("/api/costs/alerts/", "/dismiss", "alert_id", "handle_dismiss_alert"),
                (
                    "/api/v1/costs/recommendations/",
                    "/apply",
                    "recommendation_id",
                    "handle_apply_recommendation",
                ),
                (
                    "/api/costs/recommendations/",
                    "/apply",
                    "recommendation_id",
                    "handle_apply_recommendation",
                ),
                (
                    "/api/v1/costs/recommendations/",
                    "/dismiss",
                    "recommendation_id",
                    "handle_dismiss_recommendation",
                ),
                (
                    "/api/costs/recommendations/",
                    "/dismiss",
                    "recommendation_id",
                    "handle_dismiss_recommendation",
                ),
            ],
        }

        route_map = get_routes if method == "GET" else post_routes if method == "POST" else {}
        handler_name = route_map.get(path)
        if handler_name is not None:
            return handler_name, {}

        for prefix, suffix, param_name, dynamic_handler in dynamic_routes.get(method, []):
            match = cls._match_dynamic(path, prefix=prefix, suffix=suffix, param_name=param_name)
            if match is not None:
                return dynamic_handler, match[0]
        return None

    @staticmethod
    def _build_registry_request(
        handler: Any,
        *,
        query_params: dict[str, Any],
        match_info: dict[str, str],
        body: bytes,
    ) -> Any:
        """Build the minimal aiohttp-like request object expected by the cost routes."""

        class _RequestAdapter:
            def __init__(self) -> None:
                self.query = query_params
                self.match_info = match_info
                self.headers = getattr(handler, "headers", {}) or {}
                self.method = getattr(handler, "command", "GET")
                self._auth_context = getattr(handler, "_auth_context", None)
                self.content_length = len(body) if body else None
                self._body = body

            async def json(self) -> dict[str, Any]:
                return json.loads(self._body.decode("utf-8")) if self._body else {}

            async def read(self) -> bytes:
                return self._body

        return _RequestAdapter()

    @staticmethod
    def _to_handler_result(response: Any) -> HandlerResult:
        """Normalize aiohttp and handler responses to the modular HandlerResult type."""
        if isinstance(response, HandlerResult):
            return response
        body = getattr(response, "body", b"")
        if isinstance(body, bytearray):
            body = bytes(body)
        elif body is None:
            text = getattr(response, "text", "") or ""
            body = text.encode("utf-8")
        content_type = getattr(response, "content_type", "application/json")
        if not content_type:
            content_type = "application/json"
        headers = dict(getattr(response, "headers", {}) or {})
        raw_status_code: Any = getattr(response, "status_code", None)
        if raw_status_code is None:
            raw_status_code = getattr(response, "status", 200)
        if raw_status_code is None:
            raw_status_code = 200
        return HandlerResult(
            status_code=int(raw_status_code),
            content_type=str(content_type),
            body=body if isinstance(body, bytes) else bytes(body),
            headers=headers,
        )

    async def _dispatch_registry_request(
        self,
        method: str,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Adapt modular-dispatch calls to the aiohttp-style route handlers."""
        resolved = self._resolve_registry_target(path, method)
        if resolved is None:
            return HandlerResult(
                status_code=404,
                content_type="application/json",
                body=json.dumps({"error": "Not found"}).encode("utf-8"),
                headers={},
            )
        handler_name, match_info = resolved
        route_handler = getattr(self, handler_name)
        request = self._build_registry_request(
            handler,
            query_params=query_params,
            match_info=match_info,
            body=self._read_request_body(handler) if method == "POST" else b"",
        )
        return self._to_handler_result(await route_handler(request))

    @api_endpoint(
        method="GET",
        path="/api/v1/costs",
        summary="Get cost summary",
        description="Fetch cost dashboard summary data including spending, budgets, and alerts.",
    )
    @rate_limit(requests_per_minute=60)  # Read operation
    @require_permission("costs:read")
    async def handle_get_costs(self, request: web.Request) -> web.Response:
        """
        GET /api/costs

        Get cost dashboard data.

        Query params:
            - range: Time range (24h, 7d, 30d, 90d)
            - workspace_id: Workspace ID (default: default)
        """
        try:
            time_range = request.query.get("range", "7d")
            workspace_id = request.query.get("workspace_id", "default")

            summary = await _models.get_cost_summary(
                workspace_id=workspace_id,
                time_range=time_range,
            )

            return web.json_response(
                {
                    "data": {
                        "total_cost_usd": summary.total_cost,
                        "budget_usd": summary.budget,
                        "tokens_in": getattr(summary, "tokens_in", summary.tokens_used),
                        "tokens_out": getattr(summary, "tokens_out", 0),
                        "api_calls": summary.api_calls,
                        "period_start": getattr(summary, "period_start", ""),
                        "period_end": getattr(summary, "period_end", ""),
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get costs: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/breakdown",
        summary="Get cost breakdown",
        description="Fetch cost breakdown by provider, feature, or model.",
    )
    @rate_limit(requests_per_minute=60)  # Read operation
    @require_permission("costs:read")
    async def handle_get_breakdown(self, request: web.Request) -> web.Response:
        """
        GET /api/costs/breakdown

        Get detailed cost breakdown.
        """
        try:
            time_range = request.query.get("range", "7d")
            workspace_id = request.query.get("workspace_id", "default")
            _group_by = request.query.get("group_by", "provider")  # provider, feature, model

            summary = await _models.get_cost_summary(
                workspace_id=workspace_id, time_range=time_range
            )

            # Build breakdown in the format the frontend expects
            by_provider = summary.cost_by_provider or []
            by_feature = summary.cost_by_feature or []
            total = summary.total_cost or 0

            def _to_items(raw_list: list, total_cost: float) -> list[dict]:
                items = []
                for entry in raw_list:
                    if isinstance(entry, dict):
                        cost = float(entry.get("cost", 0))
                        items.append(
                            {
                                "name": entry.get("name", entry.get("provider", "unknown")),
                                "cost": cost,
                                "percentage": (cost / total_cost * 100) if total_cost > 0 else 0,
                                "tokens": entry.get("tokens"),
                                "calls": entry.get("calls"),
                            }
                        )
                return items

            return web.json_response(
                {
                    "data": {
                        "by_provider": _to_items(by_provider, total),
                        "by_feature": _to_items(by_feature, total),
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get breakdown: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/timeline",
        summary="Get cost timeline",
        description="Fetch cost timeline data over a specified period.",
    )
    @rate_limit(requests_per_minute=60)  # Read operation
    @require_permission("costs:read")
    async def handle_get_timeline(self, request: web.Request) -> web.Response:
        """
        GET /api/costs/timeline

        Get usage timeline data.
        """
        try:
            time_range = request.query.get("range", "7d")
            workspace_id = request.query.get("workspace_id", "default")

            summary = await _models.get_cost_summary(
                workspace_id=workspace_id, time_range=time_range
            )

            daily = summary.daily_costs or []
            total_cost = summary.total_cost or 0

            return web.json_response(
                {
                    "data": {
                        "data_points": [
                            {
                                "date": d.get("date", "") if isinstance(d, dict) else "",
                                "cost": float(d.get("cost", 0)) if isinstance(d, dict) else 0,
                                "tokens": d.get("tokens", 0) if isinstance(d, dict) else 0,
                            }
                            for d in daily
                        ],
                        "total_cost": total_cost,
                        "average_daily_cost": (total_cost / len(daily) if daily else 0),
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get timeline: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/alerts",
        summary="Get budget alerts",
        description="Fetch active budget alerts for the workspace.",
    )
    @rate_limit(requests_per_minute=60)  # Read operation
    @require_permission("costs:read")
    async def handle_get_alerts(self, request: web.Request) -> web.Response:
        """
        GET /api/costs/alerts

        Get budget alerts.
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")

            tracker = _models._get_cost_tracker()
            if tracker:
                active_alerts = _models._get_active_alerts(tracker, workspace_id)

                # Also get historical alerts from Knowledge Mound if available
                km_alerts = tracker.query_km_workspace_alerts(
                    workspace_id=workspace_id,
                    min_level="warning",
                    limit=20,
                )
                for km_alert in km_alerts:
                    if not km_alert.get("acknowledged"):
                        active_alerts.append(
                            {
                                "id": km_alert.get("id", ""),
                                "type": km_alert.get("level", "info"),
                                "message": km_alert.get("message", ""),
                                "severity": km_alert.get("level", "info"),
                                "timestamp": km_alert.get("created_at", ""),
                            }
                        )
            else:
                active_alerts = []

            return web.json_response({"data": {"alerts": active_alerts}})

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get alerts: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="POST",
        path="/api/v1/costs/budget",
        summary="Set budget limits",
        description="Set or update workspace budget limits.",
    )
    @rate_limit(requests_per_minute=20)  # Write operation
    @require_permission("budget:set")
    async def handle_set_budget(self, request: web.Request) -> web.Response:
        """
        POST /api/costs/budget

        Set budget limits.

        Body:
            - budget: Monthly budget in USD
            - workspace_id: Workspace ID
            - daily_limit: Optional daily limit
            - name: Optional budget name
        """
        try:
            body, err = await parse_json_body(request, context="set_budget")
            if err:
                return err
            budget_amount = body.get("budget")
            workspace_id = body.get("workspace_id", "default")
            daily_limit = body.get("daily_limit")
            name = body.get("name", f"Budget for {workspace_id}")

            if budget_amount is None or budget_amount < 0:
                return web_error_response("Valid budget amount required", 400)

            tracker = _models._get_cost_tracker()
            if tracker:
                from aragora.billing.cost_tracker import Budget

                budget = Budget(
                    name=name,
                    workspace_id=workspace_id,
                    monthly_limit_usd=Decimal(str(budget_amount)),
                    daily_limit_usd=Decimal(str(daily_limit)) if daily_limit else None,
                )
                tracker.set_budget(budget)
                logger.info("[CostHandler] Budget set for %s: $%s", workspace_id, budget_amount)

            return web.json_response(
                {
                    "success": True,
                    "budget": budget_amount,
                    "workspace_id": workspace_id,
                    "daily_limit": daily_limit,
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to set budget: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="POST",
        path="/api/v1/costs/alerts/{alert_id}/dismiss",
        summary="Dismiss alert",
        description="Dismiss a budget alert.",
    )
    @rate_limit(requests_per_minute=20)  # Write operation
    @require_permission("costs:read")
    async def handle_dismiss_alert(self, request: web.Request) -> web.Response:
        """
        POST /api/costs/alerts/{alert_id}/dismiss

        Dismiss a budget alert.
        """
        try:
            alert_id = request.match_info.get("alert_id")
            workspace_id = request.query.get("workspace_id", "default")

            # For now, alerts are ephemeral (recalculated from budget state)
            # In production, this would update a database record
            logger.info("[CostHandler] Alert %s dismissed for %s", alert_id, workspace_id)

            return web.json_response(
                {
                    "success": True,
                    "alert_id": alert_id,
                    "dismissed": True,
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to dismiss alert: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/recommendations",
        summary="Get recommendations",
        description="Get cost optimization recommendations for the workspace.",
    )
    @rate_limit(requests_per_minute=60)  # Read operation
    @require_permission("costs:read")
    async def handle_get_recommendations(self, request: web.Request) -> web.Response:
        """
        GET /api/costs/recommendations

        Get cost optimization recommendations.

        Query params:
            - workspace_id: Workspace ID (default: default)
            - status: Filter by status (pending, applied, dismissed)
            - type: Filter by type (model_downgrade, caching, batching)
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")
            status_filter = request.query.get("status")
            type_filter = request.query.get("type")

            from aragora.billing.optimizer import get_cost_optimizer
            from aragora.billing.recommendations import (
                RecommendationStatus,
                RecommendationType,
            )

            optimizer = get_cost_optimizer()

            # Generate new recommendations if none exist
            existing = optimizer.get_workspace_recommendations(workspace_id)
            if not existing:
                await optimizer.analyze_workspace(workspace_id)

            # Apply filters
            status = RecommendationStatus(status_filter) if status_filter else None
            rec_type = RecommendationType(type_filter) if type_filter else None

            recommendations = optimizer.get_workspace_recommendations(
                workspace_id, status=status, type_filter=rec_type
            )

            summary = optimizer.get_summary(workspace_id)

            return web.json_response(
                {
                    "data": {
                        "recommendations": [r.to_dict() for r in recommendations],
                        "summary": summary.to_dict(),
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get recommendations: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/recommendations/{recommendation_id}",
        summary="Get recommendation",
        description="Get a specific cost optimization recommendation.",
    )
    @rate_limit(requests_per_minute=60)  # Read operation
    @require_permission("costs:read")
    async def handle_get_recommendation(self, request: web.Request) -> web.Response:
        """
        GET /api/costs/recommendations/{recommendation_id}

        Get a specific recommendation.
        """
        try:
            recommendation_id = request.match_info.get("recommendation_id")

            from aragora.billing.optimizer import get_cost_optimizer

            optimizer = get_cost_optimizer()
            recommendation = optimizer.get_recommendation(recommendation_id)

            if not recommendation:
                return web_error_response("Recommendation not found", 404)

            return web.json_response(recommendation.to_dict())

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get recommendation: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="POST",
        path="/api/v1/costs/recommendations/{recommendation_id}/apply",
        summary="Apply recommendation",
        description="Apply a cost optimization recommendation.",
    )
    @rate_limit(requests_per_minute=20)  # Write operation
    @require_permission("costs:write")
    async def handle_apply_recommendation(self, request: web.Request) -> web.Response:
        """
        POST /api/costs/recommendations/{recommendation_id}/apply

        Apply a recommendation.
        """
        try:
            recommendation_id = request.match_info.get("recommendation_id")
            body, err = await parse_json_body(request, context="apply_recommendation")
            if err:
                return err
            user_id = body.get("user_id", "unknown")

            from aragora.billing.optimizer import get_cost_optimizer

            optimizer = get_cost_optimizer()
            success = optimizer.apply_recommendation(recommendation_id, user_id)

            if not success:
                return web_error_response("Recommendation not found", 404)

            recommendation = optimizer.get_recommendation(recommendation_id)

            return web.json_response(
                {
                    "success": True,
                    "recommendation": recommendation.to_dict() if recommendation else None,
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to apply recommendation: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="POST",
        path="/api/v1/costs/recommendations/{recommendation_id}/dismiss",
        summary="Dismiss recommendation",
        description="Dismiss a cost optimization recommendation.",
    )
    @rate_limit(requests_per_minute=20)  # Write operation
    @require_permission("costs:write")
    async def handle_dismiss_recommendation(self, request: web.Request) -> web.Response:
        """
        POST /api/costs/recommendations/{recommendation_id}/dismiss

        Dismiss a recommendation.
        """
        try:
            recommendation_id = request.match_info.get("recommendation_id")

            from aragora.billing.optimizer import get_cost_optimizer

            optimizer = get_cost_optimizer()
            success = optimizer.dismiss_recommendation(recommendation_id)

            if not success:
                return web_error_response("Recommendation not found", 404)

            return web.json_response({"success": True, "dismissed": True})

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to dismiss recommendation: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/efficiency",
        summary="Get efficiency metrics",
        description="Get cost efficiency metrics including cost per token and model utilization.",
    )
    @rate_limit(requests_per_minute=60)  # Read operation
    @require_permission("costs:read")
    async def handle_get_efficiency(self, request: web.Request) -> web.Response:
        """
        GET /api/costs/efficiency

        Get efficiency metrics.

        Query params:
            - workspace_id: Workspace ID (default: default)
            - range: Time range (24h, 7d, 30d)
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")
            _time_range = request.query.get("range", "7d")  # reserved for future filtering

            tracker = _models._get_cost_tracker()
            if not tracker:
                return web_error_response("Cost tracker not available", 503)

            stats = tracker.get_workspace_stats(workspace_id)

            # Calculate efficiency metrics
            total_tokens = stats.get("total_tokens_in", 0) + stats.get("total_tokens_out", 0)
            total_calls = stats.get("total_api_calls", 0)
            total_cost = float(stats.get("total_cost_usd", "0"))

            cost_per_1k_tokens = (total_cost / total_tokens * 1000) if total_tokens > 0 else 0
            tokens_per_call = total_tokens / total_calls if total_calls > 0 else 0
            cost_per_call = total_cost / total_calls if total_calls > 0 else 0

            # Model utilization
            cost_by_model = stats.get("cost_by_model", {})
            model_utilization = []
            for model, cost in cost_by_model.items():
                model_utilization.append(
                    {
                        "model": model,
                        "cost": str(cost),
                        "percentage": (float(cost) / total_cost * 100) if total_cost > 0 else 0,
                    }
                )

            # Efficiency score: higher is better (0-100)
            efficiency_score = (
                max(0.0, min(100.0, 100 - (cost_per_1k_tokens / 0.01 * 50)))
                if cost_per_1k_tokens > 0
                else 50.0
            )

            return web.json_response(
                {
                    "data": {
                        "cost_per_1k_tokens": round(cost_per_1k_tokens, 4),
                        "cost_per_call": round(cost_per_call, 4),
                        "cache_hit_rate": stats.get("cache_hit_rate", 0),
                        "avg_tokens_per_call": round(tokens_per_call, 0),
                        "efficiency_score": round(efficiency_score, 1),
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get efficiency: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/forecast",
        summary="Get cost forecast",
        description="Get cost forecast for the specified number of days.",
    )
    @rate_limit(requests_per_minute=60)  # Read operation
    @require_permission("costs:read")
    async def handle_get_forecast(self, request: web.Request) -> web.Response:
        """
        GET /api/costs/forecast

        Get cost forecast.

        Query params:
            - workspace_id: Workspace ID (default: default)
            - days: Forecast days (default: 30)
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")
            forecast_days = safe_query_int(
                request.query, "days", default=30, min_val=1, max_val=365
            )

            from aragora.billing.forecaster import get_cost_forecaster

            forecaster = get_cost_forecaster()
            report = await forecaster.generate_forecast(
                workspace_id=workspace_id,
                forecast_days=forecast_days,
            )

            report_data = report.to_dict()
            return web.json_response(
                {
                    "data": {
                        "projected_monthly_cost": report_data.get("projected_monthly_cost", 0),
                        "projected_end_of_month": report_data.get("projected_end_of_month", 0),
                        "trend": report_data.get("trend", "stable"),
                        "confidence": report_data.get("confidence", 0),
                        "recommended_tier": report_data.get("recommended_tier"),
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get forecast: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="POST",
        path="/api/v1/costs/forecast/simulate",
        summary="Simulate cost scenario",
        description="Simulate a cost scenario with hypothetical changes.",
    )
    @rate_limit(requests_per_minute=5)  # Expensive: simulation
    @require_permission("costs:read")
    async def handle_simulate_forecast(self, request: web.Request) -> web.Response:
        """
        POST /api/costs/forecast/simulate

        Simulate a cost scenario.

        Body:
            - workspace_id: Workspace ID
            - scenario: Scenario object with name, description, changes
            - days: Days to simulate (default: 30)
        """
        try:
            body, err = await parse_json_body(request, context="simulate_forecast")
            if err:
                return err
            workspace_id = body.get("workspace_id", "default")
            scenario_data = body.get("scenario", {})
            days = body.get("days", 30)

            from aragora.billing.forecaster import SimulationScenario, get_cost_forecaster

            scenario = SimulationScenario(
                name=scenario_data.get("name", "Custom Scenario"),
                description=scenario_data.get("description", ""),
                changes=scenario_data.get("changes", {}),
            )

            forecaster = get_cost_forecaster()
            result = await forecaster.simulate_scenario(
                workspace_id=workspace_id,
                scenario=scenario,
                days=days,
            )

            return web.json_response(result.to_dict())

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to simulate forecast: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/export",
        summary="Export cost data",
        description="Export usage data as CSV or JSON.",
    )
    @rate_limit(requests_per_minute=10)  # Export can be expensive
    @require_permission("costs:read")
    async def handle_export(self, request: web.Request) -> web.Response:
        """
        GET /api/costs/export

        Export usage data as CSV or JSON.

        Query params:
            - format: Export format (csv, json). Default: json
            - range: Time range (24h, 7d, 30d, 90d). Default: 30d
            - workspace_id: Workspace ID (default: default)
            - group_by: Grouping (daily, provider, feature). Default: daily
        """
        try:
            export_format = request.query.get("format", "json")
            time_range = request.query.get("range", "30d")
            workspace_id = request.query.get("workspace_id", "default")
            group_by = request.query.get("group_by", "daily")

            if export_format not in ("csv", "json"):
                return web_error_response("format must be 'csv' or 'json'", 400)

            summary = await _models.get_cost_summary(
                workspace_id=workspace_id,
                time_range=time_range,
            )

            # Build export rows based on grouping
            rows = _build_export_rows(summary, group_by)

            if export_format == "csv":
                return _export_csv_response(rows, workspace_id, time_range)

            # JSON export
            return web.json_response(
                {
                    "workspace_id": workspace_id,
                    "time_range": time_range,
                    "group_by": group_by,
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "total_cost": summary.total_cost,
                    "total_tokens": summary.tokens_used,
                    "total_api_calls": summary.api_calls,
                    "rows": rows,
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to export costs: %s", e)
            return web_error_response("Internal server error", 500)

    # =========================================================================
    # New Endpoints: Usage, Budgets, Constraints, Estimates, Detailed Views
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/usage",
        summary="Get usage tracking",
        description="Get detailed usage tracking data for the workspace.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_get_usage(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/usage

        Get detailed usage tracking data.

        Query params:
            - workspace_id: Workspace ID (default: default)
            - range: Time range (24h, 7d, 30d, 90d). Default: 7d
            - group_by: Grouping (provider, model, operation). Default: provider
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")
            time_range = request.query.get("range", "7d")
            group_by = request.query.get("group_by", "provider")

            tracker = _models._get_cost_tracker()
            if not tracker:
                return web_error_response("Cost tracker not available", 503)

            # Get usage data from cost tracker
            now = datetime.now(timezone.utc)
            range_days = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}.get(time_range, 7)
            start_date = now - timedelta(days=range_days)

            from aragora.billing.cost_tracker import CostGranularity

            report = await tracker.generate_report(
                workspace_id=workspace_id,
                period_start=start_date,
                period_end=now,
                granularity=CostGranularity.DAILY,
            )

            # Build usage breakdown based on group_by
            usage_breakdown = []
            if group_by == "provider" and report.cost_by_provider:
                for name, cost in report.cost_by_provider.items():
                    usage_breakdown.append(
                        {
                            "name": name,
                            "cost_usd": float(cost),
                            "api_calls": report.calls_by_provider.get(name, 0)
                            if hasattr(report, "calls_by_provider")
                            else 0,
                        }
                    )
            elif group_by == "model" and hasattr(report, "cost_by_model"):
                for name, cost in report.cost_by_model.items():
                    usage_breakdown.append(
                        {
                            "name": name,
                            "cost_usd": float(cost),
                        }
                    )
            elif group_by == "operation" and report.cost_by_operation:
                for name, cost in report.cost_by_operation.items():
                    usage_breakdown.append(
                        {
                            "name": name,
                            "cost_usd": float(cost),
                        }
                    )

            return web.json_response(
                {
                    "workspace_id": workspace_id,
                    "time_range": time_range,
                    "group_by": group_by,
                    "total_cost_usd": float(report.total_cost_usd),
                    "total_tokens_in": report.total_tokens_in,
                    "total_tokens_out": report.total_tokens_out,
                    "total_api_calls": report.total_api_calls,
                    "usage": usage_breakdown,
                    "period_start": start_date.isoformat(),
                    "period_end": now.isoformat(),
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get usage: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/budgets",
        summary="List budgets",
        description="List all budgets for the workspace.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_list_budgets(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/budgets

        List all budgets for the workspace.

        Query params:
            - workspace_id: Workspace ID (default: default)
            - active_only: Only show active budgets (default: true)
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")
            # Note: active_only filter not yet implemented
            # active_only = request.query.get("active_only", "true").lower() == "true"

            tracker = _models._get_cost_tracker()
            if not tracker:
                return web_error_response("Cost tracker not available", 503)

            # Get budget from tracker
            budget = tracker.get_budget(workspace_id=workspace_id)
            budgets = []

            if budget:
                budget_dict = {
                    "id": f"budget_{workspace_id}",
                    "workspace_id": workspace_id,
                    "name": budget.name
                    if hasattr(budget, "name")
                    else f"Budget for {workspace_id}",
                    "monthly_limit_usd": float(budget.monthly_limit_usd)
                    if budget.monthly_limit_usd
                    else None,
                    "daily_limit_usd": float(budget.daily_limit_usd)
                    if budget.daily_limit_usd
                    else None,
                    "current_monthly_spend": float(budget.current_monthly_spend)
                    if hasattr(budget, "current_monthly_spend")
                    else 0,
                    "current_daily_spend": float(budget.current_daily_spend)
                    if hasattr(budget, "current_daily_spend")
                    else 0,
                    "active": True,
                }
                budgets.append(budget_dict)

            return web.json_response(
                {
                    "budgets": budgets,
                    "count": len(budgets),
                    "workspace_id": workspace_id,
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to list budgets: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="POST",
        path="/api/v1/costs/budgets",
        summary="Create budget",
        description="Create a new budget for the workspace.",
    )
    @rate_limit(requests_per_minute=20)
    @require_permission("budget:set")
    async def handle_create_budget(self, request: web.Request) -> web.Response:
        """
        POST /api/v1/costs/budgets

        Create a new budget.

        Body:
            - workspace_id: Workspace ID
            - name: Budget name
            - monthly_limit_usd: Monthly spending limit
            - daily_limit_usd: Optional daily limit
            - alert_thresholds: Optional list of alert thresholds (percentages)
        """
        try:
            body, err = await parse_json_body(request, context="create_budget")
            if err:
                return err

            workspace_id = body.get("workspace_id", "default")
            name = body.get("name", f"Budget for {workspace_id}")
            monthly_limit = body.get("monthly_limit_usd")
            daily_limit = body.get("daily_limit_usd")
            alert_thresholds = body.get("alert_thresholds", [50, 75, 90, 100])

            if monthly_limit is None or monthly_limit < 0:
                return web_error_response("Valid monthly_limit_usd required", 400)

            tracker = _models._get_cost_tracker()
            if tracker:
                from aragora.billing.cost_tracker import Budget

                budget = Budget(
                    name=name,
                    workspace_id=workspace_id,
                    monthly_limit_usd=Decimal(str(monthly_limit)),
                    daily_limit_usd=Decimal(str(daily_limit)) if daily_limit else None,
                    alert_threshold_50=50 in alert_thresholds,
                    alert_threshold_75=75 in alert_thresholds,
                    alert_threshold_90=90 in alert_thresholds,
                )
                tracker.set_budget(budget)
                logger.info("[CostHandler] Budget created for %s: $%s", workspace_id, monthly_limit)

            return web.json_response(
                {
                    "success": True,
                    "budget": {
                        "id": f"budget_{workspace_id}",
                        "workspace_id": workspace_id,
                        "name": name,
                        "monthly_limit_usd": monthly_limit,
                        "daily_limit_usd": daily_limit,
                        "alert_thresholds": alert_thresholds,
                    },
                },
                status=201,
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to create budget: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="POST",
        path="/api/v1/costs/constraints/check",
        summary="Check cost constraints",
        description="Pre-flight check if an operation would exceed budget constraints.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_check_constraints(self, request: web.Request) -> web.Response:
        """
        POST /api/v1/costs/constraints/check

        Pre-flight check if an operation would exceed budget constraints.

        Body:
            - workspace_id: Workspace ID
            - estimated_cost_usd: Estimated cost of the operation
            - operation: Operation type (optional)
        """
        try:
            body, err = await parse_json_body(request, context="check_constraints")
            if err:
                return err

            workspace_id = body.get("workspace_id", "default")
            estimated_cost = body.get("estimated_cost_usd", 0)
            operation = body.get("operation", "unknown")

            if estimated_cost < 0:
                return web_error_response("estimated_cost_usd must be non-negative", 400)

            tracker = _models._get_cost_tracker()
            allowed = True
            reason = "OK"
            remaining_budget = None

            if tracker:
                budget = tracker.get_budget(workspace_id=workspace_id)
                if budget and budget.monthly_limit_usd:
                    current_spend = (
                        float(budget.current_monthly_spend)
                        if hasattr(budget, "current_monthly_spend")
                        else 0
                    )
                    limit = float(budget.monthly_limit_usd)
                    remaining_budget = limit - current_spend

                    if current_spend + estimated_cost > limit:
                        allowed = False
                        reason = f"Would exceed monthly budget (${limit:.2f})"

                    # Check daily limit if set
                    if budget.daily_limit_usd and allowed:
                        daily_spend = (
                            float(budget.current_daily_spend)
                            if hasattr(budget, "current_daily_spend")
                            else 0
                        )
                        daily_limit = float(budget.daily_limit_usd)
                        if daily_spend + estimated_cost > daily_limit:
                            allowed = False
                            reason = f"Would exceed daily budget (${daily_limit:.2f})"

            return web.json_response(
                {
                    "allowed": allowed,
                    "reason": reason,
                    "workspace_id": workspace_id,
                    "estimated_cost_usd": estimated_cost,
                    "operation": operation,
                    "remaining_monthly_budget": remaining_budget,
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to check constraints: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="POST",
        path="/api/v1/costs/estimate",
        summary="Estimate operation cost",
        description="Estimate the cost of an operation before executing it.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_estimate_cost(self, request: web.Request) -> web.Response:
        """
        POST /api/v1/costs/estimate

        Estimate the cost of an operation.

        Body:
            - operation: Operation type (debate, analysis, etc.)
            - tokens_input: Estimated input tokens
            - tokens_output: Estimated output tokens
            - model: Model to use (optional, uses default pricing)
            - provider: Provider (optional)
        """
        try:
            body, err = await parse_json_body(request, context="estimate_cost")
            if err:
                return err

            operation = body.get("operation", "unknown")
            tokens_input = body.get("tokens_input", 0)
            tokens_output = body.get("tokens_output", 0)
            model = body.get("model", "claude-opus-4")
            provider = body.get("provider", "anthropic")

            # Use canonical pricing from billing module. Both the breakdown
            # and the per-1M figures are derived FROM the same
            # calculate_token_cost answer rather than re-derived from a
            # PROVIDER_PRICING bucket, so all three agree by construction.
            #
            # Re-deriving them was wrong two ways (2026-09-05 wave-2
            # re-review): the flat bucket rate cannot express a documented
            # long-context tier, so input_cost + output_cost stopped summing
            # to the total above the threshold; and the bucket lookup used
            # the caller's provider LABEL, so an unrecognised label reported
            # the $2/$8 default while calculate_token_cost correctly charged
            # the model's real rate.
            total_cost = calculate_token_cost(provider, model, tokens_input, tokens_output)
            input_cost = float(calculate_token_cost(provider, model, tokens_input, 0))
            output_cost = float(total_cost) - input_cost

            # EFFECTIVE per-1M rates: what this request is actually billed
            # at, including any long-context tier. With no tokens on a side
            # there is no effective rate to report, so fall back to the
            # bucket's list price for that side.
            provider_prices = PROVIDER_PRICING.get(provider, PROVIDER_PRICING["openrouter"])
            input_key = model if model in provider_prices else "default"
            output_key = (
                f"{model}-output" if f"{model}-output" in provider_prices else "default-output"
            )
            input_price = (
                input_cost * 1_000_000 / tokens_input
                if tokens_input
                else float(provider_prices.get(input_key, Decimal("2.00")))
            )
            output_price = (
                output_cost * 1_000_000 / tokens_output
                if tokens_output
                else float(provider_prices.get(output_key, Decimal("8.00")))
            )

            return web.json_response(
                {
                    "estimated_cost_usd": round(float(total_cost), 6),
                    "breakdown": {
                        "input_tokens": tokens_input,
                        "output_tokens": tokens_output,
                        "input_cost_usd": round(input_cost, 6),
                        "output_cost_usd": round(output_cost, 6),
                    },
                    "pricing": {
                        "model": model,
                        "provider": provider,
                        "input_per_1m": input_price,
                        "output_per_1m": output_price,
                    },
                    "operation": operation,
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to estimate cost: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/forecast/detailed",
        summary="Get detailed forecast",
        description="Get detailed cost forecast with daily breakdowns and confidence intervals.",
    )
    @rate_limit(requests_per_minute=30)
    @require_permission("costs:read")
    async def handle_get_forecast_detailed(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/forecast/detailed

        Get detailed cost forecast with daily breakdowns.

        Query params:
            - workspace_id: Workspace ID (default: default)
            - days: Forecast days (default: 30, max: 90)
            - include_confidence: Include confidence intervals (default: true)
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")
            forecast_days = safe_query_int(request.query, "days", default=30, min_val=1, max_val=90)
            include_confidence = request.query.get("include_confidence", "true").lower() == "true"

            from aragora.billing.forecaster import get_cost_forecaster

            forecaster = get_cost_forecaster()
            report = await forecaster.generate_forecast(
                workspace_id=workspace_id,
                forecast_days=forecast_days,
            )

            # Generate daily breakdowns
            daily_forecasts = []
            base_report = report.to_dict()
            daily_cost = (
                float(base_report.get("projected_cost", 0)) / forecast_days
                if forecast_days > 0
                else 0
            )

            now = datetime.now(timezone.utc)
            for i in range(forecast_days):
                date = now + timedelta(days=i + 1)
                forecast_entry = {
                    "date": date.strftime("%Y-%m-%d"),
                    "projected_cost_usd": round(daily_cost, 2),
                }
                if include_confidence:
                    # Add confidence intervals (simplified: +/- 20%)
                    forecast_entry["confidence_low"] = round(daily_cost * 0.8, 2)
                    forecast_entry["confidence_high"] = round(daily_cost * 1.2, 2)
                daily_forecasts.append(forecast_entry)

            result = {
                "workspace_id": workspace_id,
                "forecast_days": forecast_days,
                "summary": base_report,
                "daily_forecasts": daily_forecasts,
            }

            if include_confidence:
                result["confidence_level"] = 0.80

            return web.json_response(result)

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get detailed forecast: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/recommendations/detailed",
        summary="Get detailed recommendations",
        description="Get detailed cost optimization recommendations with implementation steps.",
    )
    @rate_limit(requests_per_minute=30)
    @require_permission("costs:read")
    async def handle_get_recommendations_detailed(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/recommendations/detailed

        Get detailed cost optimization recommendations.

        Query params:
            - workspace_id: Workspace ID (default: default)
            - include_implementation: Include implementation steps (default: true)
            - min_savings: Minimum savings threshold in USD (default: 0)
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")
            include_implementation = (
                request.query.get("include_implementation", "true").lower() == "true"
            )
            min_savings = float(request.query.get("min_savings", "0"))

            from aragora.billing.optimizer import get_cost_optimizer

            optimizer = get_cost_optimizer()

            # Generate recommendations if none exist
            existing = optimizer.get_workspace_recommendations(workspace_id)
            if not existing:
                await optimizer.analyze_workspace(workspace_id)

            recommendations = optimizer.get_workspace_recommendations(workspace_id)
            summary = optimizer.get_summary(workspace_id)

            # Filter by minimum savings and add implementation details
            detailed_recs = []
            for rec in recommendations:
                rec_dict = rec.to_dict()
                savings = rec_dict.get("estimated_savings_usd", 0)

                if savings >= min_savings:
                    if include_implementation:
                        # Add implementation steps based on recommendation type
                        rec_type = rec_dict.get("type", "")
                        rec_dict["implementation_steps"] = _get_implementation_steps(rec_type)
                        rec_dict["difficulty"] = _get_implementation_difficulty(rec_type)
                        rec_dict["time_to_implement"] = _get_implementation_time(rec_type)

                    detailed_recs.append(rec_dict)

            # Sort by potential savings (descending)
            detailed_recs.sort(key=lambda x: x.get("estimated_savings_usd", 0), reverse=True)

            return web.json_response(
                {
                    "recommendations": detailed_recs,
                    "count": len(detailed_recs),
                    "summary": summary.to_dict(),
                    "workspace_id": workspace_id,
                    "total_potential_savings_usd": sum(
                        r.get("estimated_savings_usd", 0) for r in detailed_recs
                    ),
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get detailed recommendations: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="POST",
        path="/api/v1/costs/alerts",
        summary="Create cost alert",
        description="Create a new cost alert with custom thresholds.",
    )
    @rate_limit(requests_per_minute=20)
    @require_permission("costs:write")
    async def handle_create_alert(self, request: web.Request) -> web.Response:
        """
        POST /api/v1/costs/alerts

        Create a new cost alert.

        Body:
            - workspace_id: Workspace ID
            - name: Alert name
            - type: Alert type (budget_threshold, spike_detection, daily_limit)
            - threshold: Threshold value (percentage for budget, multiplier for spike)
            - notification_channels: List of notification channels (email, slack, webhook)
        """
        try:
            body, err = await parse_json_body(request, context="create_alert")
            if err:
                return err

            workspace_id = body.get("workspace_id", "default")
            name = body.get("name")
            alert_type = body.get("type", "budget_threshold")
            threshold = body.get("threshold", 80)
            notification_channels = body.get("notification_channels", ["email"])

            if not name:
                return web_error_response("Alert name is required", 400)

            if alert_type not in ("budget_threshold", "spike_detection", "daily_limit"):
                return web_error_response(
                    "Invalid alert type. Must be budget_threshold, spike_detection, or daily_limit",
                    400,
                )

            # Generate alert ID
            import uuid

            alert_id = f"alert_{uuid.uuid4().hex[:8]}"

            # In production, this would be stored in a database
            alert = {
                "id": alert_id,
                "workspace_id": workspace_id,
                "name": name,
                "type": alert_type,
                "threshold": threshold,
                "notification_channels": notification_channels,
                "active": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            logger.info("[CostHandler] Created alert %s for %s", alert_id, workspace_id)

            return web.json_response(
                {
                    "success": True,
                    "alert": alert,
                },
                status=201,
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to create alert: %s", e)
            return web_error_response("Internal server error", 500)

    # =========================================================================
    # Spend Analytics Dashboard Endpoints (issue #264)
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/analytics/trend",
        summary="Get spend trend",
        description="Get daily/weekly/monthly cost trend data for the workspace.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_get_spend_trend(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/analytics/trend

        Get daily spend trend over a time period.

        Query params:
            - workspace_id: Workspace ID (default: default)
            - period: Time period (7d, 14d, 30d, 60d, 90d). Default: 30d
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")
            period = request.query.get("period", "30d")

            from aragora.billing.spend_analytics import get_spend_analytics

            analytics = get_spend_analytics()
            trend = await analytics.get_spend_trend(workspace_id, period=period)

            return web.json_response({"data": trend.to_dict()})

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get spend trend: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/analytics/by-agent",
        summary="Get per-agent cost breakdown",
        description="Get cost breakdown by agent for the workspace.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_get_spend_by_agent(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/analytics/by-agent

        Get per-agent cost breakdown.

        Query params:
            - workspace_id: Workspace ID (default: default)
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")

            from aragora.billing.spend_analytics import get_spend_analytics

            analytics = get_spend_analytics()
            by_agent = await analytics.get_spend_by_agent(workspace_id)

            total = sum(by_agent.values())
            items = []
            for name, cost in sorted(by_agent.items(), key=lambda x: x[1], reverse=True):
                items.append(
                    {
                        "name": name,
                        "cost_usd": round(cost, 4),
                        "percentage": round(cost / total * 100, 1) if total > 0 else 0.0,
                    }
                )

            return web.json_response(
                {
                    "data": {
                        "agents": items,
                        "total_usd": round(total, 4),
                        "count": len(items),
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get agent breakdown: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/analytics/by-model",
        summary="Get per-model cost breakdown",
        description="Get cost breakdown by LLM model for the workspace.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_get_spend_by_model(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/analytics/by-model

        Get per-model cost breakdown.

        Query params:
            - workspace_id: Workspace ID (default: default)
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")

            from aragora.billing.spend_analytics import get_spend_analytics

            analytics = get_spend_analytics()
            by_model = await analytics.get_spend_by_model(workspace_id)

            total = sum(by_model.values())
            items = []
            for name, cost in sorted(by_model.items(), key=lambda x: x[1], reverse=True):
                items.append(
                    {
                        "name": name,
                        "cost_usd": round(cost, 4),
                        "percentage": round(cost / total * 100, 1) if total > 0 else 0.0,
                    }
                )

            return web.json_response(
                {
                    "data": {
                        "models": items,
                        "total_usd": round(total, 4),
                        "count": len(items),
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get model breakdown: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/analytics/by-debate",
        summary="Get per-debate cost breakdown",
        description="Get cost breakdown by debate for the workspace.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_get_spend_by_debate(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/analytics/by-debate

        Get per-debate cost breakdown.

        Query params:
            - workspace_id: Workspace ID (default: default)
            - limit: Max debates to return (default: 20)
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")
            limit = safe_query_int(request.query, "limit", default=20, min_val=1, max_val=100)

            from aragora.billing.spend_analytics import get_spend_analytics

            analytics = get_spend_analytics()
            debates = await analytics.get_spend_by_debate(workspace_id, limit=limit)

            total = sum(d["cost_usd"] for d in debates)

            return web.json_response(
                {
                    "data": {
                        "debates": debates,
                        "total_usd": round(total, 4),
                        "count": len(debates),
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get debate breakdown: %s", e)
            return web_error_response("Internal server error", 500)

    # =========================================================================
    # Debate Session Cost Calculation Endpoints
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/debates/{debate_id}",
        summary="Get debate session costs",
        description="Get cost summary for a specific debate session.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_get_debate_costs(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/debates/{debate_id}

        Get cost summary for a specific debate session including total cost,
        token usage, and budget status.

        Path params:
            - debate_id: Debate session ID
        """
        try:
            debate_id = request.match_info.get("debate_id", "")
            if not debate_id:
                return web_error_response("debate_id is required", 400)

            tracker = _models._get_cost_tracker()
            if not tracker:
                return web_error_response("Cost tracker not available", 503)

            # Get debate cost from tracker
            cost_data = await tracker.get_debate_cost(debate_id)

            # Get budget status
            budget_status = tracker.check_debate_budget(debate_id)

            # Collect per-agent and per-model breakdowns from usage buffer
            by_agent: dict[str, dict[str, Any]] = {}
            by_model: dict[str, dict[str, Any]] = {}
            call_count = 0
            total_latency = 0.0

            async with tracker._buffer_lock:
                for usage in tracker._usage_buffer:
                    if usage.debate_id != debate_id:
                        continue
                    call_count += 1
                    total_latency += usage.latency_ms

                    # Per-agent aggregation
                    agent_key = usage.agent_name or usage.agent_id or "unknown"
                    if agent_key not in by_agent:
                        by_agent[agent_key] = {
                            "agent": agent_key,
                            "cost_usd": 0.0,
                            "tokens_in": 0,
                            "tokens_out": 0,
                            "calls": 0,
                        }
                    by_agent[agent_key]["cost_usd"] += float(usage.cost_usd)
                    by_agent[agent_key]["tokens_in"] += usage.tokens_in
                    by_agent[agent_key]["tokens_out"] += usage.tokens_out
                    by_agent[agent_key]["calls"] += 1

                    # Per-model aggregation
                    model_key = usage.model or "unknown"
                    if model_key not in by_model:
                        by_model[model_key] = {
                            "model": model_key,
                            "provider": usage.provider,
                            "cost_usd": 0.0,
                            "tokens_in": 0,
                            "tokens_out": 0,
                            "calls": 0,
                        }
                    by_model[model_key]["cost_usd"] += float(usage.cost_usd)
                    by_model[model_key]["tokens_in"] += usage.tokens_in
                    by_model[model_key]["tokens_out"] += usage.tokens_out
                    by_model[model_key]["calls"] += 1

            total_cost = float(cost_data.get("total_cost_usd", "0"))
            agents_list = sorted(by_agent.values(), key=lambda x: x["cost_usd"], reverse=True)
            models_list = sorted(by_model.values(), key=lambda x: x["cost_usd"], reverse=True)

            # Round costs
            for item in agents_list:
                item["cost_usd"] = round(item["cost_usd"], 6)
            for item in models_list:
                item["cost_usd"] = round(item["cost_usd"], 6)

            return web.json_response(
                {
                    "data": {
                        "debate_id": debate_id,
                        "total_cost_usd": round(total_cost, 6),
                        "total_tokens_in": cost_data.get("total_tokens_in", 0),
                        "total_tokens_out": cost_data.get("total_tokens_out", 0),
                        "api_calls": cost_data.get("api_calls", call_count),
                        "avg_latency_ms": round(total_latency / call_count, 2)
                        if call_count > 0
                        else 0,
                        "by_agent": agents_list,
                        "by_model": models_list,
                        "budget": budget_status,
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get debate costs: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/debates/{debate_id}/line-items",
        summary="Get debate cost line items",
        description="Get individual API call cost line items for a debate session.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_get_debate_line_items(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/debates/{debate_id}/line-items

        Get line-item breakdown of individual API calls for a debate session.

        Path params:
            - debate_id: Debate session ID
        Query params:
            - sort_by: Sort field (cost, timestamp, tokens). Default: timestamp
            - order: Sort order (asc, desc). Default: desc
            - limit: Max items to return (default: 100, max: 500)
            - offset: Pagination offset (default: 0)
        """
        try:
            debate_id = request.match_info.get("debate_id", "")
            if not debate_id:
                return web_error_response("debate_id is required", 400)

            sort_by = request.query.get("sort_by", "timestamp")
            order = request.query.get("order", "desc")
            limit = safe_query_int(request.query, "limit", default=100, min_val=1, max_val=500)
            offset = safe_query_int(request.query, "offset", default=0, min_val=0, max_val=100000)

            if sort_by not in ("cost", "timestamp", "tokens"):
                return web_error_response("sort_by must be one of: cost, timestamp, tokens", 400)
            if order not in ("asc", "desc"):
                return web_error_response("order must be 'asc' or 'desc'", 400)

            tracker = _models._get_cost_tracker()
            if not tracker:
                return web_error_response("Cost tracker not available", 503)

            # Collect line items from usage buffer
            line_items: list[dict[str, Any]] = []

            async with tracker._buffer_lock:
                for usage in tracker._usage_buffer:
                    if usage.debate_id != debate_id:
                        continue
                    line_items.append(
                        {
                            "id": usage.id,
                            "timestamp": usage.timestamp.isoformat(),
                            "agent": usage.agent_name or usage.agent_id or "unknown",
                            "agent_id": usage.agent_id,
                            "provider": usage.provider,
                            "model": usage.model,
                            "operation": usage.operation,
                            "tokens_in": usage.tokens_in,
                            "tokens_out": usage.tokens_out,
                            "tokens_cached": usage.tokens_cached,
                            "cost_usd": round(float(usage.cost_usd), 6),
                            "latency_ms": round(usage.latency_ms, 2),
                        }
                    )

            # Sort
            sort_keys = {
                "cost": lambda x: x["cost_usd"],
                "timestamp": lambda x: x["timestamp"],
                "tokens": lambda x: x["tokens_in"] + x["tokens_out"],
            }
            line_items.sort(
                key=sort_keys[sort_by],
                reverse=(order == "desc"),
            )

            total_count = len(line_items)
            # Apply pagination
            line_items = line_items[offset : offset + limit]

            # Compute totals
            total_cost = sum(item["cost_usd"] for item in line_items)
            total_tokens = sum(item["tokens_in"] + item["tokens_out"] for item in line_items)

            return web.json_response(
                {
                    "data": {
                        "debate_id": debate_id,
                        "line_items": line_items,
                        "total_count": total_count,
                        "returned_count": len(line_items),
                        "offset": offset,
                        "limit": limit,
                        "page_total_cost_usd": round(total_cost, 6),
                        "page_total_tokens": total_tokens,
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get debate line items: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/debates/{debate_id}/performance",
        summary="Get debate cost performance",
        description="Get performance metrics for a debate session's API usage.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_get_debate_performance(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/debates/{debate_id}/performance

        Get performance and efficiency metrics for a debate session's API usage.

        Path params:
            - debate_id: Debate session ID
        """
        try:
            debate_id = request.match_info.get("debate_id", "")
            if not debate_id:
                return web_error_response("debate_id is required", 400)

            tracker = _models._get_cost_tracker()
            if not tracker:
                return web_error_response("Cost tracker not available", 503)

            # Collect per-call metrics from usage buffer
            latencies: list[float] = []
            costs: list[float] = []
            tokens_per_call: list[int] = []
            by_operation: dict[str, dict[str, Any]] = {}
            first_ts: datetime | None = None
            last_ts: datetime | None = None

            async with tracker._buffer_lock:
                for usage in tracker._usage_buffer:
                    if usage.debate_id != debate_id:
                        continue
                    latencies.append(usage.latency_ms)
                    costs.append(float(usage.cost_usd))
                    tokens_per_call.append(usage.tokens_in + usage.tokens_out)

                    # Track timestamps
                    if first_ts is None or usage.timestamp < first_ts:
                        first_ts = usage.timestamp
                    if last_ts is None or usage.timestamp > last_ts:
                        last_ts = usage.timestamp

                    # Per-operation breakdown
                    op = usage.operation or "unknown"
                    if op not in by_operation:
                        by_operation[op] = {
                            "operation": op,
                            "calls": 0,
                            "total_cost_usd": 0.0,
                            "total_latency_ms": 0.0,
                            "total_tokens": 0,
                        }
                    by_operation[op]["calls"] += 1
                    by_operation[op]["total_cost_usd"] += float(usage.cost_usd)
                    by_operation[op]["total_latency_ms"] += usage.latency_ms
                    by_operation[op]["total_tokens"] += usage.tokens_in + usage.tokens_out

            call_count = len(latencies)
            if call_count == 0:
                return web.json_response(
                    {
                        "data": {
                            "debate_id": debate_id,
                            "api_calls": 0,
                            "message": "No usage data found for this debate",
                        }
                    }
                )

            total_cost = sum(costs)
            total_tokens = sum(tokens_per_call)

            # Compute per-operation averages
            operations_list = []
            for op_data in by_operation.values():
                op_calls = op_data["calls"]
                operations_list.append(
                    {
                        "operation": op_data["operation"],
                        "calls": op_calls,
                        "total_cost_usd": round(op_data["total_cost_usd"], 6),
                        "avg_cost_usd": round(op_data["total_cost_usd"] / op_calls, 6),
                        "avg_latency_ms": round(op_data["total_latency_ms"] / op_calls, 2),
                        "avg_tokens": round(op_data["total_tokens"] / op_calls),
                    }
                )
            operations_list.sort(key=lambda x: x["total_cost_usd"], reverse=True)

            # Duration
            duration_seconds = (last_ts - first_ts).total_seconds() if first_ts and last_ts else 0

            # Sorted latencies for percentiles
            sorted_latencies = sorted(latencies)

            def _percentile(data: list[float], pct: float) -> float:
                if not data:
                    return 0.0
                idx = int(len(data) * pct / 100)
                idx = min(idx, len(data) - 1)
                return round(data[idx], 2)

            return web.json_response(
                {
                    "data": {
                        "debate_id": debate_id,
                        "api_calls": call_count,
                        "total_cost_usd": round(total_cost, 6),
                        "total_tokens": total_tokens,
                        "duration_seconds": round(duration_seconds, 2),
                        "throughput": {
                            "calls_per_minute": round(call_count / (duration_seconds / 60), 2)
                            if duration_seconds > 0
                            else 0,
                            "tokens_per_minute": round(total_tokens / (duration_seconds / 60), 0)
                            if duration_seconds > 0
                            else 0,
                        },
                        "latency": {
                            "avg_ms": round(sum(latencies) / call_count, 2),
                            "min_ms": round(min(latencies), 2),
                            "max_ms": round(max(latencies), 2),
                            "p50_ms": _percentile(sorted_latencies, 50),
                            "p90_ms": _percentile(sorted_latencies, 90),
                            "p99_ms": _percentile(sorted_latencies, 99),
                        },
                        "cost_efficiency": {
                            "cost_per_call_usd": round(total_cost / call_count, 6),
                            "cost_per_1k_tokens": round(total_cost / total_tokens * 1000, 6)
                            if total_tokens > 0
                            else 0,
                            "avg_tokens_per_call": round(total_tokens / call_count),
                        },
                        "by_operation": operations_list,
                        "time_range": {
                            "start": first_ts.isoformat() if first_ts else None,
                            "end": last_ts.isoformat() if last_ts else None,
                        },
                    }
                }
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get debate performance: %s", e)
            return web_error_response("Internal server error", 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/costs/analytics/budget-utilization",
        summary="Get budget utilization",
        description="Get budget utilization percentage and remaining budget.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("costs:read")
    async def handle_get_budget_utilization(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/costs/analytics/budget-utilization

        Get budget utilization metrics.

        Query params:
            - workspace_id: Workspace ID (default: default)
        """
        try:
            workspace_id = request.query.get("workspace_id", "default")

            from aragora.billing.spend_analytics import get_spend_analytics

            analytics = get_spend_analytics()
            utilization = await analytics.get_budget_utilization(workspace_id)

            return web.json_response({"data": utilization})

        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.exception("Failed to get budget utilization: %s", e)
            return web_error_response("Internal server error", 500)
