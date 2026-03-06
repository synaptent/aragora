"""
Idea Cloud — a graph-structured knowledge capture system.

Dual-purpose: Obsidian-compatible personal thinking tool AND
structured input source for aragora's debate pipeline and KnowledgeMound.

Storage: `.aragora_ideas/` vault with interlinked markdown files.

Usage:
    from aragora.ideacloud import IdeaCloud

    cloud = IdeaCloud(vault_path=".aragora_ideas")
    cloud.load()

    # Ingest manually
    node = await cloud.ingest_manual("AI safety is critical", title="AI Safety")

    # Ingest from Twitter bookmarks
    added = await cloud.ingest_twitter_bookmarks("bookmarks.js")

    # Search, auto-link, auto-cluster
    results = cloud.search("prompt injection")
    cloud.auto_link()
    clusters = cloud.auto_cluster()

    # Export cluster for debate pipeline
    ideas = cloud.export_for_pipeline(cluster_id)
    debate_ctx = cloud.export_for_debate(cluster_id)
    propositions = cloud.extract_propositions(cluster_id)
"""

from aragora.ideacloud.core import IdeaCloud
from aragora.ideacloud.graph.node import IdeaNode
from aragora.ideacloud.graph.edge import IdeaEdge
from aragora.ideacloud.graph.cluster import IdeaCluster
from aragora.ideacloud.graph.graph import IdeaGraph

__all__ = [
    "IdeaCloud",
    "IdeaNode",
    "IdeaEdge",
    "IdeaCluster",
    "IdeaGraph",
]
