"""Agent flip detection endpoint methods (AgentFlipsMixin).

Extracted from agents.py to reduce file size.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aragora.config import (
    CACHE_TTL_AGENT_FLIPS,
    CACHE_TTL_FLIPS_RECENT,
    CACHE_TTL_FLIPS_SUMMARY,
)
from aragora.persistence.db_config import DatabaseType, get_db_path

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    ttl_cache,
)
from ..openapi_decorator import api_endpoint

logger = logging.getLogger(__name__)


class AgentFlipsMixin:
    """Mixin providing agent flip detection endpoints.

    Expects the composing class to provide:
    - get_nomic_dir() -> Path | None

    This is provided by BaseHandler.
    """

    if TYPE_CHECKING:

        def get_nomic_dir(self) -> Path | None: ...

    @api_endpoint(
        method="GET",
        path="/api/v1/agent/{name}/flips",
        summary="Get recent position flips for agent",
        tags=["Agents"],
    )
    @ttl_cache(ttl_seconds=CACHE_TTL_AGENT_FLIPS, key_prefix="agent_flips", skip_first=True)
    @handle_errors("agent flips")
    def _get_agent_flips(self, agent: str, limit: int) -> HandlerResult:
        """Get recent position flips for an agent."""
        from aragora.insights.flip_detector import FlipDetector

        nomic_dir = self.get_nomic_dir()
        if nomic_dir:
            detector = FlipDetector(str(get_db_path(DatabaseType.POSITIONS, nomic_dir)))
            flips = detector.detect_flips_for_agent(agent, lookback_positions=min(limit, 100))
            consistency = detector.get_agent_consistency(agent)
            return json_response(
                {
                    "agent": agent,
                    "flips": [f.to_dict() for f in flips],
                    "consistency": consistency.to_dict(),
                    "count": len(flips),
                }
            )
        return json_response(
            {
                "agent": agent,
                "flips": [],
                "consistency": {
                    "agent_name": agent,
                    "total_positions": 0,
                    "total_flips": 0,
                    "consistency_score": 1.0,
                },
                "count": 0,
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/flips/recent",
        summary="Get recent flips across all agents",
        tags=["Agents"],
    )
    @ttl_cache(ttl_seconds=CACHE_TTL_FLIPS_RECENT, key_prefix="flips_recent", skip_first=True)
    @handle_errors("recent flips")
    def _get_recent_flips(self, limit: int) -> HandlerResult:
        """Get recent flips across all agents."""
        from aragora.insights.flip_detector import FlipDetector

        nomic_dir = self.get_nomic_dir()
        if nomic_dir:
            detector = FlipDetector(str(get_db_path(DatabaseType.POSITIONS, nomic_dir)))
            flips = detector.get_recent_flips(limit=min(limit, 100))
            summary = detector.get_flip_summary()
            return json_response(
                {
                    "flips": [f.to_dict() for f in flips],
                    "summary": summary,
                    "count": len(flips),
                }
            )
        return json_response(
            {
                "flips": [],
                "summary": {"total_flips": 0, "by_type": {}, "by_agent": {}, "recent_24h": 0},
                "count": 0,
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/flips/{flip_id}",
        summary="Get a detected flip by ID",
        tags=["Agents"],
    )
    @handle_errors("flip detail")
    def _get_flip(self, flip_id: str) -> HandlerResult:
        """Get one detected flip in the same shape as the recent-flips entries."""
        from aragora.insights.flip_detector import FlipDetector

        nomic_dir = self.get_nomic_dir()
        if not nomic_dir:
            return error_response("Flip detection not available", 503)

        detector = FlipDetector(str(get_db_path(DatabaseType.POSITIONS, nomic_dir)))
        flip = detector.get_flip(flip_id)
        if flip is None:
            return error_response("Flip not found", 404)
        return json_response(flip.to_dict())

    @api_endpoint(
        method="GET",
        path="/api/v1/flips/summary",
        summary="Get flip summary for dashboard",
        tags=["Agents"],
    )
    @ttl_cache(ttl_seconds=CACHE_TTL_FLIPS_SUMMARY, key_prefix="flips_summary", skip_first=True)
    @handle_errors("flip summary")
    def _get_flip_summary(self) -> HandlerResult:
        """Get flip summary for dashboard."""
        from aragora.insights.flip_detector import FlipDetector

        nomic_dir = self.get_nomic_dir()
        if nomic_dir:
            detector = FlipDetector(str(get_db_path(DatabaseType.POSITIONS, nomic_dir)))
            summary = detector.get_flip_summary()
            return json_response(summary)
        return json_response(
            {
                "total_flips": 0,
                "by_type": {},
                "by_agent": {},
                "recent_24h": 0,
            }
        )
