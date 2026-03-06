"""Quality filtering and deduplication for ingested ideas.

QualityFilter: scores ideas on text quality and relevance.
DeduplicationEngine: detects exact and near-duplicate ideas.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import TYPE_CHECKING

from aragora.ideacloud.graph.node import IdeaNode

if TYPE_CHECKING:
    from aragora.ideacloud.graph.graph import IdeaGraph

logger = logging.getLogger(__name__)


class QualityFilter:
    """Score and filter ideas by quality and relevance.

    Scoring (0.0 - 1.0):
    - Text length (too short or empty = low)
    - Has meaningful content (not just links/hashtags)
    - Has title
    - Has tags
    """

    def __init__(self, min_score: float = 0.3) -> None:
        self.min_score = min_score

    def score(self, node: IdeaNode) -> float:
        """Return 0.0-1.0 quality score for a node."""
        score = 0.0

        # Has title (0.3)
        if node.title and len(node.title.strip()) > 5:
            score += 0.3

        # Has body content (0.3)
        body_text = _strip_links_and_mentions(node.body)
        if len(body_text.strip()) > 20:
            score += 0.3
        elif len(body_text.strip()) > 5:
            score += 0.15

        # Has tags (0.2)
        if node.tags:
            score += min(0.2, len(node.tags) * 0.05)

        # Has source URL (0.1)
        if node.source_url:
            score += 0.1

        # Has author (0.1)
        if node.source_author:
            score += 0.1

        return min(1.0, score)

    def is_acceptable(self, node: IdeaNode) -> bool:
        """Check if node meets minimum quality threshold."""
        return self.score(node) >= self.min_score

    def filter_batch(self, nodes: list[IdeaNode]) -> list[IdeaNode]:
        """Filter a batch of nodes, returning only acceptable ones."""
        accepted = []
        rejected = 0
        for node in nodes:
            if self.is_acceptable(node):
                node.relevance_score = self.score(node)
                accepted.append(node)
            else:
                rejected += 1
        if rejected:
            logger.info("Quality filter: accepted %d, rejected %d", len(accepted), rejected)
        return accepted


class DeduplicationEngine:
    """Detect duplicate ideas using content hashing.

    Exact dedup: SHA-256 hash of normalized text.
    Near dedup: Jaccard similarity of word sets.
    """

    def __init__(self, similarity_threshold: float = 0.85) -> None:
        self.similarity_threshold = similarity_threshold

    def find_duplicates(
        self,
        node: IdeaNode,
        graph: IdeaGraph,
    ) -> list[str]:
        """Find duplicate node IDs in the graph.

        Returns list of existing node IDs that are duplicates of ``node``.
        """
        duplicates: list[str] = []
        node_hash = _normalize_hash(node.title + " " + node.body)
        node_words = _word_set(node.title + " " + node.body)

        for existing in graph.nodes.values():
            if existing.id == node.id:
                continue

            # Exact hash match
            existing_hash = _normalize_hash(existing.title + " " + existing.body)
            if node_hash == existing_hash:
                duplicates.append(existing.id)
                continue

            # Near-duplicate via Jaccard
            existing_words = _word_set(existing.title + " " + existing.body)
            if node_words and existing_words:
                jaccard = len(node_words & existing_words) / len(node_words | existing_words)
                if jaccard >= self.similarity_threshold:
                    duplicates.append(existing.id)

        return duplicates

    def deduplicate_batch(
        self,
        nodes: list[IdeaNode],
        graph: IdeaGraph,
    ) -> list[IdeaNode]:
        """Remove duplicates from a batch against the existing graph.

        Also removes intra-batch duplicates.
        """
        seen_hashes: set[str] = set()
        unique: list[IdeaNode] = []

        for node in nodes:
            h = _normalize_hash(node.title + " " + node.body)

            # Intra-batch dedup
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            # Against existing graph
            if self.find_duplicates(node, graph):
                logger.debug("Skipping duplicate: %s", node.title[:60])
                continue

            unique.append(node)

        skipped = len(nodes) - len(unique)
        if skipped:
            logger.info("Dedup: kept %d, skipped %d duplicates", len(unique), skipped)
        return unique


# ---- Helpers ----


def _strip_links_and_mentions(text: str) -> str:
    """Remove URLs and @mentions from text for quality scoring."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    return text


def _normalize_hash(text: str) -> str:
    """Normalize text and compute SHA-256 hash."""
    # Lowercase, collapse whitespace, strip punctuation
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    normalized = re.sub(r"[^\w\s]", "", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _word_set(text: str) -> set[str]:
    """Extract set of lowercase words (3+ chars) for Jaccard similarity."""
    return {w for w in re.findall(r"[a-z]{3,}", text.lower())}
