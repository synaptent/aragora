"""
HTTP API handlers for the streaming server.

This module contains the StreamAPIHandlersMixin class which provides all HTTP
API endpoint handlers for the AiohttpUnifiedServer. The mixin pattern keeps
the handler logic separate from the server infrastructure.

Handlers are organized by domain:
- Leaderboard and matches (ELO system)
- Insights and flips (InsightStore, FlipDetector)
- Tournaments (TournamentManager)
- Agent analysis (consistency, network)
- Memory and laboratory (tier stats, emergent traits)
- Graph visualization (ArgumentCartographer)
- Replays (debate replay generation)
- Debate control (start debate)
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

import aiohttp.web as web

from aragora.server.validation import safe_query_float, safe_query_int

if TYPE_CHECKING:
    from aragora.agents.personas import PersonaManager
    from aragora.debate.embeddings import DebateEmbeddingsDatabase
    from aragora.insights.flip_detector import FlipDetector
    from aragora.insights.store import InsightStore
    from aragora.ranking.elo import EloSystem
    from aragora.server.stream.emitter import AudienceInbox, SyncEventEmitter
    from aragora.visualization.mapper import ArgumentCartographer

logger = logging.getLogger(__name__)


def _load_json_object(path: Path, *, context: str) -> dict[str, Any]:
    """Load a JSON object from disk, degrading malformed shapes to {}."""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse %s %s: %s", context, path, e)
        return {}

    if not isinstance(data, dict):
        logger.warning("Ignoring non-object %s %s", context, path)
        return {}

    return data


def _parse_json_object_line(line: str, *, source: Path) -> dict[str, Any] | None:
    """Parse one JSONL line, returning only object-shaped entries."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse event line from %s: %s", source, e)
        return None

    if not isinstance(data, dict):
        logger.warning("Skipping non-object replay event in %s", source)
        return None

    return data


class StreamAPIHandlersMixin:
    """
    Mixin class providing HTTP API handlers for the streaming server.

    This mixin expects the following attributes/methods from the parent class:
    - nomic_dir: Path | None
    - elo_system: EloSystem | None
    - insight_store: InsightStore | None
    - flip_detector: FlipDetector | None
    - persona_manager: PersonaManager | None
    - debate_embeddings: DebateEmbeddingsDatabase | None
    - active_loops: dict[str, LoopInstance]
    - _active_loops_lock: threading.Lock
    - cartographers: dict[str, ArgumentCartographer]
    - _cartographers_lock: threading.Lock
    - audience_inbox: AudienceInbox
    - emitter: SyncEventEmitter
    - _cors_headers(origin: str | None) -> dict
    """

    # Type stubs for attributes expected from the parent class
    nomic_dir: Path | None
    elo_system: EloSystem | None
    insight_store: InsightStore | None
    flip_detector: FlipDetector | None
    persona_manager: PersonaManager | None
    debate_embeddings: DebateEmbeddingsDatabase | None
    active_loops: dict[str, Any]
    _active_loops_lock: threading.Lock
    cartographers: dict[str, ArgumentCartographer]
    _cartographers_lock: threading.Lock
    audience_inbox: AudienceInbox | None
    emitter: SyncEventEmitter
    _cors_headers: Callable[[str | None], dict[str, str]]

    # =========================================================================
    # CORS Handler
    # =========================================================================

    async def _handle_options(self, request) -> web.Response:
        """Handle CORS preflight requests."""

        origin = request.headers.get("Origin")
        return web.Response(status=204, headers=self._cors_headers(origin))

    # =========================================================================
    # Leaderboard and Matches (ELO System)
    # =========================================================================

    async def _handle_leaderboard(self, request) -> web.Response:
        """GET /api/leaderboard - Agent rankings."""

        origin = request.headers.get("Origin")

        if not self.elo_system:
            return web.json_response({"agents": [], "count": 0}, headers=self._cors_headers(origin))

        try:
            limit = safe_query_int(request.query, "limit", default=10, max_val=100)
            agents = self.elo_system.get_leaderboard(limit=limit)
            agent_data = [
                {
                    "name": a.agent_name,
                    "elo": round(a.elo),
                    "wins": a.wins,
                    "losses": a.losses,
                    "draws": a.draws,
                    "win_rate": round(a.win_rate * 100, 1),
                    "games": a.games_played,
                }
                for a in agents
            ]
            return web.json_response(
                {"agents": agent_data, "count": len(agent_data)}, headers=self._cors_headers(origin)
            )
        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.error("Leaderboard error: %s", e)
            return web.json_response(
                {"error": "Failed to fetch leaderboard"},
                status=500,
                headers=self._cors_headers(origin),
            )

    async def _handle_matches_recent(self, request) -> web.Response:
        """GET /api/matches/recent - Recent ELO matches."""

        origin = request.headers.get("Origin")

        if not self.elo_system:
            return web.json_response(
                {"matches": [], "count": 0}, headers=self._cors_headers(origin)
            )

        try:
            limit = safe_query_int(request.query, "limit", default=10, max_val=100)
            matches = self.elo_system.get_recent_matches(limit=limit)
            return web.json_response(
                {"matches": matches, "count": len(matches)}, headers=self._cors_headers(origin)
            )
        except (AttributeError, TypeError, ValueError) as e:
            logger.error("Matches error: %s", e)
            return web.json_response(
                {"error": "Failed to fetch matches"}, status=500, headers=self._cors_headers(origin)
            )

    # =========================================================================
    # Insights and Flips
    # =========================================================================

    async def _handle_insights_recent(self, request) -> web.Response:
        """GET /api/insights/recent - Recent debate insights."""

        origin = request.headers.get("Origin")

        if not self.insight_store:
            return web.json_response(
                {"insights": [], "count": 0}, headers=self._cors_headers(origin)
            )

        try:
            limit = safe_query_int(request.query, "limit", default=10, max_val=100)
            insights = await self.insight_store.get_recent_insights(limit=limit)
            return web.json_response(
                {
                    "insights": [i.to_dict() if hasattr(i, "to_dict") else i for i in insights],
                    "count": len(insights),
                },
                headers=self._cors_headers(origin),
            )
        except (AttributeError, TypeError, ValueError, OSError) as e:
            logger.error("Insights error: %s", e)
            return web.json_response(
                {"error": "Failed to fetch insights"},
                status=500,
                headers=self._cors_headers(origin),
            )

    async def _handle_flips_summary(self, request) -> web.Response:
        """GET /api/flips/summary - Position flip summary."""

        origin = request.headers.get("Origin")

        if not self.flip_detector:
            return web.json_response(
                {"summary": {}, "count": 0}, headers=self._cors_headers(origin)
            )

        try:
            summary = self.flip_detector.get_flip_summary()
            return web.json_response(
                {"summary": summary, "count": summary.get("total_flips", 0)},
                headers=self._cors_headers(origin),
            )
        except (AttributeError, TypeError, KeyError) as e:
            logger.error("Flips summary error: %s", e)
            return web.json_response(
                {"error": "Failed to fetch flip summary"},
                status=500,
                headers=self._cors_headers(origin),
            )

    async def _handle_flips_recent(self, request) -> web.Response:
        """GET /api/flips/recent - Recent position flips."""

        origin = request.headers.get("Origin")

        if not self.flip_detector:
            return web.json_response({"flips": [], "count": 0}, headers=self._cors_headers(origin))

        try:
            limit = safe_query_int(request.query, "limit", default=10, max_val=100)
            flips = self.flip_detector.get_recent_flips(limit=limit)
            return web.json_response(
                {"flips": flips, "count": len(flips)}, headers=self._cors_headers(origin)
            )
        except (AttributeError, TypeError, ValueError) as e:
            logger.error("Flips recent error: %s", e)
            return web.json_response(
                {"error": "Failed to fetch recent flips"},
                status=500,
                headers=self._cors_headers(origin),
            )

    # =========================================================================
    # Tournaments
    # =========================================================================

    async def _handle_tournaments(self, request) -> web.Response:
        """GET /api/tournaments - Tournament list with real data."""

        origin = request.headers.get("Origin")

        if not self.nomic_dir:
            return web.json_response(
                {"tournaments": [], "count": 0}, headers=self._cors_headers(origin)
            )

        try:
            tournaments_dir = self.nomic_dir / "tournaments"
            tournaments_list = []

            if tournaments_dir.exists():
                for db_file in sorted(tournaments_dir.glob("*.db")):
                    try:
                        from aragora.tournaments.tournament import TournamentManager

                        manager = TournamentManager(db_path=str(db_file))

                        tournament = manager.get_tournament()
                        standings = manager.get_current_standings()
                        match_summary = manager.get_match_summary()

                        if tournament:
                            tournament["participants"] = len(standings)
                            tournament["total_matches"] = match_summary["total_matches"]
                            tournament["top_agent"] = standings[0].agent_name if standings else None
                            tournaments_list.append(tournament)
                    except (OSError, ValueError, AttributeError, KeyError) as e:
                        # SQLite/file errors, invalid data, or missing attributes
                        logger.debug("Skipping corrupted tournament file: %s", e)
                        continue

            return web.json_response(
                {"tournaments": tournaments_list, "count": len(tournaments_list)},
                headers=self._cors_headers(origin),
            )
        except OSError as e:
            logger.error("Tournament list error: %s", e)
            return web.json_response(
                {"error": "Failed to fetch tournaments", "tournaments": [], "count": 0},
                status=500,
                headers=self._cors_headers(origin),
            )

    async def _handle_tournament_details(self, request) -> web.Response:
        """GET /api/tournaments/{tournament_id} - Tournament details with standings."""
        import re

        origin = request.headers.get("Origin")

        tournament_id = request.match_info.get("tournament_id", "")

        # Validate tournament_id format (prevent path traversal)
        if not re.match(r"^[a-zA-Z0-9_-]+$", tournament_id):
            return web.json_response(
                {"error": "Invalid tournament ID format"},
                status=400,
                headers=self._cors_headers(origin),
            )

        if not self.nomic_dir:
            return web.json_response(
                {"error": "Nomic directory not configured"},
                status=503,
                headers=self._cors_headers(origin),
            )

        try:
            tournament_db = self.nomic_dir / "tournaments" / f"{tournament_id}.db"

            if not tournament_db.exists():
                return web.json_response(
                    {"error": "Tournament not found"},
                    status=404,
                    headers=self._cors_headers(origin),
                )

            from aragora.tournaments.tournament import TournamentManager

            manager = TournamentManager(db_path=str(tournament_db))

            tournament = manager.get_tournament()
            standings = manager.get_current_standings()
            matches = manager.get_matches(limit=100)

            if not tournament:
                return web.json_response(
                    {"error": "Tournament data not found"},
                    status=404,
                    headers=self._cors_headers(origin),
                )

            standings_data = [
                {
                    "agent": s.agent_name,
                    "wins": s.wins,
                    "losses": s.losses,
                    "draws": s.draws,
                    "points": s.points,
                    "total_score": round(s.total_score, 2),
                    "matches_played": s.matches_played,
                    "win_rate": round(s.win_rate * 100, 1),
                }
                for s in standings
            ]

            return web.json_response(
                {
                    "tournament": tournament,
                    "standings": standings_data,
                    "standings_count": len(standings_data),
                    "recent_matches": matches,
                    "matches_count": len(matches),
                },
                headers=self._cors_headers(origin),
            )
        except (OSError, ValueError, AttributeError, KeyError) as e:
            logger.error("Tournament details error: %s", e)
            return web.json_response(
                {"error": "Failed to fetch tournament details"},
                status=500,
                headers=self._cors_headers(origin),
            )

    # =========================================================================
    # Agent Analysis
    # =========================================================================

    async def _handle_agent_consistency(self, request) -> web.Response:
        """GET /api/agent/{name}/consistency - Agent consistency score from FlipDetector."""
        import re

        origin = request.headers.get("Origin")

        agent_name = request.match_info.get("name", "")

        # Validate agent name format
        if not re.match(r"^[a-zA-Z0-9_-]+$", agent_name):
            return web.json_response(
                {"error": "Invalid agent name format"},
                status=400,
                headers=self._cors_headers(origin),
            )

        try:
            from aragora.insights.flip_detector import FlipDetector
            from aragora.persistence.db_config import DatabaseType, get_db_path

            db_path = get_db_path(DatabaseType.PERSONAS, nomic_dir=self.nomic_dir)
            detector = FlipDetector(db_path=db_path)

            score = detector.get_agent_consistency(agent_name)

            if score:
                consistency = score.consistency_score
                consistency_class = (
                    "high" if consistency >= 0.8 else ("medium" if consistency >= 0.5 else "low")
                )
                return web.json_response(
                    {
                        "agent": agent_name,
                        "consistency": consistency,
                        "consistency_class": consistency_class,
                        "total_positions": score.total_positions,
                        "total_flips": score.total_flips,
                        "flip_rate": score.flip_rate,
                        "contradictions": score.contradictions,
                        "refinements": score.refinements,
                    },
                    headers=self._cors_headers(origin),
                )
            else:
                return web.json_response(
                    {
                        "agent": agent_name,
                        "consistency": 1.0,
                        "consistency_class": "high",
                        "total_positions": 0,
                        "total_flips": 0,
                        "flip_rate": 0.0,
                        "contradictions": 0,
                        "refinements": 0,
                    },
                    headers=self._cors_headers(origin),
                )
        except (OSError, ValueError, AttributeError, KeyError) as e:
            logger.error("Agent consistency error for %s: %s", agent_name, e)
            return web.json_response(
                {"error": "Failed to fetch agent consistency"},
                status=500,
                headers=self._cors_headers(origin),
            )

    async def _handle_agent_network(self, request) -> web.Response:
        """GET /api/agent/{name}/network - Agent relationship network (rivals, allies)."""
        import re

        origin = request.headers.get("Origin")

        agent_name = request.match_info.get("name", "")

        # Validate agent name format
        if not re.match(r"^[a-zA-Z0-9_-]+$", agent_name):
            return web.json_response(
                {"error": "Invalid agent name format"},
                status=400,
                headers=self._cors_headers(origin),
            )

        try:
            network_data = {
                "agent": agent_name,
                "influences": [],
                "influenced_by": [],
                "rivals": [],
                "allies": [],
            }

            # Try persona manager first (has relationship tracker)
            if self.persona_manager and hasattr(self.persona_manager, "relationship_tracker"):
                tracker = self.persona_manager.relationship_tracker

                if hasattr(tracker, "get_rivals"):
                    rivals = tracker.get_rivals(agent_name, limit=5)
                    network_data["rivals"] = (
                        [{"agent": r[0], "score": r[1], "debate_count": 0} for r in rivals]
                        if rivals
                        else []
                    )

                if hasattr(tracker, "get_allies"):
                    allies = tracker.get_allies(agent_name, limit=5)
                    network_data["allies"] = (
                        [{"agent": a[0], "score": a[1], "debate_count": 0} for a in allies]
                        if allies
                        else []
                    )

                if hasattr(tracker, "get_influence_network"):
                    influence = tracker.get_influence_network(agent_name)
                    network_data["influences"] = [
                        {"agent": name, "score": score, "debate_count": 0}
                        for name, score in influence.get("influences", [])
                    ]
                    network_data["influenced_by"] = [
                        {"agent": name, "score": score, "debate_count": 0}
                        for name, score in influence.get("influenced_by", [])
                    ]

            # Fall back to ELO system if no persona manager
            elif self.elo_system:
                if hasattr(self.elo_system, "get_rivals"):
                    rivals = self.elo_system.get_rivals(agent_name, limit=5)
                    network_data["rivals"] = (
                        [
                            {
                                "agent": r.get("agent_b", r.get("agent")),
                                "score": r.get("rivalry_score", 0),
                                "debate_count": r.get("matches", 0),
                            }
                            for r in rivals
                        ]
                        if rivals
                        else []
                    )

                if hasattr(self.elo_system, "get_allies"):
                    allies = self.elo_system.get_allies(agent_name, limit=5)
                    network_data["allies"] = (
                        [
                            {
                                "agent": a.get("agent_b", a.get("agent")),
                                "score": a.get("alliance_score", 0),
                                "debate_count": a.get("matches", 0),
                            }
                            for a in allies
                        ]
                        if allies
                        else []
                    )

            return web.json_response(network_data, headers=self._cors_headers(origin))
        except (AttributeError, TypeError, KeyError) as e:
            logger.error("Agent network error for %s: %s", agent_name, e)
            return web.json_response(
                {"error": "Failed to fetch agent network"},
                status=500,
                headers=self._cors_headers(origin),
            )

    # =========================================================================
    # Memory and Laboratory
    # =========================================================================

    async def _handle_memory_tier_stats(self, request) -> web.Response:
        """GET /api/memory/tier-stats - Continuum memory statistics."""

        origin = request.headers.get("Origin")

        if not self.debate_embeddings:
            return web.json_response(
                {"tiers": {"fast": 0, "medium": 0, "slow": 0, "glacial": 0}, "total": 0},
                headers=self._cors_headers(origin),
            )

        try:
            stats = (
                self.debate_embeddings.get_tier_stats()
                if hasattr(self.debate_embeddings, "get_tier_stats")
                else {}
            )
            return web.json_response(
                {"tiers": stats, "total": sum(stats.values()) if stats else 0},
                headers=self._cors_headers(origin),
            )
        except (AttributeError, TypeError, ValueError) as e:
            logger.error("Memory tier stats error: %s", e)
            return web.json_response(
                {"error": "Failed to fetch memory stats"},
                status=500,
                headers=self._cors_headers(origin),
            )

    async def _handle_laboratory_emergent_traits(self, request) -> web.Response:
        """GET /api/laboratory/emergent-traits - Discovered agent traits."""

        origin = request.headers.get("Origin")

        if not self.persona_manager:
            return web.json_response({"traits": [], "count": 0}, headers=self._cors_headers(origin))

        try:
            min_confidence = safe_query_float(
                request.query, "min_confidence", default=0.3, min_val=0.0, max_val=1.0
            )
            limit = safe_query_int(request.query, "limit", default=10, max_val=100)
            traits = (
                self.persona_manager.get_emergent_traits(min_confidence=min_confidence, limit=limit)
                if hasattr(self.persona_manager, "get_emergent_traits")
                else []
            )
            return web.json_response(
                {"traits": traits, "count": len(traits)}, headers=self._cors_headers(origin)
            )
        except (AttributeError, TypeError, ValueError) as e:
            logger.error("Emergent traits error: %s", e)
            return web.json_response(
                {"error": "Failed to fetch emergent traits"},
                status=500,
                headers=self._cors_headers(origin),
            )

    async def _handle_laboratory_cross_pollinations(self, request) -> web.Response:
        """GET /api/laboratory/cross-pollinations/suggest - Trait transfer suggestions."""

        origin = request.headers.get("Origin")

        if not self.persona_manager:
            return web.json_response(
                {"suggestions": [], "count": 0}, headers=self._cors_headers(origin)
            )

        try:
            suggestions = (
                self.persona_manager.suggest_cross_pollinations()
                if hasattr(self.persona_manager, "suggest_cross_pollinations")
                else []
            )
            return web.json_response(
                {"suggestions": suggestions, "count": len(suggestions)},
                headers=self._cors_headers(origin),
            )
        except (AttributeError, TypeError, ValueError) as e:
            logger.error("Cross-pollinations error: %s", e)
            return web.json_response(
                {"error": "Failed to fetch cross-pollination suggestions"},
                status=500,
                headers=self._cors_headers(origin),
            )

    # =========================================================================
    # Nomic State
    # =========================================================================

    async def _handle_health(self, request) -> web.Response:
        """GET /api/health - Health check endpoint."""
        from datetime import datetime

        origin = request.headers.get("Origin")

        health = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "0.8.0",
        }
        return web.json_response(health, headers=self._cors_headers(origin))

    async def _handle_metrics(self, request) -> web.Response:
        """GET /metrics - Prometheus-format metrics."""

        try:
            from aragora.observability.prometheus import CONTENT_TYPE_LATEST, get_prometheus_metrics

            metrics_text = get_prometheus_metrics()
            return web.Response(
                text=metrics_text,
                content_type=CONTENT_TYPE_LATEST,
            )
        except ImportError:
            return web.Response(
                text="# prometheus_client not installed\n",
                content_type="text/plain",
            )

    async def _handle_nomic_state(self, request) -> web.Response:
        """GET /api/nomic/state - Current nomic loop state."""

        origin = request.headers.get("Origin")

        with self._active_loops_lock:
            if self.active_loops:
                loop = list(self.active_loops.values())[0]
                state = {
                    "cycle": loop.cycle,
                    "phase": loop.phase,
                    "loop_id": loop.loop_id,
                    "name": loop.name,
                }
            else:
                state = {"cycle": 0, "phase": "idle"}

        return web.json_response(state, headers=self._cors_headers(origin))

    # =========================================================================
    # Graph Visualization (ArgumentCartographer)
    # =========================================================================

    async def _handle_graph_json(self, request) -> web.Response:
        """GET /api/debate/{loop_id}/graph - Debate argument graph as JSON."""
        import re

        origin = request.headers.get("Origin")

        loop_id = request.match_info.get("loop_id", "")

        # Validate loop_id format (security: prevent injection)
        if not re.match(r"^[a-zA-Z0-9_-]+$", loop_id):
            return web.json_response(
                {"error": "Invalid loop_id format"}, status=400, headers=self._cors_headers(origin)
            )

        with self._cartographers_lock:
            cartographer = self.cartographers.get(loop_id)

        if not cartographer:
            return web.json_response(
                {"error": f"No cartographer found for loop: {loop_id}"},
                status=404,
                headers=self._cors_headers(origin),
            )

        try:
            include_full = request.query.get("full", "false").lower() == "true"
            graph_json = cartographer.export_json(include_full_content=include_full)
            return web.Response(
                text=graph_json, content_type="application/json", headers=self._cors_headers(origin)
            )
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.error("Graph JSON error for %s: %s", loop_id, e)
            return web.json_response(
                {"error": "Failed to export graph"}, status=500, headers=self._cors_headers(origin)
            )

    async def _handle_graph_mermaid(self, request) -> web.Response:
        """GET /api/debate/{loop_id}/graph/mermaid - Debate argument graph as Mermaid diagram."""
        import re

        origin = request.headers.get("Origin")

        loop_id = request.match_info.get("loop_id", "")

        # Validate loop_id format
        if not re.match(r"^[a-zA-Z0-9_-]+$", loop_id):
            return web.json_response(
                {"error": "Invalid loop_id format"}, status=400, headers=self._cors_headers(origin)
            )

        with self._cartographers_lock:
            cartographer = self.cartographers.get(loop_id)

        if not cartographer:
            return web.json_response(
                {"error": f"No cartographer found for loop: {loop_id}"},
                status=404,
                headers=self._cors_headers(origin),
            )

        try:
            direction = request.query.get("direction", "TD")
            # Validate direction (only TD or LR)
            if direction not in ("TD", "LR"):
                direction = "TD"
            mermaid = cartographer.export_mermaid(direction=direction)
            return web.Response(
                text=mermaid, content_type="text/plain", headers=self._cors_headers(origin)
            )
        except (AttributeError, TypeError, ValueError) as e:
            logger.error("Graph Mermaid error for %s: %s", loop_id, e)
            return web.json_response(
                {"error": "Failed to export Mermaid diagram"},
                status=500,
                headers=self._cors_headers(origin),
            )

    async def _handle_graph_stats(self, request) -> web.Response:
        """GET /api/debate/{loop_id}/graph/stats - Debate argument graph statistics."""
        import re

        origin = request.headers.get("Origin")

        loop_id = request.match_info.get("loop_id", "")

        # Validate loop_id format
        if not re.match(r"^[a-zA-Z0-9_-]+$", loop_id):
            return web.json_response(
                {"error": "Invalid loop_id format"}, status=400, headers=self._cors_headers(origin)
            )

        with self._cartographers_lock:
            cartographer = self.cartographers.get(loop_id)

        if not cartographer:
            return web.json_response(
                {"error": f"No cartographer found for loop: {loop_id}"},
                status=404,
                headers=self._cors_headers(origin),
            )

        try:
            stats = cartographer.get_statistics()
            return web.json_response(stats, headers=self._cors_headers(origin))
        except (AttributeError, TypeError, KeyError) as e:
            logger.error("Graph stats error for %s: %s", loop_id, e)
            return web.json_response(
                {"error": "Failed to get graph statistics"},
                status=500,
                headers=self._cors_headers(origin),
            )

    # =========================================================================
    # Audience
    # =========================================================================

    async def _handle_audience_clusters(self, request) -> web.Response:
        """GET /api/debate/{loop_id}/audience/clusters - Clustered audience suggestions."""
        import re

        origin = request.headers.get("Origin")

        loop_id = request.match_info.get("loop_id", "")

        # Validate loop_id format
        if not re.match(r"^[a-zA-Z0-9_-]+$", loop_id):
            return web.json_response(
                {"error": "Invalid loop_id format"}, status=400, headers=self._cors_headers(origin)
            )

        try:
            from aragora.audience.suggestions import cluster_suggestions

            if self.audience_inbox is None:
                return web.json_response(
                    {"clusters": [], "total": 0, "error": "Audience inbox not available"},
                    headers=self._cors_headers(origin),
                )

            # GET must be non-destructive so dashboard refreshes do not erase
            # pending audience input before the debate loop can consume it.
            suggestions = self.audience_inbox.peek_suggestions(loop_id=loop_id)

            if not suggestions:
                return web.json_response(
                    {"clusters": [], "total": 0}, headers=self._cors_headers(origin)
                )

            # Cluster suggestions
            clusters = cluster_suggestions(
                suggestions,
                similarity_threshold=safe_query_float(
                    request.query, "threshold", default=0.6, min_val=0.0, max_val=1.0
                ),
                max_clusters=safe_query_int(
                    request.query, "max_clusters", default=5, min_val=1, max_val=50
                ),
            )

            return web.json_response(
                {
                    "clusters": [
                        {
                            "representative": c.representative,
                            "count": c.count,
                            "user_ids": c.user_ids[:5],  # Limit user IDs for privacy
                        }
                        for c in clusters
                    ],
                    "total": sum(c.count for c in clusters),
                },
                headers=self._cors_headers(origin),
            )
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.error("Audience clusters error for %s: %s", loop_id, e)
            return web.json_response(
                {"error": "Failed to cluster audience suggestions"},
                status=500,
                headers=self._cors_headers(origin),
            )

    # =========================================================================
    # Replays
    # =========================================================================

    async def _handle_replays(self, request) -> web.Response:
        """GET /api/replays - List available debate replays."""

        origin = request.headers.get("Origin")

        if not self.nomic_dir:
            return web.json_response(
                {"replays": [], "count": 0}, headers=self._cors_headers(origin)
            )

        try:
            replays_dir = self.nomic_dir / "replays"
            if not replays_dir.exists():
                return web.json_response(
                    {"replays": [], "count": 0}, headers=self._cors_headers(origin)
                )

            # Get limit from query params, default 50, max 200
            try:
                limit = min(int(request.query.get("limit", "50")), 200)
            except (ValueError, TypeError):
                limit = 50
            max_to_scan = limit * 3  # Scan 3x to account for filtered items

            replays = []
            scanned = 0
            for replay_path in replays_dir.iterdir():
                if scanned >= max_to_scan:
                    break
                scanned += 1
                if replay_path.is_dir():
                    meta_file = replay_path / "meta.json"
                    if meta_file.exists():
                        meta = _load_json_object(meta_file, context="replay meta")
                        replays.append(
                            {
                                "id": replay_path.name,
                                "topic": meta.get("topic", replay_path.name),
                                "timestamp": meta.get("timestamp", ""),
                            }
                        )
                        if len(replays) >= limit:
                            break

            return web.json_response(
                {
                    "replays": sorted(replays, key=lambda x: x["id"], reverse=True)[:limit],
                    "count": len(replays),
                },
                headers=self._cors_headers(origin),
            )
        except OSError as e:
            logger.error("Replays list error: %s", e)
            return web.json_response(
                {"error": "Failed to list replays"}, status=500, headers=self._cors_headers(origin)
            )

    async def _handle_replay_html(self, request) -> web.Response:
        """GET /api/replays/{replay_id}/html - Get HTML replay visualization."""
        import re

        origin = request.headers.get("Origin")

        replay_id = request.match_info.get("replay_id", "")

        # Validate replay_id format (security: prevent path traversal)
        if not re.match(r"^[a-zA-Z0-9_-]+$", replay_id):
            return web.json_response(
                {"error": "Invalid replay_id format"},
                status=400,
                headers=self._cors_headers(origin),
            )

        if not self.nomic_dir:
            return web.json_response(
                {"error": "No nomic directory configured"},
                status=500,
                headers=self._cors_headers(origin),
            )

        try:
            replay_dir = self.nomic_dir / "replays" / replay_id
            if not replay_dir.exists():
                return web.json_response(
                    {"error": f"Replay not found: {replay_id}"},
                    status=404,
                    headers=self._cors_headers(origin),
                )

            # Check for pre-generated HTML
            html_file = replay_dir / "replay.html"
            if html_file.exists():
                return web.Response(
                    text=html_file.read_text(),
                    content_type="text/html",
                    headers=self._cors_headers(origin),
                )

            # Generate from events.jsonl if no pre-generated HTML
            events_file = replay_dir / "events.jsonl"
            meta_file = replay_dir / "meta.json"

            if not events_file.exists():
                return web.json_response(
                    {"error": f"No events found for replay: {replay_id}"},
                    status=404,
                    headers=self._cors_headers(origin),
                )

            # Load events and generate HTML
            from datetime import datetime

            from aragora.core import Message
            from aragora.visualization.replay import ReplayArtifact, ReplayGenerator, ReplayScene

            events = []
            with events_file.open() as f:
                for line in f:
                    if line.strip():
                        event = _parse_json_object_line(line, source=events_file)
                        if event is not None:
                            events.append(event)

            # Create artifact from events
            meta = _load_json_object(meta_file, context="replay meta") if meta_file.exists() else {}
            generator = ReplayGenerator()
            verdict = meta.get("verdict", {})
            if not isinstance(verdict, dict):
                verdict = {}

            # Simple HTML generation from events
            artifact = ReplayArtifact(
                debate_id=replay_id,
                task=meta.get("topic", "Unknown"),
                scenes=[],
                verdict=verdict,
                metadata=meta,
            )

            # Group events by round
            round_events: dict[int, list] = {}
            for event in events:
                round_num = event.get("round", 0)
                if isinstance(round_num, bool) or not isinstance(round_num, int):
                    round_num = 0
                round_events.setdefault(round_num, []).append(event)

            for round_num in sorted(round_events.keys()):
                messages = []
                for event in round_events[round_num]:
                    event_data = event.get("data", {})
                    if not isinstance(event_data, dict):
                        event_data = {}
                    if event.get("type") in ("agent_message", "propose", "critique"):
                        messages.append(
                            Message(
                                role=event_data.get("role", "unknown"),
                                agent=event.get("agent", "unknown"),
                                content=event_data.get("content", ""),
                                round=round_num,
                            )
                        )
                if messages:
                    artifact.scenes.append(
                        ReplayScene(
                            round_number=round_num,
                            timestamp=datetime.now(),
                            messages=messages,
                        )
                    )

            html = generator._render_html(artifact)
            return web.Response(
                text=html, content_type="text/html", headers=self._cors_headers(origin)
            )
        except (OSError, ValueError, KeyError, AttributeError) as e:
            logger.error("Replay HTML error for %s: %s", replay_id, e)
            return web.json_response(
                {"error": "Failed to generate replay HTML"},
                status=500,
                headers=self._cors_headers(origin),
            )


__all__ = ["StreamAPIHandlersMixin"]
