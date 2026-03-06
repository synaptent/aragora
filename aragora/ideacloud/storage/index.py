"""Graph index for fast lookups without parsing all markdown files.

Maintains ``index.json`` at the vault root with node metadata, edges, and clusters.
Updated on every write operation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from aragora.ideacloud.graph.cluster import IdeaCluster
from aragora.ideacloud.graph.edge import IdeaEdge
from aragora.ideacloud.graph.node import IdeaNode

logger = logging.getLogger(__name__)

INDEX_FILENAME = "index.json"


@property
def _empty_index() -> dict[str, Any]:
    return {"nodes": {}, "edges": [], "clusters": {}}


def write_index(
    vault_path: str | Path,
    nodes: dict[str, IdeaNode],
    edges: list[IdeaEdge],
    clusters: dict[str, IdeaCluster],
) -> Path:
    """Write the full graph index to index.json.

    Args:
        vault_path: Root directory of the idea vault.
        nodes: All nodes keyed by ID.
        edges: All edges.
        clusters: All clusters keyed by ID.

    Returns:
        Path to the written index file.
    """
    vault = Path(vault_path)
    vault.mkdir(parents=True, exist_ok=True)
    index_path = vault / INDEX_FILENAME

    data: dict[str, Any] = {
        "nodes": {},
        "edges": [],
        "clusters": {},
    }

    # Node summaries (lightweight — not full body)
    for nid, node in nodes.items():
        data["nodes"][nid] = {
            "title": node.title,
            "source_type": node.source_type,
            "tags": node.tags,
            "node_type": node.node_type,
            "cluster_id": node.cluster_id,
            "pipeline_status": node.pipeline_status,
            "relevance_score": node.relevance_score,
            "confidence": node.confidence,
            "km_synced": node.km_synced,
            "created_at": node.created_at,
            "updated_at": node.updated_at,
            "wiki_links": node.extract_wiki_links(),
        }

    # Edges
    data["edges"] = [e.to_dict() for e in edges]

    # Clusters
    for cid, cluster in clusters.items():
        data["clusters"][cid] = cluster.to_dict()

    index_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.debug(
        "Wrote index with %d nodes, %d edges, %d clusters", len(nodes), len(edges), len(clusters)
    )
    return index_path


def read_index(vault_path: str | Path) -> dict[str, Any]:
    """Read index.json if it exists.

    Returns:
        Parsed index dict, or empty structure if file doesn't exist.
    """
    index_path = Path(vault_path) / INDEX_FILENAME
    if not index_path.exists():
        return {"nodes": {}, "edges": [], "clusters": {}}

    try:
        raw = index_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read index: %s — returning empty", exc)
        return {"nodes": {}, "edges": [], "clusters": {}}


def load_edges_from_index(vault_path: str | Path) -> list[IdeaEdge]:
    """Load edges from index.json."""
    data = read_index(vault_path)
    return [IdeaEdge.from_dict(d) for d in data.get("edges", [])]


def load_clusters_from_index(vault_path: str | Path) -> dict[str, IdeaCluster]:
    """Load clusters from index.json."""
    data = read_index(vault_path)
    clusters: dict[str, IdeaCluster] = {}
    for cid, cd in data.get("clusters", {}).items():
        clusters[cid] = IdeaCluster.from_dict(cd)
    return clusters
