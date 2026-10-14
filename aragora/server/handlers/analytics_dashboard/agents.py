"""Agent analytics: leaderboard, comparison, trends, flip detection.

Endpoints handled:
- GET /api/analytics/agents              - Agent performance metrics (cached: 300s)
- GET /api/analytics/flips/summary       - Flip detection summary
- GET /api/analytics/flips/recent        - Recent flip events
- GET /api/analytics/flips/consistency   - Agent consistency scores
- GET /api/analytics/flips/trends        - Flip trends over time
"""

from __future__ import annotations

import sys
from typing import Any

from ._shared import (
    HandlerResult,
    cached_analytics,
    error_response,
    get_clamped_int_param,
    handle_errors,
    json_response,
    logger,
    require_user_auth,
    safe_error_message,
)


# Access _run_async through the package module so that test patches on
# ``aragora.server.handlers.analytics_dashboard._run_async`` take effect.
def _get_run_async():
    return sys.modules[__package__]._run_async


class AgentAnalyticsMixin:
    """Mixin providing agent analytics endpoint methods."""

    @require_user_auth
    @handle_errors("get agent metrics")
    @cached_analytics("agents", workspace_key="workspace_id", time_range_key="time_range")
    def _get_agent_metrics(
        self, query_params: dict[str, Any], handler: Any | None = None, user: Any | None = None
    ) -> HandlerResult:
        """
        Get agent performance metrics.

        Query params:
        - workspace_id: Workspace to analyze (required)
        - time_range: Time range - default 30d

        Caching: 300s TTL, scoped by workspace_id + time_range
        """
        workspace_id = query_params.get("workspace_id")
        if not workspace_id:
            return error_response("workspace_id is required", 400, code="MISSING_WORKSPACE_ID")

        time_range_str = query_params.get("time_range", "30d")

        try:
            from aragora.analytics import get_analytics_dashboard, TimeRange

            dashboard = get_analytics_dashboard()
            time_range = TimeRange(time_range_str)

            metrics = _get_run_async()(dashboard.get_agent_metrics(workspace_id, time_range))

            return json_response(
                {
                    "workspace_id": workspace_id,
                    "time_range": time_range_str,
                    "agents": [m.to_dict() for m in metrics],
                }
            )

        except ValueError as e:
            logger.warning("Invalid agent metrics parameter: %s", e)
            return error_response("Invalid parameter", 400, code="INVALID_PARAMETER")
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning("Data error in agent metrics: %s", e)
            return error_response(safe_error_message(e, "agent metrics"), 400, code="DATA_ERROR")
        except (ImportError, RuntimeError, OSError) as e:
            logger.exception("Unexpected error getting agent metrics: %s", e)
            return error_response(
                safe_error_message(e, "agent metrics"), 500, code="INTERNAL_ERROR"
            )

    @require_user_auth
    @handle_errors("get flip summary")
    def _get_flip_summary(
        self, query_params: dict[str, Any], handler: Any | None = None, user: Any | None = None
    ) -> HandlerResult:
        """
        Get flip detection summary for dashboard.

        Response:
        {
            "total_flips": 150,
            "by_type": {"contradiction": 45, "retraction": 20, ...},
            "by_agent": {"claude": 30, "gpt-4": 25, ...},
            "recent_24h": 12
        }
        """
        try:
            from aragora.insights.flip_detector import FlipDetector

            detector = FlipDetector()
            summary = detector.get_flip_summary()

            return json_response(summary)

        except (ImportError, RuntimeError, OSError, LookupError) as e:
            logger.exception("Error getting flip summary: %s", e)
            return error_response(safe_error_message(e, "flip summary"), 500, code="INTERNAL_ERROR")

    @require_user_auth
    @handle_errors("get recent flips")
    def _get_recent_flips(
        self, query_params: dict[str, Any], handler: Any | None = None, user: Any | None = None
    ) -> HandlerResult:
        """
        Get recent flip events.

        Query params:
        - limit: Maximum number of flips to return (default: 20, max: 100)
        - agent: Filter by agent name (optional)
        - flip_type: Filter by type (contradiction, retraction, qualification, refinement)
        """
        limit = get_clamped_int_param(query_params, "limit", 20, min_val=1, max_val=100)

        agent_filter = query_params.get("agent")
        type_filter = query_params.get("flip_type")

        try:
            from aragora.insights.flip_detector import FlipDetector, format_flip_for_ui

            detector = FlipDetector()
            flips = detector.get_recent_flips(limit=limit * 2)  # Fetch more for filtering

            # Apply filters
            if agent_filter:
                flips = [f for f in flips if f.agent_name == agent_filter]
            if type_filter:
                flips = [f for f in flips if f.flip_type == type_filter]

            # Format for UI and limit
            formatted = [format_flip_for_ui(f) for f in flips[:limit]]

            return json_response({"flips": formatted, "count": len(formatted)})

        except (ImportError, RuntimeError, OSError, LookupError) as e:
            logger.exception("Error getting recent flips: %s", e)
            return error_response(safe_error_message(e, "recent flips"), 500, code="INTERNAL_ERROR")

    @require_user_auth
    @handle_errors("get agent consistency")
    def _get_agent_consistency(
        self, query_params: dict[str, Any], handler: Any | None = None, user: Any | None = None
    ) -> HandlerResult:
        """
        Get agent consistency scores.

        Query params:
        - agents: Comma-separated list of agent names (optional, returns all if empty)
        """
        agents_param = query_params.get("agents", "")
        agent_names = [a.strip() for a in agents_param.split(",") if a.strip()]

        try:
            from aragora.insights.flip_detector import FlipDetector, format_consistency_for_ui

            detector = FlipDetector()

            if agent_names:
                # Batch query for specified agents
                scores = detector.get_agents_consistency_batch(agent_names)
                formatted = [format_consistency_for_ui(s) for s in scores.values()]
            else:
                # Get all agents with flips
                summary = detector.get_flip_summary()
                agent_names = list(summary.get("by_agent", {}).keys())
                if agent_names:
                    scores = detector.get_agents_consistency_batch(agent_names)
                    formatted = [format_consistency_for_ui(s) for s in scores.values()]
                else:
                    formatted = []

            # Sort by consistency score (highest first)
            formatted.sort(key=lambda x: float(x["consistency"].rstrip("%")), reverse=True)

            return json_response({"agents": formatted, "count": len(formatted)})

        except (ImportError, RuntimeError, OSError, LookupError) as e:
            logger.exception("Error getting agent consistency: %s", e)
            return error_response(
                safe_error_message(e, "agent consistency"), 500, code="INTERNAL_ERROR"
            )

    @require_user_auth
    @handle_errors("get flip trends")
    def _get_flip_trends(
        self, query_params: dict[str, Any], handler: Any | None = None, user: Any | None = None
    ) -> HandlerResult:
        """
        Get flip trends over time.

        Query params:
        - days: Number of days to look back (default: 30)
        - granularity: 'day' or 'week' (default: 'day')
        """
        days = get_clamped_int_param(query_params, "days", 30, min_val=1, max_val=365)

        granularity = query_params.get("granularity", "day")
        if granularity not in ("day", "week"):
            granularity = "day"

        try:
            from datetime import datetime, timedelta, timezone

            from aragora.insights.flip_detector import FlipDetector

            detector = FlipDetector()
            period_end = datetime.now(timezone.utc)
            period_start = period_end - timedelta(days=days)

            # Query flip trends from database
            data_points = []
            with detector.db.connection() as conn:
                if granularity == "day":
                    date_format = "DATE(detected_at)"
                else:
                    date_format = "strftime('%Y-W%W', detected_at)"

                # Limit based on granularity and time period
                max_periods = days if granularity == "day" else (days // 7) + 1
                row_limit = min(max_periods * 20, 1000)  # Cap at 1000 for memory safety

                rows = conn.execute(
                    f"""
                    SELECT
                        {date_format} as period,
                        flip_type,
                        COUNT(*) as count
                    FROM detected_flips
                    WHERE detected_at >= ?
                    GROUP BY {date_format}, flip_type
                    ORDER BY period
                    LIMIT ?
                    """,  # internal query construction
                    (period_start.isoformat(), row_limit),
                ).fetchall()

                # Group by period
                period_data: dict = {}
                for row in rows:
                    period = row[0]
                    flip_type = row[1]
                    count = row[2]

                    if period not in period_data:
                        period_data[period] = {"date": period, "total": 0, "by_type": {}}
                    period_data[period]["by_type"][flip_type] = count
                    period_data[period]["total"] += count

                data_points = list(period_data.values())

            # Calculate summary
            total_flips = sum(p["total"] for p in data_points)
            avg_per_day = total_flips / days if days > 0 else 0

            # Determine trend (compare first half vs second half)
            if len(data_points) >= 2:
                mid = len(data_points) // 2
                first_half = sum(p["total"] for p in data_points[:mid])
                second_half = sum(p["total"] for p in data_points[mid:])
                if second_half > first_half * 1.2:
                    trend = "increasing"
                elif second_half < first_half * 0.8:
                    trend = "decreasing"
                else:
                    trend = "stable"
            else:
                trend = "insufficient_data"

            return json_response(
                {
                    "period": {
                        "start": period_start.isoformat(),
                        "end": period_end.isoformat(),
                        "days": days,
                    },
                    "granularity": granularity,
                    "data_points": data_points,
                    "summary": {
                        "total_flips": total_flips,
                        "avg_per_day": round(avg_per_day, 2),
                        "trend": trend,
                    },
                }
            )

        except (ImportError, RuntimeError, OSError, LookupError) as e:
            logger.exception("Error getting flip trends: %s", e)
            return error_response(safe_error_message(e, "flip trends"), 500, code="INTERNAL_ERROR")
