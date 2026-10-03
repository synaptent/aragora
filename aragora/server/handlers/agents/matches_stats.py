"""Match statistics endpoint handler.

Serves the aggregate ELO match statistics documented in the OpenAPI spec:

- GET /api/matches/stats
- GET /api/v1/matches/stats

Backed by :meth:`aragora.ranking.elo.EloSystem.get_stats`. This endpoint was
previously spec-orphaned (documented but unreachable); it is served truthfully
here as a behavior-preserving correction. Like the other public ranking reads
(leaderboard, recent matches) it requires no authentication, matching the
curated spec which declares no security requirement for this operation.
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

from ..base import BaseHandler, HandlerResult, error_response, json_response

logger = logging.getLogger(__name__)

_STATS_PATH = "/api/matches/stats"


class MatchesStatsHandler(BaseHandler):
    """Handler for aggregate match statistics."""

    ROUTES = [_STATS_PATH]

    def can_handle(self, path: str) -> bool:
        # Exact match only: /api/matches/{match_id} and /api/matches/recent
        # belong to other handlers and must not be shadowed by prefix logic.
        return strip_version_prefix(path.split("?")[0]) == _STATS_PATH

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        if strip_version_prefix(path.split("?")[0]) != _STATS_PATH:
            return None

        elo = self.get_elo_system()
        if elo is None:
            return error_response("Match statistics unavailable: ELO system not configured", 503)

        try:
            stats = elo.get_stats()
        except (RuntimeError, OSError, ValueError) as exc:
            logger.warning("Failed to compute match statistics: %s", exc)
            return error_response("Failed to compute match statistics", 500)

        return json_response(stats)
