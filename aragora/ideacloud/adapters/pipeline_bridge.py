"""Pipeline bridge — convert IdeaCloud clusters to pipeline inputs.

Bridges the gap between the Idea Cloud (personal knowledge graph) and
aragora's Idea-to-Execution pipeline, enabling clusters of ideas to be
promoted into debate propositions or full pipeline runs.

Entry points:
    cluster_to_ideas(graph, cluster_id) → list[str] for pipeline.from_ideas()
    cluster_to_brain_dump(graph, cluster_id) → str for pipeline.from_brain_dump()
    cluster_to_universal_nodes(graph, cluster_id) → list[UniversalNode]
    export_cluster_for_debate(graph, cluster_id) → dict for Arena.env
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.ideacloud.graph.graph import IdeaGraph

logger = logging.getLogger(__name__)


def cluster_to_ideas(graph: IdeaGraph, cluster_id: str) -> list[str]:
    """Convert a cluster's nodes into a list of idea strings.

    This is the simplest bridge — feed the result directly into
    ``IdeaToExecutionPipeline.from_ideas(ideas)``.

    Each idea string is formatted as:
        "[Title]: [Body excerpt]"

    Args:
        graph: The idea graph.
        cluster_id: Cluster to export.

    Returns:
        List of idea strings ready for the pipeline.

    Raises:
        KeyError: If cluster_id not found.
    """
    cluster = graph.clusters.get(cluster_id)
    if not cluster:
        raise KeyError(f"Cluster {cluster_id!r} not found in graph")

    ideas: list[str] = []
    for nid in cluster.node_ids:
        node = graph.nodes.get(nid)
        if not node:
            continue

        # Build a concise idea string
        body_excerpt = node.body[:300].strip() if node.body else ""
        if node.title and body_excerpt:
            idea = f"{node.title}: {body_excerpt}"
        elif node.title:
            idea = node.title
        elif body_excerpt:
            idea = body_excerpt
        else:
            continue

        ideas.append(idea)

    logger.info("Exported %d ideas from cluster %s", len(ideas), cluster_id)
    return ideas


def cluster_to_brain_dump(graph: IdeaGraph, cluster_id: str) -> str:
    """Convert a cluster into a brain-dump text block.

    This produces a structured text blob suitable for
    ``IdeaToExecutionPipeline.from_brain_dump(text)``.

    The output includes the cluster name, common themes, and each
    idea as a bullet point with its connections noted.

    Args:
        graph: The idea graph.
        cluster_id: Cluster to export.

    Returns:
        Formatted brain-dump string.

    Raises:
        KeyError: If cluster_id not found.
    """
    cluster = graph.clusters.get(cluster_id)
    if not cluster:
        raise KeyError(f"Cluster {cluster_id!r} not found in graph")

    lines: list[str] = []
    lines.append(f"# {cluster.name}")
    lines.append("")

    if cluster.tags:
        lines.append(f"Themes: {', '.join(cluster.tags)}")
        lines.append("")

    lines.append("## Ideas")
    lines.append("")

    for nid in cluster.node_ids:
        node = graph.nodes.get(nid)
        if not node:
            continue

        body_preview = node.body[:200].strip() if node.body else ""
        lines.append(f"- **{node.title}**: {body_preview}")

        # Note connections
        edges = graph.get_edges_for(nid)
        for edge in edges:
            other_id = edge.target_id if edge.source_id == nid else edge.source_id
            other = graph.nodes.get(other_id)
            if other and other_id in cluster.node_ids:
                lines.append(f"  - {edge.edge_type} → {other.title}")

    lines.append("")
    lines.append("## Implications")
    lines.append("")
    lines.append("What patterns, risks, or opportunities emerge from these ideas together?")

    return "\n".join(lines)


def cluster_to_universal_nodes(
    graph: IdeaGraph,
    cluster_id: str,
) -> list[dict[str, Any]]:
    """Convert cluster nodes to UniversalNode-compatible dicts.

    These can be instantiated as ``UniversalNode.from_dict(d)`` and
    added to a ``UniversalGraph`` for pipeline visualization.

    Each node maps to ``PipelineStage.IDEAS`` with ``node_subtype``
    derived from the IdeaNode's ``node_type``.

    Args:
        graph: The idea graph.
        cluster_id: Cluster to export.

    Returns:
        List of dicts compatible with UniversalNode.from_dict().
    """
    cluster = graph.clusters.get(cluster_id)
    if not cluster:
        raise KeyError(f"Cluster {cluster_id!r} not found in graph")

    # Map ideacloud node_type → pipeline IdeaNodeType
    _NODE_TYPE_MAP = {
        "idea_concept": "concept",
        "idea_insight": "insight",
        "idea_evidence": "evidence",
        "idea_hypothesis": "hypothesis",
        "idea_question": "question",
        "idea_cluster": "cluster",
    }

    import time

    nodes: list[dict[str, Any]] = []
    for nid in cluster.node_ids:
        node = graph.nodes.get(nid)
        if not node:
            continue

        subtype = _NODE_TYPE_MAP.get(node.node_type, "concept")
        nodes.append(
            {
                "id": f"ic_{node.id}",
                "stage": "ideas",
                "node_subtype": subtype,
                "label": node.title or "Untitled",
                "description": node.body[:500] if node.body else "",
                "content_hash": node.content_hash,
                "confidence": node.confidence,
                "status": "active",
                "data": {
                    "source_type": node.source_type,
                    "source_url": node.source_url,
                    "source_author": node.source_author,
                    "tags": node.tags,
                    "ideacloud_id": node.id,
                    "cluster_id": cluster_id,
                },
                "metadata": {
                    "origin": "ideacloud",
                    "cluster_name": cluster.name,
                },
                "created_at": time.time(),
                "updated_at": time.time(),
            }
        )

    logger.info(
        "Exported %d UniversalNode dicts from cluster %s",
        len(nodes),
        cluster_id,
    )
    return nodes


def export_cluster_for_debate(
    graph: IdeaGraph,
    cluster_id: str,
) -> dict[str, Any]:
    """Export a cluster as a debate environment context.

    Returns a dict suitable for constructing an ``Environment`` object
    for a debate ``Arena`` run.

    Args:
        graph: The idea graph.
        cluster_id: Cluster to export.

    Returns:
        Dict with ``task``, ``context``, ``metadata`` fields.
    """
    cluster = graph.clusters.get(cluster_id)
    if not cluster:
        raise KeyError(f"Cluster {cluster_id!r} not found in graph")

    ideas = cluster_to_ideas(graph, cluster_id)

    # Build the debate task
    task = (
        f"Analyze the following cluster of ideas about '{cluster.name}' "
        f"and identify: (1) key insights, (2) potential risks, "
        f"(3) actionable implications, (4) gaps or questions to investigate."
    )

    context_lines = [f"Cluster: {cluster.name}"]
    if cluster.tags:
        context_lines.append(f"Themes: {', '.join(cluster.tags)}")
    context_lines.append("")
    context_lines.append("Ideas:")
    for i, idea in enumerate(ideas, 1):
        context_lines.append(f"  {i}. {idea}")

    return {
        "task": task,
        "context": "\n".join(context_lines),
        "metadata": {
            "origin": "ideacloud",
            "cluster_id": cluster_id,
            "cluster_name": cluster.name,
            "node_count": len(cluster.node_ids),
            "tags": cluster.tags,
        },
    }
