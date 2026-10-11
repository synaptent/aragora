"""
Analytics Dashboard Endpoints (FastAPI v2).

Migrated from: aragora/server/handlers/analytics_dashboard/ (aiohttp handler)

Surfaces the analytics dashboard as REST endpoints under /api/v2/analytics:

Debate Analytics (read-only, require_authenticated):
- GET /api/v2/analytics/summary                  - Dashboard summary
- GET /api/v2/analytics/trends/findings           - Finding trends over time
- GET /api/v2/analytics/remediation               - Remediation metrics
- GET /api/v2/analytics/agents                    - Agent performance metrics
- GET /api/v2/analytics/heatmap                   - Risk heatmap data

Cost Analytics (require analytics:cost:read):
- GET /api/v2/analytics/cost                      - Cost analysis
- GET /api/v2/analytics/cost/breakdown            - Per-agent cost breakdown

Compliance Analytics (require analytics:compliance:read):
- GET /api/v2/analytics/compliance                - Compliance scorecard

Token Analytics (require analytics:tokens:read):
- GET /api/v2/analytics/tokens                    - Token usage summary
- GET /api/v2/analytics/tokens/trends             - Token usage trends
- GET /api/v2/analytics/tokens/providers          - Provider/model breakdown

Flip Analytics (require analytics:flips:read):
- GET /api/v2/analytics/flips/summary             - Flip detection summary
- GET /api/v2/analytics/flips/recent              - Recent flip events
- GET /api/v2/analytics/flips/consistency         - Agent consistency scores
- GET /api/v2/analytics/flips/trends              - Flip trends over time

Deliberation Analytics (require analytics:deliberations:read):
- GET /api/v2/analytics/deliberations             - Deliberation summary
- GET /api/v2/analytics/deliberations/channels    - By channel/platform
- GET /api/v2/analytics/deliberations/consensus   - Consensus rates by team
- GET /api/v2/analytics/deliberations/performance - Performance metrics

Migration Notes:
    This module replaces AnalyticsDashboardHandler and its four mixin classes
    (DebateAnalyticsMixin, AgentAnalyticsMixin, UsageAnalyticsMixin,
    DeliberationAnalyticsMixin) with native FastAPI routes. Key improvements:
    - Pydantic request/response models with automatic validation
    - FastAPI dependency injection for auth
    - Proper HTTP status codes (422 for validation, 404 for not found)
    - OpenAPI schema auto-generation
    - Granular permission enforcement via require_permission dependency
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aragora.rbac.models import AuthorizationContext

from ..dependencies.auth import require_authenticated, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/analytics", tags=["Analytics"])


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


# =============================================================================
# Enums
# =============================================================================


class TimeRangeEnum(str, Enum):
    """Supported time range values."""

    h24 = "24h"
    d7 = "7d"
    d30 = "30d"
    d90 = "90d"
    d365 = "365d"
    all = "all"


class GranularityEnum(str, Enum):
    """Supported granularity values for trends."""

    hour = "hour"
    day = "day"
    week = "week"
    month = "month"


class DayGranularityEnum(str, Enum):
    """Granularity values for day/week aggregation."""

    day = "day"
    week = "week"


class TokenGranularityEnum(str, Enum):
    """Granularity values for token trend aggregation."""

    day = "day"
    hour = "hour"


# =============================================================================
# Pydantic Response Models
# =============================================================================


class PeriodInfo(BaseModel):
    """Time period information."""

    start: str
    end: str
    days: int


class AnalyticsSummaryResponse(BaseModel):
    """Response for GET /summary."""

    data: dict[str, Any]

    model_config = {"extra": "allow"}


class FindingTrendsResponse(BaseModel):
    """Response for GET /trends/findings."""

    workspace_id: str
    time_range: str
    granularity: str
    trends: list[dict[str, Any]]


class RemediationResponse(BaseModel):
    """Response for GET /remediation."""

    workspace_id: str
    time_range: str

    model_config = {"extra": "allow"}


class AgentMetricsResponse(BaseModel):
    """Response for GET /agents."""

    workspace_id: str
    time_range: str
    agents: list[dict[str, Any]]


class HeatmapResponse(BaseModel):
    """Response for GET /heatmap."""

    workspace_id: str
    time_range: str
    cells: list[dict[str, Any]]


class CostMetricsResponse(BaseModel):
    """Response for GET /cost."""

    workspace_id: str
    time_range: str

    model_config = {"extra": "allow"}


class CostBreakdownResponse(BaseModel):
    """Response for GET /cost/breakdown."""

    workspace_id: str
    total_spend_usd: str | float
    agent_costs: dict[str, Any]
    budget: dict[str, Any] = Field(default_factory=dict)


class ComplianceScorecardResponse(BaseModel):
    """Response for GET /compliance."""

    workspace_id: str
    scores: list[dict[str, Any]]


class TokenUsageResponse(BaseModel):
    """Response for GET /tokens."""

    org_id: str
    period: PeriodInfo
    total_tokens_in: int
    total_tokens_out: int
    total_tokens: int
    total_cost_usd: str
    total_debates: int
    total_agent_calls: int
    cost_by_provider: dict[str, str]
    debates_by_day: dict[str, Any] | list[Any]

    model_config = {"extra": "allow"}


class TokenTrendsResponse(BaseModel):
    """Response for GET /tokens/trends."""

    org_id: str
    granularity: str
    period: PeriodInfo
    data_points: list[dict[str, Any]]


class ProviderBreakdownResponse(BaseModel):
    """Response for GET /tokens/providers."""

    org_id: str
    period: PeriodInfo
    providers: list[dict[str, Any]]


class FlipSummaryResponse(BaseModel):
    """Response for GET /flips/summary."""

    data: dict[str, Any]


class RecentFlipsResponse(BaseModel):
    """Response for GET /flips/recent."""

    flips: list[dict[str, Any]]
    count: int


class AgentConsistencyResponse(BaseModel):
    """Response for GET /flips/consistency."""

    agents: list[dict[str, Any]]
    count: int


class FlipTrendsResponse(BaseModel):
    """Response for GET /flips/trends."""

    period: PeriodInfo
    granularity: str
    data_points: list[dict[str, Any]]
    summary: dict[str, Any]


class DeliberationSummaryResponse(BaseModel):
    """Response for GET /deliberations."""

    org_id: str
    period: PeriodInfo
    total_deliberations: int
    completed: int
    in_progress: int
    failed: int
    consensus_reached: int
    consensus_rate: str
    avg_rounds: float
    avg_duration_seconds: float
    by_template: dict[str, Any] = Field(default_factory=dict)
    by_priority: dict[str, Any] = Field(default_factory=dict)


class DeliberationByChannelResponse(BaseModel):
    """Response for GET /deliberations/channels."""

    org_id: str
    period: PeriodInfo
    channels: list[dict[str, Any]]
    by_platform: dict[str, Any]


class ConsensusRatesResponse(BaseModel):
    """Response for GET /deliberations/consensus."""

    org_id: str
    period: PeriodInfo
    overall_consensus_rate: str
    by_team_size: dict[str, Any] = Field(default_factory=dict)
    by_agent: list[dict[str, Any]] = Field(default_factory=list)
    top_teams: list[dict[str, Any]] = Field(default_factory=list)


class DeliberationPerformanceResponse(BaseModel):
    """Response for GET /deliberations/performance."""

    org_id: str
    period: PeriodInfo
    granularity: str
    summary: dict[str, Any] = Field(default_factory=dict)
    by_template: list[dict[str, Any]] = Field(default_factory=list)
    trends: list[dict[str, Any]] = Field(default_factory=list)
    cost_by_agent: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Subsystem imports with graceful degradation
# =============================================================================


def _get_analytics_dashboard() -> Any:
    """Lazily import the analytics dashboard subsystem."""
    try:
        from aragora.analytics import get_analytics_dashboard

        return get_analytics_dashboard()
    except (ImportError, RuntimeError, AttributeError) as e:
        logger.debug("Analytics dashboard not available: %s", e)
        return None


def _get_analytics_response(path: str) -> dict[str, Any]:
    """Get analytics stub/live response for unauthenticated or no-workspace requests.

    Delegates to the legacy get_analytics_response which tries live queries
    first and falls back to demo data.
    """
    try:
        from aragora.server.handlers.analytics_dashboard._shared import (
            get_analytics_response,
        )

        return get_analytics_response(path)
    except (ImportError, RuntimeError, AttributeError) as e:
        logger.debug("Analytics stub responses not available: %s", e)
        return {}


async def _await_if_needed(result: Any) -> Any:
    """Await async dashboard results while tolerating sync test doubles."""
    if inspect.isawaitable(result):
        return await result
    return result


async def _call_debate_store_method(
    store: Any,
    method_name: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run debate-store methods without blocking the FastAPI event loop."""

    method = getattr(store, method_name)
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)

    result = await asyncio.to_thread(method, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


# =============================================================================
# Debate Analytics Endpoints (read-only, require authentication)
# =============================================================================


@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def get_summary(
    workspace_id: str | None = Query(None, description="Workspace to analyze"),
    time_range: TimeRangeEnum = Query(TimeRangeEnum.d30, description="Time range"),
    auth: AuthorizationContext = Depends(require_authenticated),
) -> AnalyticsSummaryResponse:
    """
    Get dashboard summary with key metrics.

    Returns debate counts, consensus rates, duration averages, active users,
    and top topics for the specified workspace and time range.

    If no workspace_id is provided, returns demo/stub data.
    """
    if not workspace_id:
        data = _get_analytics_response("/api/analytics/summary")
        return AnalyticsSummaryResponse(data=data)

    try:
        from aragora.analytics import get_analytics_dashboard, TimeRange

        dashboard = get_analytics_dashboard()
        tr = TimeRange(time_range.value)
        summary = await _await_if_needed(dashboard.get_summary(workspace_id, tr))
        return AnalyticsSummaryResponse(data=summary.to_dict())

    except ValueError as e:
        logger.warning("Invalid analytics summary parameter: %s", e)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid time_range: {time_range.value}",
        )
    except (KeyError, TypeError, AttributeError) as e:
        logger.warning("Data error in analytics summary: %s", e)
        raise HTTPException(status_code=400, detail="Data error in analytics summary")
    except (ImportError, RuntimeError, OSError) as e:
        logger.exception("Error getting analytics summary: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get analytics summary")


@router.get("/trends/findings", response_model=FindingTrendsResponse)
async def get_finding_trends(
    workspace_id: str = Query(..., description="Workspace to analyze"),
    time_range: TimeRangeEnum = Query(TimeRangeEnum.d30, description="Time range"),
    granularity: GranularityEnum = Query(GranularityEnum.day, description="Time bucket size"),
    auth: AuthorizationContext = Depends(require_authenticated),
) -> FindingTrendsResponse:
    """
    Get finding trends over time.

    Returns finding counts bucketed by the specified granularity for the given
    workspace and time range.
    """
    try:
        from aragora.analytics import (
            Granularity,
            TimeRange,
            get_analytics_dashboard,
        )

        dashboard = get_analytics_dashboard()
        tr = TimeRange(time_range.value)
        gran = Granularity(granularity.value)

        trends = await _await_if_needed(dashboard.get_finding_trends(workspace_id, tr, gran))

        return FindingTrendsResponse(
            workspace_id=workspace_id,
            time_range=time_range.value,
            granularity=granularity.value,
            trends=[t.to_dict() for t in trends],
        )

    except ValueError as e:
        logger.warning("Invalid finding trends parameter: %s", e)
        raise HTTPException(status_code=400, detail="Invalid parameter")
    except (KeyError, TypeError, AttributeError) as e:
        logger.warning("Data error in finding trends: %s", e)
        raise HTTPException(status_code=400, detail="Data error in finding trends")
    except (ImportError, RuntimeError, OSError) as e:
        logger.exception("Error getting finding trends: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get finding trends")


@router.get("/remediation", response_model=RemediationResponse)
async def get_remediation_metrics(
    workspace_id: str = Query(..., description="Workspace to analyze"),
    time_range: TimeRangeEnum = Query(TimeRangeEnum.d30, description="Time range"),
    auth: AuthorizationContext = Depends(require_authenticated),
) -> RemediationResponse:
    """
    Get remediation performance metrics.

    Returns total findings, remediation rate, pending items, and average
    remediation time for the specified workspace.
    """
    try:
        from aragora.analytics import TimeRange, get_analytics_dashboard

        dashboard = get_analytics_dashboard()
        tr = TimeRange(time_range.value)
        metrics = await _await_if_needed(dashboard.get_remediation_metrics(workspace_id, tr))

        return RemediationResponse(
            workspace_id=workspace_id,
            time_range=time_range.value,
            **metrics.to_dict(),
        )

    except ValueError as e:
        logger.warning("Invalid remediation metrics parameter: %s", e)
        raise HTTPException(status_code=400, detail="Invalid parameter")
    except (KeyError, TypeError, AttributeError) as e:
        logger.warning("Data error in remediation metrics: %s", e)
        raise HTTPException(status_code=400, detail="Data error in remediation metrics")
    except (ImportError, RuntimeError, OSError) as e:
        logger.exception("Error getting remediation metrics: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get remediation metrics")


@router.get("/agents", response_model=AgentMetricsResponse)
async def get_agent_metrics(
    workspace_id: str = Query(..., description="Workspace to analyze"),
    time_range: TimeRangeEnum = Query(TimeRangeEnum.d30, description="Time range"),
    auth: AuthorizationContext = Depends(require_authenticated),
) -> AgentMetricsResponse:
    """
    Get agent performance metrics.

    Returns per-agent debate counts, win rates, and ELO ratings for the
    specified workspace and time range.
    """
    try:
        from aragora.analytics import TimeRange, get_analytics_dashboard

        dashboard = get_analytics_dashboard()
        tr = TimeRange(time_range.value)
        metrics = await _await_if_needed(dashboard.get_agent_metrics(workspace_id, tr))

        return AgentMetricsResponse(
            workspace_id=workspace_id,
            time_range=time_range.value,
            agents=[m.to_dict() for m in metrics],
        )

    except ValueError as e:
        logger.warning("Invalid agent metrics parameter: %s", e)
        raise HTTPException(status_code=400, detail="Invalid parameter")
    except (KeyError, TypeError, AttributeError) as e:
        logger.warning("Data error in agent metrics: %s", e)
        raise HTTPException(status_code=400, detail="Data error in agent metrics")
    except (ImportError, RuntimeError, OSError) as e:
        logger.exception("Error getting agent metrics: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get agent metrics")


@router.get("/heatmap", response_model=HeatmapResponse)
async def get_risk_heatmap(
    workspace_id: str = Query(..., description="Workspace to analyze"),
    time_range: TimeRangeEnum = Query(TimeRangeEnum.d30, description="Time range"),
    auth: AuthorizationContext = Depends(require_authenticated),
) -> HeatmapResponse:
    """
    Get risk heatmap data (category x severity).

    Returns a grid of risk values mapped by category and severity for
    the specified workspace.
    """
    try:
        from aragora.analytics import TimeRange, get_analytics_dashboard

        dashboard = get_analytics_dashboard()
        tr = TimeRange(time_range.value)
        cells = await _await_if_needed(dashboard.get_risk_heatmap(workspace_id, tr))

        return HeatmapResponse(
            workspace_id=workspace_id,
            time_range=time_range.value,
            cells=[c.to_dict() for c in cells],
        )

    except ValueError as e:
        logger.warning("Invalid risk heatmap parameter: %s", e)
        raise HTTPException(status_code=400, detail="Invalid parameter")
    except (KeyError, TypeError, AttributeError) as e:
        logger.warning("Data error in risk heatmap: %s", e)
        raise HTTPException(status_code=400, detail="Data error in risk heatmap")
    except (ImportError, RuntimeError, OSError) as e:
        logger.exception("Error getting risk heatmap: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get risk heatmap")


# =============================================================================
# Cost Analytics Endpoints (require analytics:cost:read)
# =============================================================================


@router.get("/cost", response_model=CostMetricsResponse)
async def get_cost_metrics(
    workspace_id: str = Query(..., description="Workspace to analyze"),
    time_range: TimeRangeEnum = Query(TimeRangeEnum.d30, description="Time range"),
    auth: AuthorizationContext = Depends(require_permission("analytics:cost:read")),
) -> CostMetricsResponse:
    """
    Get cost analysis for audits.

    Returns total cost, cost by model, cost by debate type, projected
    monthly cost, and cost trends.

    Requires `analytics:cost:read` permission.
    """
    try:
        from aragora.analytics import TimeRange, get_analytics_dashboard

        dashboard = get_analytics_dashboard()
        tr = TimeRange(time_range.value)
        metrics = await _await_if_needed(dashboard.get_cost_metrics(workspace_id, tr))

        return CostMetricsResponse(
            workspace_id=workspace_id,
            time_range=time_range.value,
            **metrics.to_dict(),
        )

    except ValueError as e:
        logger.warning("Invalid cost metrics parameter: %s", e)
        raise HTTPException(status_code=400, detail="Invalid parameter")
    except (KeyError, TypeError, AttributeError) as e:
        logger.warning("Data error in cost metrics: %s", e)
        raise HTTPException(status_code=400, detail="Data error in cost metrics")
    except (ImportError, RuntimeError, OSError) as e:
        logger.exception("Error getting cost metrics: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get cost metrics")


@router.get("/cost/breakdown", response_model=CostBreakdownResponse)
async def get_cost_breakdown(
    workspace_id: str = Query(..., description="Workspace/org ID"),
    auth: AuthorizationContext = Depends(require_permission("analytics:cost:read")),
) -> CostBreakdownResponse:
    """
    Get cost breakdown with per-agent costs and budget utilization.

    Returns total spend, per-agent cost breakdown, and budget utilization
    percentage for the specified workspace.

    Requires `analytics:cost:read` permission.
    """
    try:
        from aragora.billing.cost_tracker import get_cost_tracker

        cost_tracker = get_cost_tracker()
        workspace_stats = cost_tracker.get_workspace_stats(workspace_id) or {}

        total_spend = workspace_stats.get("total_cost_usd", "0")
        agent_costs = workspace_stats.get("cost_by_agent", {}) or {}

        if not _has_cost_breakdown(total_spend, agent_costs):
            try:
                total_spend, agent_costs = await _get_metered_cost_breakdown(workspace_id)
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
                    "utilization_percent": (
                        round(current_spend / monthly_limit * 100, 1) if monthly_limit > 0 else 0
                    ),
                }
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug("Budget info unavailable: %s", e)

        return CostBreakdownResponse(
            workspace_id=workspace_id,
            total_spend_usd=total_spend,
            agent_costs=agent_costs,
            budget=budget_info,
        )

    except (ImportError, RuntimeError, OSError) as e:
        logger.exception("Error getting cost breakdown: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get cost breakdown")


# =============================================================================
# Compliance Analytics Endpoints (require analytics:compliance:read)
# =============================================================================


@router.get("/compliance", response_model=ComplianceScorecardResponse)
async def get_compliance_scorecard(
    workspace_id: str = Query(..., description="Workspace to analyze"),
    frameworks: str = Query(
        "SOC2,GDPR,HIPAA,PCI-DSS",
        description="Comma-separated list of compliance frameworks",
    ),
    auth: AuthorizationContext = Depends(require_permission("analytics:compliance:read")),
) -> ComplianceScorecardResponse:
    """
    Get compliance scorecard for specified frameworks.

    Returns compliance scores for each requested framework (SOC2, GDPR,
    HIPAA, PCI-DSS) in the specified workspace.

    Requires `analytics:compliance:read` permission.
    """
    framework_list = [f.strip() for f in frameworks.split(",") if f.strip()]

    try:
        from aragora.analytics import get_analytics_dashboard

        dashboard = get_analytics_dashboard()
        scores = await _await_if_needed(
            dashboard.get_compliance_scorecard(workspace_id, framework_list)
        )

        return ComplianceScorecardResponse(
            workspace_id=workspace_id,
            scores=[s.to_dict() for s in scores],
        )

    except ValueError as e:
        logger.warning("Invalid compliance scorecard parameter: %s", e)
        raise HTTPException(status_code=400, detail="Invalid parameter")
    except (KeyError, TypeError, AttributeError) as e:
        logger.warning("Data error in compliance scorecard: %s", e)
        raise HTTPException(status_code=400, detail="Data error in compliance scorecard")
    except (ImportError, RuntimeError, OSError) as e:
        logger.exception("Error getting compliance scorecard: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get compliance scorecard")


# =============================================================================
# Token Analytics Endpoints (require analytics:tokens:read)
# =============================================================================


@router.get("/tokens", response_model=TokenUsageResponse)
async def get_token_usage(
    org_id: str = Query(..., description="Organization ID"),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    auth: AuthorizationContext = Depends(require_permission("analytics:tokens:read")),
) -> TokenUsageResponse:
    """
    Get token usage summary.

    Returns total token counts (in/out), cost, debate counts, and
    per-provider cost breakdown for the specified organization.

    Requires `analytics:tokens:read` permission.
    """
    try:
        from datetime import datetime, timedelta, timezone

        from aragora.billing.usage import UsageTracker

        tracker = UsageTracker()
        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days)

        summary = tracker.get_summary(org_id, period_start, period_end)

        return TokenUsageResponse(
            org_id=org_id,
            period=PeriodInfo(
                start=period_start.isoformat(),
                end=period_end.isoformat(),
                days=days,
            ),
            total_tokens_in=summary.total_tokens_in,
            total_tokens_out=summary.total_tokens_out,
            total_tokens=summary.total_tokens_in + summary.total_tokens_out,
            total_cost_usd=str(summary.total_cost_usd),
            total_debates=summary.total_debates,
            total_agent_calls=summary.total_agent_calls,
            cost_by_provider={k: str(v) for k, v in summary.cost_by_provider.items()},
            debates_by_day=summary.debates_by_day,
        )

    except (ImportError, RuntimeError, OSError, LookupError) as e:
        logger.exception("Error getting token usage: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get token usage")


@router.get("/tokens/trends", response_model=TokenTrendsResponse)
async def get_token_trends(
    org_id: str = Query(..., description="Organization ID"),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    granularity: TokenGranularityEnum = Query(
        TokenGranularityEnum.day, description="Aggregation granularity"
    ),
    auth: AuthorizationContext = Depends(require_permission("analytics:tokens:read")),
) -> TokenTrendsResponse:
    """
    Get token usage trends over time.

    Returns time-bucketed token usage data (tokens in/out, cost, event count)
    for the specified organization.

    Requires `analytics:tokens:read` permission.
    """
    try:
        from datetime import datetime, timedelta, timezone

        from aragora.billing.usage import UsageTracker

        tracker = UsageTracker()
        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days)

        data_points: list[dict[str, Any]] = []
        with tracker._connection() as conn:
            if granularity == TokenGranularityEnum.day:
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

        return TokenTrendsResponse(
            org_id=org_id,
            granularity=granularity.value,
            period=PeriodInfo(
                start=period_start.isoformat(),
                end=period_end.isoformat(),
                days=days,
            ),
            data_points=data_points,
        )

    except (ImportError, RuntimeError, OSError, LookupError) as e:
        logger.exception("Error getting token trends: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get token trends")


@router.get("/tokens/providers", response_model=ProviderBreakdownResponse)
async def get_provider_breakdown(
    org_id: str = Query(..., description="Organization ID"),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    auth: AuthorizationContext = Depends(require_permission("analytics:tokens:read")),
) -> ProviderBreakdownResponse:
    """
    Get detailed breakdown by provider and model.

    Returns per-provider token totals, costs, and per-model sub-breakdowns
    sorted by total cost descending.

    Requires `analytics:tokens:read` permission.
    """
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

        # Format totals and sort by cost
        result_providers = []
        for p in providers.values():
            p["total_tokens"] = p["total_tokens_in"] + p["total_tokens_out"]
            p["total_cost"] = f"{p['total_cost']:.4f}"
            result_providers.append(p)

        result_providers.sort(key=lambda x: float(x["total_cost"]), reverse=True)

        return ProviderBreakdownResponse(
            org_id=org_id,
            period=PeriodInfo(
                start=period_start.isoformat(),
                end=period_end.isoformat(),
                days=days,
            ),
            providers=result_providers,
        )

    except (ImportError, RuntimeError, OSError, LookupError) as e:
        logger.exception("Error getting provider breakdown: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get provider breakdown")


# =============================================================================
# Flip Analytics Endpoints (require analytics:flips:read)
# =============================================================================


@router.get("/flips/summary", response_model=FlipSummaryResponse)
async def get_flip_summary(
    auth: AuthorizationContext = Depends(require_permission("analytics:flips:read")),
) -> FlipSummaryResponse:
    """
    Get flip detection summary for the dashboard.

    Returns total flip count, breakdown by type (contradiction, retraction, etc.),
    breakdown by agent, and recent 24-hour count.

    Requires `analytics:flips:read` permission.
    """
    try:
        from aragora.insights.flip_detector import FlipDetector

        detector = FlipDetector()
        summary = detector.get_flip_summary()
        return FlipSummaryResponse(data=summary)

    except (ImportError, RuntimeError, OSError, LookupError) as e:
        logger.exception("Error getting flip summary: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get flip summary")


@router.get("/flips/recent", response_model=RecentFlipsResponse)
async def get_recent_flips(
    limit: int = Query(20, ge=1, le=100, description="Maximum flips to return"),
    agent: str | None = Query(None, description="Filter by agent name"),
    flip_type: str | None = Query(
        None,
        description="Filter by type (contradiction, retraction, qualification, refinement)",
    ),
    auth: AuthorizationContext = Depends(require_permission("analytics:flips:read")),
) -> RecentFlipsResponse:
    """
    Get recent flip events.

    Returns recent position-change events with optional filtering by agent
    and flip type.

    Requires `analytics:flips:read` permission.
    """
    try:
        from aragora.insights.flip_detector import FlipDetector, format_flip_for_ui

        detector = FlipDetector()
        flips = detector.get_recent_flips(limit=limit * 2)  # Fetch more for filtering

        # Apply filters
        if agent:
            flips = [f for f in flips if f.agent_name == agent]
        if flip_type:
            flips = [f for f in flips if f.flip_type == flip_type]

        # Format for UI and limit
        formatted = [format_flip_for_ui(f) for f in flips[:limit]]

        return RecentFlipsResponse(flips=formatted, count=len(formatted))

    except (ImportError, RuntimeError, OSError, LookupError) as e:
        logger.exception("Error getting recent flips: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get recent flips")


@router.get("/flips/consistency", response_model=AgentConsistencyResponse)
async def get_agent_consistency(
    agents: str | None = Query(
        None,
        description="Comma-separated list of agent names (returns all if empty)",
    ),
    auth: AuthorizationContext = Depends(require_permission("analytics:flips:read")),
) -> AgentConsistencyResponse:
    """
    Get agent consistency scores.

    Returns a consistency score for each agent, sorted highest first.
    If no agent names are specified, returns scores for all agents with
    recorded flips.

    Requires `analytics:flips:read` permission.
    """
    agent_names: list[str] = []
    if agents:
        agent_names = [a.strip() for a in agents.split(",") if a.strip()]

    try:
        from aragora.insights.flip_detector import (
            FlipDetector,
            format_consistency_for_ui,
        )

        detector = FlipDetector()

        if agent_names:
            scores = detector.get_agents_consistency_batch(agent_names)
            formatted = [format_consistency_for_ui(s) for s in scores.values()]
        else:
            summary = detector.get_flip_summary()
            discovered_names = list(summary.get("by_agent", {}).keys())
            if discovered_names:
                scores = detector.get_agents_consistency_batch(discovered_names)
                formatted = [format_consistency_for_ui(s) for s in scores.values()]
            else:
                formatted = []

        # Sort by consistency score (highest first)
        formatted.sort(key=lambda x: float(x["consistency"].rstrip("%")), reverse=True)

        return AgentConsistencyResponse(agents=formatted, count=len(formatted))

    except (ImportError, RuntimeError, OSError, LookupError) as e:
        logger.exception("Error getting agent consistency: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get agent consistency")


@router.get("/flips/trends", response_model=FlipTrendsResponse)
async def get_flip_trends(
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    granularity: DayGranularityEnum = Query(
        DayGranularityEnum.day, description="Aggregation granularity"
    ),
    auth: AuthorizationContext = Depends(require_permission("analytics:flips:read")),
) -> FlipTrendsResponse:
    """
    Get flip trends over time.

    Returns time-bucketed flip counts with breakdown by type and a trend
    summary (increasing, decreasing, or stable).

    Requires `analytics:flips:read` permission.
    """
    try:
        from datetime import datetime, timedelta, timezone

        from aragora.insights.flip_detector import FlipDetector

        detector = FlipDetector()
        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days)

        data_points: list[dict[str, Any]] = []
        with detector.db.connection() as conn:
            if granularity == DayGranularityEnum.day:
                date_format = "DATE(detected_at)"
            else:
                date_format = "strftime('%Y-W%W', detected_at)"

            max_periods = days if granularity == DayGranularityEnum.day else (days // 7) + 1
            row_limit = min(max_periods * 20, 1000)

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
            period_data: dict[str, dict[str, Any]] = {}
            for row in rows:
                period = row[0]
                ft = row[1]
                count = row[2]
                if period not in period_data:
                    period_data[period] = {
                        "date": period,
                        "total": 0,
                        "by_type": {},
                    }
                period_data[period]["by_type"][ft] = count
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

        return FlipTrendsResponse(
            period=PeriodInfo(
                start=period_start.isoformat(),
                end=period_end.isoformat(),
                days=days,
            ),
            granularity=granularity.value,
            data_points=data_points,
            summary={
                "total_flips": total_flips,
                "avg_per_day": round(avg_per_day, 2),
                "trend": trend,
            },
        )

    except (ImportError, RuntimeError, OSError, LookupError) as e:
        logger.exception("Error getting flip trends: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get flip trends")


# =============================================================================
# Deliberation Analytics Endpoints (require analytics:deliberations:read)
# =============================================================================


@router.get("/deliberations", response_model=DeliberationSummaryResponse)
async def get_deliberation_summary(
    org_id: str = Query(..., description="Organization ID"),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    auth: AuthorizationContext = Depends(require_permission("analytics:deliberations:read")),
) -> DeliberationSummaryResponse:
    """
    Get deliberation analytics summary.

    Returns deliberation counts, consensus rates, average rounds and
    duration, and breakdowns by template and priority.

    Requires `analytics:deliberations:read` permission.
    """
    try:
        from datetime import datetime, timedelta, timezone

        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days)

        from aragora.memory.debate_store import get_debate_store

        store = get_debate_store()
        stats = await _call_debate_store_method(
            store,
            "get_deliberation_stats",
            org_id=org_id,
            start_time=period_start,
            end_time=period_end,
        )

        total = stats.get("total", 0)
        completed = stats.get("completed", 0)
        consensus_reached = stats.get("consensus_reached", 0)
        consensus_rate = f"{(consensus_reached / completed * 100):.1f}%" if completed > 0 else "0%"

        return DeliberationSummaryResponse(
            org_id=org_id,
            period=PeriodInfo(
                start=period_start.isoformat(),
                end=period_end.isoformat(),
                days=days,
            ),
            total_deliberations=total,
            completed=completed,
            in_progress=stats.get("in_progress", 0),
            failed=stats.get("failed", 0),
            consensus_reached=consensus_reached,
            consensus_rate=consensus_rate,
            avg_rounds=round(stats.get("avg_rounds", 0), 1),
            avg_duration_seconds=round(stats.get("avg_duration_seconds", 0), 1),
            by_template=stats.get("by_template", {}),
            by_priority=stats.get("by_priority", {}),
        )

    except (ImportError, RuntimeError, OSError, LookupError) as e:
        logger.exception("Error getting deliberation summary: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get deliberation summary")


@router.get("/deliberations/channels", response_model=DeliberationByChannelResponse)
async def get_deliberation_by_channel(
    org_id: str = Query(..., description="Organization ID"),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    auth: AuthorizationContext = Depends(require_permission("analytics:deliberations:read")),
) -> DeliberationByChannelResponse:
    """
    Get deliberation breakdown by channel/platform.

    Returns per-channel deliberation counts and consensus rates, plus
    an aggregated by-platform summary.

    Requires `analytics:deliberations:read` permission.
    """
    try:
        from datetime import datetime, timedelta, timezone

        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days)

        from aragora.memory.debate_store import get_debate_store

        store = get_debate_store()
        channel_stats = await _call_debate_store_method(
            store,
            "get_deliberation_stats_by_channel",
            org_id=org_id,
            start_time=period_start,
            end_time=period_end,
        )

        # Aggregate by platform
        by_platform: dict[str, dict[str, int]] = {}
        for ch in channel_stats:
            platform = ch.get("platform", "api")
            if platform not in by_platform:
                by_platform[platform] = {
                    "count": 0,
                    "consensus_count": 0,
                    "total_duration": 0,
                }
            by_platform[platform]["count"] += ch.get("total_deliberations", 0)
            by_platform[platform]["consensus_count"] += ch.get("consensus_reached", 0)
            by_platform[platform]["total_duration"] += ch.get("total_duration", 0)

        # Calculate platform-level rates
        platform_summary: dict[str, dict[str, Any]] = {}
        for platform, data in by_platform.items():
            count = data["count"]
            consensus_rate = (
                f"{(data['consensus_count'] / count * 100):.0f}%" if count > 0 else "0%"
            )
            platform_summary[platform] = {
                "count": count,
                "consensus_rate": consensus_rate,
            }

        return DeliberationByChannelResponse(
            org_id=org_id,
            period=PeriodInfo(
                start=period_start.isoformat(),
                end=period_end.isoformat(),
                days=days,
            ),
            channels=channel_stats,
            by_platform=platform_summary,
        )

    except (ImportError, RuntimeError, OSError, LookupError) as e:
        logger.exception("Error getting deliberation by channel: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to get deliberation channel breakdown",
        )


@router.get("/deliberations/consensus", response_model=ConsensusRatesResponse)
async def get_consensus_rates(
    org_id: str = Query(..., description="Organization ID"),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    auth: AuthorizationContext = Depends(require_permission("analytics:deliberations:read")),
) -> ConsensusRatesResponse:
    """
    Get consensus rates by agent team composition.

    Returns overall consensus rate, breakdown by team size, per-agent
    consensus rates, and top-performing team compositions.

    Requires `analytics:deliberations:read` permission.
    """
    try:
        from datetime import datetime, timedelta, timezone

        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days)

        from aragora.memory.debate_store import get_debate_store

        store = get_debate_store()
        consensus_stats = await _call_debate_store_method(
            store,
            "get_consensus_stats",
            org_id=org_id,
            start_time=period_start,
            end_time=period_end,
        )

        return ConsensusRatesResponse(
            org_id=org_id,
            period=PeriodInfo(
                start=period_start.isoformat(),
                end=period_end.isoformat(),
                days=days,
            ),
            overall_consensus_rate=consensus_stats.get("overall_consensus_rate", "0%"),
            by_team_size=consensus_stats.get("by_team_size", {}),
            by_agent=consensus_stats.get("by_agent", []),
            top_teams=consensus_stats.get("top_teams", []),
        )

    except (ImportError, RuntimeError, OSError, LookupError) as e:
        logger.exception("Error getting consensus rates: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get consensus rates")


@router.get(
    "/deliberations/performance",
    response_model=DeliberationPerformanceResponse,
)
async def get_deliberation_performance(
    org_id: str = Query(..., description="Organization ID"),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    granularity: DayGranularityEnum = Query(
        DayGranularityEnum.day, description="Aggregation granularity"
    ),
    auth: AuthorizationContext = Depends(require_permission("analytics:deliberations:read")),
) -> DeliberationPerformanceResponse:
    """
    Get deliberation performance metrics (latency, cost, efficiency).

    Returns performance summary, per-template breakdowns, time-series
    trends, and per-agent cost allocation.

    Requires `analytics:deliberations:read` permission.
    """
    try:
        from datetime import datetime, timedelta, timezone

        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days)

        from aragora.memory.debate_store import get_debate_store

        store = get_debate_store()
        perf_stats = await _call_debate_store_method(
            store,
            "get_deliberation_performance",
            org_id=org_id,
            start_time=period_start,
            end_time=period_end,
            granularity=granularity.value,
        )

        return DeliberationPerformanceResponse(
            org_id=org_id,
            period=PeriodInfo(
                start=period_start.isoformat(),
                end=period_end.isoformat(),
                days=days,
            ),
            granularity=granularity.value,
            summary=perf_stats.get("summary", {}),
            by_template=perf_stats.get("by_template", []),
            trends=perf_stats.get("trends", []),
            cost_by_agent=perf_stats.get("cost_by_agent", {}),
        )

    except (ImportError, RuntimeError, OSError, LookupError) as e:
        logger.exception("Error getting deliberation performance: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to get deliberation performance",
        )
