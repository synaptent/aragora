"""IdeaGraph — in-memory graph of ideas with search and traversal.

Loads from an Obsidian-compatible vault (markdown files + index.json),
provides search, neighbour traversal, and persistence back to vault.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from aragora.ideacloud.graph.cluster import IdeaCluster
from aragora.ideacloud.graph.edge import IdeaEdge
from aragora.ideacloud.graph.node import IdeaNode
from aragora.ideacloud.storage import index as idx
from aragora.ideacloud.storage import markdown_io as md

logger = logging.getLogger(__name__)


class IdeaGraph:
    """In-memory graph backed by an Obsidian vault.

    Usage:
        graph = IdeaGraph(".aragora_ideas")
        graph.load()
        graph.add_node(node)
        results = graph.search("prompt injection")
        graph.save()
    """

    def __init__(self, vault_path: str | Path) -> None:
        self.vault_path = Path(vault_path)
        self.nodes: dict[str, IdeaNode] = {}
        self.edges: list[IdeaEdge] = []
        self.clusters: dict[str, IdeaCluster] = {}

        # Adjacency index (rebuilt on load/add)
        self._adjacency: dict[str, list[str]] = defaultdict(list)

    # ---- Load / Save ----

    def load(self) -> int:
        """Load all nodes from vault markdown files, edges and clusters from index.

        Returns:
            Number of nodes loaded.
        """
        self.nodes.clear()
        self.edges.clear()
        self.clusters.clear()
        self._adjacency.clear()

        # Load nodes from .md files
        for fp in md.list_node_files(self.vault_path):
            try:
                node = md.read_node(fp)
                self.nodes[node.id] = node
            except Exception as exc:
                logger.warning("Failed to load %s: %s", fp, exc)

        # Load edges and clusters from index
        self.edges = idx.load_edges_from_index(self.vault_path)
        self.clusters = idx.load_clusters_from_index(self.vault_path)

        # Rebuild adjacency
        self._rebuild_adjacency()

        logger.info(
            "Loaded idea graph: %d nodes, %d edges, %d clusters",
            len(self.nodes),
            len(self.edges),
            len(self.clusters),
        )
        return len(self.nodes)

    def save(self) -> None:
        """Persist all nodes to markdown files and update index."""
        for node in self.nodes.values():
            md.write_node(node, self.vault_path)
        idx.write_index(self.vault_path, self.nodes, self.edges, self.clusters)
        logger.info("Saved idea graph: %d nodes", len(self.nodes))

    def save_node(self, node_id: str) -> None:
        """Persist a single node and update index."""
        if node_id in self.nodes:
            md.write_node(self.nodes[node_id], self.vault_path)
            idx.write_index(self.vault_path, self.nodes, self.edges, self.clusters)

    # ---- Node operations ----

    def add_node(self, node: IdeaNode, persist: bool = True) -> None:
        """Add a node to the graph.

        Args:
            node: The idea node to add.
            persist: If True, immediately write to disk and update index.
        """
        self.nodes[node.id] = node
        if persist:
            md.write_node(node, self.vault_path)
            idx.write_index(self.vault_path, self.nodes, self.edges, self.clusters)

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and its edges from the graph.

        Returns True if node was found and removed.
        """
        if node_id not in self.nodes:
            return False

        del self.nodes[node_id]

        # Remove edges involving this node
        self.edges = [e for e in self.edges if e.source_id != node_id and e.target_id != node_id]

        # Remove from clusters
        for cluster in self.clusters.values():
            cluster.remove_node(node_id)

        # Clean up empty clusters
        self.clusters = {cid: c for cid, c in self.clusters.items() if c.size > 0}

        self._rebuild_adjacency()
        md.delete_node_file(self.vault_path, node_id)
        idx.write_index(self.vault_path, self.nodes, self.edges, self.clusters)
        return True

    def get_node(self, node_id: str) -> IdeaNode | None:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    # ---- Edge operations ----

    def add_edge(self, edge: IdeaEdge) -> None:
        """Add an edge to the graph."""
        # Avoid duplicates
        for existing in self.edges:
            if (
                existing.source_id == edge.source_id
                and existing.target_id == edge.target_id
                and existing.edge_type == edge.edge_type
            ):
                return  # Already exists

        self.edges.append(edge)
        self._adjacency[edge.source_id].append(edge.target_id)
        self._adjacency[edge.target_id].append(edge.source_id)

    def get_edges_for(self, node_id: str) -> list[IdeaEdge]:
        """Get all edges involving a node."""
        return [e for e in self.edges if e.source_id == node_id or e.target_id == node_id]

    # ---- Cluster operations ----

    def add_cluster(self, cluster: IdeaCluster) -> None:
        """Add or update a cluster."""
        self.clusters[cluster.id] = cluster
        # Update node cluster assignments
        for nid in cluster.node_ids:
            if nid in self.nodes:
                self.nodes[nid].cluster_id = cluster.id

    def get_cluster(self, cluster_id: str) -> IdeaCluster | None:
        """Get a cluster by ID."""
        return self.clusters.get(cluster_id)

    # ---- Search ----

    def search(self, query: str, limit: int = 10) -> list[tuple[IdeaNode, float]]:
        """Search nodes by text query.

        Returns (node, relevance_score) tuples sorted by relevance.

        MVP implementation: keyword overlap scoring.
        Future: embedding-based semantic similarity.
        """
        query_lower = query.lower()
        query_terms = set(query_lower.split())

        scored: list[tuple[IdeaNode, float]] = []
        for node in self.nodes.values():
            score = _text_match_score(query_terms, query_lower, node)
            if score > 0:
                scored.append((node, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    # ---- Traversal ----

    def get_neighbours(self, node_id: str, depth: int = 1) -> set[str]:
        """Get all node IDs within N hops of a node."""
        visited: set[str] = set()
        frontier: set[str] = {node_id}

        for _ in range(depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                if nid in visited:
                    continue
                visited.add(nid)
                next_frontier.update(self._adjacency.get(nid, []))
            frontier = next_frontier - visited

        # Include frontier nodes discovered but not yet expanded
        visited.update(frontier)
        visited.discard(node_id)  # Don't include the start node
        return visited

    # ---- Stats ----

    @property
    def stats(self) -> dict[str, Any]:
        """Summary statistics for the graph."""
        status_counts: dict[str, int] = defaultdict(int)
        source_counts: dict[str, int] = defaultdict(int)
        for node in self.nodes.values():
            status_counts[node.pipeline_status] += 1
            source_counts[node.source_type] += 1

        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "total_clusters": len(self.clusters),
            "by_status": dict(status_counts),
            "by_source": dict(source_counts),
        }

    # ---- Internal ----

    def _rebuild_adjacency(self) -> None:
        """Rebuild the adjacency index from edges."""
        self._adjacency.clear()
        for edge in self.edges:
            self._adjacency[edge.source_id].append(edge.target_id)
            self._adjacency[edge.target_id].append(edge.source_id)


def _text_match_score(
    query_terms: set[str],
    query_lower: str,
    node: IdeaNode,
) -> float:
    """Score a node against a search query using keyword overlap.

    Scoring:
    - Title exact substring match: 0.5
    - Title term overlap: 0.3 * (matched terms / total terms)
    - Body term overlap: 0.15 * (matched terms / total terms)
    - Tag match: 0.3 per matching tag (capped at 0.6)
    """
    score = 0.0

    # Title substring match (highest signal)
    if query_lower in node.title.lower():
        score += 0.5

    # Term overlap in title
    title_lower = node.title.lower()
    title_hits = sum(1 for t in query_terms if t in title_lower)
    if query_terms:
        score += 0.3 * (title_hits / len(query_terms))

    # Term overlap in body
    body_lower = node.body.lower()
    body_hits = sum(1 for t in query_terms if t in body_lower)
    if query_terms:
        score += 0.15 * (body_hits / len(query_terms))

    # Tag matches
    tag_hits = 0
    for tag in node.tags:
        tag_lower = tag.lower().lstrip("#")
        if any(t in tag_lower or tag_lower in t for t in query_terms):
            tag_hits += 1
    score += min(0.6, tag_hits * 0.3)

    return min(1.0, score)
