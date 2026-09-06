"""
Agent recommendation and leaderboard endpoints.

Provides:
- GET /api/v1/agents/recommend?domain=financial&limit=5
  Top agents with name, ELO, calibration, domain expertise, estimated cost.
- GET /api/v1/agents/leaderboard with domain filter
  Agent leaderboard with ELO rankings and optional domain filtering.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aragora.models.pricing_mirror import input_cost_per_1k_rows
from aragora.rbac.decorators import require_permission
from aragora.server.versioning.compat import strip_version_prefix

if TYPE_CHECKING:
    from aragora.ranking.elo import EloSystem

from ..base import (
    SAFE_ID_PATTERN,
    BaseHandler,
    HandlerResult,
    agent_to_dict,
    error_response,
    get_agent_name,
    get_int_param,
    get_string_param,
    json_response,
    validate_path_segment,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter: 30 requests per minute (cached data)
_recommend_limiter = RateLimiter(requests_per_minute=30)

# Cost estimates by agent type (USD per 1K INPUT tokens).
#
# The hand-written rows are the historical per-FAMILY labels the ELO
# leaderboard actually reports agents under ("claude", "gpt4", "gemini",
# ...) and are kept verbatim, including their position: ``_estimated_cost``
# falls back to PREFIX matching in iteration order, so a name like
# "claude-3-opus" must still reach the "claude" row. The generated rows are
# appended after them, one per spelling of every active catalog row, so an
# agent reported under its full frontier model id gets its real rate instead
# of ``None`` (2026-09-04 controller ruling, wave 3).
_LEGACY_AGENT_COST_ESTIMATES: dict[str, float] = {
    "claude": 0.015,
    "gpt4": 0.03,
    "gpt-4": 0.03,
    "gpt-4o": 0.005,
    "gemini": 0.00125,
    "grok": 0.005,
    "codex": 0.03,
    "deepseek": 0.002,
    "mistral": 0.004,
    "llama": 0.001,
    "qwen": 0.001,
}

_AGENT_COST_ESTIMATES: dict[str, float] = {
    **_LEGACY_AGENT_COST_ESTIMATES,
    **input_cost_per_1k_rows(),
}


class AgentRecommendationHandler(BaseHandler):
    """Handler for agent recommendation and leaderboard endpoints."""

    ROUTES = ["/api/v1/agents/recommend", "/api/v1/agents/leaderboard"]

    def __init__(self, ctx: dict[str, Any] | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        cleaned = strip_version_prefix(path)
        return cleaned in ("/api/agents/recommend", "/api/agents/leaderboard")

    @require_permission("agents:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests."""
        cleaned = strip_version_prefix(path)

        # Rate limit
        client_ip = get_client_ip(handler)
        if not _recommend_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if cleaned == "/api/agents/recommend":
            return self._get_recommendations(query_params)
        elif cleaned == "/api/agents/leaderboard":
            return self._get_leaderboard(query_params)

        return None

    def _get_recommendations(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get top agent recommendations for a domain."""
        domain = get_string_param(query_params, "domain")
        limit = get_int_param(query_params, "limit", 5)
        limit = max(1, min(limit, 20))

        if domain:
            is_valid, err = validate_path_segment(domain, "domain", SAFE_ID_PATTERN)
            if not is_valid:
                return error_response(err, 400)

        elo: EloSystem | None = self.get_elo_system()
        if not elo:
            return error_response("ELO system not available", 503)

        try:
            if domain:
                agents = elo.get_top_agents_for_domain(domain=domain, limit=limit)
            else:
                agents = elo.get_leaderboard(limit=limit)

            recommendations = []
            for agent in agents:
                agent_dict = agent_to_dict(agent)
                name = get_agent_name(agent) or "unknown"

                # Add calibration score if available
                calibration = getattr(agent, "calibration_score", None)
                if calibration is not None:
                    agent_dict["calibration_score"] = round(calibration, 3)

                # Add domain expertise indicator
                if domain:
                    domain_elo = getattr(agent, "domain_elo", None)
                    agent_dict["domain"] = domain
                    if domain_elo is not None:
                        agent_dict["domain_elo"] = domain_elo

                # Add estimated cost
                name_lower = name.lower()
                cost = _AGENT_COST_ESTIMATES.get(name_lower)
                if cost is None:
                    # Try prefix matching
                    for key, val in _AGENT_COST_ESTIMATES.items():
                        if name_lower.startswith(key):
                            cost = val
                            break
                agent_dict["estimated_cost_per_1k_tokens"] = cost

                # Add introspection if available
                try:
                    from aragora.introspection.api import get_agent_introspection

                    snapshot = get_agent_introspection(name)
                    if snapshot:
                        agent_dict["strengths"] = getattr(snapshot, "strengths", [])
                        agent_dict["expertise"] = getattr(snapshot, "expertise_areas", [])
                except ImportError:
                    pass

                recommendations.append(agent_dict)

            return json_response(
                {
                    "recommendations": recommendations,
                    "domain": domain,
                    "count": len(recommendations),
                }
            )
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.error("Agent recommendation failed: %s: %s", type(e).__name__, e)
            return error_response("Failed to get agent recommendations", 500)

    def _get_leaderboard(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get agent leaderboard with optional domain filter."""
        domain = get_string_param(query_params, "domain")
        limit = get_int_param(query_params, "limit", 20)
        limit = max(1, min(limit, 50))

        if domain:
            is_valid, err = validate_path_segment(domain, "domain", SAFE_ID_PATTERN)
            if not is_valid:
                return error_response(err, 400)

        elo: EloSystem | None = self.get_elo_system()
        if not elo:
            return error_response("ELO system not available", 503)

        try:
            if domain:
                rankings = elo.get_leaderboard(limit=limit, domain=domain)
            else:
                rankings = (
                    elo.get_cached_leaderboard(limit=limit)
                    if hasattr(elo, "get_cached_leaderboard")
                    else elo.get_leaderboard(limit=limit)
                )

            agents = []
            for rank, agent in enumerate(rankings, 1):
                agent_dict = agent_to_dict(agent)
                agent_dict["rank"] = rank
                agents.append(agent_dict)

            stats = elo.get_stats() if hasattr(elo, "get_stats") else {}

            return json_response(
                {
                    "leaderboard": agents,
                    "count": len(agents),
                    "domain": domain,
                    "stats": {
                        "total_agents": stats.get("total_agents", len(agents)),
                        "total_matches": stats.get("total_matches", 0),
                        "mean_elo": stats.get("avg_elo", stats.get("mean_elo", 1500)),
                    },
                }
            )
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.error("Leaderboard fetch failed: %s: %s", type(e).__name__, e)
            return error_response("Failed to get leaderboard", 500)
