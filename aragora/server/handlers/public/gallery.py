"""
Public Gallery endpoint handlers.

Exposes debate archives publicly with stable, shareable URLs.
Based on the nomic loop proposal for public debate visibility.

Endpoints:
- GET /api/gallery - List public debates
- GET /api/gallery/:debate_id - Get specific debate with full history
- GET /api/gallery/:debate_id/embed - Get embeddable debate summary
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_int_param,
    json_response,
)
from ..utils.rate_limit import RateLimiter, get_client_ip
from aragora.rbac.decorators import require_permission
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)

# Rate limiter for gallery endpoints (60 requests per minute)
_gallery_limiter = RateLimiter(requests_per_minute=60)


@dataclass
class PublicDebate:
    """A debate entry for the public gallery."""

    id: str  # Stable ID (hash of debate_id + loop_id)
    title: str
    topic: str
    created_at: str
    agents: list[str]
    rounds: int
    consensus_reached: bool
    winner: str | None
    preview: str  # First 500 chars of final answer

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "topic": self.topic,
            "created_at": self.created_at,
            "agents": self.agents,
            "rounds": self.rounds,
            "consensus_reached": self.consensus_reached,
            "winner": self.winner,
            "preview": self.preview,
        }


def generate_stable_id(debate_id: str, loop_id: str | None = None) -> str:
    """
    Generate a stable, shareable ID for a debate.

    Combines debate_id and loop_id to create a unique hash that
    remains stable across server restarts.
    """
    source = debate_id
    if loop_id:
        source = f"{loop_id}:{debate_id}"
    return hashlib.sha256(source.encode()).hexdigest()[:12]


class GalleryHandler(BaseHandler):
    """Handler for public gallery endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/gallery",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        path = strip_version_prefix(path)
        if path in self.ROUTES:
            return True
        # Dynamic routes for specific debate
        if path.startswith("/api/gallery/") and len(path.split("/")) >= 4:
            return True
        return False

    @require_permission("gallery:read")
    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route gallery requests to appropriate methods."""
        path = strip_version_prefix(path)
        logger.debug("Gallery request: %s params=%s", path, query_params)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _gallery_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for gallery endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/gallery":
            return self._list_public_debates(query_params)

        # Parse debate_id from path
        # Path: /api/gallery/{debate_id} -> parts: ['', 'api', 'gallery', '{debate_id}']
        parts = path.split("/")
        if len(parts) >= 4 and parts[1] == "api" and parts[2] == "gallery":
            debate_id = parts[3]

            # Check for sub-routes
            if len(parts) == 5 and parts[4] == "embed":
                return self._get_embed(debate_id)

            return self._get_debate(debate_id)

        return None

    def _list_public_debates(self, query_params: dict) -> HandlerResult:
        """
        List public debates with pagination.

        Query params:
        - limit: Max debates to return (default 20, max 100)
        - offset: Skip first N debates (default 0)
        - agent: Filter by agent name
        """
        limit = min(get_int_param(query_params, "limit", 20), 100)
        offset = get_int_param(query_params, "offset", 0)
        agent_filter = query_params.get("agent", [None])[0]

        # Get debates from memory store
        nomic_dir = self.ctx.get("nomic_dir")
        debates = self._load_debates_from_replays(nomic_dir, limit, offset, agent_filter)

        logger.info(
            "Gallery listing: %s debates (limit=%s, offset=%s)", len(debates), limit, offset
        )
        return json_response(
            {
                "debates": [d.to_dict() for d in debates],
                "total": len(debates),
                "limit": limit,
                "offset": offset,
            }
        )

    def _get_debate(self, debate_id: str) -> HandlerResult:
        """Get full debate details by stable ID."""
        nomic_dir = self.ctx.get("nomic_dir")
        debate = self._find_debate_by_id(nomic_dir, debate_id)

        if not debate:
            logger.debug("Debate not found: %s", debate_id)
            return error_response("Debate not found", status=404)

        logger.info("Retrieved debate %s with %s events", debate_id, len(debate.get("events", [])))
        return json_response(debate)

    def _get_embed(self, debate_id: str) -> HandlerResult:
        """Get embeddable debate summary for sharing."""
        nomic_dir = self.ctx.get("nomic_dir")
        debate = self._find_debate_by_id(nomic_dir, debate_id)

        if not debate:
            return error_response("Debate not found", status=404)

        # Return minimal embed data
        embed = {
            "id": debate_id,
            "title": debate.get("title", "Untitled Debate"),
            "topic": debate.get("topic", "")[:200],
            "agents": debate.get("agents", []),
            "consensus_reached": debate.get("consensus_reached", False),
            "winner": debate.get("winner"),
            "preview": debate.get("preview", "")[:300],
            "embed_url": f"/api/gallery/{debate_id}/embed",
            "full_url": f"/api/gallery/{debate_id}",
        }

        return json_response(embed)

    def _load_debates_from_replays(
        self,
        nomic_dir: Path | None,
        limit: int,
        offset: int,
        agent_filter: str | None,
    ) -> list[PublicDebate]:
        """Load debates from replay files."""
        debates: list[PublicDebate] = []

        if not nomic_dir:
            return debates

        replays_dir = Path(nomic_dir) / "replays"
        if not replays_dir.exists():
            return debates

        # Collect directory entries with modification times (bounded iteration)
        # Scan more than needed to account for filtering and non-directory entries
        max_to_scan = (offset + limit + 100) * 2
        dir_entries: list[tuple[float, Path]] = []

        for replay_path in replays_dir.iterdir():
            if not replay_path.is_dir():
                continue
            try:
                mtime = replay_path.stat().st_mtime
                dir_entries.append((mtime, replay_path))
            except OSError:
                continue
            # Early termination to prevent memory exhaustion
            if len(dir_entries) >= max_to_scan:
                break

        # Sort only the collected subset by modification time (newest first)
        dir_entries.sort(key=lambda x: x[0], reverse=True)

        for _, replay_path in dir_entries:
            meta_path = replay_path / "meta.json"
            if not meta_path.exists():
                continue

            try:
                with open(meta_path) as f:
                    meta = json.load(f)

                # Extract debate info
                agents = meta.get("agents", [])
                if agent_filter and agent_filter not in agents:
                    continue

                debate_id = meta.get("debate_id", replay_path.name)
                loop_id = meta.get("loop_id")
                stable_id = generate_stable_id(debate_id, loop_id)

                # Get preview from final answer or topic
                final_answer = meta.get("final_answer", "")
                preview = final_answer[:500] if final_answer else meta.get("topic", "")[:500]

                debate = PublicDebate(
                    id=stable_id,
                    title=meta.get("title", replay_path.name),
                    topic=meta.get("topic", ""),
                    created_at=meta.get("created_at", ""),
                    agents=agents,
                    rounds=meta.get("rounds", 0),
                    consensus_reached=meta.get("consensus_reached", False),
                    winner=meta.get("winner"),
                    preview=preview,
                )
                debates.append(debate)

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to load replay meta %s: %s", meta_path, e)
                continue

        # Apply pagination
        return debates[offset : offset + limit]

    def _find_debate_by_id(self, nomic_dir: Path | None, stable_id: str) -> dict | None:
        """Find a specific debate by its stable ID (bounded search)."""
        if not nomic_dir:
            return None

        replays_dir = Path(nomic_dir) / "replays"
        if not replays_dir.exists():
            return None

        max_search = 1000  # Reasonable search limit to prevent DoS
        searched = 0
        for replay_path in replays_dir.iterdir():
            if searched >= max_search:
                logger.warning("Gallery search exceeded limit (%s) for %s", max_search, stable_id)
                return None  # Not found within limit
            if not replay_path.is_dir():
                continue
            searched += 1

            meta_path = replay_path / "meta.json"
            if not meta_path.exists():
                continue

            try:
                with open(meta_path) as f:
                    meta = json.load(f)

                debate_id = meta.get("debate_id", replay_path.name)
                loop_id = meta.get("loop_id")
                current_stable_id = generate_stable_id(debate_id, loop_id)

                if current_stable_id == stable_id:
                    # Load full debate data including events
                    events_path = replay_path / "events.jsonl"
                    events = []
                    if events_path.exists():
                        with open(events_path) as ef:
                            for line in ef:
                                try:
                                    events.append(json.loads(line))
                                except json.JSONDecodeError:
                                    continue

                    return {
                        "id": stable_id,
                        "debate_id": debate_id,
                        "loop_id": loop_id,
                        **meta,
                        "events": events,
                    }

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to load replay %s: %s", replay_path, e)
                continue

        return None


# Convenience function to register with handler registry
def get_handler_class() -> type[GalleryHandler]:
    """Return the handler class for registration."""
    return GalleryHandler
