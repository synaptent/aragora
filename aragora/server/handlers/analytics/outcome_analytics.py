"""
Decision Outcome Analytics endpoint handler.

Provides REST API for querying decision outcome analytics:

- GET /api/analytics/outcomes - Full outcome analytics summary
- GET /api/analytics/outcomes/consensus-rate - Consensus rate for period
- GET /api/analytics/outcomes/average-rounds - Mean rounds to conclusion
- GET /api/analytics/outcomes/contributions - Agent contribution scores
- GET /api/analytics/outcomes/quality-trend - Decision quality over time
- GET /api/analytics/outcomes/topics - Topic distribution
- GET /api/analytics/outcomes/{debate_id} - Single debate outcome summary
"""

from __future__ import annotations

import logging
import re
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..secure import ForbiddenError, SecureHandler, UnauthorizedError
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Permission required for outcome analytics access
OUTCOME_ANALYTICS_PERMISSION = "analytics:read"

# Rate limiter (60 requests per minute - cached data)
_outcome_analytics_limiter = RateLimiter(requests_per_minute=60)


class OutcomeAnalyticsHandler(SecureHandler):
    """Handler for decision outcome analytics endpoints.

    Requires authentication and analytics:read permission (RBAC).
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/analytics/outcomes",
        "/api/analytics/outcomes/consensus-rate",
        "/api/analytics/outcomes/average-rounds",
        "/api/analytics/outcomes/contributions",
        "/api/analytics/outcomes/quality-trend",
        "/api/analytics/outcomes/topics",
    ]

    # Pattern for single debate outcome: /api/analytics/outcomes/{debate_id}
    DEBATE_OUTCOME_PATTERN = re.compile(r"^/api/analytics/outcomes/([a-zA-Z0-9_-]+)$")

    # Known sub-route suffixes that should NOT match as debate IDs
    _KNOWN_SUFFIXES = {
        "consensus-rate",
        "average-rounds",
        "contributions",
        "quality-trend",
        "topics",
    }

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        if normalized in self.ROUTES:
            return True
        match = self.DEBATE_OUTCOME_PATTERN.match(normalized)
        if match and match.group(1) not in self._KNOWN_SUFFIXES:
            return True
        return False

    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route GET requests to appropriate outcome analytics methods."""
        normalized = strip_version_prefix(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _outcome_analytics_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for outcome analytics: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # RBAC: Require authentication and analytics:read permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, OUTCOME_ANALYTICS_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401, code="AUTH_REQUIRED")
        except ForbiddenError as e:
            logger.warning("Outcome analytics access denied: %s", e)
            return error_response("Permission denied", 403, code="PERMISSION_DENIED")

        # Route to appropriate method
        if normalized == "/api/analytics/outcomes":
            return await self._get_outcomes_summary(query_params)
        elif normalized == "/api/analytics/outcomes/consensus-rate":
            return await self._get_consensus_rate(query_params)
        elif normalized == "/api/analytics/outcomes/average-rounds":
            return await self._get_average_rounds(query_params)
        elif normalized == "/api/analytics/outcomes/contributions":
            return await self._get_contributions(query_params)
        elif normalized == "/api/analytics/outcomes/quality-trend":
            return await self._get_quality_trend(query_params)
        elif normalized == "/api/analytics/outcomes/topics":
            return await self._get_topics(query_params)

        # Single debate outcome
        match = self.DEBATE_OUTCOME_PATTERN.match(normalized)
        if match:
            debate_id = match.group(1)
            if debate_id not in self._KNOWN_SUFFIXES:
                return await self._get_debate_outcome(debate_id)

        return None

    @handle_errors("get outcomes summary")
    async def _get_outcomes_summary(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/analytics/outcomes - Full outcome analytics summary."""
        from aragora.analytics.outcome_analytics import get_outcome_analytics

        period = query_params.get("period", "30d")
        analytics = get_outcome_analytics()

        consensus_rate = await analytics.get_consensus_rate(period=period)
        avg_rounds = await analytics.get_average_rounds(period=period)
        topics = await analytics.get_topic_distribution(period=period)

        return json_response(
            {
                "data": {
                    "period": period,
                    "consensus_rate": round(consensus_rate, 4),
                    "average_rounds": round(avg_rounds, 2),
                    "topic_distribution": topics,
                }
            }
        )

    @handle_errors("get consensus rate")
    async def _get_consensus_rate(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/analytics/outcomes/consensus-rate"""
        from aragora.analytics.outcome_analytics import get_outcome_analytics

        period = query_params.get("period", "30d")
        analytics = get_outcome_analytics()
        rate = await analytics.get_consensus_rate(period=period)

        return json_response(
            {
                "data": {
                    "period": period,
                    "consensus_rate": round(rate, 4),
                }
            }
        )

    @handle_errors("get average rounds")
    async def _get_average_rounds(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/analytics/outcomes/average-rounds"""
        from aragora.analytics.outcome_analytics import get_outcome_analytics

        period = query_params.get("period", "30d")
        analytics = get_outcome_analytics()
        avg = await analytics.get_average_rounds(period=period)

        return json_response(
            {
                "data": {
                    "period": period,
                    "average_rounds": round(avg, 2),
                }
            }
        )

    @handle_errors("get agent contributions")
    async def _get_contributions(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/analytics/outcomes/contributions"""
        from aragora.analytics.outcome_analytics import get_outcome_analytics

        period = query_params.get("period", "30d")
        analytics = get_outcome_analytics()
        contributions = await analytics.get_agent_contribution_scores(period=period)

        return json_response(
            {
                "data": {
                    "period": period,
                    "contributions": {
                        agent_id: contrib.to_dict() for agent_id, contrib in contributions.items()
                    },
                }
            }
        )

    @handle_errors("get quality trend")
    async def _get_quality_trend(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/analytics/outcomes/quality-trend"""
        from aragora.analytics.outcome_analytics import get_outcome_analytics

        period = query_params.get("period", "90d")
        analytics = get_outcome_analytics()
        trend = await analytics.get_decision_quality_trend(period=period)

        return json_response(
            {
                "data": {
                    "period": period,
                    "trend": [point.to_dict() for point in trend],
                }
            }
        )

    @handle_errors("get topic distribution")
    async def _get_topics(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/analytics/outcomes/topics"""
        from aragora.analytics.outcome_analytics import get_outcome_analytics

        period = query_params.get("period", "30d")
        analytics = get_outcome_analytics()
        topics = await analytics.get_topic_distribution(period=period)

        return json_response(
            {
                "data": {
                    "period": period,
                    "topics": topics,
                }
            }
        )

    @handle_errors("get debate outcome")
    async def _get_debate_outcome(self, debate_id: str) -> HandlerResult:
        """GET /api/analytics/outcomes/{debate_id}"""
        from aragora.analytics.outcome_analytics import get_outcome_analytics

        analytics = get_outcome_analytics()
        summary = await analytics.get_outcome_summary(debate_id)

        if summary is None:
            return error_response(f"Debate not found: {debate_id}", 404, code="NOT_FOUND")

        return json_response({"data": summary.to_dict()})


__all__ = [
    "OutcomeAnalyticsHandler",
    "OUTCOME_ANALYTICS_PERMISSION",
]
