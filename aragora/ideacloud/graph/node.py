"""IdeaNode — the atomic unit of the Idea Cloud.

Each node is both:
- An Obsidian markdown file (human-readable, editable, interlinked)
- A structured object for aragora (searchable, queryable, pipeline-compatible)

Frontmatter holds all metadata; the markdown body is free-form content.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

# Wiki-link pattern: [[Target]] or [[Target|Display Text]]
WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# Valid node types (aligned with KnowledgeMound NodeType literals)
IdeaNodeType = Literal[
    "idea_concept",
    "idea_insight",
    "idea_evidence",
    "idea_hypothesis",
    "idea_question",
    "idea_observation",
    "idea_cluster",
]

# Pipeline lifecycle stages
PipelineStatus = Literal["inbox", "candidate", "prioritized", "exported"]

# Source types
SourceType = Literal[
    "twitter_bookmark",
    "twitter_like",
    "rss",
    "manual",
]


def _generate_id() -> str:
    """Generate a short unique ID with ic_ prefix."""
    return f"ic_{uuid.uuid4().hex[:7]}"


def _content_hash(text: str) -> str:
    """SHA-256 hash of content for change detection and dedup."""
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def _now_iso() -> str:
    """Current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class IdeaNode:
    """An idea in the cloud with dual Obsidian/aragora representation."""

    # Identity
    id: str = field(default_factory=_generate_id)
    title: str = ""

    # Content (markdown body, separate from frontmatter)
    body: str = ""

    # Source tracking
    source_type: str = "manual"  # SourceType
    source_url: str | None = None
    source_author: str | None = None
    date: str = field(default_factory=_now_iso)

    # Tags (human + auto)
    tags: list[str] = field(default_factory=list)

    # Aragora metadata
    node_type: str = "idea_insight"  # IdeaNodeType
    cluster_id: str | None = None
    pipeline_status: str = "inbox"  # PipelineStatus
    relevance_score: float = 0.5
    confidence: float = 0.5

    # KnowledgeMound sync
    km_synced: bool = False
    km_node_id: str | None = None

    # Provenance
    content_hash: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = _content_hash(self.title + self.body)

    # ---- Wiki-link extraction ----

    def extract_wiki_links(self) -> list[str]:
        """Extract all [[wiki-link]] targets from the body."""
        return WIKI_LINK_PATTERN.findall(self.body)

    # ---- Frontmatter serialization ----

    def to_frontmatter_dict(self) -> dict[str, Any]:
        """Serialize metadata to a dict suitable for YAML frontmatter."""
        fm: dict[str, Any] = {
            "title": self.title,
            "source_type": self.source_type,
            "date": self.date,
            "tags": self.tags,
            # Aragora metadata
            "id": self.id,
            "node_type": self.node_type,
            "pipeline_status": self.pipeline_status,
            "relevance_score": self.relevance_score,
            "confidence": self.confidence,
            "km_synced": self.km_synced,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        # Optional fields — only include if set
        if self.source_url:
            fm["source_url"] = self.source_url
        if self.source_author:
            fm["source_author"] = self.source_author
        if self.cluster_id:
            fm["cluster_id"] = self.cluster_id
        if self.km_node_id:
            fm["km_node_id"] = self.km_node_id
        return fm

    @classmethod
    def from_frontmatter_dict(cls, fm: dict[str, Any], body: str = "") -> IdeaNode:
        """Deserialize from frontmatter dict + body text."""
        return cls(
            id=fm.get("id", _generate_id()),
            title=fm.get("title", ""),
            body=body,
            source_type=fm.get("source_type", "manual"),
            source_url=fm.get("source_url"),
            source_author=fm.get("source_author"),
            date=fm.get("date", _now_iso()),
            tags=fm.get("tags", []),
            node_type=fm.get("node_type", "idea_insight"),
            cluster_id=fm.get("cluster_id"),
            pipeline_status=fm.get("pipeline_status", "inbox"),
            relevance_score=float(fm.get("relevance_score", 0.5)),
            confidence=float(fm.get("confidence", 0.5)),
            km_synced=bool(fm.get("km_synced", False)),
            km_node_id=fm.get("km_node_id"),
            content_hash=fm.get("content_hash", ""),
            created_at=fm.get("created_at", _now_iso()),
            updated_at=fm.get("updated_at", _now_iso()),
        )

    # ---- Content update ----

    def update_content(self, title: str | None = None, body: str | None = None) -> None:
        """Update content and refresh hash + timestamp."""
        if title is not None:
            self.title = title
        if body is not None:
            self.body = body
        self.content_hash = _content_hash(self.title + self.body)
        self.updated_at = _now_iso()

    # ---- Searchable text ----

    @property
    def searchable_text(self) -> str:
        """Combined text for search indexing."""
        parts = [self.title, self.body]
        parts.extend(self.tags)
        if self.source_author:
            parts.append(self.source_author)
        return " ".join(parts).lower()

    def __repr__(self) -> str:
        return f"IdeaNode(id={self.id!r}, title={self.title[:50]!r}, tags={self.tags})"
