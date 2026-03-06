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


class TwitterLikesIngestor(BaseIdeaIngestor):
    """Ingest liked tweets from Twitter data export."""

    source_type = "twitter_like"

    async def ingest(self, source: str | Path) -> list[IdeaNode]:
        """Parse like.js and return IdeaNodes.

        Args:
            source: Path to the like.js file from Twitter data export.

        Returns:
            List of IdeaNode objects, one per like.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Likes file not found: {path}")

        raw = path.read_text(encoding="utf-8")
        data = _parse_twitter_js(raw)

        nodes: list[IdeaNode] = []
        for entry in data:
            # Unwrap "like" wrapper if present
            like_data = entry.get("like", entry)
            node = _bookmark_entry_to_node({"bookmark": like_data})
            if node:
                node.source_type = "twitter_like"
                nodes.append(node)

        logger.info("Parsed %d likes from %s", len(nodes), path.name)
        return nodes
