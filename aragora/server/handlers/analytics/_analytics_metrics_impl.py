"""
Analytics Dashboard Metrics endpoint handlers.

Provides REST APIs for analytics dashboard showing debate metrics and agent performance:

Debate Analytics:
- GET /api/analytics/debates/overview - Total debates, consensus rate, avg rounds
- GET /api/analytics/debates/trends - Debates over time (daily/weekly/monthly)
- GET /api/analytics/debates/topics - Topic distribution
- GET /api/analytics/debates/outcomes - Win/loss/draw distribution

Agent Performance:
- GET /api/analytics/agents/leaderboard - ELO rankings with win rates
- GET /api/analytics/agents/{agent_id}/performance - Individual agent stats
- GET /api/analytics/agents/comparison - Compare multiple agents
- GET /api/analytics/agents/trends - Agent performance over time

Usage Analytics:
- GET /api/analytics/usage/tokens - Token consumption trends
- GET /api/analytics/usage/costs - Cost breakdown by provider/model
- GET /api/analytics/usage/active_users - Active user counts
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.rbac.decorators import require_permission  # noqa: F401

try:
    from aragora.rbac.checker import check_permission  # noqa: F401

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    HandlerResult,
    error_response,
)
from ..secure import ForbiddenError, SecureHandler, UnauthorizedError
from ..utils.rate_limit import RateLimiter, get_client_ip

# Re-export from submodules for backward compatibility
from ._analytics_metrics_common import (  # noqa: F401
    VALID_GRANULARITIES,
    VALID_TIME_RANGES,
    _group_by_time,
    _parse_time_range,
)
from ._analytics_metrics_agents import AgentAnalyticsMixin  # noqa: F401
from ._analytics_metrics_debates import DebateAnalyticsMixin  # noqa: F401
from ._analytics_metrics_usage import UsageAnalyticsMixin  # noqa: F401

logger = logging.getLogger(__name__)

# Permission required for analytics metrics access
ANALYTICS_METRICS_PERMISSION = "analytics:read"

# Rate limiter for analytics metrics endpoints (60 requests per minute)
_analytics_metrics_limiter = RateLimiter(requests_per_minute=60)


def _is_demo_mode() -> bool:
    """Check if server is running in demo/offline mode."""
    return os.environ.get("ARAGORA_DEMO_MODE", "").lower() in ("true", "1", "yes")


def _demo_response(normalized: str) -> HandlerResult | None:
    """Return demo data for analytics endpoints when in demo mode."""
    from ..base import json_response as _json

    demo = {
        "/api/analytics/debates/overview": {
            "time_range": "30d",
            "total_debates": 47,
            "debates_this_period": 18,
            "debates_previous_period": 14,
            "growth_rate": 28.6,
            "consensus_reached": 34,
            "consensus_rate": 72.3,
            "avg_rounds": 3.1,
            "avg_agents_per_debate": 4.2,
            "avg_confidence": 0.81,
        },
        "/api/analytics/debates/trends": {
            "data_points": [
                {
                    "period": "2026-02-16",
                    "total": 8,
                    "consensus_reached": 6,
                    "consensus_rate": 75.0,
                    "avg_rounds": 2.9,
                },
                {
                    "period": "2026-02-17",
                    "total": 11,
                    "consensus_reached": 8,
                    "consensus_rate": 72.7,
                    "avg_rounds": 3.2,
                },
                {
                    "period": "2026-02-18",
                    "total": 6,
                    "consensus_reached": 4,
                    "consensus_rate": 66.7,
                    "avg_rounds": 3.5,
                },
                {
                    "period": "2026-02-19",
                    "total": 13,
                    "consensus_reached": 10,
                    "consensus_rate": 76.9,
                    "avg_rounds": 2.8,
                },
                {
                    "period": "2026-02-20",
                    "total": 9,
                    "consensus_reached": 6,
                    "consensus_rate": 66.7,
                    "avg_rounds": 3.3,
                },
            ]
        },
        "/api/analytics/debates/topics": {
            "topics": [
                {"topic": "API rate limiting strategy", "count": 8, "consensus_rate": 87.5},
                {"topic": "Database migration approach", "count": 6, "consensus_rate": 66.7},
                {"topic": "Authentication architecture", "count": 5, "consensus_rate": 80.0},
                {"topic": "Cost optimization", "count": 4, "consensus_rate": 75.0},
                {"topic": "Error handling patterns", "count": 3, "consensus_rate": 100.0},
            ]
        },
        "/api/analytics/debates/outcomes": {
            "outcomes": {"consensus": 34, "no_consensus": 8, "timeout": 3, "error": 2}
        },
        "/api/analytics/agents/leaderboard": {
            "leaderboard": [
                {
                    "agent_id": "claude-opus",
                    "agent_name": "Claude Opus",
                    "elo": 1847,
                    "win_rate": 0.78,
                    "debates": 42,
                    "rank": 1,
                },
                {
                    "agent_id": "gpt-4o",
                    "agent_name": "GPT-4o",
                    "elo": 1792,
                    "win_rate": 0.71,
                    "debates": 38,
                    "rank": 2,
                },
                {
                    "agent_id": "gemini-pro",
                    "agent_name": "Gemini Pro",
                    "elo": 1734,
                    "win_rate": 0.65,
                    "debates": 35,
                    "rank": 3,
                },
                {
                    "agent_id": "claude-sonnet",
                    "agent_name": "Claude Sonnet",
                    "elo": 1715,
                    "win_rate": 0.62,
                    "debates": 40,
                    "rank": 4,
                },
                {
                    "agent_id": "mistral-large",
                    "agent_name": "Mistral Large",
                    "elo": 1688,
                    "win_rate": 0.58,
                    "debates": 28,
                    "rank": 5,
                },
            ],
            "total_agents": 5,
        },
        "/api/analytics/usage/tokens": {
            "summary": {
                "total_tokens_in": 284500,
                "total_tokens_out": 142300,
                "total_tokens": 426800,
                "avg_tokens_per_day": 85360,
            },
            "by_agent": {
                "claude-opus": {"tokens": 168200, "percentage": 39.4},
                "gpt-4o": {"tokens": 124600, "percentage": 29.2},
                "gemini-pro": {"tokens": 72400, "percentage": 17.0},
                "claude-sonnet": {"tokens": 38900, "percentage": 9.1},
                "mistral-large": {"tokens": 22700, "percentage": 5.3},
            },
        },
        "/api/analytics/usage/costs": {
            "total_cost_usd": 12.47,
            "projected_monthly_cost": 18.70,
            "by_provider": {
                "Anthropic": {"cost": "7.46", "percentage": 59.8},
                "OpenAI": {"cost": "3.91", "percentage": 31.4},
                "Google": {"cost": "0.78", "percentage": 6.3},
                "Mistral": {"cost": "0.32", "percentage": 2.6},
            },
            "by_model": {
                "claude-opus-4": {"cost": "5.82", "percentage": 46.7},
                "gpt-4o": {"cost": "3.91", "percentage": 31.4},
                "claude-opus-4-8": {"cost": "1.64", "percentage": 13.1},
                "gemini-1.5-pro": {"cost": "0.78", "percentage": 6.3},
                "mistral-large": {"cost": "0.32", "percentage": 2.6},
            },
        },
        "/api/analytics/usage/active_users": {
            "active_users_24h": 3,
            "active_users_7d": 5,
            "active_users_30d": 8,
        },
    }
    data = demo.get(normalized)
    if data is not None:
        return _json(data)
    return None


class AnalyticsMetricsHandler(
    DebateAnalyticsMixin,
    AgentAnalyticsMixin,
    UsageAnalyticsMixin,
    SecureHandler,
):
    """Handler for analytics metrics dashboard endpoints.

    Requires authentication and analytics:read permission (RBAC).
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    def _validate_org_access(
        self,
        auth_context: Any,
        requested_org_id: str | None,
    ) -> tuple[str | None, HandlerResult | None]:
        """Validate user has access to the requested organization.

        Args:
            auth_context: The user's authorization context
            requested_org_id: The org_id requested in query params

        Returns:
            Tuple of (validated_org_id, error_response or None)
            If error_response is not None, return it immediately.
            If requested_org_id is None, returns user's org_id.
        """
        user_org_id = getattr(auth_context, "org_id", None)
        user_roles = getattr(auth_context, "roles", []) or []

        # Platform admins can access any org
        if "platform_admin" in user_roles or "admin" in user_roles:
            return requested_org_id, None

        # If no org requested, use user's org
        if not requested_org_id:
            return user_org_id, None

        # User can only access their own org
        if user_org_id and requested_org_id != user_org_id:
            return None, error_response(
                "Access denied to organization",
                403,
                code="ORG_ACCESS_DENIED",
            )

        return requested_org_id, None

    ROUTES = [
        # Debate Analytics
        "/api/analytics/debates/overview",
        "/api/analytics/debates/trends",
        "/api/analytics/debates/topics",
        "/api/analytics/debates/outcomes",
        # Agent Performance
        "/api/analytics/agents/leaderboard",
        "/api/analytics/agents/comparison",
        "/api/analytics/agents/trends",
        # Usage Analytics
        "/api/analytics/usage/tokens",
        "/api/analytics/usage/costs",
        "/api/analytics/usage/active_users",
    ]

    # Pattern for agent-specific performance endpoint
    AGENT_PERFORMANCE_PATTERN = re.compile(r"^/api/analytics/agents/([a-zA-Z0-9_-]+)/performance$")

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        if normalized in self.ROUTES:
            return True
        # Check agent performance pattern
        return bool(self.AGENT_PERFORMANCE_PATTERN.match(normalized))

    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route GET requests to appropriate methods with RBAC."""
        normalized = strip_version_prefix(path)

        # Demo mode: return sample data without auth
        if _is_demo_mode():
            demo_result = _demo_response(normalized)
            if demo_result is not None:
                return demo_result

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _analytics_metrics_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for analytics metrics: %s", client_ip)
            return error_response(
                "Rate limit exceeded. Please try again later.",
                429,
            )

        # RBAC: Require authentication and analytics:read permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, ANALYTICS_METRICS_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401, code="AUTH_REQUIRED")
        except ForbiddenError as e:
            logger.warning("Analytics metrics access denied: %s", e)
            return error_response("Permission denied", 403, code="PERMISSION_DENIED")

        # Additional RBAC check via rbac.checker if available
        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                return error_response("Service unavailable: access control module not loaded", 503)
        elif hasattr(handler, "auth_context"):
            decision = check_permission(handler.auth_context, ANALYTICS_METRICS_PERMISSION)
            if not decision.allowed:
                logger.warning("RBAC denied analytics metrics access: %s", decision.reason)
                return error_response(
                    "Permission denied",
                    403,
                    code="PERMISSION_DENIED",
                )

        # Debate Analytics
        if normalized == "/api/analytics/debates/overview":
            return self._get_debates_overview(query_params, auth_context)
        elif normalized == "/api/analytics/debates/trends":
            return self._get_debates_trends(query_params, auth_context)
        elif normalized == "/api/analytics/debates/topics":
            return self._get_debates_topics(query_params, auth_context)
        elif normalized == "/api/analytics/debates/outcomes":
            return self._get_debates_outcomes(query_params, auth_context)

        # Agent Performance
        elif normalized == "/api/analytics/agents/leaderboard":
            return self._get_agents_leaderboard(query_params)
        elif normalized == "/api/analytics/agents/comparison":
            return self._get_agents_comparison(query_params)
        elif normalized == "/api/analytics/agents/trends":
            return self._get_agents_trends(query_params)

        # Agent-specific performance
        match = self.AGENT_PERFORMANCE_PATTERN.match(normalized)
        if match:
            agent_id = match.group(1)
            return self._get_agent_performance(agent_id, query_params)

        # Usage Analytics
        if normalized == "/api/analytics/usage/tokens":
            return self._get_usage_tokens(query_params, auth_context)
        elif normalized == "/api/analytics/usage/costs":
            return self._get_usage_costs(query_params, auth_context)
        elif normalized == "/api/analytics/usage/active_users":
            return self._get_active_users(query_params, auth_context)

        return None


__all__ = [
    "AnalyticsMetricsHandler",
    # Re-exports from submodules
    "AgentAnalyticsMixin",
    "DebateAnalyticsMixin",
    "UsageAnalyticsMixin",
    "VALID_GRANULARITIES",
    "VALID_TIME_RANGES",
    "_group_by_time",
    "_parse_time_range",
]
