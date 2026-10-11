"""Agent rankings and leaderboard endpoint methods (AgentRankingsMixin).

Extracted from agents.py to reduce file size.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aragora.config import (
    CACHE_TTL_CALIBRATION_LB,
    CACHE_TTL_RECENT_MATCHES,
    ELO_INITIAL_RATING,
)
from aragora.persistence.db_config import DatabaseType, get_db_path

if TYPE_CHECKING:
    from aragora.ranking.elo import EloSystem

from ..base import (
    HandlerResult,
    agent_to_dict,
    error_response,
    get_agent_name,
    json_response,
    safe_error_message,
    ttl_cache,
)
from ..openapi_decorator import api_endpoint
from ..utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)


class AgentRankingsMixin:
    """Mixin providing agent ranking and leaderboard endpoints.

    Expects the composing class to provide:
    - get_nomic_dir() -> Path | None
    - get_elo_system() -> EloSystem | None

    These are provided by BaseHandler.
    """

    if TYPE_CHECKING:

        def get_nomic_dir(self) -> Path | None: ...
        def get_elo_system(self) -> EloSystem | None: ...

    @api_endpoint(
        method="GET",
        path="/api/v1/leaderboard",
        summary="Get agent rankings leaderboard",
        tags=["Agents"],
    )
    @rate_limit(requests_per_minute=30, limiter_name="leaderboard")
    def _get_leaderboard(self, limit: int, domain: str | None) -> HandlerResult:
        """Get agent leaderboard with consistency scores (batched to avoid N+1)."""
        elo = self.get_elo_system()
        if not elo:
            return error_response("ELO system not available", 503)

        try:
            # Use cached leaderboard when available (no domain filter needed for cache)
            if domain is None:
                rankings = elo.get_cached_leaderboard(limit=min(limit, 50))
            else:
                rankings = elo.get_leaderboard(limit=min(limit, 50), domain=domain)

            # Batch fetch consistency scores (uses 3 queries instead of 3*N)
            consistency_map = {}
            try:
                from aragora.insights.flip_detector import FlipDetector

                nomic_dir = self.get_nomic_dir()
                if nomic_dir:
                    detector = FlipDetector(str(get_db_path(DatabaseType.POSITIONS, nomic_dir)))
                    # Extract all agent names first
                    agent_names = []
                    for agent in rankings:
                        name = get_agent_name(agent)
                        if name:
                            agent_names.append(name)

                    # Batch fetch all consistency scores at once
                    if agent_names:
                        try:
                            scores = detector.get_agents_consistency_batch(agent_names)
                            for agent_name, score in scores.items():
                                total_positions = max(score.total_positions, 1)
                                consistency = 1.0 - (score.total_flips / total_positions)
                                consistency_map[agent_name] = {
                                    "consistency": round(consistency, 3),
                                    "consistency_class": (
                                        "high"
                                        if consistency >= 0.8
                                        else "medium"
                                        if consistency >= 0.6
                                        else "low"
                                    ),
                                }
                        except (KeyError, ValueError, AttributeError, OSError) as e:
                            # Fallback: set default consistency for all agents
                            logger.warning(
                                "Consistency detection failed, using fallback: %s: %s",
                                type(e).__name__,
                                e,
                            )
                            for name in agent_names:
                                consistency_map[name] = {
                                    "consistency": 1.0,
                                    "consistency_class": "high",
                                    "degraded": True,
                                    "degraded_reason": "Consistency detection unavailable",
                                }
            except ImportError:
                # FlipDetector not available - set degraded flag so clients know
                logger.debug("FlipDetector import failed - consistency scores unavailable")
                for agent in rankings:
                    name = get_agent_name(agent)
                    if name:
                        consistency_map[name] = {
                            "consistency": None,
                            "consistency_class": "unknown",
                            "degraded": True,
                            "degraded_reason": "FlipDetector module not available",
                        }

            # Enhance rankings with consistency data
            enhanced_rankings = []
            for agent in rankings:
                agent_dict = agent_to_dict(agent)
                agent_name = agent_dict.get("name", "unknown")

                if agent_name in consistency_map:
                    agent_dict.update(consistency_map[agent_name])

                enhanced_rankings.append(agent_dict)

            return json_response({"rankings": enhanced_rankings, "agents": enhanced_rankings})
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            return error_response(safe_error_message(e, "get leaderboard"), 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/calibration/leaderboard",
        summary="Get calibration leaderboard",
        tags=["Agents"],
    )
    @ttl_cache(ttl_seconds=CACHE_TTL_CALIBRATION_LB, key_prefix="calibration_lb", skip_first=True)
    def _get_calibration_leaderboard(self, limit: int) -> HandlerResult:
        """Get calibration leaderboard."""
        elo = self.get_elo_system()
        if not elo:
            return error_response("ELO system not available", 503)

        try:
            # Get calibration scores from ELO system
            rankings = elo.get_leaderboard(limit=min(limit, 50))
            # Add calibration data if available
            return json_response({"rankings": rankings})
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            return error_response(safe_error_message(e, "get calibration leaderboard"), 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/matches/recent",
        summary="Get recent agent matches",
        tags=["Agents"],
    )
    @ttl_cache(ttl_seconds=CACHE_TTL_RECENT_MATCHES, key_prefix="recent_matches", skip_first=True)
    def _get_recent_matches(self, limit: int, loop_id: str | None) -> HandlerResult:
        """Get recent matches (uses JSON snapshot cache for fast reads)."""
        elo = self.get_elo_system()
        if not elo:
            return error_response("ELO system not available", 503)

        try:
            # Use cached matches from JSON snapshot (avoids SQLite locking)
            if hasattr(elo, "get_cached_recent_matches"):
                matches = elo.get_cached_recent_matches(limit=min(limit, 50))
            else:
                matches = elo.get_recent_matches(limit=min(limit, 50))
            return json_response({"matches": matches})
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            return error_response(safe_error_message(e, "get recent matches"), 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/agent/compare",
        summary="Compare multiple agents",
        tags=["Agents"],
    )
    def _compare_agents(self, agents: list[str]) -> HandlerResult:
        """Compare multiple agents using batch rating lookups."""
        if len(agents) < 2:
            return error_response("Need at least 2 agents to compare", 400)

        elo = self.get_elo_system()
        if not elo:
            return error_response("ELO system not available", 503)

        try:
            # Limit to 5 agents and batch fetch ratings in single query
            limited_agents = agents[:5]
            ratings_map = elo.get_ratings_batch(limited_agents)

            profiles = []
            for agent in limited_agents:
                rating = ratings_map.get(agent) or ELO_INITIAL_RATING
                stats = elo.get_agent_stats(agent) if hasattr(elo, "get_agent_stats") else {}
                profiles.append(
                    {
                        "name": agent,
                        "rating": rating,
                        **stats,
                    }
                )

            # Get head-to-head if exactly 2 agents
            head_to_head = None
            if len(agents) == 2:
                try:
                    h2h = elo.get_head_to_head(agents[0], agents[1])
                    head_to_head = h2h
                except Exception as e:  # noqa: BLE001 - graceful degradation, return comparison without h2h
                    logger.warning(
                        "Head-to-head lookup failed for %s vs %s: %s: %s",
                        agents[0],
                        agents[1],
                        type(e).__name__,
                        e,
                    )

            return json_response(
                {
                    "agents": profiles,
                    "head_to_head": head_to_head,
                }
            )
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            return error_response(safe_error_message(e, "comparison"), 500)
