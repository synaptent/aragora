"""Manual paste ingestor — URL or free-text input.

Handles:
- URLs: creates a node with the URL as source
- Tweet URLs: extracts tweet metadata from URL structure
- Plain text: uses as title + body

Usage:
    ingestor = ManualPasteIngestor()
    nodes = await ingestor.ingest("https://example.com/article")
    nodes = await ingestor.ingest("Some interesting thought about AI safety")
"""

from __future__ import annotations

import logging
import re

from aragora.ideacloud.graph.node import IdeaNode, _generate_id
from aragora.ideacloud.ingestion.base import BaseIdeaIngestor

logger = logging.getLogger(__name__)

# URL detection
URL_PATTERN = re.compile(r"https?://\S+")

# Twitter/X URL pattern
TWEET_URL_PATTERN = re.compile(r"https?://(?:twitter\.com|x\.com)/(\w+)/status/(\d+)")


class ManualPasteIngestor(BaseIdeaIngestor):
    """Ingest manually pasted content (URL, tweet text, or free text)."""

    source_type = "manual"

    async def ingest(self, source: str) -> list[IdeaNode]:
        """Parse pasted content and return IdeaNodes.

        Args:
            source: URL string, tweet text, or free-form text.

        Returns:
            List containing one IdeaNode.
        """
        source = source.strip()
        if not source:
            return []

        # Check if it's a tweet URL
        tweet_match = TWEET_URL_PATTERN.search(source)
        if tweet_match:
            return [_tweet_url_to_node(tweet_match, source)]

        # Check if it's a generic URL
        url_match = URL_PATTERN.match(source)
        if url_match:
            return [_url_to_node(source)]

        # Free text
        return [_text_to_node(source)]

    async def ingest_with_context(
        self,
        content: str,
        title: str | None = None,
        source_url: str | None = None,
        source_author: str | None = None,
        tags: list[str] | None = None,
    ) -> IdeaNode:
        """Ingest with explicit metadata (for programmatic use).

        Args:
            content: The body text.
            title: Optional title (derived from content if not provided).
            source_url: Optional source URL.
            source_author: Optional author.
            tags: Optional tags.

        Returns:
            Single IdeaNode.
        """
        if not title:
            title = _derive_title(content)

        return IdeaNode(
            id=_generate_id(),
            title=title,
            body=content,
            source_type="manual",
            source_url=source_url,
            source_author=source_author,
            tags=tags or [],
            node_type="idea_insight",
            pipeline_status="inbox",
        )


def _tweet_url_to_node(match: re.Match, full_text: str) -> IdeaNode:
    """Create a node from a tweet URL."""
    username = match.group(1)
    url = match.group(0)

    # Use the full pasted text as body (may contain more than just the URL)
    body = full_text.replace(url, "").strip()

    return IdeaNode(
        id=_generate_id(),
        title=f"Tweet by @{username}",
        body=body if body else f"Tweet: {url}",
        source_type="manual",
        source_url=url,
        source_author=f"@{username}",
        tags=[],
        node_type="idea_insight",
        pipeline_status="inbox",
    )


def _url_to_node(url: str) -> IdeaNode:
    """Create a node from a generic URL."""
    # Extract domain for basic title
    domain_match = re.search(r"https?://(?:www\.)?([^/]+)", url)
    domain = domain_match.group(1) if domain_match else "unknown"

    return IdeaNode(
        id=_generate_id(),
        title=f"Link from {domain}",
        body=f"Source: {url}",
        source_type="manual",
        source_url=url,
        tags=[],
        node_type="idea_insight",
        pipeline_status="inbox",
    )


def _text_to_node(text: str) -> IdeaNode:
    """Create a node from free-form text."""
    title = _derive_title(text)

    return IdeaNode(
        id=_generate_id(),
        title=title,
        body=text,
        source_type="manual",
        tags=[],
        node_type="idea_insight",
        pipeline_status="inbox",
    )


def _derive_title(text: str) -> str:
    """Derive a title from the first line or first 100 chars."""
    first_line = text.split("\n")[0].strip()
    if len(first_line) > 100:
        return first_line[:97] + "..."
    return first_line or "Untitled Idea"
