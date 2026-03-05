"""
SME Success Dashboard API Handlers.

Provides role-specific success views for SME users:
- GET /api/v1/sme/success - Unified success metrics
- GET /api/v1/sme/success/cfo - CFO-focused view (costs, ROI, budget)
- GET /api/v1/sme/success/pm - PM-focused view (velocity, consensus, decisions)
- GET /api/v1/sme/success/hr - HR-focused view (alignment, time savings)
- GET /api/v1/sme/success/milestones - Achievement milestones and gamification
- GET /api/v1/sme/success/insights - Actionable insights and recommendations

Designed for SME adoption with focus on demonstrating value and ROI.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from .base import (
    error_response,
    get_string_param,
    handle_errors,
    json_response,
)
from .utils.responses import HandlerResult
from .secure import SecureHandler
from .utils.decorators import require_permission
from .utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)


def _get_real_consensus_rate(
    org_id: str,
    start_time: datetime,
    end_time: datetime,
    default: float = 85.0,
) -> float:
    """Get real consensus rate from debate store.

    Returns the percentage of completed debates that reached consensus.
    Falls back to default if no data is available.

    Args:
        org_id: Organization ID
        start_time: Period start
        end_time: Period end
        default: Default rate when no data available (default: 85.0)

    Returns:
        Consensus rate as a percentage (0-100)
    """
    try:
        from aragora.memory.debate_store import get_debate_store

        store = get_debate_store()
        stats = store.get_consensus_stats(org_id, start_time, end_time)

        # Parse the rate string (e.g., "85%") to float
        rate_str = stats.get("overall_consensus_rate", "")
        if rate_str and rate_str != "0%":
            rate = float(rate_str.rstrip("%"))
            if rate > 0:
                return rate

        # No data available, use default
        return default
    except (ImportError, KeyError, ValueError, AttributeError, TypeError) as e:
        logger.warning("Failed to get consensus rate: %s", e)
        return default


# Rate limiter for success dashboard (60 requests per minute)
_dashboard_limiter = RateLimiter(requests_per_minute=60)

# Milestone definitions for gamification
MILESTONES = [
    {
        "id": "first_debate",
        "name": "First Decision",
        "description": "Completed your first AI-assisted debate",
        "icon": "rocket",
        "threshold": 1,
        "metric": "total_debates",
    },
    {
        "id": "debate_10",
        "name": "Decision Maker",
        "description": "Completed 10 debates",
        "icon": "trophy",
        "threshold": 10,
        "metric": "total_debates",
    },
    {
        "id": "debate_50",
        "name": "Decision Champion",
        "description": "Completed 50 debates",
        "icon": "crown",
        "threshold": 50,
        "metric": "total_debates",
    },
    {
        "id": "debate_100",
        "name": "Decision Master",
        "description": "Completed 100 debates",
        "icon": "star",
        "threshold": 100,
        "metric": "total_debates",
    },
    {
        "id": "consensus_streak_5",
        "name": "Consensus Builder",
        "description": "Reached consensus on 5 consecutive debates",
        "icon": "handshake",
        "threshold": 5,
        "metric": "consensus_streak",
    },
    {
        "id": "time_saved_1h",
        "name": "Time Saver",
        "description": "Saved 1 hour of decision-making time",
        "icon": "clock",
        "threshold": 60,
        "metric": "minutes_saved",
    },
    {
        "id": "time_saved_10h",
        "name": "Efficiency Expert",
        "description": "Saved 10 hours of decision-making time",
        "icon": "lightning",
        "threshold": 600,
        "metric": "minutes_saved",
    },
    {
        "id": "roi_positive",
        "name": "ROI Positive",
        "description": "Achieved positive return on investment",
        "icon": "trending-up",
        "threshold": 0,
        "metric": "roi_percentage",
    },
    {
        "id": "roi_100",
        "name": "ROI Champion",
        "description": "Achieved 100% return on investment",
        "icon": "chart",
        "threshold": 100,
        "metric": "roi_percentage",
    },
    {
        "id": "cost_saved_100",
        "name": "Cost Cutter",
        "description": "Saved $100 vs manual decision-making",
        "icon": "dollar",
        "threshold": 100,
        "metric": "cost_saved_usd",
    },
    {
        "id": "cost_saved_1000",
        "name": "Budget Hero",
        "description": "Saved $1,000 vs manual decision-making",
        "icon": "piggy-bank",
        "threshold": 1000,
        "metric": "cost_saved_usd",
    },
]


class SMESuccessDashboardHandler(SecureHandler):
    """Handler for SME success dashboard endpoints.

    Provides role-specific success metrics, gamification milestones,
    and actionable insights for SME customers.
    """

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    RESOURCE_TYPE = "success_dashboard"

    ROUTES = [
        "/api/v1/sme/success",
        "/api/v1/sme/success/cfo",
        "/api/v1/sme/success/pm",
        "/api/v1/sme/success/hr",
        "/api/v1/sme/success/milestones",
        "/api/v1/sme/success/insights",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES or path.startswith("/api/v1/sme/success")

    @require_permission("org:usage:read")
    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
        method: str = "GET",
    ) -> HandlerResult | None:
        """Route success dashboard requests to appropriate methods."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _dashboard_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for success dashboard: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # Determine HTTP method from handler if not provided
        if hasattr(handler, "command"):
            method = handler.command

        route_map = {
            "/api/v1/sme/success": self._get_success_summary,
            "/api/v1/sme/success/cfo": self._get_cfo_view,
            "/api/v1/sme/success/pm": self._get_pm_view,
            "/api/v1/sme/success/hr": self._get_hr_view,
            "/api/v1/sme/success/milestones": self._get_milestones,
            "/api/v1/sme/success/insights": self._get_insights,
        }

        if path in route_map and method == "GET":
            return route_map[path](handler, query_params)

        return error_response("Method not allowed", 405)

    def _get_user_and_org(self, handler: Any, user: Any) -> tuple[Any, Any, HandlerResult | None]:
        """Get user and organization from context."""
        user_store = self.ctx.get("user_store")
        if not user_store:
            return None, None, error_response("Service unavailable", 503)

        db_user = user_store.get_user_by_id(user.user_id)
        if not db_user:
            return None, None, error_response("User not found", 404)

        org = None
        if db_user.org_id:
            org = user_store.get_organization_by_id(db_user.org_id)

        if not org:
            return None, None, error_response("No organization found", 404)

        return db_user, org, None

    def _get_debate_analytics(self) -> Any | None:
        """Get debate analytics service instance."""
        try:
            from aragora.analytics.debate_analytics import get_debate_analytics

            return get_debate_analytics()
        except ImportError:
            logger.debug("DebateAnalytics not available")
            return None

    def _get_cost_tracker(self) -> Any | None:
        """Get cost tracker instance."""
        from aragora.billing.cost_tracker import get_cost_tracker

        return get_cost_tracker()

    def _get_onboarding_activation_metrics(self, org_id: str) -> dict[str, Any]:
        """Get onboarding activation/timing metrics for PM view."""
        try:
            from aragora.server.handlers.onboarding import get_onboarding_analytics_snapshot

            analytics = get_onboarding_analytics_snapshot(organization_id=org_id)
            funnel = analytics.get("funnel", {})
            timing = analytics.get("timing", {})
            return {
                "started": int(funnel.get("started", 0) or 0),
                "first_debate": int(funnel.get("first_debate", 0) or 0),
                "first_receipt": int(funnel.get("first_receipt", 0) or 0),
                "completed": int(funnel.get("completed", 0) or 0),
                "completion_rate_percent": float(funnel.get("completion_rate", 0.0) or 0.0),
                "time_to_first_debate_seconds": timing.get("time_to_first_debate_seconds"),
                "time_to_first_receipt_seconds": timing.get("time_to_first_receipt_seconds"),
                "step_drop_off": analytics.get("step_drop_off", {}),
            }
        except (ImportError, AttributeError, TypeError, ValueError) as e:
            logger.debug("Onboarding analytics unavailable for org %s: %s", org_id, e)
            return {
                "started": 0,
                "first_debate": 0,
                "first_receipt": 0,
                "completed": 0,
                "completion_rate_percent": 0.0,
                "time_to_first_debate_seconds": None,
                "time_to_first_receipt_seconds": None,
                "step_drop_off": {},
            }

    def _get_roi_calculator(self, benchmark: str = "sme") -> Any:
        """Get ROI calculator with benchmark."""
        from aragora.billing.roi_calculator import IndustryBenchmark, ROICalculator

        try:
            benchmark_enum = IndustryBenchmark(benchmark)
        except ValueError:
            benchmark_enum = IndustryBenchmark.SME

        return ROICalculator(benchmark=benchmark_enum)

    def _parse_period(self, handler: Any) -> tuple[datetime, datetime, str]:
        """Parse period parameters from request."""
        period = get_string_param(handler, "period", "month")
        now = datetime.now(timezone.utc)

        if period == "week":
            start_date = now - timedelta(days=7)
        elif period == "month":
            start_date = now - timedelta(days=30)
        elif period == "quarter":
            start_date = now - timedelta(days=90)
        elif period == "year":
            start_date = now - timedelta(days=365)
        else:
            start_date = now - timedelta(days=30)
            period = "month"

        return start_date, now, period

    def _calculate_success_metrics(
        self, org_id: str, start_date: datetime, end_date: datetime
    ) -> dict[str, Any]:
        """Calculate core success metrics for an organization.

        Attempts to use DebateAnalytics for real debate data (counts, consensus rate,
        avg duration). Falls back to cost-tracker-based estimation when analytics
        data is unavailable.
        """
        cost_tracker = self._get_cost_tracker()
        workspace_stats = cost_tracker.get_workspace_stats(org_id)

        # Get usage data from cost tracker
        total_cost = Decimal(workspace_stats.get("total_cost_usd", "0"))
        api_calls = workspace_stats.get("total_api_calls", 0)

        # Try to get real debate stats from DebateAnalytics
        days_back = max(1, (end_date - start_date).days)
        debate_stats = None
        analytics = self._get_debate_analytics()
        if analytics is not None:
            try:
                from aragora.utils.async_utils import get_event_loop_safe

                debate_stats = get_event_loop_safe().run_until_complete(
                    analytics.get_debate_stats(org_id=org_id, days_back=days_back)
                )
            except RuntimeError:
                # No running event loop or nested call - try creating a new one
                try:
                    debate_stats = asyncio.run(
                        analytics.get_debate_stats(org_id=org_id, days_back=days_back)
                    )
                except (RuntimeError, ValueError, AttributeError) as e:
                    logger.debug("Failed to run async get_debate_stats: %s", e)
            except (RuntimeError, ValueError, AttributeError) as e:
                logger.debug("Failed to get debate stats from analytics: %s", e)

        # Use real data if available, fall back to estimates
        if debate_stats is not None and debate_stats.total_debates > 0:
            estimated_debates = debate_stats.total_debates
            consensus_rate = debate_stats.consensus_rate * 100  # Convert 0-1 to percentage
            avg_debate_duration_minutes = (
                debate_stats.avg_duration_seconds / 60
                if debate_stats.avg_duration_seconds > 0
                else 5
            )
        else:
            # Fallback: estimate debates from API calls
            estimated_debates = max(1, api_calls // 10) if api_calls > 0 else 0
            avg_debate_duration_minutes = 5
            # Get consensus rate from debate store
            consensus_rate = _get_real_consensus_rate(org_id, start_date, end_date)

        # Calculate ROI metrics
        calculator = self._get_roi_calculator("sme")

        manual_decision_time_minutes = 45  # Industry benchmark
        hourly_rate = calculator.hourly_rate

        # Time savings
        total_ai_time = estimated_debates * avg_debate_duration_minutes
        manual_time_equivalent = estimated_debates * manual_decision_time_minutes
        minutes_saved = max(0, manual_time_equivalent - total_ai_time)
        hours_saved = minutes_saved / 60

        # Cost savings (time value)
        time_value_saved = Decimal(str(hours_saved)) * hourly_rate

        # Net savings
        net_savings = time_value_saved - total_cost
        roi_percentage = float((net_savings / total_cost) * 100) if total_cost > 0 else 0

        return {
            "total_debates": estimated_debates,
            "total_cost_usd": float(total_cost),
            "minutes_saved": minutes_saved,
            "hours_saved": round(hours_saved, 1),
            "cost_saved_usd": float(time_value_saved),
            "net_savings_usd": float(net_savings),
            "roi_percentage": round(roi_percentage, 1),
            "consensus_rate": consensus_rate,
            "consensus_streak": min(estimated_debates, 5),  # Placeholder
            "avg_debate_time_minutes": avg_debate_duration_minutes,
            "manual_equivalent_minutes": manual_decision_time_minutes,
        }

    @handle_errors("get success summary")
    @require_permission("org:usage:read")
    def _get_success_summary(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """
        Get unified success metrics summary.

        Returns key value metrics that demonstrate ROI and success.
        """
        db_user, org, error = self._get_user_and_org(handler, user)
        if error:
            return error

        start_date, end_date, period = self._parse_period(handler)
        metrics = self._calculate_success_metrics(org.id, start_date, end_date)

        # Build headline success message
        if metrics["net_savings_usd"] > 0:
            headline = f"You've saved ${metrics['net_savings_usd']:.2f} this {period}!"
            subheadline = f"That's {metrics['hours_saved']:.1f} hours of decision-making time."
        else:
            headline = f"You've made {metrics['total_debates']} decisions this {period}!"
            subheadline = "Keep going to see your ROI grow."

        return json_response(
            {
                "success": {
                    "headline": headline,
                    "subheadline": subheadline,
                    "period": period,
                    "key_metrics": {
                        "decisions_made": metrics["total_debates"],
                        "time_saved_hours": metrics["hours_saved"],
                        "money_saved_usd": round(metrics["cost_saved_usd"], 2),
                        "net_roi_usd": round(metrics["net_savings_usd"], 2),
                        "roi_percentage": metrics["roi_percentage"],
                        "consensus_rate": metrics["consensus_rate"],
                    },
                    "comparison": {
                        "manual_time_hours": round(
                            metrics["total_debates"] * metrics["manual_equivalent_minutes"] / 60, 1
                        ),
                        "ai_time_hours": round(
                            metrics["total_debates"] * metrics["avg_debate_time_minutes"] / 60, 1
                        ),
                        "efficiency_multiplier": round(
                            metrics["manual_equivalent_minutes"]
                            / metrics["avg_debate_time_minutes"],
                            1,
                        )
                        if metrics["avg_debate_time_minutes"] > 0
                        else 0,
                    },
                }
            }
        )

    @handle_errors("get CFO view")
    @require_permission("org:usage:read")
    def _get_cfo_view(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """
        Get CFO-focused success view.

        Emphasizes: costs, ROI, budget utilization, cost trends.
        """
        db_user, org, error = self._get_user_and_org(handler, user)
        if error:
            return error

        start_date, end_date, period = self._parse_period(handler)
        metrics = self._calculate_success_metrics(org.id, start_date, end_date)

        # Get budget info
        cost_tracker = self._get_cost_tracker()
        budget = cost_tracker.get_budget(workspace_id=org.id, org_id=org.id)

        budget_info = {}
        if budget:
            budget_info = {
                "monthly_limit_usd": float(budget.monthly_limit_usd or 0),
                "spent_usd": float(budget.current_monthly_spend),
                "remaining_usd": float(
                    max(0, (budget.monthly_limit_usd or 0) - budget.current_monthly_spend)
                ),
                "utilization_percent": round(
                    float(budget.current_monthly_spend / budget.monthly_limit_usd * 100)
                    if budget.monthly_limit_usd and budget.monthly_limit_usd > 0
                    else 0,
                    1,
                ),
            }

        return json_response(
            {
                "cfo_view": {
                    "role": "cfo",
                    "headline": f"${metrics['net_savings_usd']:.2f} net savings this {period}",
                    "period": period,
                    "financial_summary": {
                        "total_spend_usd": metrics["total_cost_usd"],
                        "value_generated_usd": metrics["cost_saved_usd"],
                        "net_roi_usd": metrics["net_savings_usd"],
                        "roi_percentage": metrics["roi_percentage"],
                    },
                    "cost_efficiency": {
                        "cost_per_decision_usd": round(
                            metrics["total_cost_usd"] / metrics["total_debates"], 2
                        )
                        if metrics["total_debates"] > 0
                        else 0,
                        "manual_cost_per_decision_usd": round(
                            metrics["manual_equivalent_minutes"]
                            / 60
                            * float(self._get_roi_calculator().hourly_rate),
                            2,
                        ),
                        "savings_per_decision_usd": round(
                            (metrics["cost_saved_usd"] - metrics["total_cost_usd"])
                            / metrics["total_debates"],
                            2,
                        )
                        if metrics["total_debates"] > 0
                        else 0,
                    },
                    "budget": budget_info,
                    "projections": {
                        "monthly_run_rate_usd": round(
                            metrics["total_cost_usd"] * 30 / max(1, (end_date - start_date).days), 2
                        ),
                        "projected_annual_savings_usd": round(metrics["net_savings_usd"] * 12, 2),
                    },
                }
            }
        )

    @handle_errors("get PM view")
    @require_permission("org:usage:read")
    def _get_pm_view(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """
        Get PM-focused success view.

        Emphasizes: decision velocity, consensus rates, decision quality.
        """
        db_user, org, error = self._get_user_and_org(handler, user)
        if error:
            return error

        start_date, end_date, period = self._parse_period(handler)
        metrics = self._calculate_success_metrics(org.id, start_date, end_date)
        activation = self._get_onboarding_activation_metrics(org.id)

        days_in_period = max(1, (end_date - start_date).days)
        decisions_per_day = metrics["total_debates"] / days_in_period

        return json_response(
            {
                "pm_view": {
                    "role": "pm",
                    "headline": f"{metrics['total_debates']} decisions made {metrics['consensus_rate']}% faster",
                    "period": period,
                    "velocity": {
                        "total_decisions": metrics["total_debates"],
                        "decisions_per_day": round(decisions_per_day, 1),
                        "decisions_per_week": round(decisions_per_day * 7, 1),
                        "avg_decision_time_minutes": metrics["avg_debate_time_minutes"],
                        "time_to_consensus_minutes": round(
                            metrics["avg_debate_time_minutes"] * 0.8, 1
                        ),
                    },
                    "quality": {
                        "consensus_rate_percent": metrics["consensus_rate"],
                        "consensus_streak": metrics["consensus_streak"],
                        "decisions_with_consensus": round(
                            metrics["total_debates"] * metrics["consensus_rate"] / 100
                        ),
                    },
                    "efficiency": {
                        "manual_equivalent_hours": round(
                            metrics["total_debates"] * metrics["manual_equivalent_minutes"] / 60, 1
                        ),
                        "actual_hours": round(
                            metrics["total_debates"] * metrics["avg_debate_time_minutes"] / 60, 1
                        ),
                        "hours_saved": metrics["hours_saved"],
                        "efficiency_gain_percent": round(
                            (
                                1
                                - metrics["avg_debate_time_minutes"]
                                / metrics["manual_equivalent_minutes"]
                            )
                            * 100,
                            1,
                        )
                        if metrics["manual_equivalent_minutes"] > 0
                        else 0,
                    },
                    "trends": {
                        "velocity_trend": "stable",  # Placeholder
                        "consensus_trend": "improving",  # Placeholder
                    },
                    "activation": activation,
                }
            }
        )

    @handle_errors("get HR view")
    @require_permission("org:usage:read")
    def _get_hr_view(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """
        Get HR-focused success view.

        Emphasizes: team alignment, time savings, decision participation.
        """
        db_user, org, error = self._get_user_and_org(handler, user)
        if error:
            return error

        start_date, end_date, period = self._parse_period(handler)
        metrics = self._calculate_success_metrics(org.id, start_date, end_date)

        return json_response(
            {
                "hr_view": {
                    "role": "hr",
                    "headline": f"Team aligned on {metrics['consensus_rate']:.0f}% of decisions",
                    "period": period,
                    "alignment": {
                        "consensus_rate_percent": metrics["consensus_rate"],
                        "decisions_with_alignment": round(
                            metrics["total_debates"] * metrics["consensus_rate"] / 100
                        ),
                        "alignment_trend": "improving",  # Placeholder
                    },
                    "time_impact": {
                        "hours_saved_total": metrics["hours_saved"],
                        "hours_saved_per_person": round(
                            metrics["hours_saved"] / 5, 1
                        ),  # Assume 5-person team
                        "meeting_hours_avoided": round(
                            metrics["hours_saved"] * 0.6, 1
                        ),  # 60% would be meetings
                    },
                    "participation": {
                        "total_decisions": metrics["total_debates"],
                        "avg_participants_per_decision": 3,  # Placeholder
                        "decision_inclusivity_score": 85,  # Placeholder
                    },
                    "wellbeing_impact": {
                        "decision_fatigue_reduction_percent": round(
                            (
                                1
                                - metrics["avg_debate_time_minutes"]
                                / metrics["manual_equivalent_minutes"]
                            )
                            * 100,
                            1,
                        )
                        if metrics["manual_equivalent_minutes"] > 0
                        else 0,
                        "conflict_reduction_score": 78,  # Placeholder (AI mediates disagreements)
                    },
                }
            }
        )

    @handle_errors("get milestones")
    @require_permission("org:usage:read")
    def _get_milestones(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """
        Get achievement milestones and gamification status.

        Returns earned and upcoming milestones.
        """
        db_user, org, error = self._get_user_and_org(handler, user)
        if error:
            return error

        # Calculate all-time metrics for milestones
        start_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
        end_date = datetime.now(timezone.utc)
        metrics = self._calculate_success_metrics(org.id, start_date, end_date)

        # Evaluate milestones
        earned: list[dict[str, Any]] = []
        upcoming: list[dict[str, Any]] = []
        next_milestone = None

        for milestone in MILESTONES:
            metric_key = str(milestone["metric"])
            raw_metric = metrics.get(metric_key, 0)
            metric_value: int = int(raw_metric) if raw_metric else 0
            raw_threshold = milestone["threshold"]
            # raw_threshold is int from MILESTONES dict above
            threshold: int = (
                int(raw_threshold) if isinstance(raw_threshold, (int, float, str)) else 0
            )

            milestone_data = {
                "id": milestone["id"],
                "name": milestone["name"],
                "description": milestone["description"],
                "icon": milestone["icon"],
                "threshold": threshold,
                "current_value": metric_value,
            }

            if metric_value >= threshold:
                milestone_data["earned"] = True
                milestone_data["earned_date"] = end_date.isoformat()  # Approximate
                earned.append(milestone_data)
            else:
                milestone_data["earned"] = False
                milestone_data["progress_percent"] = (
                    round(min(100, (metric_value / threshold) * 100), 1) if threshold > 0 else 0
                )
                milestone_data["remaining"] = threshold - metric_value
                upcoming.append(milestone_data)

                # Track next closest milestone
                current_progress = milestone_data.get("progress_percent", 0)
                next_progress = next_milestone.get("progress_percent", 0) if next_milestone else 0
                # Both progress values are either float or 0 from above calculations
                current_progress_val = (
                    float(current_progress) if isinstance(current_progress, (int, float)) else 0.0
                )
                next_progress_val = (
                    float(next_progress) if isinstance(next_progress, (int, float)) else 0.0
                )
                if next_milestone is None or current_progress_val > next_progress_val:
                    next_milestone = milestone_data

        # Sort earned by threshold (most impressive first)
        earned.sort(key=lambda x: x["threshold"], reverse=True)

        # Sort upcoming by progress (closest to earning first)
        upcoming.sort(key=lambda x: x["progress_percent"], reverse=True)

        return json_response(
            {
                "milestones": {
                    "total_earned": len(earned),
                    "total_available": len(MILESTONES),
                    "completion_percent": round(len(earned) / len(MILESTONES) * 100, 1),
                    "earned": earned,
                    "upcoming": upcoming[:5],  # Top 5 closest
                    "next_milestone": next_milestone,
                }
            }
        )

    @handle_errors("get insights")
    @require_permission("org:usage:read")
    def _get_insights(
        self,
        handler: Any,
        query_params: dict[str, Any],
        user: Any | None = None,
    ) -> HandlerResult:
        """
        Get actionable insights and recommendations.

        Analyzes usage patterns and suggests improvements.
        """
        db_user, org, error = self._get_user_and_org(handler, user)
        if error:
            return error

        start_date, end_date, period = self._parse_period(handler)
        metrics = self._calculate_success_metrics(org.id, start_date, end_date)

        insights: list[dict[str, Any]] = []

        # Generate contextual insights
        if metrics["total_debates"] == 0:
            insights.append(
                {
                    "type": "getting_started",
                    "priority": "high",
                    "title": "Start Your First Decision",
                    "message": "You haven't run any debates yet. Start with a simple decision to see Aragora in action.",
                    "action": "Create your first debate",
                    "action_url": "/debates/new",
                }
            )
        elif metrics["total_debates"] < 5:
            insights.append(
                {
                    "type": "engagement",
                    "priority": "medium",
                    "title": "Build Your Decision Habit",
                    "message": f"You've made {metrics['total_debates']} decisions. Try using Aragora for your next team decision to build momentum.",
                    "action": "Schedule a recurring decision review",
                    "action_url": "/settings/automation",
                }
            )

        if metrics["roi_percentage"] > 100:
            insights.append(
                {
                    "type": "success",
                    "priority": "low",
                    "title": "Excellent ROI!",
                    "message": f"Your {metrics['roi_percentage']:.0f}% ROI is outstanding. Consider expanding usage to other teams.",
                    "action": "Invite team members",
                    "action_url": "/settings/team",
                }
            )
        elif metrics["roi_percentage"] > 0:
            insights.append(
                {
                    "type": "optimization",
                    "priority": "medium",
                    "title": "Boost Your ROI",
                    "message": "You're ROI-positive! Increase decision volume to maximize savings.",
                    "action": "View suggested decisions",
                    "action_url": "/debates/suggestions",
                }
            )
        elif metrics["total_debates"] > 0:
            insights.append(
                {
                    "type": "optimization",
                    "priority": "high",
                    "title": "Path to Positive ROI",
                    "message": "You're close to positive ROI. A few more high-value decisions will tip the balance.",
                    "action": "See high-value decision types",
                    "action_url": "/insights/decision-types",
                }
            )

        if metrics["consensus_rate"] < 70 and metrics["total_debates"] > 5:
            insights.append(
                {
                    "type": "quality",
                    "priority": "medium",
                    "title": "Improve Consensus Rates",
                    "message": f"Your consensus rate is {metrics['consensus_rate']:.0f}%. Try adding more context to debates.",
                    "action": "View best practices",
                    "action_url": "/help/consensus-tips",
                }
            )

        if metrics["hours_saved"] > 10:
            insights.append(
                {
                    "type": "celebration",
                    "priority": "low",
                    "title": "Time Well Saved!",
                    "message": f"You've saved {metrics['hours_saved']:.1f} hours this {period}. That's a full day+ of productive time!",
                    "action": "Share your success",
                    "action_url": "/share/success-story",
                }
            )

        return json_response(
            {
                "insights": {
                    "count": len(insights),
                    "items": insights,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        )


__all__ = ["SMESuccessDashboardHandler"]
