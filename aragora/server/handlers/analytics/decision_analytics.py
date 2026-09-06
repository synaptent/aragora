"""
Decision Outcome Analytics Dashboard Handler.

Provides API endpoints for tracking AI-assisted decision quality over time:
- GET /api/v1/decision-analytics/overview       - Summary metrics
- GET /api/v1/decision-analytics/trends         - Quality over time
- GET /api/v1/decision-analytics/outcomes       - Decision list with outcomes
- GET /api/v1/decision-analytics/agents         - Per-agent quality metrics
- GET /api/v1/decision-analytics/domains        - Quality by domain/topic

All GET endpoints return {"data": {...}} envelope for frontend hook compatibility.

Issue: #281
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

from aragora.server.handlers.utils.aiohttp_responses import web_error_response
from aragora.server.handlers.utils.responses import HandlerResult
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.handlers.api_decorators import api_endpoint
from aragora.server.validation.query_params import safe_query_int
from aragora.rbac.decorators import require_permission

logger = logging.getLogger(__name__)

# Standard exception tuple for error handlers — matches existing handler convention
_SAFE_EXCEPTIONS = (
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    RuntimeError,
    OSError,
    ImportError,
)


def _get_outcome_analytics():
    """Lazy import of OutcomeAnalytics to avoid heavy startup cost."""
    from aragora.analytics.outcome_analytics import get_outcome_analytics

    return get_outcome_analytics()


class DecisionAnalyticsHandler:
    """Handler for decision outcome analytics API endpoints.

    Surfaces decision quality metrics, trends, per-agent contributions,
    and domain-level breakdowns. Backed by OutcomeAnalytics from
    aragora.analytics.outcome_analytics.
    """

    ROUTES = [
        # Versioned paths (canonical)
        "/api/v1/decision-analytics/overview",
        "/api/v1/decision-analytics/trends",
        "/api/v1/decision-analytics/outcomes",
        "/api/v1/decision-analytics/agents",
        "/api/v1/decision-analytics/domains",
        # Legacy paths (unversioned)
        "/api/decision-analytics/overview",
        "/api/decision-analytics/trends",
        "/api/decision-analytics/outcomes",
        "/api/decision-analytics/agents",
        "/api/decision-analytics/domains",
    ]

    _GET_ROUTE_HANDLERS = {
        "/api/v1/decision-analytics/overview": "handle_get_overview",
        "/api/v1/decision-analytics/trends": "handle_get_trends",
        "/api/v1/decision-analytics/outcomes": "handle_get_outcomes",
        "/api/v1/decision-analytics/agents": "handle_get_agents",
        "/api/v1/decision-analytics/domains": "handle_get_domains",
        "/api/decision-analytics/overview": "handle_get_overview",
        "/api/decision-analytics/trends": "handle_get_trends",
        "/api/decision-analytics/outcomes": "handle_get_outcomes",
        "/api/decision-analytics/agents": "handle_get_agents",
        "/api/decision-analytics/domains": "handle_get_domains",
    }

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Return whether modular dispatch should route this analytics path here."""
        return method == "GET" and path in self._GET_ROUTE_HANDLERS

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route modular GET dispatch through the aiohttp-style handlers."""
        if getattr(handler, "command", "GET") != "GET":
            return HandlerResult(
                status_code=405,
                content_type="application/json",
                body=json.dumps({"error": "Method not allowed"}).encode("utf-8"),
                headers={"Allow": "GET"},
            )
        return self._run_async(self._dispatch_registry_request(path, query_params, handler))

    @staticmethod
    def _run_async(coro: Any) -> HandlerResult | None:
        """Synchronously resolve async route helpers inside modular dispatch."""
        from aragora.server.handler_registry.core import _run_handler_coroutine

        return _run_handler_coroutine(coro)

    @staticmethod
    def _build_registry_request(
        handler: Any,
        *,
        query_params: dict[str, Any],
    ) -> Any:
        """Build the minimal aiohttp-like request object expected by these routes."""

        class _RequestAdapter:
            def __init__(self) -> None:
                self.query = query_params
                self.match_info: dict[str, str] = {}
                self.headers = getattr(handler, "headers", {}) or {}
                self.method = getattr(handler, "command", "GET")
                self._auth_context = getattr(handler, "_auth_context", None)

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
        content_type = getattr(response, "content_type", "application/json") or "application/json"
        headers = dict(getattr(response, "headers", {}) or {})
        status_code = getattr(response, "status_code", None)
        if status_code is None:
            status_code = getattr(response, "status", None)
        if status_code is None:
            status_code = 200
        return HandlerResult(
            status_code=int(status_code),
            content_type=str(content_type),
            body=body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"),
            headers=headers,
        )

    async def _dispatch_registry_request(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Adapt modular-dispatch calls to the aiohttp-style route handlers."""
        handler_name = self._GET_ROUTE_HANDLERS.get(path)
        if handler_name is None:
            return HandlerResult(
                status_code=404,
                content_type="application/json",
                body=json.dumps({"error": "Not found"}).encode("utf-8"),
                headers={},
            )
        route_handler = getattr(self, handler_name)
        request = self._build_registry_request(handler, query_params=query_params)
        return self._to_handler_result(await route_handler(request))

    # =========================================================================
    # GET /api/v1/decision-analytics/overview
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/decision-analytics/overview",
        summary="Get decision analytics overview",
        description="Summary of total decisions, consensus rate, average confidence, and rounds.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("analytics:read")
    async def handle_get_overview(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/decision-analytics/overview

        Get decision analytics overview.

        Query params:
            - period: Time period (24h, 7d, 30d, 90d). Default: 30d
        """
        try:
            period = request.query.get("period", "30d")

            analytics = _get_outcome_analytics()
            consensus_rate = await analytics.get_consensus_rate(period=period)
            avg_rounds = await analytics.get_average_rounds(period=period)

            # Get debate stats for totals
            da = analytics._get_debate_analytics()
            from aragora.analytics.outcome_analytics import _parse_period

            delta = _parse_period(period)
            stats = await da.get_debate_stats(days_back=delta.days or 1)

            return web.json_response(
                {
                    "data": {
                        "total_decisions": stats.total_debates,
                        "consensus_reached": stats.consensus_reached,
                        "consensus_rate": round(consensus_rate, 4),
                        "avg_confidence": round(consensus_rate, 4),
                        "avg_rounds": round(avg_rounds, 2),
                        "period": period,
                    }
                }
            )

        except _SAFE_EXCEPTIONS as e:
            logger.exception("Failed to get decision analytics overview: %s", e)
            return web_error_response("Internal server error", 500)

    # =========================================================================
    # GET /api/v1/decision-analytics/trends
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/decision-analytics/trends",
        summary="Get decision quality trends",
        description="Decision quality metrics over time in weekly buckets.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("analytics:read")
    async def handle_get_trends(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/decision-analytics/trends

        Get decision quality trend data.

        Query params:
            - period: Time period (7d, 30d, 90d, 365d). Default: 90d
        """
        try:
            period = request.query.get("period", "90d")

            analytics = _get_outcome_analytics()
            trend_points = await analytics.get_decision_quality_trend(period=period)

            return web.json_response(
                {
                    "data": {
                        "period": period,
                        "points": [p.to_dict() for p in trend_points],
                        "count": len(trend_points),
                    }
                }
            )

        except _SAFE_EXCEPTIONS as e:
            logger.exception("Failed to get decision quality trends: %s", e)
            return web_error_response("Internal server error", 500)

    # =========================================================================
    # GET /api/v1/decision-analytics/outcomes
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/decision-analytics/outcomes",
        summary="Get decision outcomes list",
        description="Paginated list of individual decision outcomes.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("analytics:read")
    async def handle_get_outcomes(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/decision-analytics/outcomes

        Get a list of individual decision outcomes.

        Query params:
            - period: Time period (24h, 7d, 30d, 90d). Default: 30d
            - limit: Max items (default: 50, max: 200)
            - offset: Pagination offset (default: 0)
        """
        try:
            period = request.query.get("period", "30d")
            limit = safe_query_int(request.query, "limit", default=50, min_val=1, max_val=200)
            offset = safe_query_int(request.query, "offset", default=0, min_val=0, max_val=10000)

            analytics = _get_outcome_analytics()

            from aragora.analytics.outcome_analytics import _parse_period

            delta = _parse_period(period)

            # Query debate records directly for paginated listing
            da = analytics._get_debate_analytics()
            import json as _json
            import sqlite3
            from datetime import datetime, timezone

            outcomes: list[dict[str, Any]] = []
            total_count = 0
            period_start = datetime.now(timezone.utc) - delta

            try:
                with sqlite3.connect(da.db_path) as conn:
                    conn.row_factory = sqlite3.Row

                    # Get total count
                    count_row = conn.execute(
                        "SELECT COUNT(*) as cnt FROM debate_records WHERE created_at >= ?",
                        (period_start.isoformat(),),
                    ).fetchone()
                    total_count = count_row["cnt"] if count_row else 0

                    # Get paginated results
                    cursor = conn.execute(
                        """
                        SELECT debate_id, status, rounds, consensus_reached,
                               duration_seconds, agents, protocol, created_at
                        FROM debate_records
                        WHERE created_at >= ?
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (period_start.isoformat(), limit, offset),
                    )
                    for row in cursor.fetchall():
                        agents = _json.loads(row["agents"]) if row["agents"] else []
                        outcomes.append(
                            {
                                "debate_id": row["debate_id"],
                                "task": row["protocol"] or "",
                                "consensus_reached": bool(row["consensus_reached"]),
                                "confidence": 1.0 if row["consensus_reached"] else 0.0,
                                "rounds": row["rounds"] or 0,
                                "agents": agents,
                                "duration_seconds": round(row["duration_seconds"] or 0.0, 2),
                                "created_at": row["created_at"] or "",
                            }
                        )
            except (sqlite3.Error, OSError, _json.JSONDecodeError) as e:
                logger.warning("Failed to query debate records: %s", e)

            return web.json_response(
                {
                    "data": {
                        "outcomes": outcomes,
                        "total": total_count,
                        "limit": limit,
                        "offset": offset,
                        "period": period,
                    }
                }
            )

        except _SAFE_EXCEPTIONS as e:
            logger.exception("Failed to get decision outcomes: %s", e)
            return web_error_response("Internal server error", 500)

    # =========================================================================
    # GET /api/v1/decision-analytics/agents
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/decision-analytics/agents",
        summary="Get per-agent quality metrics",
        description="Agent contribution scores and quality metrics.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("analytics:read")
    async def handle_get_agents(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/decision-analytics/agents

        Get per-agent decision quality metrics.

        Query params:
            - period: Time period (24h, 7d, 30d, 90d). Default: 30d
        """
        try:
            period = request.query.get("period", "30d")

            analytics = _get_outcome_analytics()
            contributions = await analytics.get_agent_contribution_scores(period=period)

            agents_list = sorted(
                [c.to_dict() for c in contributions.values()],
                key=lambda x: x["contribution_score"],
                reverse=True,
            )

            return web.json_response(
                {
                    "data": {
                        "agents": agents_list,
                        "count": len(agents_list),
                        "period": period,
                    }
                }
            )

        except _SAFE_EXCEPTIONS as e:
            logger.exception("Failed to get agent quality metrics: %s", e)
            return web_error_response("Internal server error", 500)

    # =========================================================================
    # GET /api/v1/decision-analytics/domains
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/decision-analytics/domains",
        summary="Get quality by domain",
        description="Decision quality breakdown by topic/domain.",
    )
    @rate_limit(requests_per_minute=60)
    @require_permission("analytics:read")
    async def handle_get_domains(self, request: web.Request) -> web.Response:
        """
        GET /api/v1/decision-analytics/domains

        Get decision quality breakdown by domain/topic.

        Query params:
            - period: Time period (24h, 7d, 30d, 90d). Default: 30d
        """
        try:
            period = request.query.get("period", "30d")

            analytics = _get_outcome_analytics()
            topics = await analytics.get_topic_distribution(period=period)

            total = sum(topics.values()) if topics else 0

            domains = sorted(
                [
                    {
                        "domain": topic,
                        "decision_count": count,
                        "percentage": round(count / total * 100, 1) if total > 0 else 0.0,
                    }
                    for topic, count in topics.items()
                ],
                key=lambda x: x["decision_count"],
                reverse=True,
            )

            return web.json_response(
                {
                    "data": {
                        "domains": domains,
                        "total_decisions": total,
                        "count": len(domains),
                        "period": period,
                    }
                }
            )

        except _SAFE_EXCEPTIONS as e:
            logger.exception("Failed to get domain quality breakdown: %s", e)
            return web_error_response("Internal server error", 500)


__all__ = ["DecisionAnalyticsHandler"]
