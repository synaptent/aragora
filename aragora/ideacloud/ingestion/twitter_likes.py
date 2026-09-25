"""Twitter likes ingestor — parse Twitter data export likes.

Twitter data exports contain a ``data/like.js`` file with format:
    window.YTD.like.part0 = [
      {"like": {"tweetId": "123456789", "fullText": "..."}},
      ...
    ]

Reuses the same parsing logic as bookmarks with different source_type.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aragora.ideacloud.graph.node import IdeaNode
from aragora.ideacloud.ingestion.base import BaseIdeaIngestor
from aragora.ideacloud.ingestion.twitter_bookmarks import (
    _parse_twitter_js,
    _bookmark_entry_to_node,
)

logger = logging.getLogger(__name__)

__all__ = [
    "TwitterLikesIngestor",
    "_like_entry_to_node",
    "_parse_twitter_js",
]


def _like_entry_to_node(
    entry: dict[str, object], *, source_type: str = "twitter_like"
) -> IdeaNode | None:
    """Convert one like export entry into an IdeaNode when possible."""

    like_data = entry.get("like", entry)
    node = _bookmark_entry_to_node({"bookmark": like_data})
    if node:
        node.source_type = source_type
    return node


class TwitterLikesIngestor(BaseIdeaIngestor):
    """Ingest liked tweets from Twitter data export."""

    source_type = "twitter_like"

    async def ingest(self, source: str | Path) -> list[IdeaNode]:
        """Parse like.js — or fetch live via ``api:`` — into IdeaNodes.

        Args:
            source: Path to the like.js file from Twitter data export, or an
                ``api:`` string (optionally ``api:<max_items>``) to fetch new
                likes from the X API v2 (OAuth2 user context).

        Returns:
            List of IdeaNode objects, one per like.
        """
        from aragora.ideacloud.ingestion.x_api import fetch_live_entries, is_api_source

        if is_api_source(source):
            entries, self._pending_commit = await fetch_live_entries(self.source_type, str(source))
            api_nodes = [
                node
                for entry in entries
                if (node := _like_entry_to_node({"like": entry}, source_type=self.source_type))
            ]
            logger.info("Ingested %d likes from X API", len(api_nodes))
            return api_nodes

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Likes file not found: {path}")

        raw = path.read_text(encoding="utf-8")
        data = _parse_twitter_js(raw)

        nodes: list[IdeaNode] = []
        for entry in data:
            node = _like_entry_to_node(entry, source_type=self.source_type)
            if node:
                nodes.append(node)

        logger.info("Parsed %d likes from %s", len(nodes), path.name)
        return nodes
