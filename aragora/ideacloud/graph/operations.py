"""Graph operations — auto-linking, clustering, proposition extraction.

These transform the raw idea graph into a structured, interconnected
knowledge base suitable for debate generation and pipeline export.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from aragora.ideacloud.graph.cluster import IdeaCluster, _generate_cluster_id
from aragora.ideacloud.graph.edge import IdeaEdge
from aragora.ideacloud.graph.node import IdeaNode, _now_iso

if TYPE_CHECKING:
    from aragora.ideacloud.graph.graph import IdeaGraph

logger = logging.getLogger(__name__)


# ---- Auto-Linking ----


def auto_link(
    graph: IdeaGraph,
    node_id: str | None = None,
    min_similarity: float = 0.3,
    max_suggestions: int = 5,
    inject_wiki_links: bool = True,
    embedding_provider: Any | None = None,
) -> list[IdeaEdge]:
    """Find and create connections between ideas based on text similarity.

    If ``node_id`` is provided, only link that node to existing nodes.
    If ``None``, run auto-linking across all unlinked node pairs.

    Uses keyword/tag overlap scoring by default. When ``embedding_provider``
    is supplied, blends embedding-based cosine similarity for higher-quality
    semantic matching.

    Args:
        graph: The idea graph.
        node_id: Specific node to link, or None for all.
        min_similarity: Minimum similarity threshold for creating an edge.
        max_suggestions: Max new edges per node.
        inject_wiki_links: Whether to inject [[wiki-links]] into node bodies.
        embedding_provider: Optional EmbeddingProvider for semantic similarity.

    Returns:
        List of newly created edges.
    """
    new_edges: list[IdeaEdge] = []

    if node_id:
        target_node = graph.get_node(node_id)
        if not target_node:
            return []
        candidates = [n for n in graph.nodes.values() if n.id != node_id]
        new_edges.extend(
            _link_node_to_candidates(
                graph, target_node, candidates, min_similarity, max_suggestions, embedding_provider
            )
        )
    else:
        # Link all nodes that have few connections
        for node in graph.nodes.values():
            existing_edges = graph.get_edges_for(node.id)
            if len(existing_edges) >= max_suggestions:
                continue
            remaining = max_suggestions - len(existing_edges)
            candidates = [n for n in graph.nodes.values() if n.id != node.id]
            new_edges.extend(
                _link_node_to_candidates(
                    graph, node, candidates, min_similarity, remaining, embedding_provider
                )
            )

    # Add edges to graph and inject wiki-links into node bodies
    for edge in new_edges:
        graph.add_edge(edge)
        if inject_wiki_links:
            _inject_wiki_link(graph, edge)

    if new_edges:
        logger.info("Auto-linked %d new connections", len(new_edges))

    return new_edges


def _link_node_to_candidates(
    graph: IdeaGraph,
    node: IdeaNode,
    candidates: list[IdeaNode],
    min_similarity: float,
    max_results: int,
    embedding_provider: Any | None = None,
) -> list[IdeaEdge]:
    """Score and link a node to its best candidate matches.

    When ``embedding_provider`` is available, blends keyword similarity
    (40%) with embedding cosine similarity (60%) for better semantic
    matching. Otherwise uses keyword similarity only.
    """
    scored: list[tuple[IdeaNode, float]] = []

    for candidate in candidates:
        # Skip if already connected
        existing = [
            e
            for e in graph.edges
            if (e.source_id == node.id and e.target_id == candidate.id)
            or (e.source_id == candidate.id and e.target_id == node.id)
        ]
        if existing:
            continue

        keyword_sim = _pairwise_similarity(node, candidate)

        # Blend with embedding similarity if available
        if embedding_provider and getattr(embedding_provider, "available", False):
            try:
                text_a = f"{node.title} {node.body}"
                text_b = f"{candidate.title} {candidate.body}"
                embed_sim = embedding_provider.similarity(text_a, text_b)
                # Blend: 40% keyword + 60% embedding
                sim = 0.4 * keyword_sim + 0.6 * embed_sim
            except Exception:
                sim = keyword_sim
        else:
            sim = keyword_sim

        if sim >= min_similarity:
            scored.append((candidate, sim))

    scored.sort(key=lambda x: x[1], reverse=True)

    edges: list[IdeaEdge] = []
    for candidate, sim in scored[:max_results]:
        edge = IdeaEdge(
            source_id=node.id,
            target_id=candidate.id,
            edge_type="relates_to",
            weight=sim,
            auto_created=True,
            confidence=sim,
        )
        edges.append(edge)

    return edges


def _pairwise_similarity(a: IdeaNode, b: IdeaNode) -> float:
    """Compute similarity between two nodes using keyword and tag overlap.

    Scoring (uses blend of Jaccard and overlap coefficient):
    - Tag similarity: weighted blend favoring overlap coefficient (weight 0.4)
    - Keyword similarity: Jaccard of significant words (weight 0.4)
    - Title similarity: shared significant words in titles (weight 0.2)

    The overlap coefficient (|intersection| / min(|A|, |B|)) rewards sharing
    any tags even when the total tag sets are diverse, which is typical for
    nodes in the same broad domain (e.g., ai-security) but with different
    specific sub-topics.
    """
    # Tag similarity — blend Jaccard and overlap coefficient
    tags_a = {t.lower().lstrip("#") for t in a.tags}
    tags_b = {t.lower().lstrip("#") for t in b.tags}
    tag_sim = _blended_similarity(tags_a, tags_b) if (tags_a or tags_b) else 0.0

    # Keyword similarity (body + title)
    words_a = _extract_keywords(a.title + " " + a.body)
    words_b = _extract_keywords(b.title + " " + b.body)
    keyword_sim = _jaccard(words_a, words_b) if (words_a or words_b) else 0.0

    # Title word similarity
    title_a = _extract_keywords(a.title)
    title_b = _extract_keywords(b.title)
    title_sim = _jaccard(title_a, title_b) if (title_a or title_b) else 0.0

    return 0.5 * tag_sim + 0.35 * keyword_sim + 0.15 * title_sim


def _overlap_coefficient(set_a: set[str], set_b: set[str]) -> float:
    """Overlap coefficient: |A ∩ B| / min(|A|, |B|).

    Returns 1.0 when all elements of the smaller set appear in the larger set,
    regardless of how large the larger set is. This is less punishing than
    Jaccard for sets of unequal size.
    """
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    return len(intersection) / min(len(set_a), len(set_b))


def _blended_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Blend of Jaccard (0.4) and overlap coefficient (0.6).

    Overlap coefficient is weighted higher because ideas in the same domain
    often share a few key tags while diverging in specifics.
    """
    return 0.4 * _jaccard(set_a, set_b) + 0.6 * _overlap_coefficient(set_a, set_b)


def _jaccard(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


# Stopwords for keyword extraction
_STOPWORDS = frozenset(
    "the a an is are was were be been being have has had do does did "
    "will would shall should may might can could of in to for on with "
    "at by from as into through during before after above below between "
    "out off over under again further then once here there when where "
    "why how all each every both few more most other some such no nor "
    "not only own same so than too very it its this that these those "
    "and but or if while because until about against".split()
)


def _extract_keywords(text: str) -> set[str]:
    """Extract significant keywords from text (lowercase, no stopwords)."""
    words = re.findall(r"[a-z]{3,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


# ---- Clustering ----


def auto_cluster(
    graph: IdeaGraph,
    min_cluster_size: int = 2,
) -> dict[str, IdeaCluster]:
    """Cluster ideas using connected components from edges + shared tags.

    1. Build adjacency from explicit edges
    2. Add implicit edges for nodes sharing 2+ tags
    3. Find connected components
    4. Each component with ≥ min_cluster_size becomes a cluster

    Returns:
        Dict of cluster_id → IdeaCluster (also updates graph.clusters).
    """
    # Build adjacency graph
    adj: dict[str, set[str]] = defaultdict(set)

    # From explicit edges
    for edge in graph.edges:
        if edge.source_id in graph.nodes and edge.target_id in graph.nodes:
            adj[edge.source_id].add(edge.target_id)
            adj[edge.target_id].add(edge.source_id)

    # From shared tags (2+ shared tags = implicit connection)
    node_list = list(graph.nodes.values())
    for i, a in enumerate(node_list):
        tags_a = {t.lower().lstrip("#") for t in a.tags}
        for b in node_list[i + 1 :]:
            tags_b = {t.lower().lstrip("#") for t in b.tags}
            shared = tags_a & tags_b
            if len(shared) >= 2:
                adj[a.id].add(b.id)
                adj[b.id].add(a.id)

    # Find connected components via BFS
    visited: set[str] = set()
    components: list[set[str]] = []

    for nid in graph.nodes:
        if nid in visited:
            continue
        component: set[str] = set()
        queue = [nid]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            queue.extend(adj.get(current, set()) - visited)
        if len(component) >= min_cluster_size:
            components.append(component)

    # Create clusters
    new_clusters: dict[str, IdeaCluster] = {}
    for component in components:
        # Check if an existing cluster covers this component
        existing = _find_matching_cluster(graph.clusters, component)
        if existing:
            # Update existing cluster
            existing.node_ids = sorted(component)
            existing.tags = _derive_cluster_tags(graph, component)
            existing.updated_at = _now_iso()
            new_clusters[existing.id] = existing
        else:
            # Create new cluster
            tags = _derive_cluster_tags(graph, component)
            name = _derive_cluster_name(tags, graph, component)
            cluster = IdeaCluster(
                id=_generate_cluster_id(),
                name=name,
                node_ids=sorted(component),
                tags=tags,
                confidence=0.5,
            )
            new_clusters[cluster.id] = cluster

    # Update graph
    graph.clusters = new_clusters
    for cluster in new_clusters.values():
        for nid in cluster.node_ids:
            if nid in graph.nodes:
                graph.nodes[nid].cluster_id = cluster.id

    logger.info(
        "Clustering produced %d clusters from %d nodes", len(new_clusters), len(graph.nodes)
    )

    return new_clusters


def _find_matching_cluster(
    existing: dict[str, IdeaCluster],
    component: set[str],
) -> IdeaCluster | None:
    """Find an existing cluster that substantially overlaps with a component."""
    for cluster in existing.values():
        existing_set = set(cluster.node_ids)
        overlap = existing_set & component
        if overlap and len(overlap) / max(len(existing_set), len(component)) > 0.5:
            return cluster
    return None


def _derive_cluster_tags(graph: IdeaGraph, node_ids: set[str]) -> list[str]:
    """Derive cluster tags from the most common tags across member nodes."""
    tag_counts: Counter[str] = Counter()
    for nid in node_ids:
        node = graph.nodes.get(nid)
        if node:
            for tag in node.tags:
                tag_counts[tag.lower().lstrip("#")] += 1

    # Return tags that appear in at least half the nodes (min 1)
    threshold = max(1, len(node_ids) // 2)
    return [tag for tag, count in tag_counts.most_common(10) if count >= threshold]


def _derive_cluster_name(
    tags: list[str],
    graph: IdeaGraph,
    node_ids: set[str],
) -> str:
    """Derive a human-readable cluster name."""
    if tags:
        return " + ".join(tags[:3]).title()
    # Fall back to first node's title
    for nid in sorted(node_ids):
        node = graph.nodes.get(nid)
        if node and node.title:
            return node.title[:50]
    return "Unnamed Cluster"


# ---- Wiki-link Injection ----


def _inject_wiki_link(graph: IdeaGraph, edge: IdeaEdge) -> None:
    """Inject a wiki-link into the source node's body for a new edge.

    Appends a ``[[Target Title]]`` link under a ``## Connections`` section
    in the node's markdown body, creating the section if it doesn't exist.
    """
    source = graph.nodes.get(edge.source_id)
    target = graph.nodes.get(edge.target_id)
    if not source or not target or not target.title:
        return

    wiki_link = f"[[{target.title}]]"

    # Don't add duplicates
    if wiki_link in source.body:
        return

    # Find or create the Connections section
    if "## Connections" in source.body:
        # Append to existing section
        source.body = source.body.replace(
            "## Connections",
            f"## Connections\n- {wiki_link} ({edge.edge_type})",
            1,
        )
    else:
        # Create new section at the end
        source.body = source.body.rstrip() + f"\n\n## Connections\n- {wiki_link} ({edge.edge_type})"


# ---- Proposition Extraction ----


def extract_propositions(graph: IdeaGraph, cluster_id: str) -> list[str]:
    """Extract debate-ready propositions from a cluster.

    Analyzes the cluster's ideas and generates proposition strings
    suitable for feeding into a debate ``Arena``.

    Each proposition is a standalone debatable statement derived from
    the ideas and their connections.

    Args:
        graph: The idea graph.
        cluster_id: Cluster to extract propositions from.

    Returns:
        List of proposition strings.
    """
    cluster = graph.clusters.get(cluster_id)
    if not cluster:
        return []

    propositions: list[str] = []

    for nid in cluster.node_ids:
        node = graph.nodes.get(nid)
        if not node:
            continue

        # Each node's title is a natural proposition seed
        if node.title:
            propositions.append(node.title)

        # Look for edges that create interesting tensions
        edges = graph.get_edges_for(nid)
        for edge in edges:
            if edge.edge_type in ("refutes", "conflicts"):
                other_id = edge.target_id if edge.source_id == nid else edge.source_id
                other = graph.nodes.get(other_id)
                if other and other.title:
                    propositions.append(f"Tension: {node.title} vs {other.title}")
            elif edge.edge_type == "extends":
                other_id = edge.target_id if edge.source_id == nid else edge.source_id
                other = graph.nodes.get(other_id)
                if other and other.title:
                    propositions.append(f"Building on {other.title}: {node.title}")

    # Add a synthesis proposition from cluster tags
    if cluster.tags and len(cluster.node_ids) >= 2:
        tag_str = ", ".join(cluster.tags[:3])
        propositions.append(
            f"Synthesis: What patterns emerge from {tag_str} across {len(cluster.node_ids)} ideas?"
        )

    return propositions
