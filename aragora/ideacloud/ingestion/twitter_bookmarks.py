"""Twitter bookmarks ingestor — parse Twitter data export.

Twitter data exports contain a ``data/bookmarks.js`` file with format:
    window.YTD.bookmark.part0 = [
      {"bookmark": {"tweetId": "123456789"}},
      ...
    ]

Some exports include full tweet objects with text, author, etc.
Others only have tweetIds requiring separate enrichment.

Usage:
    ingestor = TwitterBookmarksIngestor()
    nodes = await ingestor.ingest("path/to/data/bookmarks.js")
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from aragora.ideacloud.graph.node import IdeaNode, _generate_id
from aragora.ideacloud.ingestion.base import BaseIdeaIngestor

logger = logging.getLogger(__name__)

# Pattern to strip the JS variable assignment wrapper
JS_WRAPPER_PATTERN = re.compile(r"^window\.YTD\.\w+\.part\d+\s*=\s*", re.MULTILINE)


class TwitterBookmarksIngestor(BaseIdeaIngestor):
    """Ingest bookmarked tweets from Twitter data export."""

    source_type = "twitter_bookmark"

    async def ingest(self, source: str | Path) -> list[IdeaNode]:
        """Parse bookmarks.js and return IdeaNodes.

        Args:
            source: Path to the bookmarks.js file from Twitter data export.

        Returns:
            List of IdeaNode objects, one per bookmark.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Bookmarks file not found: {path}")

        raw = path.read_text(encoding="utf-8")
        data = _parse_twitter_js(raw)

        nodes: list[IdeaNode] = []
        for entry in data:
            node = _bookmark_entry_to_node(entry)
            if node:
                nodes.append(node)

        logger.info("Parsed %d bookmarks from %s", len(nodes), path.name)
        return nodes


def _parse_twitter_js(raw: str) -> list[dict[str, Any]]:
    """Parse Twitter JS export format to JSON array.

    Handles both:
    - ``window.YTD.bookmark.part0 = [...]`` wrapper
    - Raw JSON arrays
    """
    # Strip JS wrapper if present
    stripped = JS_WRAPPER_PATTERN.sub("", raw).strip()
    # Remove trailing semicolons
    if stripped.endswith(";"):
        stripped = stripped[:-1].strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse Twitter JS: %s", exc)
        return []

    if not isinstance(data, list):
        logger.warning("Expected list, got %s", type(data).__name__)
        return []

    return data


def _bookmark_entry_to_node(entry: dict[str, Any]) -> IdeaNode | None:
    """Convert a single bookmark entry to an IdeaNode.

    Handles multiple Twitter export formats:
    - {"bookmark": {"tweetId": "..."}} (minimal)
    - {"bookmark": {"tweetId": "...", "fullText": "..."}} (with text)
    - Direct tweet objects with "full_text", "user", etc. (legacy)
    """
    bookmark = entry.get("bookmark", entry)  # Unwrap if nested

    tweet_id = (
        bookmark.get("tweetId")
        or bookmark.get("tweet_id")
        or bookmark.get("id_str")
        or bookmark.get("id")
    )
    if not tweet_id:
        return None

    # Extract text
    full_text = bookmark.get("fullText") or bookmark.get("full_text") or bookmark.get("text") or ""

    # Extract author
    user = bookmark.get("user", {})
    screen_name = (
        bookmark.get("screenName") or bookmark.get("screen_name") or user.get("screen_name") or ""
    )

    # Build URL
    tweet_url = (
        f"https://x.com/{screen_name}/status/{tweet_id}"
        if screen_name
        else f"https://x.com/i/status/{tweet_id}"
    )

    # Title: first line or first 100 chars
    title = _extract_title(full_text)

    # Extract hashtags as tags
    tags = _extract_hashtags(full_text)

    return IdeaNode(
        id=_generate_id(),
        title=title,
        body=full_text,
        source_type="twitter_bookmark",
        source_url=tweet_url,
        source_author=f"@{screen_name}" if screen_name else None,
        tags=tags,
        node_type="idea_insight",
        pipeline_status="inbox",
    )


def _extract_title(text: str) -> str:
    """Extract a title from tweet text (first sentence or 100 chars)."""
    if not text:
        return "Untitled Bookmark"

    # First sentence
    sentences = re.split(r"[.!?\n]", text)
    first = sentences[0].strip() if sentences else text.strip()

    if len(first) > 100:
        return first[:97] + "..."
    return first or "Untitled Bookmark"


def _extract_hashtags(text: str) -> list[str]:
    """Extract hashtags from tweet text."""
    return re.findall(r"#(\w+)", text)
