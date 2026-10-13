"""Usage analytics: tokens, costs, active users, provider breakdown.

Endpoints handled:
- GET /api/analytics/cost              - Cost analysis (cached: 300s)
- GET /api/analytics/cost/breakdown    - Per-agent cost breakdown + budget utilization
- GET /api/analytics/tokens            - Token usage summary (cached: 300s)
- GET /api/analytics/tokens/trends     - Token usage trends
- GET /api/analytics/tokens/providers  - Provider/model breakdown
"""

from __future__ import annotations

import sys
from decimal import Decimal, InvalidOperation
from typing import Any

from ._shared import (
    HandlerResult,
    cached_analytics,
    cached_analytics_org,
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


def _has_positive_cost(value: Any) -> bool:
    """Return whether a cost-like value is greater than zero."""
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _has_cost_breakdown(total_spend: Any, agent_costs: Any) -> bool:
    """Return whether the current breakdown already carries non-zero spend."""
    if _has_positive_cost(total_spend):
        return True
    if not isinstance(agent_costs, dict):
        return False
    return any(_has_positive_cost(cost) for cost in agent_costs.values())


def _format_cost(value: Any) -> str:
    """Format metered costs with at least cents and up to 4 decimals."""
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


def _metered_agent_costs(breakdown: Any) -> dict[str, str]:
    """Project durable metering breakdowns onto the legacy agent-costs shape."""
    agent_costs: dict[str, str] = {}
    for row in getattr(breakdown, "by_model", []) or []:
        model = row.get("model")
        cost = row.get("cost")
        if model and _has_positive_cost(cost):
            agent_costs[str(model)] = _format_cost(cost)
    if agent_costs:
        return agent_costs
    for row in getattr(breakdown, "by_provider", []) or []:
        provider = row.get("provider")
        cost = row.get("cost")
        if provider and _has_positive_cost(cost):
            agent_costs[str(provider)] = _format_cost(cost)
    return agent_costs


async def _get_metered_cost_breakdown(workspace_id: str) -> tuple[str, dict[str, str]]:
    """Load durable cost totals from usage metering for a workspace/org."""
    from aragora.services.usage_metering import get_usage_meter

    breakdown = await get_usage_meter().get_usage_breakdown(org_id=workspace_id)
    return _format_cost(getattr(breakdown, "total_cost", 0)), _metered_agent_costs(breakdown)


class UsageAnalyticsMixin:
    """Mixin providing usage/cost analytics endpoint methods."""

    @require_user_auth
    @handle_errors("get cost metrics")
    @cached_analytics("cost", workspace_key="workspace_id", time_range_key="time_range")
    def _get_cost_metrics(
        self, query_params: dict[str, Any], handler: Any | None = None, user: Any | None = None
    ) -> HandlerResult:
        """
        Get cost analysis for audits.

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

            metrics = _get_run_async()(dashboard.get_cost_metrics(workspace_id, time_range))

            return json_response(
                {
                    "workspace_id": workspace_id,
                    "time_range": time_range_str,
                    **metrics.to_dict(),
                }
            )

        except ValueError as e:
            logger.warning("Invalid cost metrics parameter: %s", e)
            return error_response("Invalid parameter", 400, code="INVALID_PARAMETER")
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning("Data error in cost metrics: %s", e)
            return error_response(safe_error_message(e, "cost metrics"), 400, code="DATA_ERROR")
        except (ImportError, RuntimeError, OSError) as e:
            logger.exception("Unexpected error getting cost metrics: %s", e)
            return error_response(safe_error_message(e, "cost metrics"), 500, code="INTERNAL_ERROR")

    @require_user_auth
    @handle_errors("get token usage")
    @cached_analytics_org("tokens", org_key="org_id", days_key="days")
    def _get_token_usage(
        self, query_params: dict[str, Any], handler: Any | None = None, user: Any | None = None
    ) -> HandlerResult:
        """
        Get token usage summary.

        Query params:
        - org_id: Organization ID (required)
        - days: Number of days to look back (default: 30)

        Caching: 300s TTL, scoped by org_id + days
        """
        org_id = query_params.get("org_id")
        if not org_id:
            return error_response("org_id is required", 400, code="MISSING_ORG_ID")

        days = get_clamped_int_param(query_params, "days", 30, min_val=1, max_val=365)

        try:
            from datetime import datetime, timedelta, timezone

            from aragora.billing.usage import UsageTracker

            tracker = UsageTracker()
            period_end = datetime.now(timezone.utc)
            period_start = period_end - timedelta(days=days)

            summary = tracker.get_summary(org_id, period_start, period_end)

            return json_response(
                {
                    "org_id": org_id,
                    "period": {
                        "start": period_start.isoformat(),
                        "end": period_end.isoformat(),
                        "days": days,
                    },
                    "total_tokens_in": summary.total_tokens_in,
                    "total_tokens_out": summary.total_tokens_out,
                    "total_tokens": summary.total_tokens_in + summary.total_tokens_out,
                    "total_cost_usd": str(summary.total_cost_usd),
                    "total_debates": summary.total_debates,
                    "total_agent_calls": summary.total_agent_calls,
                    "cost_by_provider": {k: str(v) for k, v in summary.cost_by_provider.items()},
                    "debates_by_day": summary.debates_by_day,
                }
            )

        except (ImportError, RuntimeError, OSError, LookupError) as e:
            logger.exception("Unexpected error getting token usage: %s", e)
            return error_response(safe_error_message(e, "token usage"), 500, code="INTERNAL_ERROR")

    @require_user_auth
    @handle_errors("get token trends")
    def _get_token_trends(
        self, query_params: dict[str, Any], handler: Any | None = None, user: Any | None = None
    ) -> HandlerResult:
        """
        Get token usage trends over time.

        Query params:
        - org_id: Organization ID (required)
        - days: Number of days to look back (default: 30)
        - granularity: 'day' or 'hour' (default: 'day')
        """
        org_id = query_params.get("org_id")
        if not org_id:
            return error_response("org_id is required", 400, code="MISSING_ORG_ID")

        days = get_clamped_int_param(query_params, "days", 30, min_val=1, max_val=365)

        granularity = query_params.get("granularity", "day")
        if granularity not in ("day", "hour"):
            granularity = "day"

        try:
            from datetime import datetime, timedelta, timezone

            from aragora.billing.usage import UsageTracker

            tracker = UsageTracker()
            period_end = datetime.now(timezone.utc)
            period_start = period_end - timedelta(days=days)

            data_points = []
            with tracker._connection() as conn:
                if granularity == "day":
                    date_format = "DATE(created_at)"
                else:
                    date_format = "strftime('%Y-%m-%d %H:00', created_at)"

                rows = conn.execute(
                    f"""
                    SELECT
                        {date_format} as period,
                        SUM(tokens_in) as tokens_in,
                        SUM(tokens_out) as tokens_out,
                        SUM(CAST(cost_usd AS REAL)) as cost,
                        COUNT(*) as event_count
                    FROM usage_events
                    WHERE org_id = ?
                        AND created_at >= ?
                        AND created_at <= ?
                    GROUP BY {date_format}
                    ORDER BY period
                    LIMIT 1000
                    """,  # internal query construction
                    (org_id, period_start.isoformat(), period_end.isoformat()),
                ).fetchall()

                for row in rows:
                    data_points.append(
                        {
                            "period": row["period"],
                            "tokens_in": row["tokens_in"] or 0,
                            "tokens_out": row["tokens_out"] or 0,
                            "total_tokens": (row["tokens_in"] or 0) + (row["tokens_out"] or 0),
                            "cost_usd": f"{row['cost'] or 0:.4f}",
                            "event_count": row["event_count"],
                        }
                    )

            return json_response(
                {
                    "org_id": org_id,
                    "granularity": granularity,
                    "period": {
                        "start": period_start.isoformat(),
                        "end": period_end.isoformat(),
                        "days": days,
                    },
                    "data_points": data_points,
                }
            )

        except (ImportError, RuntimeError, OSError, LookupError) as e:
            logger.exception("Unexpected error getting token trends: %s", e)
            return error_response(safe_error_message(e, "token trends"), 500, code="INTERNAL_ERROR")

    @require_user_auth
    @handle_errors("get provider breakdown")
    def _get_provider_breakdown(
        self, query_params: dict[str, Any], handler: Any | None = None, user: Any | None = None
    ) -> HandlerResult:
        """
        Get detailed breakdown by provider and model.

        Query params:
        - org_id: Organization ID (required)
        - days: Number of days to look back (default: 30)
        """
        org_id = query_params.get("org_id")
        if not org_id:
            return error_response("org_id is required", 400, code="MISSING_ORG_ID")

        days = get_clamped_int_param(query_params, "days", 30, min_val=1, max_val=365)

        try:
            from datetime import datetime, timedelta, timezone

            from aragora.billing.usage import UsageTracker

            tracker = UsageTracker()
            period_end = datetime.now(timezone.utc)
            period_start = period_end - timedelta(days=days)

            providers: dict[str, Any] = {}
            with tracker._connection() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        provider,
                        model,
                        SUM(tokens_in) as tokens_in,
                        SUM(tokens_out) as tokens_out,
                        SUM(CAST(cost_usd AS REAL)) as cost,
                        COUNT(*) as call_count
                    FROM usage_events
                    WHERE org_id = ?
                        AND created_at >= ?
                        AND created_at <= ?
                        AND provider IS NOT NULL
                        AND provider != ''
                    GROUP BY provider, model
                    ORDER BY cost DESC
                    LIMIT 500
                    """,
                    (org_id, period_start.isoformat(), period_end.isoformat()),
                ).fetchall()

                for row in rows:
                    provider = row["provider"] or "unknown"
                    if provider not in providers:
                        providers[provider] = {
                            "provider": provider,
                            "total_tokens_in": 0,
                            "total_tokens_out": 0,
                            "total_cost": 0.0,
                            "models": [],
                        }

                    tokens_in = row["tokens_in"] or 0
                    tokens_out = row["tokens_out"] or 0
                    cost = row["cost"] or 0.0

                    providers[provider]["total_tokens_in"] += tokens_in
                    providers[provider]["total_tokens_out"] += tokens_out
                    providers[provider]["total_cost"] += cost
                    providers[provider]["models"].append(
                        {
                            "model": row["model"] or "unknown",
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                            "total_tokens": tokens_in + tokens_out,
                            "cost_usd": f"{cost:.4f}",
                            "call_count": row["call_count"],
                        }
                    )

            # Format totals
            result_providers = []
            for p in providers.values():
                p["total_tokens"] = p["total_tokens_in"] + p["total_tokens_out"]
                p["total_cost"] = f"{p['total_cost']:.4f}"
                result_providers.append(p)

            # Sort by total cost
            result_providers.sort(key=lambda x: float(x["total_cost"]), reverse=True)

            return json_response(
                {
                    "org_id": org_id,
                    "period": {
                        "start": period_start.isoformat(),
                        "end": period_end.isoformat(),
                        "days": days,
                    },
                    "providers": result_providers,
                }
            )

        except (ImportError, RuntimeError, OSError, LookupError) as e:
            logger.exception("Unexpected error getting provider breakdown: %s", e)
            return error_response(
                safe_error_message(e, "provider breakdown"), 500, code="INTERNAL_ERROR"
            )

    @require_user_auth
    @handle_errors("get cost breakdown")
    def _get_cost_breakdown(
        self, query_params: dict[str, Any], handler: Any | None = None, user: Any | None = None
    ) -> HandlerResult:
        """
        Get cost breakdown with per-agent costs and budget utilization.

        Query params:
        - workspace_id: Workspace/org ID (required)

        Returns total spend, per-agent cost breakdown, and budget utilization.
        """
        workspace_id = query_params.get("workspace_id")
        if not workspace_id:
            return error_response("workspace_id is required", 400, code="MISSING_WORKSPACE_ID")

        try:
            from aragora.billing.cost_tracker import get_cost_tracker

            cost_tracker = get_cost_tracker()
            workspace_stats = cost_tracker.get_workspace_stats(workspace_id) or {}

            total_spend = workspace_stats.get("total_cost_usd", "0")
            agent_costs = workspace_stats.get("cost_by_agent", {}) or {}

            if not _has_cost_breakdown(total_spend, agent_costs):
                try:
                    total_spend, agent_costs = _get_run_async()(
                        _get_metered_cost_breakdown(workspace_id)
                    )
                except Exception as e:  # noqa: BLE001 - metering fallback must stay best-effort
                    logger.debug("Metered cost breakdown unavailable: %s", e)

            # Get budget utilization
            budget_info: dict[str, Any] = {}
            try:
                budget = cost_tracker.get_budget(workspace_id=workspace_id, org_id=workspace_id)
                if budget and budget.monthly_limit_usd:
                    monthly_limit = float(budget.monthly_limit_usd)
                    current_spend = float(budget.current_monthly_spend)
                    budget_info = {
                        "monthly_limit_usd": monthly_limit,
                        "current_spend_usd": current_spend,
                        "remaining_usd": max(0, monthly_limit - current_spend),
                        "utilization_percent": round(current_spend / monthly_limit * 100, 1)
                        if monthly_limit > 0
                        else 0,
                    }
            except (AttributeError, TypeError, ValueError) as e:
                logger.debug("Budget info unavailable: %s", e)

            return json_response(
                {
                    "workspace_id": workspace_id,
                    "total_spend_usd": total_spend,
                    "agent_costs": agent_costs,
                    "budget": budget_info,
                }
            )

        except (ImportError, RuntimeError, OSError) as e:
            logger.exception("Unexpected error getting cost breakdown: %s", e)
            return error_response(
                safe_error_message(e, "cost breakdown"), 500, code="INTERNAL_ERROR"
            )
