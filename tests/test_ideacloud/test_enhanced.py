"""Tests for Idea Cloud Phase 1+ and Phase 2 enhancements.

Covers: pipeline bridge, RSS ingestor, wiki-link injection,
proposition extraction, promote/status management, KM adapter sync.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from aragora.ideacloud.graph.node import IdeaNode
from aragora.ideacloud.graph.edge import IdeaEdge
from aragora.ideacloud.graph.cluster import IdeaCluster
from aragora.ideacloud.graph.graph import IdeaGraph
from aragora.ideacloud.graph import operations as ops
from aragora.ideacloud.core import IdeaCloud
from aragora.ideacloud.adapters.pipeline_bridge import (
    cluster_to_ideas,
    cluster_to_brain_dump,
    cluster_to_universal_nodes,
    export_cluster_for_debate,
)


@pytest.fixture
def tmp_vault(tmp_path):
    vault = tmp_path / ".aragora_ideas"
    vault.mkdir()
    return vault


@pytest.fixture
def populated_graph(tmp_vault):
    """Graph with 3 linked nodes in a cluster for testing exports."""
    graph = IdeaGraph(tmp_vault)

    n1 = IdeaNode(
        id="ic_exp1",
        title="Brainworm: CUA Malware via Context Injection",
        body="Natural language malware that lives in CLAUDE.md files.",
        tags=["ai-security", "prompt-injection", "agent-safety"],
        source_url="https://originhq.com/blog/brainworm",
        source_author="Origin HQ",
        node_type="idea_insight",
    )
    n2 = IdeaNode(
        id="ic_exp2",
        title="OBLITERATUS: LLM Refusal Removal Toolkit",
        body="Toolkit for removing refusal behaviors from open-weight LLMs.",
        tags=["ai-security", "model-modification", "alignment"],
        source_url="https://x.com/elder_plinius/status/123",
        source_author="@elder_plinius",
        node_type="idea_evidence",
    )
    n3 = IdeaNode(
        id="ic_exp3",
        title="RLHF Moral Inconsistency",
        body="RLHF creates mechanical overgeneralization of harm categories.",
        tags=["ai-security", "rlhf", "alignment", "bias"],
        source_author="@ValerioCapraro",
        node_type="idea_hypothesis",
    )

    for n in [n1, n2, n3]:
        graph.add_node(n, persist=False)

    graph.add_edge(
        IdeaEdge(
            source_id="ic_exp1",
            target_id="ic_exp2",
            edge_type="relates_to",
            weight=0.7,
        )
    )
    graph.add_edge(
        IdeaEdge(
            source_id="ic_exp2",
            target_id="ic_exp3",
            edge_type="extends",
            weight=0.5,
        )
    )

    cluster = IdeaCluster(
        id="cl_test1",
        name="AI Security Threats",
        node_ids=["ic_exp1", "ic_exp2", "ic_exp3"],
        tags=["ai-security", "alignment"],
        confidence=0.8,
    )
    graph.clusters["cl_test1"] = cluster
    for nid in cluster.node_ids:
        graph.nodes[nid].cluster_id = "cl_test1"

    return graph


# ---- Pipeline Bridge Tests ----


class TestClusterToIdeas:
    def test_basic_export(self, populated_graph):
        ideas = cluster_to_ideas(populated_graph, "cl_test1")
        assert len(ideas) == 3
        assert any("Brainworm" in i for i in ideas)
        assert any("OBLITERATUS" in i for i in ideas)

    def test_nonexistent_cluster_raises(self, populated_graph):
        with pytest.raises(KeyError, match="not found"):
            cluster_to_ideas(populated_graph, "cl_nonexistent")


class TestClusterToBrainDump:
    def test_brain_dump_format(self, populated_graph):
        dump = cluster_to_brain_dump(populated_graph, "cl_test1")
        assert "# AI Security Threats" in dump
        assert "Themes:" in dump
        assert "Brainworm" in dump
        assert "## Implications" in dump

    def test_includes_connections(self, populated_graph):
        dump = cluster_to_brain_dump(populated_graph, "cl_test1")
        # Should show edge relationships
        assert "relates_to" in dump or "extends" in dump


class TestClusterToUniversalNodes:
    def test_universal_node_format(self, populated_graph):
        nodes = cluster_to_universal_nodes(populated_graph, "cl_test1")
        assert len(nodes) == 3

        # Check structure
        n = nodes[0]
        assert "id" in n
        assert n["stage"] == "ideas"
        assert n["node_subtype"] in (
            "concept",
            "insight",
            "evidence",
            "hypothesis",
            "question",
            "cluster",
        )
        assert "data" in n
        assert n["data"]["source_type"] is not None
        assert n["metadata"]["origin"] == "ideacloud"

    def test_type_mapping(self, populated_graph):
        nodes = cluster_to_universal_nodes(populated_graph, "cl_test1")
        subtypes = {n["label"]: n["node_subtype"] for n in nodes}
        assert subtypes["Brainworm: CUA Malware via Context Injection"] == "insight"
        assert subtypes["OBLITERATUS: LLM Refusal Removal Toolkit"] == "evidence"
        assert subtypes["RLHF Moral Inconsistency"] == "hypothesis"


class TestExportForDebate:
    def test_debate_export_structure(self, populated_graph):
        result = export_cluster_for_debate(populated_graph, "cl_test1")
        assert "task" in result
        assert "context" in result
        assert "metadata" in result
        assert result["metadata"]["cluster_id"] == "cl_test1"
        assert result["metadata"]["node_count"] == 3

    def test_debate_task_is_actionable(self, populated_graph):
        result = export_cluster_for_debate(populated_graph, "cl_test1")
        assert "Analyze" in result["task"]
        assert "AI Security Threats" in result["task"]


# ---- Wiki-Link Injection Tests ----


class TestWikiLinkInjection:
    def test_auto_link_injects_wiki_links(self, tmp_vault):
        graph = IdeaGraph(tmp_vault)
        n1 = IdeaNode(
            id="ic_wl1",
            title="AI Safety Fundamentals",
            body="Core concepts in AI safety research.",
            tags=["ai-safety", "research"],
        )
        n2 = IdeaNode(
            id="ic_wl2",
            title="AI Safety Testing Methods",
            body="Methods for testing AI safety properties.",
            tags=["ai-safety", "research", "testing"],
        )
        graph.add_node(n1, persist=False)
        graph.add_node(n2, persist=False)

        edges = ops.auto_link(graph, min_similarity=0.1, inject_wiki_links=True)
        assert len(edges) > 0

        # Check that wiki-links were injected
        source = graph.nodes[edges[0].source_id]
        target = graph.nodes[edges[0].target_id]
        assert f"[[{target.title}]]" in source.body

    def test_wiki_link_no_duplicates(self, tmp_vault):
        graph = IdeaGraph(tmp_vault)
        n1 = IdeaNode(
            id="ic_wl3",
            title="Topic A",
            body="Some content.\n\n## Connections\n- [[Topic B]] (relates_to)",
            tags=["test"],
        )
        n2 = IdeaNode(
            id="ic_wl4",
            title="Topic B",
            body="Other content.",
            tags=["test"],
        )
        graph.add_node(n1, persist=False)
        graph.add_node(n2, persist=False)

        # Manually inject a link that already exists
        edge = IdeaEdge(source_id="ic_wl3", target_id="ic_wl4", edge_type="relates_to")
        graph.add_edge(edge)
        ops._inject_wiki_link(graph, edge)

        # Should not add a duplicate
        assert n1.body.count("[[Topic B]]") == 1

    def test_auto_link_without_wiki_links(self, tmp_vault):
        graph = IdeaGraph(tmp_vault)
        n1 = IdeaNode(id="ic_wl5", title="X", body="Body A.", tags=["test", "same"])
        n2 = IdeaNode(id="ic_wl6", title="Y", body="Body B.", tags=["test", "same"])
        graph.add_node(n1, persist=False)
        graph.add_node(n2, persist=False)

        edges = ops.auto_link(graph, min_similarity=0.1, inject_wiki_links=False)
        assert len(edges) > 0

        # Wiki-links should NOT be injected
        assert "[[" not in graph.nodes["ic_wl5"].body
        assert "[[" not in graph.nodes["ic_wl6"].body


# ---- Proposition Extraction Tests ----


class TestPropositionExtraction:
    def test_extract_from_cluster(self, populated_graph):
        propositions = ops.extract_propositions(populated_graph, "cl_test1")
        assert len(propositions) > 0
        # Should include node titles
        assert any("Brainworm" in p for p in propositions)

    def test_extends_edge_creates_building_proposition(self, populated_graph):
        propositions = ops.extract_propositions(populated_graph, "cl_test1")
        # n2 extends n3, so should see a "Building on" proposition
        assert any("Building on" in p for p in propositions)

    def test_synthesis_proposition(self, populated_graph):
        propositions = ops.extract_propositions(populated_graph, "cl_test1")
        assert any("Synthesis" in p for p in propositions)

    def test_nonexistent_cluster(self, populated_graph):
        propositions = ops.extract_propositions(populated_graph, "cl_none")
        assert propositions == []


# ---- RSS Ingestor Tests ----


class TestRSSFeedIngestor:
    def test_create_ingestor(self):
        from aragora.ideacloud.ingestion.rss_feeds import RSSFeedIngestor

        ingestor = RSSFeedIngestor(
            relevance_keywords=["ai", "security"],
            min_relevance=0.5,
        )
        assert len(ingestor.feeds) == 0
        assert ingestor.min_relevance == 0.5

    def test_add_and_remove_feed(self):
        from aragora.ideacloud.ingestion.rss_feeds import RSSFeedIngestor

        ingestor = RSSFeedIngestor()
        ingestor.add_feed("https://example.com/feed.xml", name="Example")
        assert len(ingestor.feeds) == 1
        assert ingestor.feeds[0].name == "Example"

        assert ingestor.remove_feed("https://example.com/feed.xml")
        assert len(ingestor.feeds) == 0

        # Removing non-existent returns False
        assert not ingestor.remove_feed("https://no.such/feed")

    def test_relevance_filter(self):
        from aragora.ideacloud.ingestion.rss_feeds import RSSFeedIngestor

        ingestor = RSSFeedIngestor(
            relevance_keywords=["ai", "security", "safety"],
            min_relevance=0.5,
        )

        # Node with 2/3 keywords = 0.67 relevance → passes
        relevant = IdeaNode(
            title="AI Security Research",
            body="This is about ai and security topics.",
            tags=["tech"],
        )
        assert ingestor._passes_relevance(relevant)

        # Node with 0/3 keywords = 0 relevance → rejected
        irrelevant = IdeaNode(
            title="Cooking Recipes",
            body="How to make pasta.",
            tags=["cooking"],
        )
        assert not ingestor._passes_relevance(irrelevant)

    def test_ingest_no_feeds_returns_empty(self):
        from aragora.ideacloud.ingestion.rss_feeds import RSSFeedIngestor

        ingestor = RSSFeedIngestor()
        result = asyncio.run(ingestor.ingest())
        assert result == []


# ---- Core Orchestrator Enhancement Tests ----


class TestIdeaCloudPipelineBridge:
    def test_export_for_pipeline(self, tmp_vault):
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()

        # Add nodes and cluster them
        asyncio.run(
            cloud.ingest_manual(
                content="AI safety is critical for trustworthy systems.",
                title="AI Safety",
                tags=["ai-safety", "trustworthy"],
            )
        )
        asyncio.run(
            cloud.ingest_manual(
                content="Adversarial testing reveals AI vulnerabilities.",
                title="Adversarial Testing",
                tags=["ai-safety", "testing", "trustworthy"],
            )
        )

        clusters = cloud.auto_cluster()
        if clusters:
            cid = list(clusters.keys())[0]
            ideas = cloud.export_for_pipeline(cid)
            assert len(ideas) > 0
            assert isinstance(ideas[0], str)

    def test_export_for_debate(self, tmp_vault):
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()

        asyncio.run(
            cloud.ingest_manual(
                content="Test idea A",
                title="Idea A",
                tags=["test", "alpha"],
            )
        )
        asyncio.run(
            cloud.ingest_manual(
                content="Test idea B",
                title="Idea B",
                tags=["test", "alpha"],
            )
        )

        clusters = cloud.auto_cluster()
        if clusters:
            cid = list(clusters.keys())[0]
            result = cloud.export_for_debate(cid)
            assert "task" in result
            assert "context" in result


class TestPromoteStatus:
    def test_promote_node(self, tmp_vault):
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()

        node = asyncio.run(
            cloud.ingest_manual(
                content="Important idea",
                title="Test Promote",
            )
        )
        assert node is not None
        assert node.pipeline_status == "inbox"

        assert cloud.promote_node(node.id, "candidate")
        reloaded = cloud.get_node(node.id)
        assert reloaded.pipeline_status == "candidate"

    def test_promote_invalid_status(self, tmp_vault):
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()

        node = asyncio.run(
            cloud.ingest_manual(
                content="A substantial idea about testing promotion status transitions",
                title="Testing Status Promotion",
                tags=["test"],
            )
        )
        assert node is not None
        assert not cloud.promote_node(node.id, "invalid_status")

    def test_promote_nonexistent_node(self, tmp_vault):
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()
        assert not cloud.promote_node("ic_nonexistent", "candidate")

    def test_promote_cluster(self, tmp_vault):
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()

        asyncio.run(
            cloud.ingest_manual(
                content="A",
                title="A",
                tags=["same", "group"],
            )
        )
        asyncio.run(
            cloud.ingest_manual(
                content="B",
                title="B",
                tags=["same", "group"],
            )
        )

        clusters = cloud.auto_cluster()
        if clusters:
            cid = list(clusters.keys())[0]
            count = cloud.promote_cluster(cid, "prioritized")
            assert count >= 2

            # Verify nodes were promoted
            for node in cloud.cluster_nodes(cid):
                assert node.pipeline_status == "prioritized"


class TestExtractPropositionsFromCloud:
    def test_extract_via_core(self, tmp_vault):
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()

        asyncio.run(
            cloud.ingest_manual(
                content="Idea 1 content",
                title="Idea One",
                tags=["topic", "sub"],
            )
        )
        asyncio.run(
            cloud.ingest_manual(
                content="Idea 2 content",
                title="Idea Two",
                tags=["topic", "sub"],
            )
        )

        clusters = cloud.auto_cluster()
        if clusters:
            cid = list(clusters.keys())[0]
            props = cloud.extract_propositions(cid)
            assert len(props) > 0
