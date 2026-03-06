"""Pulse → IdeaCloud bridge.

Converts trending topics from aragora's Pulse system into IdeaNodes
for ingestion into the Idea Cloud graph.

Usage:
    bridge = PulseBridge(
        relevance_keywords=["ai", "security", "agents"],
        min_volume=100,
        categories=["tech", "ai", "science"],
    )
    nodes = await bridge.fetch_and_convert(
        platforms=["hackernews", "reddit"],
        limit_per_platform=5,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aragora.ideacloud.graph.node import IdeaNode

logger = logging.getLogger(__name__)

# Platform → source_type mapping
_PLATFORM_SOURCE_MAP = {
    "hackernews": "pulse_hackernews",
    "reddit": "pulse_reddit",
    "twitter": "pulse_twitter",
    "arxiv": "pulse_arxiv",
    "github": "pulse_github",
    "google_trends": "pulse_google_trends",
    "lobsters": "pulse_lobsters",
    "devto": "pulse_devto",
    "producthunt": "pulse_producthunt",
    "substack": "pulse_substack",
}


@dataclass
class PulseBridge:
    """Bridge between Pulse trending topics and IdeaCloud nodes.

    Fetches trending topics from configured Pulse platforms, filters
    by relevance keywords and engagement volume, then converts to
    IdeaNodes ready for IdeaCloud ingestion.
    """

    relevance_keywords: list[str] = field(default_factory=list)
    min_volume: int = 50
    categories: list[str] = field(default_factory=lambda: ["tech", "ai", "science"])

    async def fetch_and_convert(
        self,
        platforms: list[str] | None = None,
        limit_per_platform: int = 5,
    ) -> list[IdeaNode]:
        """Fetch trending topics and convert to IdeaNodes.

        Args:
            platforms: Platforms to query (default: hackernews, reddit).
            limit_per_platform: Max topics per platform.

        Returns:
            List of IdeaNodes created from trending topics.
        """
        platforms = platforms or ["hackernews", "reddit"]
        topics = await self._fetch_topics(platforms, limit_per_platform)

        # Filter by volume and category
        filtered = self._filter_topics(topics)

        # Convert to IdeaNodes
        nodes = [self._topic_to_node(t) for t in filtered]
        logger.info(
            "Pulse bridge: %d topics → %d filtered → %d nodes",
            len(topics),
            len(filtered),
            len(nodes),
        )
        return nodes

    async def _fetch_topics(
        self,
        platforms: list[str],
        limit: int,
    ) -> list[Any]:
        """Fetch trending topics from Pulse.

        Tries to use PulseManager from aragora.pulse.
        Falls back gracefully if Pulse module is unavailable.
        """
        try:
            from aragora.pulse import PulseManager
            from aragora.pulse.ingestor import (
                HackerNewsIngestor,
                RedditIngestor,
            )
        except ImportError:
            logger.warning("Pulse module not available; cannot fetch trending topics")
            return []

        manager = PulseManager()

        # Register available ingestors
        _ingestor_map = {
            "hackernews": HackerNewsIngestor,
            "reddit": RedditIngestor,
        }

        # Try to import optional ingestors
        try:
            from aragora.pulse.ingestor import ArxivIngestor

            _ingestor_map["arxiv"] = ArxivIngestor
        except ImportError:
            pass

        try:
            from aragora.pulse.ingestor import GitHubTrendingIngestor

            _ingestor_map["github"] = GitHubTrendingIngestor
        except ImportError:
            pass

        try:
            from aragora.pulse.ingestor import LobstersIngestor

            _ingestor_map["lobsters"] = LobstersIngestor
        except ImportError:
            pass

        try:
            from aragora.pulse.ingestor import DevToIngestor

            _ingestor_map["devto"] = DevToIngestor
        except ImportError:
            pass

        for name in platforms:
            cls = _ingestor_map.get(name)
            if cls:
                try:
                    manager.add_ingestor(name, cls())
                except Exception as exc:
                    logger.warning("Failed to create %s ingestor: %s", name, exc)
            else:
                logger.debug("No ingestor available for platform: %s", name)

        filters: dict[str, Any] = {}
        if self.min_volume > 0:
            filters["min_volume"] = self.min_volume
        if self.categories:
            filters["categories"] = self.categories

        try:
            topics = await manager.get_trending_topics(
                platforms=platforms,
                limit_per_platform=limit,
                filters=filters,
            )
            return topics
        except Exception as exc:
            logger.warning("Failed to fetch Pulse topics: %s", exc)
            return []

    def _filter_topics(self, topics: list[Any]) -> list[Any]:
        """Filter topics by relevance keywords and engagement."""
        if not self.relevance_keywords:
            return topics

        filtered = []
        keywords_lower = [k.lower() for k in self.relevance_keywords]

        for topic in topics:
            text = getattr(topic, "topic", str(topic)).lower()
            category = getattr(topic, "category", "").lower()

            # Check if any keyword appears in topic text or category
            matches = sum(1 for kw in keywords_lower if kw in text or kw in category)

            if matches > 0 or not self.relevance_keywords:
                filtered.append(topic)

        return filtered

    def _topic_to_node(self, topic: Any) -> IdeaNode:
        """Convert a TrendingTopic to an IdeaNode."""
        platform = getattr(topic, "platform", "pulse")
        topic_text = getattr(topic, "topic", str(topic))
        volume = getattr(topic, "volume", 0)
        category = getattr(topic, "category", "")
        raw_data = getattr(topic, "raw_data", {})

        # Build tags from category and platform
        tags = [f"pulse-{platform}"]
        if category:
            tags.append(category)
        # Add any keyword matches as tags
        for kw in self.relevance_keywords:
            if kw.lower() in topic_text.lower():
                tags.append(kw.lower())

        # Extract URL from raw data if available
        source_url = raw_data.get("url", raw_data.get("link", ""))

        # Build title — truncate long topics
        title = topic_text[:120]
        if len(topic_text) > 120:
            title += "..."

        # Construct body with engagement context
        body_parts = [topic_text]
        if volume:
            body_parts.append(f"\nEngagement: {volume}")
        if category:
            body_parts.append(f"Category: {category}")
        if source_url:
            body_parts.append(f"Source: {source_url}")

        # Include any extra context from raw_data
        for key in ("score", "num_comments", "points", "stars"):
            val = raw_data.get(key)
            if val:
                body_parts.append(f"{key}: {val}")

        source_type = _PLATFORM_SOURCE_MAP.get(platform, f"pulse_{platform}")

        return IdeaNode(
            title=title,
            body="\n".join(body_parts),
            tags=tags,
            source_type=source_type,
            source_url=source_url or None,
            source_author=raw_data.get("author", raw_data.get("by", "")),
            node_type="idea_insight",
            relevance_score=min(1.0, volume / 1000.0) if volume else 0.5,
        )
