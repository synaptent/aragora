"""
Cost Visibility Endpoints (FastAPI v2).

Migrated from: aragora/server/handlers/costs/handler.py (aiohttp handler)

Provides async cost management endpoints:
- GET  /api/v2/costs                          - Cost dashboard summary
- GET  /api/v2/costs/breakdown                - Cost breakdown by provider/feature
- GET  /api/v2/costs/timeline                 - Cost timeline data points
- GET  /api/v2/costs/alerts                   - Active budget alerts
- POST /api/v2/costs/budget                   - Set workspace budget limits
- GET  /api/v2/costs/usage                    - Token usage statistics
- GET  /api/v2/costs/efficiency               - Cost efficiency metrics
- GET  /api/v2/costs/forecast                 - Spend forecast
- GET  /api/v2/costs/recommendations          - Cost optimization recommendations
- POST /api/v2/costs/estimate                 - Estimate cost for a debate config
- GET  /api/v2/costs/budgets                  - List all workspace budgets
- GET  /api/v2/costs/analytics/trend          - Spend trend analytics
- GET  /api/v2/costs/analytics/by-agent       - Spend by agent analytics
- GET  /api/v2/costs/analytics/by-model       - Spend by model analytics
- POST /api/v2/costs/export                   - Export cost data (CSV/JSON)

Migration Notes:
    Replaces legacy CostHandler with native FastAPI routes. Key improvements:
    - Pydantic response models with auto-validation
    - FastAPI dependency injection for auth and cost tracker
    - Response envelope: {"data": ...} for frontend compatibility
    - Proper HTTP status codes and OpenAPI docs
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from aragora.rbac.models import AuthorizationContext

from ..dependencies.auth import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["Costs"])


def _infer_provider(model: str) -> str:
    """Infer provider name from a model identifier for pricing lookup."""
    model_lower = model.lower()
    if "claude" in model_lower:
        return "anthropic"
    if "gpt" in model_lower:
        return "openai"
    if "gemini" in model_lower:
        return "google"
    if "deepseek" in model_lower:
        return "deepseek"
    if "grok" in model_lower:
        return "xai"
    if "mistral" in model_lower:
        return "mistral"
    return "openrouter"


# =============================================================================
# Pydantic Models
# =============================================================================


class CostSummaryData(BaseModel):
    """Cost dashboard summary."""

    total_cost_usd: float = 0.0
    budget_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    api_calls: int = 0
    period_start: str = ""
    period_end: str = ""

    model_config = {"extra": "allow"}


class CostSummaryResponse(BaseModel):
    """Wrapped response for cost summary."""

    data: CostSummaryData


class BreakdownItem(BaseModel):
    """A single breakdown entry."""

    name: str
    cost: float = 0.0
    percentage: float = 0.0
    tokens: int | None = None
    calls: int | None = None

    model_config = {"extra": "allow"}


class BreakdownData(BaseModel):
    """Cost breakdown data."""

    by_provider: list[BreakdownItem] = Field(default_factory=list)
    by_feature: list[BreakdownItem] = Field(default_factory=list)


class BreakdownResponse(BaseModel):
    """Wrapped response for breakdown."""

    data: BreakdownData


class TimelinePoint(BaseModel):
    """A single timeline data point."""

    date: str = ""
    cost: float = 0.0
    tokens: int = 0

    model_config = {"extra": "allow"}


class TimelineData(BaseModel):
    """Timeline response data."""

    data_points: list[TimelinePoint] = Field(default_factory=list)
    total_cost: float = 0.0
    average_daily_cost: float = 0.0


class TimelineResponse(BaseModel):
    """Wrapped response for timeline."""

    data: TimelineData


class AlertItem(BaseModel):
    """A budget alert."""

    id: str = ""
    type: str = ""
    message: str = ""
    severity: str = "info"
    timestamp: str = ""

    model_config = {"extra": "allow"}


class AlertsData(BaseModel):
    """Alerts response data."""

    alerts: list[AlertItem] = Field(default_factory=list)


class AlertsResponse(BaseModel):
    """Wrapped response for alerts."""

    data: AlertsData


class BudgetSetRequest(BaseModel):
    """Request to set budget limits."""

    monthly_limit_usd: float
    alert_threshold: float = 0.8
    workspace_id: str = "default"

    model_config = {"extra": "allow"}


class BudgetData(BaseModel):
    """Budget response data."""

    monthly_limit_usd: float = 0.0
    current_spend_usd: float = 0.0
    remaining_usd: float = 0.0
    alert_threshold: float = 0.8
    utilization_pct: float = 0.0

    model_config = {"extra": "allow"}


class BudgetResponse(BaseModel):
    """Wrapped response for budget operations."""

    data: BudgetData


class UsageData(BaseModel):
    """Token usage statistics."""

    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_api_calls: int = 0
    by_model: list[dict[str, Any]] = Field(default_factory=list)
    by_provider: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class UsageResponse(BaseModel):
    """Wrapped response for usage."""

    data: UsageData


class EfficiencyData(BaseModel):
    """Cost efficiency metrics."""

    cost_per_debate: float = 0.0
    cost_per_token: float = 0.0
    tokens_per_debate: float = 0.0
    efficiency_score: float = 0.0
    trend: str = "stable"

    model_config = {"extra": "allow"}


class EfficiencyResponse(BaseModel):
    """Wrapped response for efficiency."""

    data: EfficiencyData


class ForecastData(BaseModel):
    """Spend forecast."""

    projected_monthly: float = 0.0
    projected_daily: float = 0.0
    confidence: float = 0.0
    trend: str = "stable"
    data_points: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class ForecastResponse(BaseModel):
    """Wrapped response for forecast."""

    data: ForecastData


class RecommendationItem(BaseModel):
    """A cost optimization recommendation."""

    id: str = ""
    title: str = ""
    description: str = ""
    potential_savings_usd: float = 0.0
    difficulty: str = "medium"
    category: str = ""
    status: str = "pending"

    model_config = {"extra": "allow"}


class RecommendationsData(BaseModel):
    """Recommendations response data."""

    recommendations: list[RecommendationItem] = Field(default_factory=list)
    total_potential_savings: float = 0.0


class RecommendationsResponse(BaseModel):
    """Wrapped response for recommendations."""

    data: RecommendationsData


class EstimateRequest(BaseModel):
    """Request to estimate debate cost."""

    model: str = "claude-sonnet-4-6"
    rounds: int = 3
    agents: int = 4
    estimated_tokens_per_round: int = 2000

    model_config = {"extra": "allow"}


class EstimateData(BaseModel):
    """Cost estimate response."""

    estimated_cost_usd: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    model: str = ""
    breakdown: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class EstimateResponse(BaseModel):
    """Wrapped response for estimate."""

    data: EstimateData


# =============================================================================
# Dependencies
# =============================================================================


def _get_cost_tracker():
    """Get the global cost tracker instance."""
    try:
        from aragora.server.handlers.costs.models import _get_cost_tracker

        return _get_cost_tracker()
    except (ImportError, RuntimeError, OSError) as e:
        logger.debug("CostTracker not available: %s", e)
        return None


async def _get_cost_summary(workspace_id: str, time_range: str):
    """Get cost summary via the models module."""
    try:
        from aragora.server.handlers.costs.models import get_cost_summary

        return await get_cost_summary(workspace_id=workspace_id, time_range=time_range)
    except (ImportError, RuntimeError, OSError) as e:
        logger.debug("Cost summary unavailable: %s", e)
        return None


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/costs", response_model=CostSummaryResponse)
async def get_costs(
    request: Request,
    range: str = Query("7d", alias="range", description="Time range: 24h, 7d, 30d, 90d"),
    workspace_id: str = Query("default"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> CostSummaryResponse:
    """Get cost dashboard summary data."""
    try:
        summary = await _get_cost_summary(workspace_id, range)
        if not summary:
            return CostSummaryResponse(data=CostSummaryData())

        return CostSummaryResponse(
            data=CostSummaryData(
                total_cost_usd=summary.total_cost,
                budget_usd=summary.budget,
                tokens_in=getattr(summary, "tokens_in", summary.tokens_used),
                tokens_out=getattr(summary, "tokens_out", 0),
                api_calls=summary.api_calls,
                period_start=getattr(summary, "period_start", ""),
                period_end=getattr(summary, "period_end", ""),
            )
        )
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to get costs: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve cost data")


@router.get("/costs/breakdown", response_model=BreakdownResponse)
async def get_breakdown(
    request: Request,
    range: str = Query("7d", alias="range"),
    workspace_id: str = Query("default"),
    group_by: str = Query("provider", description="Group by: provider, feature, model"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> BreakdownResponse:
    """Get cost breakdown by provider, feature, or model."""
    try:
        summary = await _get_cost_summary(workspace_id, range)
        if not summary:
            return BreakdownResponse(data=BreakdownData())

        total = summary.total_cost or 0

        def _to_items(raw_list: list) -> list[BreakdownItem]:
            items = []
            for entry in raw_list:
                if isinstance(entry, dict):
                    cost = float(entry.get("cost", 0))
                    items.append(
                        BreakdownItem(
                            name=entry.get("name", entry.get("provider", "unknown")),
                            cost=cost,
                            percentage=(cost / total * 100) if total > 0 else 0,
                            tokens=entry.get("tokens"),
                            calls=entry.get("calls"),
                        )
                    )
            return items

        return BreakdownResponse(
            data=BreakdownData(
                by_provider=_to_items(summary.cost_by_provider or []),
                by_feature=_to_items(summary.cost_by_feature or []),
            )
        )
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to get breakdown: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve breakdown data")


@router.get("/costs/timeline", response_model=TimelineResponse)
async def get_timeline(
    request: Request,
    range: str = Query("7d", alias="range"),
    workspace_id: str = Query("default"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> TimelineResponse:
    """Get cost timeline data points over a period."""
    try:
        summary = await _get_cost_summary(workspace_id, range)
        if not summary:
            return TimelineResponse(data=TimelineData())

        daily = summary.daily_costs or []
        total_cost = summary.total_cost or 0

        return TimelineResponse(
            data=TimelineData(
                data_points=[
                    TimelinePoint(
                        date=d.get("date", "") if isinstance(d, dict) else "",
                        cost=float(d.get("cost", 0)) if isinstance(d, dict) else 0,
                        tokens=d.get("tokens", 0) if isinstance(d, dict) else 0,
                    )
                    for d in daily
                ],
                total_cost=total_cost,
                average_daily_cost=(total_cost / len(daily)) if daily else 0,
            )
        )
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to get timeline: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve timeline data")


@router.get("/costs/alerts", response_model=AlertsResponse)
async def get_alerts(
    request: Request,
    workspace_id: str = Query("default"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> AlertsResponse:
    """Get active budget alerts for a workspace."""
    try:
        from aragora.server.handlers.costs.models import _get_active_alerts

        tracker = _get_cost_tracker()
        if not tracker:
            return AlertsResponse(data=AlertsData())

        active_alerts = _get_active_alerts(tracker, workspace_id)

        # Also get historical alerts from Knowledge Mound
        try:
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
        except (AttributeError, RuntimeError, TypeError):
            pass

        return AlertsResponse(
            data=AlertsData(
                alerts=[AlertItem(**a) if isinstance(a, dict) else a for a in active_alerts]
            )
        )
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to get alerts: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve alerts")


@router.post("/costs/budget", response_model=BudgetResponse, status_code=200)
async def set_budget(
    request: Request,
    body: BudgetSetRequest,
    auth: AuthorizationContext = Depends(require_permission("budget:set")),
) -> BudgetResponse:
    """Set or update workspace budget limits."""
    tracker = _get_cost_tracker()
    if not tracker:
        raise HTTPException(status_code=503, detail="Cost tracking not available")

    try:
        await asyncio.to_thread(
            tracker.set_budget,
            workspace_id=body.workspace_id,
            monthly_limit_usd=Decimal(str(body.monthly_limit_usd)),
            alert_threshold=body.alert_threshold,
        )

        budget = await asyncio.to_thread(tracker.get_budget, workspace_id=body.workspace_id)
        current_spend = float(budget.current_monthly_spend) if budget else 0.0
        limit = body.monthly_limit_usd

        return BudgetResponse(
            data=BudgetData(
                monthly_limit_usd=limit,
                current_spend_usd=current_spend,
                remaining_usd=max(0, limit - current_spend),
                alert_threshold=body.alert_threshold,
                utilization_pct=(current_spend / limit * 100) if limit > 0 else 0,
            )
        )
    except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to set budget: %s", e)
        raise HTTPException(status_code=500, detail="Failed to set budget")


@router.get("/costs/usage", response_model=UsageResponse)
async def get_usage(
    request: Request,
    range: str = Query("7d", alias="range"),
    workspace_id: str = Query("default"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> UsageResponse:
    """Get token usage statistics."""
    try:
        summary = await _get_cost_summary(workspace_id, range)
        if not summary:
            return UsageResponse(data=UsageData())

        tokens_in = getattr(summary, "tokens_in", summary.tokens_used)
        tokens_out = getattr(summary, "tokens_out", 0)

        return UsageResponse(
            data=UsageData(
                total_tokens_in=tokens_in,
                total_tokens_out=tokens_out,
                total_api_calls=summary.api_calls,
                by_model=[],
                by_provider=summary.cost_by_provider or [],
            )
        )
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to get usage: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve usage data")


@router.get("/costs/efficiency", response_model=EfficiencyResponse)
async def get_efficiency(
    request: Request,
    range: str = Query("7d", alias="range"),
    workspace_id: str = Query("default"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> EfficiencyResponse:
    """Get cost efficiency metrics."""
    try:
        summary = await _get_cost_summary(workspace_id, range)
        if not summary:
            return EfficiencyResponse(data=EfficiencyData())

        total_cost = summary.total_cost or 0
        total_tokens = summary.tokens_used or 0
        api_calls = summary.api_calls or 0

        cost_per_debate = (total_cost / api_calls) if api_calls > 0 else 0
        cost_per_token = (total_cost / total_tokens) if total_tokens > 0 else 0
        tokens_per_debate = (total_tokens / api_calls) if api_calls > 0 else 0

        # Simple efficiency score: lower cost per token = higher score
        efficiency_score = min(100, max(0, 100 - (cost_per_token * 1e6)))

        return EfficiencyResponse(
            data=EfficiencyData(
                cost_per_debate=round(cost_per_debate, 6),
                cost_per_token=round(cost_per_token, 8),
                tokens_per_debate=round(tokens_per_debate, 0),
                efficiency_score=round(efficiency_score, 1),
                trend="stable",
            )
        )
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to get efficiency: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve efficiency data")


@router.get("/costs/forecast", response_model=ForecastResponse)
async def get_forecast(
    request: Request,
    range: str = Query("30d", alias="range"),
    workspace_id: str = Query("default"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> ForecastResponse:
    """Get spend forecast based on historical trends."""
    try:
        summary = await _get_cost_summary(workspace_id, range)
        if not summary:
            return ForecastResponse(data=ForecastData())

        daily = summary.daily_costs or []
        total_cost = summary.total_cost or 0
        avg_daily = (total_cost / len(daily)) if daily else 0

        return ForecastResponse(
            data=ForecastData(
                projected_monthly=round(avg_daily * 30, 2),
                projected_daily=round(avg_daily, 2),
                confidence=0.7 if len(daily) >= 7 else 0.3,
                trend="stable",
                data_points=[],
            )
        )
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to get forecast: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve forecast")


@router.get("/costs/recommendations", response_model=RecommendationsResponse)
async def get_recommendations(
    request: Request,
    workspace_id: str = Query("default"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> RecommendationsResponse:
    """Get cost optimization recommendations."""
    try:
        summary = await _get_cost_summary(workspace_id, "30d")

        recommendations: list[RecommendationItem] = []
        total_savings = 0.0

        if summary and summary.total_cost > 0:
            # Check provider concentration
            providers = summary.cost_by_provider or []
            if len(providers) == 1 and providers[0].get("cost", 0) > 10:
                savings = providers[0].get("cost", 0) * 0.15
                total_savings += savings
                recommendations.append(
                    RecommendationItem(
                        id="diversify-providers",
                        title="Diversify AI providers",
                        description="Using multiple providers can reduce costs via competition and fallback pricing.",
                        potential_savings_usd=round(savings, 2),
                        difficulty="medium",
                        category="provider",
                    )
                )

            # Check if budget is set
            if summary.budget <= 0:
                recommendations.append(
                    RecommendationItem(
                        id="set-budget",
                        title="Set a workspace budget",
                        description="Budget limits prevent unexpected cost spikes and enable alerting.",
                        potential_savings_usd=0,
                        difficulty="easy",
                        category="governance",
                    )
                )

        return RecommendationsResponse(
            data=RecommendationsData(
                recommendations=recommendations,
                total_potential_savings=round(total_savings, 2),
            )
        )
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to get recommendations: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve recommendations")


@router.post("/costs/estimate", response_model=EstimateResponse)
async def estimate_cost(
    request: Request,
    body: EstimateRequest,
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> EstimateResponse:
    """Estimate cost for a debate configuration."""
    try:
        from aragora.billing.usage import calculate_token_cost

        tokens_in = body.estimated_tokens_per_round * body.rounds * body.agents
        tokens_out = int(tokens_in * 0.3)

        # Infer provider from model name for pricing lookup
        provider = getattr(body, "provider", None) or _infer_provider(body.model)

        cost = calculate_token_cost(provider, body.model, tokens_in, tokens_out)

        # The breakdown must SUM to the total. Costing the output half with
        # tokens_in=0 asked for a flat-rate quote, so above a documented
        # long-context threshold (gpt-6-astra's 272k, xAI's) the two halves
        # no longer added up -- 300k in / 10k out on gpt-6-astra reported
        # 6.00 + 0.50 against a real 6.75 (2026-09-05 wave-2 re-review).
        # Deriving the output half by subtraction makes the identity hold by
        # construction for every model, tiered or flat.
        input_cost = calculate_token_cost(provider, body.model, tokens_in, 0)

        return EstimateResponse(
            data=EstimateData(
                estimated_cost_usd=float(cost),
                tokens_input=tokens_in,
                tokens_output=tokens_out,
                model=body.model,
                breakdown={
                    "input_cost": float(input_cost),
                    "output_cost": float(cost - input_cost),
                    "rounds": body.rounds,
                    "agents": body.agents,
                },
            )
        )
    except (ImportError, ValueError, KeyError, TypeError) as e:
        logger.exception("Failed to estimate cost: %s", e)
        raise HTTPException(status_code=500, detail="Failed to estimate cost")


@router.get("/costs/budgets")
async def list_budgets(
    request: Request,
    workspace_id: str = Query("default"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> dict[str, Any]:
    """List all workspace budgets."""
    tracker = _get_cost_tracker()
    if not tracker:
        return {"data": {"budgets": []}}

    try:
        budget = await asyncio.to_thread(tracker.get_budget, workspace_id=workspace_id)
        if not budget:
            return {"data": {"budgets": []}}

        return {
            "data": {
                "budgets": [
                    {
                        "workspace_id": workspace_id,
                        "monthly_limit_usd": float(budget.monthly_limit_usd)
                        if budget.monthly_limit_usd
                        else 0,
                        "current_spend_usd": float(budget.current_monthly_spend)
                        if budget.current_monthly_spend
                        else 0,
                        "alert_threshold": getattr(budget, "alert_threshold", 0.8),
                    }
                ]
            }
        }
    except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to list budgets: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list budgets")


@router.get("/costs/analytics/trend")
async def get_spend_trend(
    request: Request,
    range: str = Query("30d", alias="range"),
    workspace_id: str = Query("default"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> dict[str, Any]:
    """Get spend trend analytics."""
    try:
        summary = await _get_cost_summary(workspace_id, range)
        if not summary:
            return {"data": {"trend": "stable", "data_points": [], "change_pct": 0}}

        daily = summary.daily_costs or []
        if len(daily) >= 2:
            first_half = daily[: len(daily) // 2]
            second_half = daily[len(daily) // 2 :]
            first_total = sum(
                float(d.get("cost", 0)) if isinstance(d, dict) else 0 for d in first_half
            )
            second_total = sum(
                float(d.get("cost", 0)) if isinstance(d, dict) else 0 for d in second_half
            )
            change_pct = (
                ((second_total - first_total) / first_total * 100) if first_total > 0 else 0
            )
            trend = (
                "increasing" if change_pct > 10 else "decreasing" if change_pct < -10 else "stable"
            )
        else:
            change_pct = 0
            trend = "stable"

        return {"data": {"trend": trend, "change_pct": round(change_pct, 1), "data_points": daily}}
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to get spend trend: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve trend data")


@router.get("/costs/analytics/by-agent")
async def get_spend_by_agent(
    request: Request,
    range: str = Query("7d", alias="range"),
    workspace_id: str = Query("default"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> dict[str, Any]:
    """Get spend breakdown by agent."""
    try:
        summary = await _get_cost_summary(workspace_id, range)
        if not summary:
            return {"data": {"by_agent": []}}

        # Agent-level breakdown comes from feature/operation data
        return {"data": {"by_agent": summary.cost_by_feature or []}}
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to get spend by agent: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve agent spend data")


@router.get("/costs/analytics/by-model")
async def get_spend_by_model(
    request: Request,
    range: str = Query("7d", alias="range"),
    workspace_id: str = Query("default"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> dict[str, Any]:
    """Get spend breakdown by model."""
    try:
        tracker = _get_cost_tracker()
        if not tracker:
            return {"data": {"by_model": []}}

        now = datetime.now(timezone.utc)
        range_days = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}.get(range, 7)
        start = now - timedelta(days=range_days)

        try:
            from aragora.billing.cost_tracker import CostGranularity

            report = await tracker.generate_report(
                workspace_id=workspace_id,
                period_start=start,
                period_end=now,
                granularity=CostGranularity.DAILY,
            )
            by_model = [
                {"name": name, "cost": float(cost)}
                for name, cost in sorted(
                    (report.cost_by_model or {}).items(),
                    key=lambda x: float(x[1]),
                    reverse=True,
                )
            ]
            return {"data": {"by_model": by_model}}
        except (ImportError, AttributeError):
            return {"data": {"by_model": []}}

    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to get spend by model: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve model spend data")


@router.post("/costs/export")
async def export_costs(
    request: Request,
    range: str = Query("30d", alias="range"),
    workspace_id: str = Query("default"),
    format: str = Query("json", description="Export format: json, csv"),
    auth: AuthorizationContext = Depends(require_permission("costs:read")),
) -> dict[str, Any]:
    """Export cost data in JSON or CSV format."""
    try:
        summary = await _get_cost_summary(workspace_id, range)
        if not summary:
            return {"data": {"rows": [], "format": format}}

        rows = []
        for d in summary.daily_costs or []:
            if isinstance(d, dict):
                rows.append(
                    {
                        "date": d.get("date", ""),
                        "cost": float(d.get("cost", 0)),
                        "tokens": d.get("tokens", 0),
                    }
                )

        return {
            "data": {
                "rows": rows,
                "format": format,
                "total_cost": summary.total_cost,
                "period": range,
            }
        }
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Failed to export costs: %s", e)
        raise HTTPException(status_code=500, detail="Failed to export cost data")
