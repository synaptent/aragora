"""
Spend Analytics API Handler.

Provides actionable cost-visibility endpoints for the spend analytics
dashboard (GitHub issue #264):

- GET /api/v1/spend/analytics          - Full analytics summary
- GET /api/v1/spend/analytics/trend    - Spend trend over time
- GET /api/v1/spend/analytics/provider - Breakdown by provider
- GET /api/v1/spend/analytics/agent    - Breakdown by agent
- GET /api/v1/spend/analytics/forecast - Linear cost forecast
- GET /api/v1/spend/analytics/anomalies- Detect anomalous spend days
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..base import (
    error_response,
    get_string_param,
    handle_errors,
    json_response,
)
from ..utils.responses import HandlerResult
from ..secure import SecureHandler
from ..utils.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter: 60 requests per minute
_spend_limiter = RateLimiter(requests_per_minute=60)


def _get_analytics() -> Any:
    """Lazy import of SpendAnalytics to avoid circular imports."""
    from aragora.billing.spend_analytics import get_spend_analytics

    return get_spend_analytics()


class SpendAnalyticsHandler(SecureHandler):
    """Handler for spend analytics endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    RESOURCE_TYPE = "spend_analytics"

    ROUTES = [
        "/api/v1/spend/analytics",
        "/api/v1/spend/analytics/trend",
        "/api/v1/spend/analytics/provider",
        "/api/v1/spend/analytics/agent",
        "/api/v1/spend/analytics/forecast",
        "/api/v1/spend/analytics/anomalies",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    @require_permission("org:usage:read")
    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
        method: str = "GET",
    ) -> HandlerResult | None:
        """Route spend analytics requests to appropriate methods."""
        client_ip = get_client_ip(handler)
        if not _spend_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for spend analytics: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if hasattr(handler, "command"):
            method = handler.command

        route_map = {
            "/api/v1/spend/analytics": self._get_full_analytics,
            "/api/v1/spend/analytics/trend": self._get_trend,
            "/api/v1/spend/analytics/provider": self._get_by_provider,
            "/api/v1/spend/analytics/agent": self._get_by_agent,
            "/api/v1/spend/analytics/forecast": self._get_forecast,
            "/api/v1/spend/analytics/anomalies": self._get_anomalies,
        }

        if path in route_map and method == "GET":
            return route_map[path](handler, query_params)

        return error_response("Method not allowed", 405)

    # ------------------------------------------------------------------
    # Helper to resolve workspace_id from query or context
    # ------------------------------------------------------------------

    def _resolve_workspace_id(self, handler: Any) -> str:
        """Get workspace_id from query parameter or default."""
        return get_string_param(handler, "workspace_id", "default")

    # ------------------------------------------------------------------
    # Endpoint implementations
    # ------------------------------------------------------------------

    @handle_errors("get spend analytics")
    @require_permission("org:usage:read")
    def _get_full_analytics(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """GET /api/v1/spend/analytics - Full analytics summary."""
        workspace_id = self._resolve_workspace_id(handler)
        period = get_string_param(handler, "period", "30d")

        analytics = _get_analytics()

        loop = asyncio.new_event_loop()
        try:
            trend = loop.run_until_complete(analytics.get_spend_trend(workspace_id, period=period))
            by_provider = loop.run_until_complete(analytics.get_spend_by_provider(workspace_id))
            by_agent = loop.run_until_complete(analytics.get_spend_by_agent(workspace_id))
            forecast = loop.run_until_complete(analytics.get_cost_forecast(workspace_id))
            anomalies = loop.run_until_complete(
                analytics.get_anomalies(workspace_id, period=period)
            )
        finally:
            loop.close()

        return json_response(
            {
                "data": {
                    "trend": trend.to_dict(),
                    "by_provider": by_provider,
                    "by_agent": by_agent,
                    "forecast": forecast.to_dict(),
                    "anomalies": [a.to_dict() for a in anomalies],
                }
            }
        )

    @handle_errors("get spend trend")
    @require_permission("org:usage:read")
    def _get_trend(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """GET /api/v1/spend/analytics/trend"""
        workspace_id = self._resolve_workspace_id(handler)
        period = get_string_param(handler, "period", "30d")

        analytics = _get_analytics()
        loop = asyncio.new_event_loop()
        try:
            trend = loop.run_until_complete(analytics.get_spend_trend(workspace_id, period=period))
        finally:
            loop.close()

        return json_response({"data": trend.to_dict()})

    @handle_errors("get spend by provider")
    @require_permission("org:usage:read")
    def _get_by_provider(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """GET /api/v1/spend/analytics/provider"""
        workspace_id = self._resolve_workspace_id(handler)

        analytics = _get_analytics()
        loop = asyncio.new_event_loop()
        try:
            by_provider = loop.run_until_complete(analytics.get_spend_by_provider(workspace_id))
        finally:
            loop.close()

        return json_response({"data": {"by_provider": by_provider}})

    @handle_errors("get spend by agent")
    @require_permission("org:usage:read")
    def _get_by_agent(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """GET /api/v1/spend/analytics/agent"""
        workspace_id = self._resolve_workspace_id(handler)

        analytics = _get_analytics()
        loop = asyncio.new_event_loop()
        try:
            by_agent = loop.run_until_complete(analytics.get_spend_by_agent(workspace_id))
        finally:
            loop.close()

        return json_response({"data": {"by_agent": by_agent}})

    @handle_errors("get spend forecast")
    @require_permission("org:usage:read")
    def _get_forecast(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """GET /api/v1/spend/analytics/forecast"""
        workspace_id = self._resolve_workspace_id(handler)
        days_str = get_string_param(handler, "days", "30")
        try:
            days = int(days_str)
        except ValueError:
            days = 30

        analytics = _get_analytics()
        loop = asyncio.new_event_loop()
        try:
            forecast = loop.run_until_complete(analytics.get_cost_forecast(workspace_id, days=days))
        finally:
            loop.close()

        return json_response({"data": forecast.to_dict()})

    @handle_errors("get spend anomalies")
    @require_permission("org:usage:read")
    def _get_anomalies(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """GET /api/v1/spend/analytics/anomalies"""
        workspace_id = self._resolve_workspace_id(handler)
        period = get_string_param(handler, "period", "30d")

        analytics = _get_analytics()
        loop = asyncio.new_event_loop()
        try:
            anomalies = loop.run_until_complete(
                analytics.get_anomalies(workspace_id, period=period)
            )
        finally:
            loop.close()

        return json_response({"data": {"anomalies": [a.to_dict() for a in anomalies]}})


__all__ = ["SpendAnalyticsHandler"]
