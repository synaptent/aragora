"""
Spend Analytics Dashboard Handler.

Provides the five REST endpoints for the Spend Analytics dashboard:

- GET /api/v1/analytics/spend/summary      - Total spend, budget utilization %, trend direction
- GET /api/v1/analytics/spend/trends       - Daily/weekly/monthly spend over time
- GET /api/v1/analytics/spend/by-agent     - Cost breakdown per agent type
- GET /api/v1/analytics/spend/by-decision  - Cost per debate/decision
- GET /api/v1/analytics/spend/budget       - Budget limits, remaining, forecast to exhaustion

These endpoints aggregate data from:
- aragora.billing.cost_tracker.CostTracker (in-memory workspace stats)
- aragora.billing.budget_manager.BudgetManager (budget CRUD and enforcement)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix
from aragora.utils.async_utils import run_async

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..secure import SecureHandler
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter: 60 requests per minute
_spend_dashboard_limiter = RateLimiter(requests_per_minute=60)


def _get_cost_tracker() -> Any:
    """Lazy import of CostTracker to avoid circular imports."""
    try:
        from aragora.billing.cost_tracker import get_cost_tracker

        return get_cost_tracker()
    except (ImportError, RuntimeError, OSError) as e:
        logger.debug("CostTracker not available: %s", e)
        return None


def _get_budget_manager() -> Any:
    """Lazy import of BudgetManager to avoid circular imports."""
    try:
        from aragora.billing.budget_manager import get_budget_manager

        return get_budget_manager()
    except (ImportError, RuntimeError, OSError) as e:
        logger.debug("BudgetManager not available: %s", e)
        return None


def _has_positive_cost(value: Any) -> bool:
    """Return whether a cost-like value is greater than zero."""
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _format_cost(value: Any) -> str:
    """Format costs with at least cents and up to 4 decimals."""
    try:
        quantized = Decimal(str(value)).quantize(Decimal("0.0001"))
    except (InvalidOperation, TypeError, ValueError):
        return "0.00"
    rendered = format(quantized, "f").rstrip("0").rstrip(".")
    if not rendered:
        return "0.00"
    if "." not in rendered:
        return f"{rendered}.00"
    decimals = rendered.split(".", 1)[1]
    if len(decimals) == 1:
        return f"{rendered}0"
    return rendered


def _summary_has_usage(total_spend_usd: Any, total_api_calls: Any, total_tokens: Any) -> bool:
    """Return whether the current summary already carries meaningful usage."""
    return _has_positive_cost(total_spend_usd) or bool(total_api_calls) or bool(total_tokens)


def _get_metered_summary(scope_id: str) -> tuple[str, int, int]:
    """Load durable spend summary data from usage metering."""
    from aragora.services.usage_metering import get_usage_meter

    summary = run_async(get_usage_meter().get_usage_summary(org_id=scope_id))
    return _format_cost(summary.token_cost), summary.api_call_count, summary.total_tokens


def _get_metered_agents(org_id: str) -> tuple[str, list[dict[str, Any]]]:
    """Load durable per-agent spend from usage metering token usage rows."""
    from aragora.services.usage_metering import get_usage_meter

    meter = get_usage_meter()
    run_async(meter.initialize())
    if meter._conn is None:
        return "0.00", []

    cursor = meter._conn.cursor()
    rows = cursor.execute(
        """
        SELECT metadata, total_cost
        FROM token_usage
        WHERE org_id = ?
        """,
        (org_id,),
    ).fetchall()

    by_agent: dict[str, Decimal] = {}
    total_cost = Decimal("0")
    for row in rows:
        raw_cost = row["total_cost"] or "0"
        try:
            cost = Decimal(str(raw_cost))
        except (InvalidOperation, TypeError, ValueError):
            cost = Decimal("0")
        total_cost += cost

        metadata_raw = row["metadata"]
        metadata: dict[str, Any] = {}
        if isinstance(metadata_raw, str) and metadata_raw.strip():
            try:
                parsed = json.loads(metadata_raw)
                if isinstance(parsed, dict):
                    metadata = parsed
            except json.JSONDecodeError:
                metadata = {}

        agent_name = (
            str(metadata.get("agent_name") or metadata.get("agent") or "unknown").strip()
            or "unknown"
        )
        by_agent[agent_name] = by_agent.get(agent_name, Decimal("0")) + cost

    rendered_total = _format_cost(total_cost)
    total_float = float(total_cost) if total_cost > 0 else 0.0
    agents = [
        {
            "agent_name": agent_name,
            "cost_usd": _format_cost(cost),
            "percentage": round((float(cost) / total_float) * 100, 1) if total_float > 0 else 0.0,
        }
        for agent_name, cost in sorted(by_agent.items(), key=lambda item: item[1], reverse=True)
    ]
    return rendered_total, agents


def _get_metered_decisions(org_id: str, limit: int) -> list[dict[str, str]]:
    """Load per-debate costs from durable usage metering."""
    from aragora.services.usage_metering import get_usage_meter

    meter = get_usage_meter()
    run_async(meter.initialize())
    if meter._conn is None:
        return []

    cursor = meter._conn.cursor()
    rows = cursor.execute(
        """
        SELECT debate_id, SUM(CAST(total_cost AS REAL)) AS cost
        FROM debate_usage
        WHERE org_id = ?
        GROUP BY debate_id
        ORDER BY cost DESC
        LIMIT ?
        """,
        (org_id, limit),
    ).fetchall()

    return [
        {
            "debate_id": row["debate_id"],
            "cost_usd": _format_cost(row["cost"]),
        }
        for row in rows
        if row["debate_id"]
    ]


class SpendAnalyticsDashboardHandler(SecureHandler):
    """Handler for the spend analytics dashboard endpoints.

    Aggregates data from billing CostTracker and BudgetManager to provide
    a unified view of organizational spend, agent costs, per-decision costs,
    budget utilization, and trend analysis.
    """

    ROUTES = [
        "/api/analytics/spend/summary",
        "/api/analytics/spend/trends",
        "/api/analytics/spend/by-agent",
        "/api/analytics/spend/by-decision",
        "/api/analytics/spend/budget",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        return normalized in self.ROUTES

    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route GET requests to appropriate methods."""
        normalized = strip_version_prefix(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _spend_dashboard_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for spend analytics dashboard: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        route_map: dict[str, Any] = {
            "/api/analytics/spend/summary": self._get_summary,
            "/api/analytics/spend/trends": self._get_trends,
            "/api/analytics/spend/by-agent": self._get_by_agent,
            "/api/analytics/spend/by-decision": self._get_by_decision,
            "/api/analytics/spend/budget": self._get_budget,
        }

        method_fn = route_map.get(normalized)
        if method_fn is not None:
            return method_fn(query_params, handler)

        return None

    # ------------------------------------------------------------------
    # Helper to get workspace_id from query params
    # ------------------------------------------------------------------

    @staticmethod
    def _get_workspace_id(query_params: dict[str, Any]) -> str:
        """Extract workspace_id from query params with default."""
        ws = query_params.get("workspace_id", "default")
        if isinstance(ws, list):
            ws = ws[0] if ws else "default"
        return str(ws)

    @staticmethod
    def _get_org_id(query_params: dict[str, Any]) -> str:
        """Extract org_id from query params with default."""
        org = query_params.get("org_id", "default")
        if isinstance(org, list):
            org = org[0] if org else "default"
        return str(org)

    @staticmethod
    def _get_period(query_params: dict[str, Any]) -> str:
        """Extract period from query params with default."""
        period = query_params.get("period", "daily")
        if isinstance(period, list):
            period = period[0] if period else "daily"
        valid = {"daily", "weekly", "monthly"}
        return str(period) if period in valid else "daily"

    @staticmethod
    def _get_days(query_params: dict[str, Any]) -> int:
        """Extract days from query params with default."""
        days_raw = query_params.get("days", "30")
        if isinstance(days_raw, list):
            days_raw = days_raw[0] if days_raw else "30"
        try:
            days = int(days_raw)
        except (ValueError, TypeError):
            days = 30
        return max(1, min(days, 365))

    # ------------------------------------------------------------------
    # Endpoint: GET /api/v1/analytics/spend/summary
    # ------------------------------------------------------------------

    @handle_errors("get spend summary")
    def _get_summary(
        self,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Return total spend, budget utilization %, and trend direction.

        Query params:
        - workspace_id: Workspace to query (default: "default")
        - org_id: Organization to query (default: "default")
        """
        workspace_id = self._get_workspace_id(query_params)
        org_id = self._get_org_id(query_params)

        tracker = _get_cost_tracker()
        budget_mgr = _get_budget_manager()

        # Total spend from tracker
        total_spend_usd = "0.00"
        total_api_calls = 0
        total_tokens = 0
        if tracker:
            stats = tracker.get_workspace_stats(workspace_id)
            total_spend_usd = stats.get("total_cost_usd", "0")
            total_api_calls = stats.get("total_api_calls", 0)
            total_tokens = stats.get("total_tokens_in", 0) + stats.get("total_tokens_out", 0)

        if not _summary_has_usage(total_spend_usd, total_api_calls, total_tokens):
            try:
                scope_id = org_id if org_id and org_id != "default" else workspace_id
                total_spend_usd, total_api_calls, total_tokens = _get_metered_summary(scope_id)
            except Exception as e:  # noqa: BLE001 - metering fallback must stay best-effort
                logger.debug("Metered spend summary unavailable: %s", e)

        # Budget utilization
        budget_limit_usd = 0.0
        budget_spent_usd = 0.0
        utilization_pct = 0.0
        if budget_mgr:
            budgets = budget_mgr.get_budgets_for_org(org_id, active_only=True)
            for b in budgets:
                budget_limit_usd += b.amount_usd
                budget_spent_usd += b.spent_usd
            if budget_limit_usd > 0:
                utilization_pct = round((budget_spent_usd / budget_limit_usd) * 100, 1)

        # Trend direction: compare first vs second half of spend if tracker has data
        trend_direction = "stable"
        if tracker:
            dashboard = tracker.get_dashboard_summary(workspace_id=workspace_id, org_id=org_id)
            projected = dashboard.get("projections", {}).get("projected_monthly_usd")
            if projected:
                try:
                    proj_val = float(projected)
                    cur_val = float(total_spend_usd)
                    if proj_val > cur_val * 1.1:
                        trend_direction = "increasing"
                    elif proj_val < cur_val * 0.9:
                        trend_direction = "decreasing"
                except (ValueError, TypeError):
                    pass

        return json_response(
            {
                "total_spend_usd": total_spend_usd,
                "total_api_calls": total_api_calls,
                "total_tokens": total_tokens,
                "budget_limit_usd": round(budget_limit_usd, 2),
                "budget_spent_usd": round(budget_spent_usd, 2),
                "utilization_pct": utilization_pct,
                "trend_direction": trend_direction,
                "avg_cost_per_decision": (
                    round(float(total_spend_usd) / max(total_api_calls, 1), 4)
                ),
            }
        )

    # ------------------------------------------------------------------
    # Endpoint: GET /api/v1/analytics/spend/trends
    # ------------------------------------------------------------------

    @handle_errors("get spend trends")
    def _get_trends(
        self,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Return daily/weekly/monthly spend over time.

        Query params:
        - org_id: Organization to query (default: "default")
        - period: "daily" | "weekly" | "monthly" (default: "daily")
        - days: Number of data points to return (default: 30, max: 365)
        """
        org_id = self._get_org_id(query_params)
        period = self._get_period(query_params)
        days = self._get_days(query_params)

        budget_mgr = _get_budget_manager()
        data_points: list[dict[str, Any]] = []

        if budget_mgr:
            # Map period param to budget manager's period param
            period_map = {"daily": "day", "weekly": "week", "monthly": "month"}
            bm_period = period_map.get(period, "day")

            trends = budget_mgr.get_org_spending_trends(
                org_id=org_id,
                period=bm_period,
                limit=days,
            )
            data_points = trends

        return json_response(
            {
                "org_id": org_id,
                "period": period,
                "days": days,
                "data_points": data_points,
            }
        )

    # ------------------------------------------------------------------
    # Endpoint: GET /api/v1/analytics/spend/by-agent
    # ------------------------------------------------------------------

    @handle_errors("get spend by agent")
    def _get_by_agent(
        self,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Return cost breakdown per agent type.

        Query params:
        - workspace_id: Workspace to query (default: "default")
        """
        workspace_id = self._get_workspace_id(query_params)

        tracker = _get_cost_tracker()
        agents: list[dict[str, Any]] = []
        total_usd = "0"

        if tracker:
            stats = tracker.get_workspace_stats(workspace_id)
            cost_by_agent = stats.get("cost_by_agent", {})
            total_usd = stats.get("total_cost_usd", "0")

            try:
                total_float = float(total_usd)
            except (ValueError, TypeError):
                total_float = 0.0

            for agent_name, cost_str in cost_by_agent.items():
                try:
                    cost_val = float(cost_str)
                except (ValueError, TypeError):
                    cost_val = 0.0
                pct = round((cost_val / total_float * 100), 1) if total_float > 0 else 0.0
                agents.append(
                    {
                        "agent_name": agent_name,
                        "cost_usd": cost_str,
                        "percentage": pct,
                    }
                )

            # Sort by cost descending
            agents.sort(key=lambda x: float(x.get("cost_usd", "0")), reverse=True)

        if not agents:
            try:
                total_usd, agents = _get_metered_agents(workspace_id)
            except Exception as e:  # noqa: BLE001 - metering fallback must stay best-effort
                logger.debug("Metered agent spend unavailable: %s", e)

        return json_response(
            {
                "workspace_id": workspace_id,
                "total_usd": total_usd,
                "agents": agents,
            }
        )

    # ------------------------------------------------------------------
    # Endpoint: GET /api/v1/analytics/spend/by-decision
    # ------------------------------------------------------------------

    @handle_errors("get spend by decision")
    def _get_by_decision(
        self,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Return cost per debate/decision.

        Query params:
        - workspace_id: Workspace to query (default: "default")
        - limit: Maximum number of debates to return (default: 20, max: 100)
        """
        workspace_id = self._get_workspace_id(query_params)
        limit_raw = query_params.get("limit", "20")
        if isinstance(limit_raw, list):
            limit_raw = limit_raw[0] if limit_raw else "20"
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            limit = 20
        limit = max(1, min(limit, 100))

        tracker = _get_cost_tracker()
        decisions: list[dict[str, Any]] = []

        if tracker:
            # Pull debate costs from the tracker's internal tracking
            debate_costs = dict(tracker._debate_costs)
            sorted_debates = sorted(debate_costs.items(), key=lambda x: x[1], reverse=True)

            for debate_id, cost in sorted_debates[:limit]:
                decisions.append(
                    {
                        "debate_id": debate_id,
                        "cost_usd": str(cost),
                    }
                )

        if not decisions:
            try:
                decisions = _get_metered_decisions(workspace_id, limit)
            except Exception as e:  # noqa: BLE001 - metering fallback must stay best-effort
                logger.debug("Metered decision spend unavailable: %s", e)

        return json_response(
            {
                "workspace_id": workspace_id,
                "decisions": decisions,
                "count": len(decisions),
            }
        )

    # ------------------------------------------------------------------
    # Endpoint: GET /api/v1/analytics/spend/budget
    # ------------------------------------------------------------------

    @handle_errors("get spend budget")
    def _get_budget(
        self,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Return budget limits, remaining, and forecast to exhaustion.

        Query params:
        - org_id: Organization to query (default: "default")
        """
        org_id = self._get_org_id(query_params)
        budget_mgr = _get_budget_manager()

        if not budget_mgr:
            return json_response(
                {
                    "org_id": org_id,
                    "budgets": [],
                    "total_budget_usd": 0.0,
                    "total_spent_usd": 0.0,
                    "total_remaining_usd": 0.0,
                    "utilization_pct": 0.0,
                    "forecast_exhaustion_days": None,
                }
            )

        summary = budget_mgr.get_summary(org_id)

        # Forecast exhaustion: days until budget runs out at current rate
        total_budget = summary.get("total_budget_usd", 0)
        total_spent = summary.get("total_spent_usd", 0)
        remaining = summary.get("total_remaining_usd", 0)

        forecast_exhaustion_days = None
        if total_spent > 0 and remaining > 0:
            # Estimate daily rate from budgets
            budgets_list = summary.get("budgets", [])
            active_budgets = [
                b for b in budgets_list if b.get("status") == "active" and b.get("period_start")
            ]
            if active_budgets:
                now = datetime.now(timezone.utc).timestamp()
                total_daily_rate = 0.0
                for b in active_budgets:
                    period_start = b.get("period_start", now)
                    days_elapsed = max(1, (now - period_start) / 86400)
                    daily_rate = b.get("spent_usd", 0) / days_elapsed
                    total_daily_rate += daily_rate
                if total_daily_rate > 0:
                    forecast_exhaustion_days = round(remaining / total_daily_rate, 1)

        utilization_pct = round((total_spent / total_budget * 100) if total_budget > 0 else 0, 1)

        return json_response(
            {
                "org_id": org_id,
                "budgets": summary.get("budgets", []),
                "total_budget_usd": total_budget,
                "total_spent_usd": total_spent,
                "total_remaining_usd": remaining,
                "utilization_pct": utilization_pct,
                "forecast_exhaustion_days": forecast_exhaustion_days,
            }
        )


__all__ = ["SpendAnalyticsDashboardHandler"]
