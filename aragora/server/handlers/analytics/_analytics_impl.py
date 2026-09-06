"""
Analytics and metrics endpoint handlers.

Endpoints:
- GET /api/analytics/disagreements - Get disagreement statistics
- GET /api/analytics/role-rotation - Get role rotation statistics
- GET /api/analytics/early-stops - Get early stopping statistics
- GET /api/ranking/stats - Get ranking statistics
- GET /api/memory/stats - Get memory statistics

Cross-Pollination Endpoints (v2.0.3):
- GET /api/analytics/cross-pollination - Get aggregate cross-pollination stats
- GET /api/analytics/learning-efficiency?agent=&domain= - Get learning efficiency
- GET /api/analytics/voting-accuracy?agent= - Get voting accuracy stats
- GET /api/analytics/calibration?agent= - Get calibration stats
"""

from __future__ import annotations

__all__ = [
    "AnalyticsHandler",
]

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.rbac.decorators import require_permission  # noqa: F401

from aragora.config import (
    CACHE_TTL_ANALYTICS,
    CACHE_TTL_ANALYTICS_DEBATES,
    CACHE_TTL_ANALYTICS_MEMORY,
    CACHE_TTL_ANALYTICS_RANKING,
    DB_INSIGHTS_PATH,
)

logger = logging.getLogger(__name__)
from aragora.server.validation.query_params import safe_query_int
from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    ttl_cache,
)
from ..secure import ForbiddenError, SecureHandler, UnauthorizedError
from aragora.server.versioning.compat import strip_version_prefix
from ..utils.rate_limit import RateLimiter, get_client_ip

# Permission required for analytics access
ANALYTICS_PERMISSION = "analytics:read"

# Rate limiter for analytics endpoints (30 requests per minute - cached data)
_analytics_limiter = RateLimiter(requests_per_minute=30)


class AnalyticsHandler(SecureHandler):
    """Handler for analytics and metrics endpoints.

    Requires authentication and analytics:read permission (RBAC).
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/analytics/disagreements",
        "/api/analytics/role-rotation",
        "/api/analytics/early-stops",
        "/api/analytics/consensus-quality",
        "/api/ranking/stats",
        "/api/memory/stats",
        # Cross-pollination stats
        "/api/analytics/cross-pollination",
        "/api/analytics/learning-efficiency",
        "/api/analytics/voting-accuracy",
        "/api/analytics/calibration",
        # Note: /api/memory/tier-stats moved to MemoryHandler for more specific handling
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return strip_version_prefix(path) in self.ROUTES

    @handle_errors("analytics request routing")
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route analytics requests to appropriate methods with RBAC."""
        path = strip_version_prefix(path)
        logger.debug("Analytics request: %s", path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _analytics_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for analytics endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # Root analytics endpoint is public (dashboard index)
        if path == "/api/analytics":
            return json_response(
                {
                    "endpoints": [
                        "/api/analytics/disagreements",
                        "/api/analytics/role-rotation",
                        "/api/analytics/early-stops",
                        "/api/analytics/consensus-quality",
                        "/api/analytics/cross-pollination",
                        "/api/analytics/learning-efficiency",
                        "/api/analytics/voting-accuracy",
                        "/api/analytics/calibration",
                    ],
                    "description": "Analytics and metrics endpoints (authentication required for data access)",
                }
            )

        # RBAC: Require authentication and analytics:read permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, ANALYTICS_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Analytics access denied: %s", e)
            return error_response("Permission denied", 403)

        if path == "/api/analytics/disagreements":
            return self._get_disagreement_stats()

        if path == "/api/analytics/role-rotation":
            return self._get_role_rotation_stats()

        if path == "/api/analytics/early-stops":
            return self._get_early_stop_stats()

        if path == "/api/analytics/consensus-quality":
            return self._get_consensus_quality()

        if path == "/api/ranking/stats":
            return self._get_ranking_stats()

        if path == "/api/memory/stats":
            return self._get_memory_stats()

        # Cross-pollination endpoints
        if path == "/api/analytics/cross-pollination":
            return self._get_cross_pollination_stats()

        if path == "/api/analytics/learning-efficiency":
            return self._get_learning_efficiency_stats(query_params)

        if path == "/api/analytics/voting-accuracy":
            return self._get_voting_accuracy_stats(query_params)

        if path == "/api/analytics/calibration":
            return self._get_calibration_stats(query_params)

        return None

    @ttl_cache(
        ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_disagreement", skip_first=True
    )
    @handle_errors("disagreement stats retrieval")
    def _get_disagreement_stats(self) -> HandlerResult:
        """Get statistics about debate disagreements."""
        storage = self.get_storage()
        if not storage:
            return json_response({"stats": {}})

        debates = storage.list_debates(limit=100)

        stats: dict[str, Any] = {
            "total_debates": len(debates),
            "with_disagreements": 0,
            "unanimous": 0,
            "disagreement_types": {},
        }

        for debate in debates:
            debate_dict = debate if isinstance(debate, dict) else {}
            result = debate_dict.get("result", {})
            report = result.get("disagreement_report")
            if report:
                if report.get("unanimous_critiques"):
                    stats["with_disagreements"] += 1
                else:
                    stats["unanimous"] += 1

                dtype = result.get("uncertainty_metrics", {}).get("disagreement_type", "unknown")
                stats["disagreement_types"][dtype] = stats["disagreement_types"].get(dtype, 0) + 1

        logger.info(
            "Disagreement stats: %s debates, %s with disagreements",
            stats["total_debates"],
            stats["with_disagreements"],
        )
        return json_response({"stats": stats})

    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_roles", skip_first=True)
    @handle_errors("role rotation stats retrieval")
    def _get_role_rotation_stats(self) -> HandlerResult:
        """Get statistics about cognitive role rotation."""
        storage = self.get_storage()
        if not storage:
            return json_response({"stats": {}})

        debates = storage.list_debates(limit=100)

        stats: dict[str, Any] = {
            "total_debates": len(debates),
            "with_rotation": 0,
            "role_assignments": {},
        }

        for debate in debates:
            debate_dict = debate if isinstance(debate, dict) else {}
            messages = debate_dict.get("messages", [])
            for msg in messages:
                role = msg.get("cognitive_role", msg.get("role", "unknown"))
                stats["role_assignments"][role] = stats["role_assignments"].get(role, 0) + 1

        logger.info(
            "Role rotation stats: %s roles across %s debates",
            len(stats["role_assignments"]),
            stats["total_debates"],
        )
        return json_response({"stats": stats})

    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_early_stop", skip_first=True)
    @handle_errors("early stop stats retrieval")
    def _get_early_stop_stats(self) -> HandlerResult:
        """Get statistics about early debate stopping."""
        storage = self.get_storage()
        if not storage:
            return json_response({"stats": {}})

        debates = storage.list_debates(limit=100)

        stats = {
            "total_debates": len(debates),
            "early_stopped": 0,
            "full_rounds": 0,
            "average_rounds": 0.0,
        }

        total_rounds = 0
        for debate in debates:
            debate_dict = debate if isinstance(debate, dict) else {}
            result = debate_dict.get("result", {})
            rounds = result.get("rounds_used", 0)
            total_rounds += rounds

            if result.get("early_stopped"):
                stats["early_stopped"] += 1
            else:
                stats["full_rounds"] += 1

        if debates:
            stats["average_rounds"] = total_rounds / len(debates)

        logger.info(
            "Early stop stats: %s/%s early stopped", stats["early_stopped"], stats["total_debates"]
        )
        return json_response({"stats": stats})

    @ttl_cache(
        ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_consensus_quality", skip_first=True
    )
    @handle_errors("consensus quality stats retrieval")
    def _get_consensus_quality(self) -> HandlerResult:
        """Get consensus quality monitoring metrics.

        Tracks consensus confidence history across debates and detects declining trends.
        Returns quality metrics including:
        - confidence_history: Recent consensus confidence scores
        - trend: 'improving', 'stable', 'declining'
        - average_confidence: Mean confidence across recent debates
        - consensus_rate: Percentage of debates reaching consensus
        - quality_score: Overall quality score (0-100)
        - alert: Warning if quality is below threshold
        """
        storage = self.get_storage()
        if not storage:
            return json_response({"stats": {}, "quality_score": 0, "alert": None})

        debates = storage.list_debates(limit=50)

        # Extract confidence history
        confidence_history: list[dict] = []
        consensus_reached_count = 0

        for debate in debates:
            debate_dict = debate if isinstance(debate, dict) else {}
            result = debate_dict.get("result", {})
            confidence = result.get("confidence", 0.0)
            consensus = result.get("consensus_reached", False)
            debate_id = debate_dict.get("id", "")
            timestamp = debate_dict.get("timestamp", "")

            confidence_history.append(
                {
                    "debate_id": debate_id[:8] if debate_id else "",
                    "confidence": confidence,
                    "consensus_reached": consensus,
                    "timestamp": timestamp,
                }
            )

            if consensus:
                consensus_reached_count += 1

        # Calculate metrics
        total_debates = len(debates)
        if total_debates == 0:
            return json_response(
                {
                    "stats": {
                        "total_debates": 0,
                        "confidence_history": [],
                        "trend": "insufficient_data",
                        "average_confidence": 0.0,
                        "consensus_rate": 0.0,
                    },
                    "quality_score": 0,
                    "alert": None,
                }
            )

        confidences = [h["confidence"] for h in confidence_history]
        average_confidence = sum(confidences) / len(confidences)
        consensus_rate = consensus_reached_count / total_debates

        # Detect trend using simple linear regression
        trend = "stable"
        if len(confidences) >= 5:
            # Compare first half vs second half
            mid = len(confidences) // 2
            first_half_avg = sum(confidences[:mid]) / mid if mid > 0 else 0
            second_half_avg = sum(confidences[mid:]) / (len(confidences) - mid)

            diff = second_half_avg - first_half_avg
            if diff > 0.05:
                trend = "improving"
            elif diff < -0.05:
                trend = "declining"

        # Calculate quality score (0-100)
        # Weight: 50% average confidence, 30% consensus rate, 20% trend bonus
        trend_bonus = 10 if trend == "improving" else (-10 if trend == "declining" else 0)
        quality_score = min(
            100, max(0, int(average_confidence * 50 + consensus_rate * 30 + 20 + trend_bonus))
        )

        # Generate alert if quality is low
        alert = None
        if quality_score < 40:
            alert = {
                "level": "critical",
                "message": f"Consensus quality critically low ({quality_score}/100). Consider reviewing agent configurations.",
            }
        elif quality_score < 60:
            alert = {
                "level": "warning",
                "message": f"Consensus quality below target ({quality_score}/100). {trend.title()} trend detected.",
            }
        elif trend == "declining" and average_confidence < 0.7:
            alert = {
                "level": "info",
                "message": "Declining consensus trend detected. Monitor closely.",
            }

        return json_response(
            {
                "stats": {
                    "total_debates": total_debates,
                    "confidence_history": confidence_history[:20],  # Last 20 for UI
                    "trend": trend,
                    "average_confidence": round(average_confidence, 3),
                    "consensus_rate": round(consensus_rate, 3),
                    "consensus_reached_count": consensus_reached_count,
                },
                "quality_score": quality_score,
                "alert": alert,
            }
        )

    @ttl_cache(
        ttl_seconds=CACHE_TTL_ANALYTICS_RANKING, key_prefix="analytics_ranking", skip_first=True
    )
    @handle_errors("ranking stats retrieval")
    def _get_ranking_stats(self) -> HandlerResult:
        """Get ranking system statistics."""
        elo = self.get_elo_system()
        if not elo:
            return error_response("Ranking system not available", 503)

        leaderboard = elo.get_leaderboard(limit=100)

        stats = {
            "total_agents": len(leaderboard),
            "total_matches": sum(a.debates_count for a in leaderboard) if leaderboard else 0,
            "avg_elo": (
                sum(a.elo for a in leaderboard) / len(leaderboard) if leaderboard else 1500
            ),
            "top_agent": leaderboard[0].agent_name if leaderboard else None,
            "elo_range": {
                "min": min(a.elo for a in leaderboard) if leaderboard else 1500,
                "max": max(a.elo for a in leaderboard) if leaderboard else 1500,
            },
        }

        return json_response({"stats": stats})

    @ttl_cache(
        ttl_seconds=CACHE_TTL_ANALYTICS_DEBATES, key_prefix="analytics_debates", skip_first=True
    )
    def _get_cached_debates(self, limit: int = 100) -> list[Any]:
        """Cached helper for retrieving debates."""
        storage = self.get_storage()
        if not storage:
            return []
        try:
            return storage.list_debates(limit=limit)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
            logger.warning("Failed to list debates for analytics: %s: %s", type(e).__name__, e)
            return []

    @ttl_cache(
        ttl_seconds=CACHE_TTL_ANALYTICS_MEMORY, key_prefix="analytics_memory", skip_first=True
    )
    @handle_errors("memory stats retrieval")
    def _get_memory_stats(self) -> HandlerResult:
        """Get memory system statistics."""
        nomic_dir = self.get_nomic_dir()
        if not nomic_dir:
            return json_response({"stats": {}})

        stats = {
            "embeddings_db": False,
            "insights_db": False,
            "continuum_memory": False,
        }

        # Check for database files
        if (nomic_dir / "debate_embeddings.db").exists():
            stats["embeddings_db"] = True

        if (nomic_dir / DB_INSIGHTS_PATH).exists():
            stats["insights_db"] = True

        if (nomic_dir / "continuum_memory.db").exists():
            stats["continuum_memory"] = True

        return json_response({"stats": stats})

    # ==========================================================================
    # Cross-Pollination Stats
    # ==========================================================================

    @ttl_cache(
        ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_cross_pollination", skip_first=True
    )
    @handle_errors("cross-pollination stats retrieval")
    def _get_cross_pollination_stats(self) -> HandlerResult:
        """Get aggregate cross-pollination statistics.

        Returns summary of all cross-pollination integrations:
        - Calibration adjustments
        - Learning bonuses
        - Voting accuracy
        - Adaptive rounds
        - RLM cache performance
        """
        stats: dict[str, Any] = {
            "calibration": {"enabled": False, "adjustments": 0},
            "learning": {"enabled": False, "bonuses_applied": 0},
            "voting_accuracy": {"enabled": False, "updates": 0},
            "adaptive_rounds": {"enabled": False, "changes": 0},
            "rlm_cache": {"enabled": False, "hits": 0, "misses": 0, "hit_rate": 0.0},
        }

        # Try to get RLM cache stats
        try:
            from aragora.rlm.bridge import RLMHierarchyCache

            cache = RLMHierarchyCache()
            cache_stats = cache.get_stats()
            stats["rlm_cache"] = {
                "enabled": True,
                "hits": cache_stats.get("hits", 0),
                "misses": cache_stats.get("misses", 0),
                "hit_rate": cache_stats.get("hit_rate", 0.0),
            }
        except ImportError:
            pass

        # Try to get ELO system stats for learning and voting
        try:
            from aragora.ranking.elo import get_elo_store

            get_elo_store()
            stats["learning"]["enabled"] = True
            stats["voting_accuracy"]["enabled"] = True
            stats["calibration"]["enabled"] = True
        except ImportError:
            pass

        logger.info("Cross-pollination stats retrieved")
        return json_response({"stats": stats, "version": "2.0.3"})

    @handle_errors("learning efficiency stats retrieval")
    def _get_learning_efficiency_stats(self, query_params: dict) -> HandlerResult:
        """Get learning efficiency statistics for agents.

        Query params:
            agent: Optional agent name filter
            domain: Optional domain filter
            limit: Max agents to return (default 20)
        """
        agent = query_params.get("agent", [None])[0]
        domain = query_params.get("domain", ["general"])[0]
        limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=1000)

        try:
            from aragora.ranking.elo import get_elo_store

            elo = get_elo_store()
        except ImportError:
            return json_response({"error": "ELO system not available", "agents": []})

        if agent:
            # Get specific agent
            efficiency = elo.get_learning_efficiency(agent, domain=domain)
            return json_response({"agent": agent, "domain": domain, "efficiency": efficiency})

        # Get top agents by learning efficiency (batch query for performance)
        leaderboard = elo.get_leaderboard(limit=limit)
        agent_names = [entry.agent_name for entry in leaderboard]

        # Batch fetch learning efficiency for all agents at once
        efficiency_batch = elo.get_learning_efficiency_batch(agent_names, domain=domain)
        agents_data = [
            {"agent": name, "efficiency": efficiency_batch.get(name, {})} for name in agent_names
        ]

        return json_response({"domain": domain, "agents": agents_data})

    @handle_errors("voting accuracy stats retrieval")
    def _get_voting_accuracy_stats(self, query_params: dict) -> HandlerResult:
        """Get voting accuracy statistics for agents.

        Query params:
            agent: Optional agent name filter
            limit: Max agents to return (default 20)
        """
        agent = query_params.get("agent", [None])[0]
        limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=1000)

        try:
            from aragora.ranking.elo import get_elo_store

            elo = get_elo_store()
        except ImportError:
            return json_response({"error": "ELO system not available", "agents": []})

        if agent:
            accuracy = elo.get_voting_accuracy(agent)
            return json_response({"agent": agent, "accuracy": accuracy})

        # Get top agents by voting accuracy (batch query for performance)
        leaderboard = elo.get_leaderboard(limit=limit)
        agent_names = [entry.agent_name for entry in leaderboard]

        # Batch fetch voting accuracy for all agents at once
        accuracy_batch = elo.get_voting_accuracy_batch(agent_names)
        agents_data = [
            {"agent": name, "accuracy": accuracy_batch.get(name, {})} for name in agent_names
        ]

        return json_response({"agents": agents_data})

    @handle_errors("calibration stats retrieval")
    def _get_calibration_stats(self, query_params: dict) -> HandlerResult:
        """Get calibration statistics for agents.

        Query params:
            agent: Optional agent name filter
            limit: Max agents to return (default 20)
        """
        agent = query_params.get("agent", [None])[0]
        limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=1000)

        try:
            from aragora.ranking.elo import get_elo_store

            elo = get_elo_store()
        except ImportError:
            return json_response({"error": "ELO system not available", "agents": []})

        # Try to get calibration tracker
        try:
            from aragora.ranking.calibration import CalibrationTracker

            tracker = CalibrationTracker()
        except ImportError:
            tracker = None

        if agent:
            # Get specific agent calibration
            if tracker:
                summary = tracker.get_calibration_summary(agent)
                if summary:
                    return json_response(
                        {
                            "agent": agent,
                            "calibration": {
                                "total_predictions": summary.total_predictions,
                                "temperature": summary.temperature,
                                "scaling_factor": getattr(summary, "scaling_factor", 1.0),
                            },
                        }
                    )
            return json_response({"agent": agent, "calibration": None})

        # Get calibration for top agents
        leaderboard = elo.get_leaderboard(limit=limit)
        agents_data = []
        for entry in leaderboard:
            name = entry.agent_name
            cal_data = None
            if tracker:
                summary = tracker.get_calibration_summary(name)
                if summary:
                    cal_data = {
                        "total_predictions": summary.total_predictions,
                        "temperature": summary.temperature,
                    }
            agents_data.append({"agent": name, "calibration": cal_data})

        return json_response({"agents": agents_data})
