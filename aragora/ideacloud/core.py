"""IdeaCloud — the main orchestrator for the Idea Cloud system.

Ties together the graph, storage, ingestion, and operations layers
into a single high-level API.

Usage:
    cloud = IdeaCloud(".aragora_ideas")
    cloud.load()

    # Ingest from various sources
    cloud.ingest_manual("https://example.com/article", title="...", tags=[...])
    await cloud.ingest_twitter_bookmarks("path/to/bookmarks.js")

    # Search and explore
    results = cloud.search("prompt injection")
    cluster = cloud.get_cluster("cl_abc1234")

    # Auto-organize
    cloud.auto_link()
    cloud.auto_cluster()

    # Export for debate
    propositions = cloud.cluster_summary("cl_abc1234")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aragora.ideacloud.graph.cluster import IdeaCluster
from aragora.ideacloud.graph.edge import IdeaEdge
from aragora.ideacloud.graph.graph import IdeaGraph
from aragora.ideacloud.graph.node import IdeaNode
from aragora.ideacloud.graph import operations as ops
from aragora.ideacloud.ingestion.quality import DeduplicationEngine, QualityFilter

logger = logging.getLogger(__name__)

# Default vault location (relative to workspace root)
DEFAULT_VAULT_PATH = ".aragora_ideas"


class IdeaCloud:
    """High-level API for the Idea Cloud system.

    Orchestrates graph, storage, ingestion, and operations.
    """

    def __init__(
        self,
        vault_path: str | Path = DEFAULT_VAULT_PATH,
        min_quality: float = 0.3,
        dedup_threshold: float = 0.85,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.graph = IdeaGraph(self.vault_path)
        self.quality_filter = QualityFilter(min_score=min_quality)
        self.dedup_engine = DeduplicationEngine(similarity_threshold=dedup_threshold)

    # ---- Lifecycle ----

    def load(self) -> int:
        """Load the idea graph from vault.

        Returns:
            Number of nodes loaded.
        """
        return self.graph.load()

    def save(self) -> None:
        """Persist all changes to vault."""
        self.graph.save()

    @property
    def stats(self) -> dict[str, Any]:
        """Graph statistics."""
        return self.graph.stats

    # ---- Ingestion ----

    def add(self, node: IdeaNode, skip_quality: bool = False) -> bool:
        """Add a single idea node to the graph.

        Runs quality filter and deduplication unless ``skip_quality=True``.

        Returns:
            True if added, False if rejected (low quality or duplicate).
        """
        if not skip_quality:
            if not self.quality_filter.is_acceptable(node):
                logger.debug("Rejected low-quality node: %s", node.title[:60])
                return False
            node.relevance_score = self.quality_filter.score(node)

            dupes = self.dedup_engine.find_duplicates(node, self.graph)
            if dupes:
                logger.debug("Rejected duplicate node: %s (matches %s)", node.title[:60], dupes)
                return False

        self.graph.add_node(node)
        return True

    async def ingest_manual(
        self,
        content: str,
        title: str | None = None,
        source_url: str | None = None,
        source_author: str | None = None,
        tags: list[str] | None = None,
    ) -> IdeaNode | None:
        """Ingest a manually pasted idea.

        Returns the created node, or None if rejected.
        """
        from aragora.ideacloud.ingestion.manual import ManualPasteIngestor

        ingestor = ManualPasteIngestor()

        if title or source_url or source_author or tags:
            node = await ingestor.ingest_with_context(
                content=content,
                title=title,
                source_url=source_url,
                source_author=source_author,
                tags=tags,
            )
            return node if self.add(node) else None

        nodes = await ingestor.ingest(content)
        if nodes and self.add(nodes[0]):
            return nodes[0]
        return None

    async def ingest_twitter_bookmarks(self, file_path: str | Path) -> list[IdeaNode]:
        """Ingest from Twitter bookmarks export.

        Returns list of successfully added nodes.
        """
        from aragora.ideacloud.ingestion.twitter_bookmarks import TwitterBookmarksIngestor

        ingestor = TwitterBookmarksIngestor()
        raw_nodes = await ingestor.ingest(file_path)
        return self._ingest_batch(raw_nodes)

    async def ingest_twitter_likes(self, file_path: str | Path) -> list[IdeaNode]:
        """Ingest from Twitter likes export.

        Returns list of successfully added nodes.
        """
        from aragora.ideacloud.ingestion.twitter_likes import TwitterLikesIngestor

        ingestor = TwitterLikesIngestor()
        raw_nodes = await ingestor.ingest(file_path)
        return self._ingest_batch(raw_nodes)

    def _ingest_batch(self, nodes: list[IdeaNode]) -> list[IdeaNode]:
        """Filter, deduplicate, and add a batch of nodes."""
        # Quality filter
        filtered = self.quality_filter.filter_batch(nodes)
        # Dedup
        unique = self.dedup_engine.deduplicate_batch(filtered, self.graph)
        # Add to graph
        added: list[IdeaNode] = []
        for node in unique:
            self.graph.add_node(node)
            added.append(node)
        logger.info("Ingested %d/%d nodes", len(added), len(nodes))
        return added

    # ---- Search ----

    def search(self, query: str, limit: int = 10) -> list[tuple[IdeaNode, float]]:
        """Search ideas by text query.

        Returns (node, relevance) tuples sorted by relevance.
        """
        return self.graph.search(query, limit=limit)

    # ---- Graph operations ----

    def auto_link(
        self,
        node_id: str | None = None,
        min_similarity: float = 0.3,
    ) -> list[IdeaEdge]:
        """Auto-create connections between related ideas.

        Args:
            node_id: Link a specific node, or None for all.
            min_similarity: Minimum similarity threshold.

        Returns:
            List of newly created edges.
        """
        new_edges = ops.auto_link(self.graph, node_id=node_id, min_similarity=min_similarity)
        if new_edges:
            self.graph.save()
        return new_edges

    def auto_cluster(self, min_cluster_size: int = 2) -> dict[str, IdeaCluster]:
        """Auto-cluster ideas based on connections and shared tags.

        Returns dict of cluster_id → IdeaCluster.
        """
        clusters = ops.auto_cluster(self.graph, min_cluster_size=min_cluster_size)
        self.graph.save()
        return clusters

    # ---- Cluster access ----

    def get_cluster(self, cluster_id: str) -> IdeaCluster | None:
        """Get a cluster by ID."""
        return self.graph.get_cluster(cluster_id)

    def list_clusters(self) -> list[IdeaCluster]:
        """List all clusters sorted by size (largest first)."""
        return sorted(
            self.graph.clusters.values(),
            key=lambda c: c.size,
            reverse=True,
        )

    def cluster_nodes(self, cluster_id: str) -> list[IdeaNode]:
        """Get all nodes in a cluster."""
        cluster = self.graph.get_cluster(cluster_id)
        if not cluster:
            return []
        return [self.graph.nodes[nid] for nid in cluster.node_ids if nid in self.graph.nodes]

    def cluster_summary(self, cluster_id: str) -> str:
        """Generate a text summary of a cluster for debate proposition generation.

        Returns a markdown summary of the cluster's ideas and connections.
        """
        cluster = self.graph.get_cluster(cluster_id)
        if not cluster:
            return ""

        lines: list[str] = []
        lines.append(f"# Cluster: {cluster.name}")
        if cluster.description:
            lines.append(f"\n{cluster.description}")
        lines.append(f"\nTags: {', '.join(cluster.tags)}")
        lines.append(f"\n## Ideas ({cluster.size})")

        for nid in cluster.node_ids:
            node = self.graph.nodes.get(nid)
            if not node:
                continue
            lines.append(f"\n### {node.title}")
            if node.source_url:
                lines.append(f"Source: {node.source_url}")
            if node.body:
                # First 500 chars of body
                body_preview = node.body[:500]
                if len(node.body) > 500:
                    body_preview += "..."
                lines.append(body_preview)

        return "\n".join(lines)

    # ---- RSS Ingestion ----

    async def ingest_rss(
        self,
        feeds: list[dict[str, Any]] | None = None,
        relevance_keywords: list[str] | None = None,
        min_relevance: float = 0.0,
    ) -> list[IdeaNode]:
        """Ingest from RSS/Atom feeds.

        Args:
            feeds: List of feed configs, each a dict with at least ``url``
                and optionally ``name``, ``category``, ``priority``.
            relevance_keywords: Keywords for relevance filtering.
            min_relevance: Minimum relevance score.

        Returns:
            List of successfully added nodes.
        """
        from aragora.ideacloud.ingestion.rss_feeds import RSSFeedIngestor

        ingestor = RSSFeedIngestor(
            relevance_keywords=relevance_keywords,
            min_relevance=min_relevance,
        )

        for feed in feeds or []:
            ingestor.add_feed(
                url=feed["url"],
                name=feed.get("name", ""),
                category=feed.get("category", ""),
                priority=feed.get("priority", 5),
                max_entries=feed.get("max_entries", 50),
                topic_keywords=feed.get("topic_keywords"),
            )

        raw_nodes = await ingestor.ingest()
        return self._ingest_batch(raw_nodes)

    # ---- Pipeline Bridge ----

    def export_for_pipeline(self, cluster_id: str) -> list[str]:
        """Export a cluster as idea strings for IdeaToExecutionPipeline.from_ideas().

        Returns:
            List of idea strings ready for the pipeline.
        """
        from aragora.ideacloud.adapters.pipeline_bridge import cluster_to_ideas

        return cluster_to_ideas(self.graph, cluster_id)

    def export_for_brain_dump(self, cluster_id: str) -> str:
        """Export a cluster as brain-dump text for pipeline.from_brain_dump().

        Returns:
            Formatted text suitable for brain-dump pipeline entry.
        """
        from aragora.ideacloud.adapters.pipeline_bridge import cluster_to_brain_dump

        return cluster_to_brain_dump(self.graph, cluster_id)

    def export_for_debate(self, cluster_id: str) -> dict[str, Any]:
        """Export a cluster as a debate environment context.

        Returns:
            Dict with ``task``, ``context``, ``metadata`` fields.
        """
        from aragora.ideacloud.adapters.pipeline_bridge import export_cluster_for_debate

        return export_cluster_for_debate(self.graph, cluster_id)

    def export_universal_nodes(self, cluster_id: str) -> list[dict[str, Any]]:
        """Export cluster as UniversalNode-compatible dicts.

        Returns:
            List of dicts for ``UniversalNode.from_dict()``.
        """
        from aragora.ideacloud.adapters.pipeline_bridge import cluster_to_universal_nodes

        return cluster_to_universal_nodes(self.graph, cluster_id)

    # ---- Proposition Extraction ----

    def extract_propositions(self, cluster_id: str) -> list[str]:
        """Extract debate-ready propositions from a cluster.

        Returns:
            List of proposition strings.
        """
        return ops.extract_propositions(self.graph, cluster_id)

    # ---- Promote / Status ----

    def promote_node(self, node_id: str, new_status: str) -> bool:
        """Change a node's pipeline status.

        Status progression: inbox → candidate → prioritized → exported

        Returns:
            True if status was updated.
        """
        node = self.graph.get_node(node_id)
        if not node:
            return False

        valid_statuses = {"inbox", "candidate", "prioritized", "exported"}
        if new_status not in valid_statuses:
            logger.warning("Invalid status: %s", new_status)
            return False

        node.pipeline_status = new_status
        node.updated_at = __import__(
            "aragora.ideacloud.graph.node", fromlist=["_now_iso"]
        )._now_iso()
        self.graph.save()
        return True

    def promote_cluster(self, cluster_id: str, new_status: str) -> int:
        """Promote all nodes in a cluster to a new pipeline status.

        Returns number of nodes promoted.
        """
        cluster = self.graph.get_cluster(cluster_id)
        if not cluster:
            return 0

        count = 0
        for nid in cluster.node_ids:
            if self.promote_node(nid, new_status):
                count += 1
        return count

    # ---- Node access ----

    def get_node(self, node_id: str) -> IdeaNode | None:
        """Get a node by ID."""
        return self.graph.get_node(node_id)

    def list_nodes(
        self,
        status: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
    ) -> list[IdeaNode]:
        """List nodes with optional filtering.

        Args:
            status: Filter by pipeline_status (inbox, candidate, etc.)
            source_type: Filter by source_type (twitter_bookmark, etc.)
            limit: Maximum results.
        """
        nodes = list(self.graph.nodes.values())

        if status:
            nodes = [n for n in nodes if n.pipeline_status == status]
        if source_type:
            nodes = [n for n in nodes if n.source_type == source_type]

        # Sort by created_at descending
        nodes.sort(key=lambda n: n.created_at, reverse=True)
        return nodes[:limit]
