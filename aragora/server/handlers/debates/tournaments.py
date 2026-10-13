"""
Tournament-related endpoint handlers.

Endpoints:
- GET  /api/tournaments - List all tournaments
- POST /api/tournaments - Create new tournament
- GET  /api/tournaments/{id} - Get tournament details
- GET  /api/tournaments/{id}/standings - Get tournament standings
- GET  /api/tournaments/{id}/bracket - Get bracket structure
- GET  /api/tournaments/{id}/matches - Get match history
- POST /api/tournaments/{id}/advance - Advance to next round
- POST /api/tournaments/{id}/matches/{match_id}/result - Record match result
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_int_param,
    handle_errors,
    json_response,
)
from aragora.rbac.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)

# Rate limiter for tournament endpoints (30 requests per minute)
_tournament_limiter = RateLimiter(requests_per_minute=30)

# Tournament listing limits
MAX_TOURNAMENTS_TO_LIST = 100  # Prevent unbounded directory iteration

# Optional import for tournament functionality
# Use Any type for optional imports to avoid mypy "Cannot assign to a type" errors
_TournamentManager: Any = None
_Tournament: Any = None
_TournamentMatch: Any = None
TOURNAMENT_AVAILABLE = False

try:
    from aragora.ranking.tournaments import Tournament, TournamentManager, TournamentMatch

    _TournamentManager = TournamentManager
    _Tournament = Tournament
    _TournamentMatch = TournamentMatch
    TOURNAMENT_AVAILABLE = True
except ImportError:
    pass


class TournamentHandler(BaseHandler):
    """Handler for tournament-related endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/tournaments",
        "/api/tournaments/*",
        "/api/tournaments/*/standings",
        "/api/tournaments/*/bracket",
        "/api/tournaments/*/matches",
        "/api/tournaments/*/advance",
        "/api/tournaments/*/matches/*/result",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        path = strip_version_prefix(path)
        if path == "/api/tournaments":
            return True
        if not path.startswith("/api/tournaments/"):
            return False

        # Parse path segments
        parts = path.split("/")
        if len(parts) < 4:
            return False

        # /api/tournaments/{id}
        if len(parts) == 4:
            return True

        # /api/tournaments/{id}/standings|bracket|matches|advance
        if len(parts) == 5 and parts[4] in ("standings", "bracket", "matches", "advance"):
            return True

        # /api/tournaments/{id}/matches/{match_id}/result
        if len(parts) == 7 and parts[4] == "matches" and parts[6] == "result":
            return True

        return False

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route tournament requests to appropriate handler methods."""
        path = strip_version_prefix(path)
        logger.debug("Tournament request: %s", path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _tournament_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for tournament endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if not path.startswith("/api/tournaments"):
            return None

        if path == "/api/tournaments":
            return self._list_tournaments()

        parts = path.split("/")
        tournament_id = parts[3] if len(parts) > 3 else None

        if not tournament_id:
            return error_response("Tournament ID required", 400)

        # Validate tournament ID to prevent path traversal
        if ".." in tournament_id or "/" in tournament_id or ";" in tournament_id:
            return error_response("Invalid tournament ID", 400)

        # /api/tournaments/{id}
        if len(parts) == 4:
            return self._get_tournament(tournament_id)

        # /api/tournaments/{id}/standings
        if len(parts) == 5 and parts[4] == "standings":
            return self._get_tournament_standings(tournament_id)

        # /api/tournaments/{id}/bracket
        if len(parts) == 5 and parts[4] == "bracket":
            return self._get_tournament_bracket(tournament_id)

        # /api/tournaments/{id}/matches
        if len(parts) == 5 and parts[4] == "matches":
            round_num = get_int_param(query_params, "round")
            return self._get_tournament_matches(tournament_id, round_num)

        # /api/tournaments/{id}/advance
        if len(parts) == 5 and parts[4] == "advance":
            return self._advance_tournament(tournament_id)

        # /api/tournaments/{id}/matches/{match_id}/result
        if len(parts) == 7 and parts[4] == "matches" and parts[6] == "result":
            match_id = parts[5]
            return self._record_match_result(tournament_id, match_id, query_params)

        return None

    @handle_errors("tournament creation")
    @require_permission("tournaments:create")
    def handle_post(self, path: str, body: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle POST requests for tournament creation and updates."""
        path = strip_version_prefix(path)
        logger.debug("Tournament POST request: %s", path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _tournament_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for tournament endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # POST /api/tournaments - Create tournament
        if path == "/api/tournaments":
            return self._create_tournament(body)

        parts = path.split("/")
        tournament_id = parts[3] if len(parts) > 3 else None

        if not tournament_id:
            return error_response("Tournament ID required", 400)

        # Validate tournament ID to prevent path traversal
        if ".." in tournament_id or "/" in tournament_id or ";" in tournament_id:
            return error_response("Invalid tournament ID", 400)

        # POST /api/tournaments/{id}/advance - Advance round
        if len(parts) == 5 and parts[4] == "advance":
            return self._advance_tournament(tournament_id)

        # POST /api/tournaments/{id}/matches/{match_id}/result - Record result
        if len(parts) == 7 and parts[4] == "matches" and parts[6] == "result":
            match_id = parts[5]
            return self._record_match_result(tournament_id, match_id, body)

        return None

    @handle_errors("tournament listing")
    def _list_tournaments(self) -> HandlerResult:
        """List all available tournaments."""
        if not TOURNAMENT_AVAILABLE:
            return error_response("Tournament system not available", 503)

        nomic_dir = self.ctx.get("nomic_dir")
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        tournaments_dir = Path(nomic_dir) / "tournaments"
        tournaments = []

        if tournaments_dir.exists():
            scanned = 0
            for db_file in tournaments_dir.glob("*.db"):
                # Limit directory iteration to prevent unbounded growth
                if scanned >= MAX_TOURNAMENTS_TO_LIST:
                    break
                scanned += 1

                tournament_id = db_file.stem
                try:
                    manager = _TournamentManager(db_path=str(db_file))
                    standings = manager.get_current_standings()
                    tournaments.append(
                        {
                            "tournament_id": tournament_id,
                            "participants": len(standings),
                            "total_matches": sum(s.wins + s.losses + s.draws for s in standings)
                            // 2,
                            "top_agent": standings[0].agent if standings else None,
                        }
                    )
                except Exception as e:  # noqa: BLE001 - graceful degradation, skip corrupted tournament files
                    logger.warning(
                        "Failed to load tournament %s: %s: %s", tournament_id, type(e).__name__, e
                    )
                    continue

        logger.info("Listed %s tournaments", len(tournaments))
        return json_response(
            {
                "tournaments": tournaments,
                "count": len(tournaments),
            }
        )

    @handle_errors("tournament standings retrieval")
    def _get_tournament_standings(self, tournament_id: str) -> HandlerResult:
        """Get current tournament standings."""
        if not TOURNAMENT_AVAILABLE:
            return error_response("Tournament system not available", 503)

        nomic_dir = self.ctx.get("nomic_dir")
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        tournament_path = Path(nomic_dir) / "tournaments" / f"{tournament_id}.db"
        if not tournament_path.exists():
            return error_response("Tournament not found", 404)

        manager = _TournamentManager(db_path=str(tournament_path))
        standings = manager.get_current_standings()

        logger.info(
            "Retrieved standings for tournament %s: %s participants", tournament_id, len(standings)
        )
        return json_response(
            {
                "tournament_id": tournament_id,
                "standings": [
                    {
                        "agent": s.agent,
                        "wins": s.wins,
                        "losses": s.losses,
                        "draws": s.draws,
                        "points": s.points,
                        "total_score": s.total_score,
                        "win_rate": s.win_rate,
                    }
                    for s in standings
                ],
                "count": len(standings),
            }
        )

    @handle_errors("tournament retrieval")
    def _get_tournament(self, tournament_id: str) -> HandlerResult:
        """Get tournament details."""
        if not TOURNAMENT_AVAILABLE:
            return error_response("Tournament system not available", 503)

        nomic_dir = self.ctx.get("nomic_dir")
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        tournament_path = Path(nomic_dir) / "tournaments" / f"{tournament_id}.db"
        if not tournament_path.exists():
            return error_response("Tournament not found", 404)

        manager = _TournamentManager(db_path=str(tournament_path))
        tournament = manager.get_tournament(tournament_id)

        if not tournament:
            # Try to get any tournament from the database
            tournaments = manager.list_tournaments(limit=1)
            tournament = tournaments[0] if tournaments else None

        if not tournament:
            return error_response("Tournament not found", 404)

        logger.info("Retrieved tournament %s", tournament_id)
        return json_response(
            {
                "tournament_id": tournament.tournament_id,
                "name": tournament.name,
                "bracket_type": tournament.bracket_type,
                "participants": tournament.participants,
                "rounds_completed": tournament.rounds_completed,
                "total_rounds": tournament.total_rounds,
                "status": tournament.status,
                "created_at": tournament.created_at,
            }
        )

    @handle_errors("tournament bracket retrieval")
    def _get_tournament_bracket(self, tournament_id: str) -> HandlerResult:
        """Get tournament bracket structure."""
        if not TOURNAMENT_AVAILABLE:
            return error_response("Tournament system not available", 503)

        nomic_dir = self.ctx.get("nomic_dir")
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        tournament_path = Path(nomic_dir) / "tournaments" / f"{tournament_id}.db"
        if not tournament_path.exists():
            return error_response("Tournament not found", 404)

        manager = _TournamentManager(db_path=str(tournament_path))
        tournament = manager.get_tournament(tournament_id)
        matches = manager.get_matches(tournament_id=tournament_id)

        if not tournament:
            tournaments = manager.list_tournaments(limit=1)
            if tournaments:
                tournament = tournaments[0]
                matches = manager.get_matches(tournament_id=tournament.tournament_id)

        if not tournament:
            return error_response("Tournament not found", 404)

        # Organize matches by round
        rounds: dict[int, list] = {}
        for m in matches:
            if m.round_num not in rounds:
                rounds[m.round_num] = []
            rounds[m.round_num].append(
                {
                    "match_id": m.match_id,
                    "agent1": m.agent1,
                    "agent2": m.agent2,
                    "winner": m.winner,
                    "score1": m.score1,
                    "score2": m.score2,
                    "completed": m.completed_at is not None,
                }
            )

        logger.info("Retrieved bracket for tournament %s", tournament_id)
        return json_response(
            {
                "tournament_id": tournament.tournament_id,
                "name": tournament.name,
                "bracket_type": tournament.bracket_type,
                "total_rounds": tournament.total_rounds,
                "rounds_completed": tournament.rounds_completed,
                "rounds": {str(k): v for k, v in sorted(rounds.items())},
            }
        )

    @handle_errors("tournament matches retrieval")
    def _get_tournament_matches(
        self, tournament_id: str, round_num: int | None = None
    ) -> HandlerResult:
        """Get tournament match history."""
        if not TOURNAMENT_AVAILABLE:
            return error_response("Tournament system not available", 503)

        nomic_dir = self.ctx.get("nomic_dir")
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        tournament_path = Path(nomic_dir) / "tournaments" / f"{tournament_id}.db"
        if not tournament_path.exists():
            return error_response("Tournament not found", 404)

        manager = _TournamentManager(db_path=str(tournament_path))
        matches = manager.get_matches(tournament_id=tournament_id, round_num=round_num)

        logger.info("Retrieved %s matches for tournament %s", len(matches), tournament_id)
        return json_response(
            {
                "tournament_id": tournament_id,
                "matches": [
                    {
                        "match_id": m.match_id,
                        "round_num": m.round_num,
                        "agent1": m.agent1,
                        "agent2": m.agent2,
                        "winner": m.winner,
                        "score1": m.score1,
                        "score2": m.score2,
                        "debate_id": m.debate_id,
                        "created_at": m.created_at,
                        "completed_at": m.completed_at,
                    }
                    for m in matches
                ],
                "count": len(matches),
            }
        )

    @handle_errors("tournament creation")
    def _create_tournament(self, body: dict) -> HandlerResult:
        """Create a new tournament."""
        if not TOURNAMENT_AVAILABLE:
            return error_response("Tournament system not available", 503)

        nomic_dir = self.ctx.get("nomic_dir")
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        # Validate request body
        name = body.get("name")
        if not name:
            return error_response("Tournament name is required", 400)

        participants = body.get("participants", [])
        if not participants or len(participants) < 2:
            return error_response("At least 2 participants are required", 400)

        bracket_type = body.get("bracket_type", "round_robin")
        if bracket_type not in ("round_robin", "single_elimination", "double_elimination"):
            return error_response(
                "Invalid bracket_type. Must be: round_robin, single_elimination, or double_elimination",
                400,
            )

        # Create tournament directory
        tournaments_dir = Path(nomic_dir) / "tournaments"
        tournaments_dir.mkdir(parents=True, exist_ok=True)

        # Create tournament with a unique database file
        import uuid

        db_name = f"{uuid.uuid4().hex[:8]}.db"
        db_path = tournaments_dir / db_name

        manager = _TournamentManager(db_path=str(db_path))
        tournament = manager.create_tournament(
            name=name,
            participants=participants,
            bracket_type=bracket_type,
        )

        logger.info("Created tournament %s", tournament.tournament_id)
        return json_response(
            {
                "tournament_id": tournament.tournament_id,
                "name": tournament.name,
                "bracket_type": tournament.bracket_type,
                "participants": tournament.participants,
                "total_rounds": tournament.total_rounds,
                "status": tournament.status,
                "created_at": tournament.created_at,
            },
            status=201,
        )

    @handle_errors("tournament advancement")
    def _advance_tournament(self, tournament_id: str) -> HandlerResult:
        """Advance tournament to next round (for elimination brackets)."""
        if not TOURNAMENT_AVAILABLE:
            return error_response("Tournament system not available", 503)

        nomic_dir = self.ctx.get("nomic_dir")
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        tournament_path = Path(nomic_dir) / "tournaments" / f"{tournament_id}.db"
        if not tournament_path.exists():
            return error_response("Tournament not found", 404)

        manager = _TournamentManager(db_path=str(tournament_path))
        advanced = manager.advance_round(tournament_id)

        if advanced:
            tournament = manager.get_tournament(tournament_id)
            logger.info(
                "Advanced tournament %s to round %s",
                tournament_id,
                tournament.rounds_completed + 1 if tournament else "unknown",
            )
            return json_response(
                {
                    "success": True,
                    "message": "Tournament advanced to next round",
                    "tournament_id": tournament_id,
                    "rounds_completed": tournament.rounds_completed if tournament else 0,
                }
            )
        else:
            return json_response(
                {
                    "success": False,
                    "message": "Cannot advance tournament. Either all rounds complete or current round not finished.",
                    "tournament_id": tournament_id,
                }
            )

    @handle_errors("match result recording")
    def _record_match_result(
        self, tournament_id: str, match_id: str, params: dict
    ) -> HandlerResult:
        """Record a match result."""
        if not TOURNAMENT_AVAILABLE:
            return error_response("Tournament system not available", 503)

        nomic_dir = self.ctx.get("nomic_dir")
        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        tournament_path = Path(nomic_dir) / "tournaments" / f"{tournament_id}.db"
        if not tournament_path.exists():
            return error_response("Tournament not found", 404)

        # Get result parameters
        winner = params.get("winner")  # Can be None for draw
        score1 = float(params.get("score1", 0.0))
        score2 = float(params.get("score2", 0.0))
        debate_id = params.get("debate_id")

        manager = _TournamentManager(db_path=str(tournament_path))
        manager.record_match_result(
            match_id=match_id,
            winner=winner,
            score1=score1,
            score2=score2,
            debate_id=debate_id,
        )

        logger.info("Recorded result for match %s: winner=%s", match_id, winner)
        return json_response(
            {
                "success": True,
                "match_id": match_id,
                "winner": winner,
                "score1": score1,
                "score2": score2,
            }
        )
