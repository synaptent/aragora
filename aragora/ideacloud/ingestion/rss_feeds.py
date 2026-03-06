"""RSS feed ingestor — wraps aragora.connectors.feeds for IdeaCloud.

Fetches entries from configured RSS/Atom feeds and converts them to
IdeaNodes with quality filtering and relevance scoring.

Usage:
    ingestor = RSSFeedIngestor()
    ingestor.add_feed("https://blog.example.com/feed.xml", name="Example Blog")
    nodes = await ingestor.ingest()

The ingestor delegates the actual feed parsing to ``FeedIngestor`` from
``aragora.connectors.feeds``, then wraps the entries as IdeaNodes with
relevance filtering based on configurable topic keywords.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from aragora.ideacloud.graph.node import IdeaNode, _generate_id, _now_iso
from aragora.ideacloud.ingestion.base import BaseIdeaIngestor

logger = logging.getLogger(__name__)


@dataclass
class FeedConfig:
    """Configuration for a single RSS feed source."""

    url: str
    name: str = ""
    category: str = ""
    priority: int = 5
    max_entries: int = 50
    enabled: bool = True
    topic_keywords: list[str] = field(default_factory=list)


class RSSFeedIngestor(BaseIdeaIngestor):
    """Ingest RSS/Atom feed entries into IdeaCloud as IdeaNodes.

    Wraps ``aragora.connectors.feeds.FeedIngestor`` for the actual
    fetching and XML parsing, adding IdeaCloud-specific quality
    filtering and relevance scoring.

    Args:
        relevance_keywords: Keywords that indicate relevant content.
            Entries matching more keywords get higher relevance scores.
            If empty, all entries are accepted.
        min_relevance: Minimum relevance score (0-1) to include an entry.
            Only applies when relevance_keywords is non-empty.
    """

    def __init__(
        self,
        relevance_keywords: list[str] | None = None,
        min_relevance: float = 0.0,
    ) -> None:
        self.feeds: list[FeedConfig] = []
        self.relevance_keywords = [k.lower() for k in (relevance_keywords or [])]
        self.min_relevance = min_relevance

    def add_feed(
        self,
        url: str,
        name: str = "",
        category: str = "",
        priority: int = 5,
        max_entries: int = 50,
        topic_keywords: list[str] | None = None,
    ) -> None:
        """Register a feed source for ingestion."""
        self.feeds.append(
            FeedConfig(
                url=url,
                name=name or url,
                category=category,
                priority=priority,
                max_entries=max_entries,
                topic_keywords=topic_keywords or [],
            )
        )

    def remove_feed(self, url: str) -> bool:
        """Remove a feed by URL. Returns True if found and removed."""
        before = len(self.feeds)
        self.feeds = [f for f in self.feeds if f.url != url]
        return len(self.feeds) < before

    async def ingest(self, source: str = "") -> list[IdeaNode]:
        """Ingest all configured feeds and return IdeaNodes.

        Args:
            source: Ignored (feeds are configured via add_feed).

        Returns:
            List of IdeaNodes created from feed entries.
        """
        if not self.feeds:
            logger.warning("No feeds configured for RSS ingestion")
            return []

        all_nodes: list[IdeaNode] = []

        try:
            from aragora.connectors.feeds import FeedEntry, FeedIngestor, FeedSource
        except ImportError:
            logger.warning(
                "aragora.connectors.feeds not available; falling back to stub RSS parsing"
            )
            return await self._fallback_ingest()

        feed_ingestor = FeedIngestor()

        for feed_config in self.feeds:
            if not feed_config.enabled:
                continue

            feed_source = FeedSource(
                url=feed_config.url,
                name=feed_config.name,
                category=feed_config.category,
                priority=feed_config.priority,
                max_entries=feed_config.max_entries,
            )
            feed_ingestor.add_source(feed_source)

        try:
            entries: list[FeedEntry] = await feed_ingestor.fetch_all()
        except Exception as exc:
            logger.error("Failed to fetch feeds: %s", exc)
            return []

        for entry in entries:
            node = self._entry_to_node(entry)
            if node and self._passes_relevance(node):
                all_nodes.append(node)

        logger.info(
            "RSS ingestion produced %d nodes from %d feeds",
            len(all_nodes),
            len(self.feeds),
        )
        return all_nodes

    def _entry_to_node(self, entry: Any) -> IdeaNode | None:
        """Convert a FeedEntry to an IdeaNode."""
        title = getattr(entry, "title", "") or ""
        content = getattr(entry, "content", "") or ""
        summary = getattr(entry, "summary", "") or ""
        link = getattr(entry, "link", "") or ""
        author = getattr(entry, "author", "") or ""
        categories = getattr(entry, "categories", []) or []
        published = getattr(entry, "published", "") or ""

        # Use content if available, else summary
        body = content or summary

        if not title and not body:
            return None

        # Strip HTML tags from body
        body = re.sub(r"<[^>]+>", "", body).strip()

        # Derive tags from categories
        tags = [c.lower().replace(" ", "-") for c in categories[:10]]

        node_id = _generate_id()
        content_hash = hashlib.sha256(f"{title}:{body[:500]}".encode()).hexdigest()[:16]

        return IdeaNode(
            id=node_id,
            title=title[:200],
            body=body,
            source_type="rss",
            source_url=link,
            source_author=author,
            tags=tags,
            content_hash=f"sha256:{content_hash}",
            created_at=published or _now_iso(),
            updated_at=_now_iso(),
        )

    def _passes_relevance(self, node: IdeaNode) -> bool:
        """Check if a node passes the relevance filter.

        If no relevance_keywords are set, all nodes pass.
        Otherwise, compute a relevance score from keyword overlap.
        """
        if not self.relevance_keywords:
            return True

        text = (node.title + " " + node.body + " " + " ".join(node.tags)).lower()
        matched = sum(1 for kw in self.relevance_keywords if kw in text)
        score = matched / len(self.relevance_keywords) if self.relevance_keywords else 0
        node.relevance_score = score
        return score >= self.min_relevance

    async def _fallback_ingest(self) -> list[IdeaNode]:
        """Minimal fallback when feed connector is unavailable.

        Uses standard library XML parsing for basic RSS/Atom support.
        """
        nodes: list[IdeaNode] = []

        try:
            import xml.etree.ElementTree as ET
            from urllib.request import urlopen
        except ImportError:
            return nodes

        for feed_config in self.feeds:
            if not feed_config.enabled:
                continue

            try:
                with urlopen(feed_config.url, timeout=30) as resp:
                    data = resp.read()
                root = ET.fromstring(data)  # noqa: S314

                # Try RSS 2.0 format
                items = root.findall(".//item")
                if not items:
                    # Try Atom format
                    ns = {"atom": "http://www.w3.org/2005/Atom"}
                    items = root.findall(".//atom:entry", ns)

                for item in items[: feed_config.max_entries]:
                    title_el = item.find("title")
                    desc_el = item.find("description") or item.find(
                        "{http://www.w3.org/2005/Atom}summary"
                    )
                    link_el = item.find("link")

                    title = title_el.text if title_el is not None else ""
                    body = desc_el.text if desc_el is not None else ""
                    link = ""
                    if link_el is not None:
                        link = link_el.text or link_el.get("href", "")

                    if body:
                        body = re.sub(r"<[^>]+>", "", body).strip()

                    if title or body:
                        node = IdeaNode(
                            id=_generate_id(),
                            title=(title or "")[:200],
                            body=body or "",
                            source_type="rss",
                            source_url=link or "",
                            source_author=feed_config.name,
                            tags=[feed_config.category] if feed_config.category else [],
                        )
                        if self._passes_relevance(node):
                            nodes.append(node)

            except Exception as exc:
                logger.error(
                    "Fallback RSS fetch failed for %s: %s",
                    feed_config.url,
                    exc,
                )

        return nodes
