"""
Agent performance analytics endpoint methods for AnalyticsMetricsHandler.

Extracted from _analytics_metrics_impl.py for modularity.
Provides agent leaderboard, comparison, individual performance, and trends endpoints.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aragora.config import CACHE_TTL_ANALYTICS
from aragora.server.validation.query_params import safe_query_int

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
)

logger = logging.getLogger(__name__)


class AgentAnalyticsMixin:
    """Mixin providing agent performance analytics endpoint methods."""

    if TYPE_CHECKING:
        get_elo_system: Any

    # =========================================================================
    # Agent Performance Endpoints
    # =========================================================================

    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_agents_leaderboard")
    @handle_errors("get agents leaderboard")
    def _get_agents_leaderboard(self, query_params: dict) -> HandlerResult:
        """
        Get agent leaderboard with ELO rankings and win rates.

        GET /api/v1/analytics/agents/leaderboard

        Query params:
        - limit: Maximum agents to return (default 20)
        - domain: Filter by domain (optional)

        Response:
        {
            "leaderboard": [
                {
                    "rank": 1,
                    "agent_name": "claude",
                    "elo": 1650,
                    "wins": 120,
                    "losses": 30,
                    "draws": 10,
                    "win_rate": 75.0,
                    "games_played": 160,
                    "calibration_score": 0.85
                },
                ...
            ],
            "total_agents": 15,
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        limit = safe_query_int(query_params, "limit", default=20, max_val=100)

        domain = query_params.get("domain")

        elo_system = self.get_elo_system()
        if not elo_system:
            return json_response(
                {
                    "leaderboard": [],
                    "total_agents": 0,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Get leaderboard from ELO system
        agents = elo_system.get_leaderboard(limit=limit, domain=domain)

        leaderboard = []
        for rank, agent in enumerate(agents, 1):
            agent_data = {
                "rank": rank,
                "agent_name": agent.agent_name,
                "elo": round(agent.elo, 0),
                "wins": agent.wins,
                "losses": agent.losses,
                "draws": agent.draws,
                "win_rate": round(agent.win_rate * 100, 1),
                "games_played": agent.games_played,
            }

            # Add calibration score if available
            if hasattr(agent, "calibration_score"):
                agent_data["calibration_score"] = round(agent.calibration_score, 2)

            leaderboard.append(agent_data)

        # Get total agent count
        total_agents = len(elo_system.list_agents())

        return json_response(
            {
                "leaderboard": leaderboard,
                "total_agents": total_agents,
                "domain": domain,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    @handle_errors("get agent performance")
    def _get_agent_performance(self, agent_id: str, query_params: dict) -> HandlerResult:
        """
        Get individual agent performance statistics.

        GET /api/v1/analytics/agents/{agent_id}/performance

        Query params:
        - time_range: Time range filter (7d, 30d, 90d, 365d, all) - default 30d

        Response:
        {
            "agent_id": "claude",
            "agent_name": "Claude",
            "time_range": "30d",
            "elo": 1650,
            "elo_change": +25,
            "rank": 1,
            "wins": 120,
            "losses": 30,
            "draws": 10,
            "win_rate": 75.0,
            "games_played": 160,
            "consensus_contribution_rate": 85.0,
            "domain_performance": {
                "security": {"elo": 1700, "wins": 45, "losses": 8},
                "performance": {"elo": 1620, "wins": 30, "losses": 12}
            },
            "recent_matches": [...],
            "elo_history": [...],
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        time_range = query_params.get("time_range", "30d")
        if time_range not in VALID_TIME_RANGES:
            time_range = "30d"

        elo_system = self.get_elo_system()
        if not elo_system:
            return error_response("ELO system not available", 503)

        # Get agent rating
        try:
            agent = elo_system.get_rating(agent_id)
        except (ValueError, KeyError):
            return error_response(f"Agent not found: {agent_id}", 404)

        # Get ELO history
        elo_history = elo_system.get_elo_history(agent_id, limit=50)

        # Calculate ELO change
        elo_change = 0.0
        if len(elo_history) >= 2:
            elo_change = agent.elo - elo_history[-1][1]

        # Get recent matches
        recent_matches = elo_system.get_recent_matches(limit=10)
        agent_matches = [m for m in recent_matches if agent_id in m.get("participants", [])]

        # Get rank
        leaderboard = elo_system.get_leaderboard(limit=100)
        rank = None
        for idx, a in enumerate(leaderboard, 1):
            if a.agent_name == agent_id:
                rank = idx
                break

        # Build response
        response = {
            "agent_id": agent_id,
            "agent_name": agent.agent_name,
            "time_range": time_range,
            "elo": round(agent.elo, 0),
            "elo_change": round(elo_change, 0),
            "rank": rank,
            "wins": agent.wins,
            "losses": agent.losses,
            "draws": agent.draws,
            "win_rate": round(agent.win_rate * 100, 1),
            "games_played": agent.games_played,
            "debates_count": agent.debates_count,
        }

        # Add domain performance if available
        if agent.domain_elos:
            response["domain_performance"] = {
                domain: {"elo": round(elo, 0)} for domain, elo in agent.domain_elos.items()
            }

        # Add calibration metrics if available
        if hasattr(agent, "calibration_score"):
            response["calibration_score"] = round(agent.calibration_score, 2)
        if hasattr(agent, "calibration_accuracy"):
            response["calibration_accuracy"] = round(agent.calibration_accuracy, 2)

        # Add recent matches
        response["recent_matches"] = agent_matches[:5]

        # Add ELO history for charting
        response["elo_history"] = [
            {"timestamp": ts, "elo": round(elo, 0)} for ts, elo in elo_history
        ]

        response["generated_at"] = datetime.now(timezone.utc).isoformat()

        return json_response(response)

    @handle_errors("get agents comparison")
    def _get_agents_comparison(self, query_params: dict) -> HandlerResult:
        """
        Compare multiple agents.

        GET /api/v1/analytics/agents/comparison

        Query params:
        - agents: Comma-separated list of agent names (required)

        Response:
        {
            "agents": ["claude", "gpt-4", "gemini"],
            "comparison": [
                {
                    "agent_name": "claude",
                    "elo": 1650,
                    "wins": 120,
                    "losses": 30,
                    "win_rate": 75.0,
                    "calibration_score": 0.85
                },
                ...
            ],
            "head_to_head": {
                "claude_vs_gpt-4": {"claude_wins": 15, "gpt-4_wins": 10, "draws": 5},
                ...
            },
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        agents_param = query_params.get("agents", "")
        if not agents_param:
            return error_response(
                "agents parameter is required (comma-separated list)",
                400,
            )

        agent_names = [a.strip() for a in agents_param.split(",") if a.strip()]
        if len(agent_names) < 2:
            return error_response(
                "At least 2 agents required for comparison",
                400,
            )
        if len(agent_names) > 10:
            return error_response(
                "Maximum 10 agents allowed for comparison",
                400,
            )

        elo_system = self.get_elo_system()
        if not elo_system:
            return error_response("ELO system not available", 503)

        # Get ratings for all agents
        comparison = []
        for agent_name in agent_names:
            try:
                agent = elo_system.get_rating(agent_name)
                agent_data = {
                    "agent_name": agent.agent_name,
                    "elo": round(agent.elo, 0),
                    "wins": agent.wins,
                    "losses": agent.losses,
                    "draws": agent.draws,
                    "win_rate": round(agent.win_rate * 100, 1),
                    "games_played": agent.games_played,
                }
                if hasattr(agent, "calibration_score"):
                    agent_data["calibration_score"] = round(agent.calibration_score, 2)
                comparison.append(agent_data)
            except (ValueError, KeyError):
                comparison.append(
                    {
                        "agent_name": agent_name,
                        "error": "Agent not found",
                    }
                )

        # Get head-to-head stats
        head_to_head = {}
        for i, agent_a in enumerate(agent_names):
            for agent_b in agent_names[i + 1 :]:
                try:
                    h2h = elo_system.get_head_to_head(agent_a, agent_b)
                    key = f"{agent_a}_vs_{agent_b}"
                    head_to_head[key] = {
                        f"{agent_a}_wins": h2h.get("a_wins", 0),
                        f"{agent_b}_wins": h2h.get("b_wins", 0),
                        "draws": h2h.get("draws", 0),
                        "total_matches": h2h.get("total", 0),
                    }
                except (ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                    logger.debug(
                        "Error computing head-to-head for %s vs %s: %s", agent_a, agent_b, e
                    )

        return json_response(
            {
                "agents": agent_names,
                "comparison": comparison,
                "head_to_head": head_to_head,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_agents_trends")
    @handle_errors("get agents trends")
    def _get_agents_trends(self, query_params: dict) -> HandlerResult:
        """
        Get agent performance trends over time.

        GET /api/v1/analytics/agents/trends

        Query params:
        - agents: Comma-separated list of agent names (optional, defaults to top 5)
        - time_range: Time range filter (7d, 30d, 90d, 365d, all) - default 30d
        - granularity: Aggregation granularity (daily, weekly, monthly) - default daily

        Response:
        {
            "agents": ["claude", "gpt-4"],
            "time_range": "30d",
            "granularity": "daily",
            "trends": {
                "claude": [
                    {"period": "2026-01-01", "elo": 1640, "games": 5},
                    ...
                ],
                "gpt-4": [...]
            },
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        time_range = query_params.get("time_range", "30d")
        if time_range not in VALID_TIME_RANGES:
            time_range = "30d"

        granularity = query_params.get("granularity", "daily")
        if granularity not in VALID_GRANULARITIES:
            granularity = "daily"

        elo_system = self.get_elo_system()
        if not elo_system:
            return error_response("ELO system not available", 503)

        # Get agents to track
        agents_param = query_params.get("agents", "")
        if agents_param:
            agent_names = [a.strip() for a in agents_param.split(",") if a.strip()]
        else:
            # Default to top 5 agents
            leaderboard = elo_system.get_leaderboard(limit=5)
            agent_names = [a.agent_name for a in leaderboard]

        # Get ELO history for each agent
        trends: dict[str, list[dict[str, Any]]] = {}

        for agent_name in agent_names[:10]:  # Limit to 10 agents
            try:
                history = elo_system.get_elo_history(agent_name, limit=100)

                # Convert to time series
                data_points = []
                for timestamp, elo in history:
                    try:
                        if isinstance(timestamp, str):
                            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        else:
                            dt = timestamp

                        # Generate period key
                        if granularity == "daily":
                            period = dt.strftime("%Y-%m-%d")
                        elif granularity == "weekly":
                            period = dt.strftime("%Y-W%W")
                        else:
                            period = dt.strftime("%Y-%m")

                        data_points.append(
                            {
                                "period": period,
                                "elo": round(elo, 0),
                                "timestamp": dt.isoformat(),
                            }
                        )
                    except (ValueError, TypeError):
                        continue

                # Group by period (take latest ELO for each period)
                period_data: dict[str, dict[str, Any]] = {}
                for dp in data_points:
                    period = str(dp["period"])
                    if (
                        period not in period_data
                        or dp["timestamp"] > period_data[period]["timestamp"]
                    ):
                        period_data[period] = dp

                trends[agent_name] = sorted(
                    [{"period": k, "elo": v["elo"]} for k, v in period_data.items()],
                    key=lambda x: x["period"],
                )
            except (ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                logger.warning("Failed to get trends for agent %s: %s", agent_name, e)
                trends[agent_name] = []

        return json_response(
            {
                "agents": agent_names,
                "time_range": time_range,
                "granularity": granularity,
                "trends": trends,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
