"""
Usage analytics endpoint methods for AnalyticsMetricsHandler.

Extracted from _analytics_metrics_impl.py for modularity.
Provides token consumption, cost breakdown, and active user endpoints.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aragora.config import CACHE_TTL_ANALYTICS

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    ttl_cache,
)
from ._analytics_metrics_common import (
    VALID_GRANULARITIES,
    VALID_TIME_RANGES,
    _parse_time_range,
)

logger = logging.getLogger(__name__)


class UsageAnalyticsMixin:
    """Mixin providing usage analytics endpoint methods."""

    if TYPE_CHECKING:
        _validate_org_access: Any
        ctx: Any

    # =========================================================================
    # Usage Analytics Endpoints
    # =========================================================================

    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_usage_tokens")
    @handle_errors("get usage tokens")
    def _get_usage_tokens(
        self, query_params: dict, auth_context: Any | None = None
    ) -> HandlerResult:
        """
        Get token consumption trends.

        GET /api/v1/analytics/usage/tokens

        Query params:
        - org_id: Organization ID (required, must be user's org unless admin)
        - time_range: Time range filter (7d, 30d, 90d, 365d, all) - default 30d
        - granularity: Aggregation granularity (daily, weekly, monthly) - default daily

        Response:
        {
            "org_id": "...",
            "time_range": "30d",
            "granularity": "daily",
            "summary": {
                "total_tokens_in": 5000000,
                "total_tokens_out": 1000000,
                "total_tokens": 6000000,
                "avg_tokens_per_day": 200000
            },
            "trends": [
                {"period": "2026-01-01", "tokens_in": 180000, "tokens_out": 35000},
                ...
            ],
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        requested_org_id = query_params.get("org_id")
        if not requested_org_id:
            return error_response("org_id is required", 400)

        # Validate org access
        org_id, err = self._validate_org_access(auth_context, requested_org_id)
        if err:
            return err

        time_range = query_params.get("time_range", "30d")
        if time_range not in VALID_TIME_RANGES:
            time_range = "30d"

        granularity = query_params.get("granularity", "daily")
        if granularity not in VALID_GRANULARITIES:
            granularity = "daily"

        try:
            from aragora.billing.cost_tracker import get_cost_tracker

            tracker = get_cost_tracker()
            stats = tracker.get_workspace_stats(org_id)

            # Get summary data
            total_in = stats.get("total_tokens_in", 0)
            total_out = stats.get("total_tokens_out", 0)

            # Parse time range for day calculation
            start_time = _parse_time_range(time_range)
            days = 30
            if start_time:
                days = (datetime.now(timezone.utc) - start_time).days

            avg_per_day = (total_in + total_out) / days if days > 0 else 0

            return json_response(
                {
                    "org_id": org_id,
                    "time_range": time_range,
                    "granularity": granularity,
                    "summary": {
                        "total_tokens_in": total_in,
                        "total_tokens_out": total_out,
                        "total_tokens": total_in + total_out,
                        "avg_tokens_per_day": round(avg_per_day, 0),
                    },
                    "by_agent": stats.get("cost_by_agent", {}),
                    "by_model": stats.get("cost_by_model", {}),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except ImportError:
            return json_response(
                {
                    "org_id": org_id,
                    "time_range": time_range,
                    "granularity": granularity,
                    "summary": {
                        "total_tokens_in": 0,
                        "total_tokens_out": 0,
                        "total_tokens": 0,
                        "avg_tokens_per_day": 0,
                    },
                    "message": "Cost tracker not available",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_usage_costs")
    @handle_errors("get usage costs")
    def _get_usage_costs(
        self, query_params: dict, auth_context: Any | None = None
    ) -> HandlerResult:
        """
        Get cost breakdown by provider and model.

        GET /api/v1/analytics/usage/costs

        Query params:
        - org_id: Organization ID (required, must be user's org unless admin)
        - time_range: Time range filter (7d, 30d, 90d, 365d, all) - default 30d

        Response:
        {
            "org_id": "...",
            "time_range": "30d",
            "summary": {
                "total_cost_usd": "125.50",
                "avg_cost_per_day": "4.18",
                "avg_cost_per_debate": "0.84"
            },
            "by_provider": {
                "anthropic": {"cost": "80.00", "percentage": 63.7},
                "openai": {"cost": "45.50", "percentage": 36.3}
            },
            "by_model": {
                "claude-opus-4": {"cost": "60.00", "tokens": 400000},
                "gpt-4": {"cost": "45.50", "tokens": 200000}
            },
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        requested_org_id = query_params.get("org_id")
        if not requested_org_id:
            return error_response("org_id is required", 400)

        # Validate org access
        org_id, err = self._validate_org_access(auth_context, requested_org_id)
        if err:
            return err

        time_range = query_params.get("time_range", "30d")
        if time_range not in VALID_TIME_RANGES:
            time_range = "30d"

        try:
            from aragora.billing.cost_tracker import get_cost_tracker

            tracker = get_cost_tracker()
            stats = tracker.get_workspace_stats(org_id)

            total_cost = float(stats.get("total_cost_usd", "0"))

            # Parse time range for day calculation
            start_time = _parse_time_range(time_range)
            days = 30
            if start_time:
                days = (datetime.now(timezone.utc) - start_time).days

            avg_per_day = total_cost / days if days > 0 else 0

            # Get API call count for per-debate cost
            api_calls = stats.get("total_api_calls", 0)
            avg_per_debate = total_cost / api_calls if api_calls > 0 else 0

            # Build provider breakdown
            by_agent = stats.get("cost_by_agent", {})
            by_model = stats.get("cost_by_model", {})

            # Calculate provider percentages
            by_provider = {}
            for agent, cost_str in by_agent.items():
                cost = float(cost_str)
                percentage = (cost / total_cost * 100) if total_cost > 0 else 0
                by_provider[agent] = {
                    "cost": f"{cost:.2f}",
                    "percentage": round(percentage, 1),
                }

            return json_response(
                {
                    "org_id": org_id,
                    "time_range": time_range,
                    "summary": {
                        "total_cost_usd": f"{total_cost:.2f}",
                        "avg_cost_per_day": f"{avg_per_day:.2f}",
                        "avg_cost_per_debate": f"{avg_per_debate:.2f}",
                        "total_api_calls": api_calls,
                    },
                    "by_provider": by_provider,
                    "by_model": by_model,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except ImportError:
            return json_response(
                {
                    "org_id": org_id,
                    "time_range": time_range,
                    "summary": {
                        "total_cost_usd": "0.00",
                        "avg_cost_per_day": "0.00",
                        "avg_cost_per_debate": "0.00",
                    },
                    "by_provider": {},
                    "by_model": {},
                    "message": "Cost tracker not available",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_active_users")
    @handle_errors("get active users")
    def _get_active_users(
        self, query_params: dict, auth_context: Any | None = None
    ) -> HandlerResult:
        """
        Get active user counts.

        GET /api/v1/analytics/usage/active_users

        Query params:
        - org_id: Organization ID (optional, defaults to user's org)
        - time_range: Time range filter (7d, 30d, 90d) - default 30d

        Response:
        {
            "org_id": "...",
            "time_range": "30d",
            "active_users": {
                "daily": 25,
                "weekly": 85,
                "monthly": 150
            },
            "user_growth": {
                "new_users": 15,
                "churned_users": 5,
                "net_growth": 10
            },
            "activity_distribution": {
                "power_users": 10,
                "regular_users": 50,
                "occasional_users": 90
            },
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        # Validate org access
        requested_org_id = query_params.get("org_id")
        org_id, err = self._validate_org_access(auth_context, requested_org_id)
        if err:
            return err

        time_range = query_params.get("time_range", "30d")
        if time_range not in {"7d", "30d", "90d"}:
            time_range = "30d"

        # Try to get user store from context
        user_store = self.ctx.get("user_store")

        if not user_store:
            # Return mock data when user store not available
            return json_response(
                {
                    "org_id": org_id,
                    "time_range": time_range,
                    "active_users": {
                        "daily": 0,
                        "weekly": 0,
                        "monthly": 0,
                    },
                    "user_growth": {
                        "new_users": 0,
                        "churned_users": 0,
                        "net_growth": 0,
                    },
                    "activity_distribution": {
                        "power_users": 0,
                        "regular_users": 0,
                        "occasional_users": 0,
                    },
                    "message": "User store not available",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        try:
            # Get active user counts if method exists
            if hasattr(user_store, "get_active_user_counts"):
                counts = user_store.get_active_user_counts(org_id=org_id)
            else:
                counts = {"daily": 0, "weekly": 0, "monthly": 0}

            # Get user growth if method exists
            if hasattr(user_store, "get_user_growth"):
                growth = user_store.get_user_growth(org_id=org_id, days=30)
            else:
                growth = {"new_users": 0, "churned_users": 0, "net_growth": 0}

            return json_response(
                {
                    "org_id": org_id,
                    "time_range": time_range,
                    "active_users": counts,
                    "user_growth": growth,
                    "activity_distribution": {
                        "power_users": 0,
                        "regular_users": 0,
                        "occasional_users": 0,
                    },
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
            logger.warning("Failed to get active users: %s", e)
            return json_response(
                {
                    "org_id": org_id,
                    "time_range": time_range,
                    "active_users": {"daily": 0, "weekly": 0, "monthly": 0},
                    "error": "Failed to retrieve active users",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
