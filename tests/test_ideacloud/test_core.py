"""Tests for the Idea Cloud module.

Tests the full pipeline: node creation, markdown round-trip,
graph operations, ingestion, search, clustering.

Includes a real-world test with the 3 tweets from the initial
design conversation (Brainworm, OBLITERATUS, Capraro).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest

from aragora.ideacloud.graph.node import IdeaNode, _generate_id, _content_hash
from aragora.ideacloud.graph.edge import IdeaEdge
from aragora.ideacloud.graph.cluster import IdeaCluster
from aragora.ideacloud.graph.graph import IdeaGraph
from aragora.ideacloud.graph import operations as ops
from aragora.ideacloud.storage import markdown_io as md
from aragora.ideacloud.storage import index as idx
from aragora.ideacloud.ingestion.quality import QualityFilter, DeduplicationEngine
from aragora.ideacloud.ingestion.manual import ManualPasteIngestor
from aragora.ideacloud.ingestion.twitter_bookmarks import (
    TwitterBookmarksIngestor,
    _parse_twitter_js,
)
from aragora.ideacloud.core import IdeaCloud


# ---- Fixtures ----


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a temporary vault directory."""
    vault = tmp_path / ".aragora_ideas"
    vault.mkdir()
    return vault


@pytest.fixture
def sample_node():
    """Create a sample IdeaNode."""
    return IdeaNode(
        id="ic_test123",
        title="Brainworm: CUA Malware via Context Injection",
        body=(
            "Natural language malware that lives in CLAUDE.md files.\n\n"
            "Key insight: everything in a context window gets reasoned over "
            "with equal authority.\n\n"
            "## Connections\n"
            "- [[OBLITERATUS]] — weight-level attacks\n"
            "- [[Aragora Consensus Defense]]\n"
        ),
        source_type="manual",
        source_url="https://www.originhq.com/blog/brainworm",
        source_author="Origin HQ",
        tags=["ai-security", "prompt-injection", "agent-safety"],
        node_type="idea_insight",
        relevance_score=0.92,
        confidence=0.85,
    )


# ---- Node Tests ----


class TestIdeaNode:
    def test_create_node(self):
        node = IdeaNode(title="Test Idea", body="Some content")
        assert node.id.startswith("ic_")
        assert node.title == "Test Idea"
        assert node.content_hash.startswith("sha256:")

    def test_extract_wiki_links(self, sample_node):
        links = sample_node.extract_wiki_links()
        assert "OBLITERATUS" in links
        assert "Aragora Consensus Defense" in links

    def test_frontmatter_roundtrip(self, sample_node):
        fm = sample_node.to_frontmatter_dict()
        restored = IdeaNode.from_frontmatter_dict(fm, body=sample_node.body)
        assert restored.id == sample_node.id
        assert restored.title == sample_node.title
        assert restored.source_url == sample_node.source_url
        assert restored.tags == sample_node.tags
        assert restored.relevance_score == sample_node.relevance_score

    def test_searchable_text(self, sample_node):
        text = sample_node.searchable_text
        assert "brainworm" in text
        assert "ai-security" in text
        assert "origin hq" in text

    def test_update_content(self):
        node = IdeaNode(title="Original", body="Original body")
        old_hash = node.content_hash
        node.update_content(title="Updated", body="New body")
        assert node.title == "Updated"
        assert node.content_hash != old_hash

    def test_content_hash_deterministic(self):
        h1 = _content_hash("hello world")
        h2 = _content_hash("hello world")
        assert h1 == h2
        assert h1.startswith("sha256:")


# ---- Edge Tests ----


class TestIdeaEdge:
    def test_create_edge(self):
        edge = IdeaEdge(
            source_id="ic_a",
            target_id="ic_b",
            edge_type="supports",
            weight=0.8,
        )
        assert edge.source_id == "ic_a"
        assert edge.edge_type == "supports"

    def test_edge_roundtrip(self):
        edge = IdeaEdge(
            source_id="ic_a",
            target_id="ic_b",
            edge_type="refutes",
            weight=0.7,
            reason="Contradicts the premise",
        )
        d = edge.to_dict()
        restored = IdeaEdge.from_dict(d)
        assert restored.source_id == edge.source_id
        assert restored.edge_type == edge.edge_type
        assert restored.reason == edge.reason


# ---- Cluster Tests ----


class TestIdeaCluster:
    def test_create_cluster(self):
        cluster = IdeaCluster(name="AI Security", node_ids=["ic_a", "ic_b"])
        assert cluster.id.startswith("cl_")
        assert cluster.size == 2

    def test_add_remove_node(self):
        cluster = IdeaCluster(name="Test")
        cluster.add_node("ic_a")
        cluster.add_node("ic_a")  # Idempotent
        assert cluster.size == 1
        cluster.remove_node("ic_a")
        assert cluster.size == 0

    def test_cluster_roundtrip(self):
        cluster = IdeaCluster(
            name="Test Cluster",
            node_ids=["ic_a", "ic_b"],
            tags=["security", "ai"],
        )
        d = cluster.to_dict()
        restored = IdeaCluster.from_dict(d)
        assert restored.name == cluster.name
        assert restored.node_ids == cluster.node_ids


# ---- Markdown I/O Tests ----


class TestMarkdownIO:
    def test_write_and_read_node(self, tmp_vault, sample_node):
        # Write
        path = md.write_node(sample_node, tmp_vault)
        assert path.exists()
        assert path.name == "ic_test123.md"

        # Read
        restored = md.read_node(path)
        assert restored.id == sample_node.id
        assert restored.title == sample_node.title
        assert restored.source_url == sample_node.source_url
        assert restored.tags == sample_node.tags
        assert "OBLITERATUS" in restored.body

    def test_list_node_files(self, tmp_vault, sample_node):
        md.write_node(sample_node, tmp_vault)
        files = md.list_node_files(tmp_vault)
        assert len(files) == 1
        assert files[0].name == "ic_test123.md"

    def test_delete_node_file(self, tmp_vault, sample_node):
        md.write_node(sample_node, tmp_vault)
        assert md.delete_node_file(tmp_vault, "ic_test123")
        assert not md.delete_node_file(tmp_vault, "ic_nonexistent")

    def test_frontmatter_parsing_preserves_body(self, tmp_vault):
        node = IdeaNode(
            id="ic_bodytest",
            title="Body Test",
            body="Line 1\n\nLine 2\n\n## Heading\n\nMore text",
        )
        md.write_node(node, tmp_vault)
        restored = md.read_node(tmp_vault / "ic_bodytest.md")
        assert "Line 1" in restored.body
        assert "## Heading" in restored.body
        assert "More text" in restored.body


# ---- Index Tests ----


class TestIndex:
    def test_write_and_read_index(self, tmp_vault, sample_node):
        nodes = {sample_node.id: sample_node}
        edges = [IdeaEdge(source_id="ic_a", target_id="ic_b")]
        clusters = {"cl_test": IdeaCluster(id="cl_test", name="Test")}

        idx.write_index(tmp_vault, nodes, edges, clusters)

        data = idx.read_index(tmp_vault)
        assert "ic_test123" in data["nodes"]
        assert len(data["edges"]) == 1
        assert "cl_test" in data["clusters"]

    def test_read_missing_index(self, tmp_vault):
        data = idx.read_index(tmp_vault)
        assert data == {"nodes": {}, "edges": [], "clusters": {}}


# ---- Graph Tests ----


class TestIdeaGraph:
    def test_add_and_search(self, tmp_vault, sample_node):
        graph = IdeaGraph(tmp_vault)
        graph.add_node(sample_node)
        assert len(graph.nodes) == 1

        results = graph.search("brainworm")
        assert len(results) > 0
        assert results[0][0].id == sample_node.id

    def test_load_save_roundtrip(self, tmp_vault, sample_node):
        # Save
        graph = IdeaGraph(tmp_vault)
        graph.add_node(sample_node)
        graph.save()

        # Load fresh
        graph2 = IdeaGraph(tmp_vault)
        loaded = graph2.load()
        assert loaded == 1
        assert sample_node.id in graph2.nodes

    def test_edges_and_neighbours(self, tmp_vault):
        graph = IdeaGraph(tmp_vault)
        n1 = IdeaNode(id="ic_n1", title="Node 1")
        n2 = IdeaNode(id="ic_n2", title="Node 2")
        n3 = IdeaNode(id="ic_n3", title="Node 3")
        graph.add_node(n1, persist=False)
        graph.add_node(n2, persist=False)
        graph.add_node(n3, persist=False)

        graph.add_edge(IdeaEdge(source_id="ic_n1", target_id="ic_n2"))
        graph.add_edge(IdeaEdge(source_id="ic_n2", target_id="ic_n3"))

        neighbours = graph.get_neighbours("ic_n1", depth=1)
        assert "ic_n2" in neighbours
        assert "ic_n3" not in neighbours

        neighbours_2 = graph.get_neighbours("ic_n1", depth=2)
        assert "ic_n3" in neighbours_2

    def test_remove_node(self, tmp_vault, sample_node):
        graph = IdeaGraph(tmp_vault)
        graph.add_node(sample_node)
        assert graph.remove_node(sample_node.id)
        assert sample_node.id not in graph.nodes

    def test_stats(self, tmp_vault, sample_node):
        graph = IdeaGraph(tmp_vault)
        graph.add_node(sample_node, persist=False)
        stats = graph.stats
        assert stats["total_nodes"] == 1
        assert stats["by_source"]["manual"] == 1


# ---- Quality & Dedup Tests ----


class TestQualityFilter:
    def test_score_good_node(self, sample_node):
        qf = QualityFilter()
        score = qf.score(sample_node)
        assert score > 0.5

    def test_score_empty_node(self):
        qf = QualityFilter()
        node = IdeaNode(title="", body="")
        score = qf.score(node)
        assert score < 0.3

    def test_filter_batch(self, sample_node):
        qf = QualityFilter(min_score=0.3)
        empty = IdeaNode(title="", body="")
        result = qf.filter_batch([sample_node, empty])
        assert len(result) == 1
        assert result[0].id == sample_node.id


class TestDeduplication:
    def test_exact_duplicate(self, tmp_vault, sample_node):
        graph = IdeaGraph(tmp_vault)
        graph.add_node(sample_node, persist=False)

        dupe = IdeaNode(
            id="ic_dupe",
            title=sample_node.title,
            body=sample_node.body,
        )
        engine = DeduplicationEngine()
        matches = engine.find_duplicates(dupe, graph)
        assert sample_node.id in matches


# ---- Ingestion Tests ----


class TestManualIngestor:
    def test_ingest_url(self):
        ingestor = ManualPasteIngestor()
        nodes = asyncio.run(ingestor.ingest("https://www.originhq.com/blog/brainworm"))
        assert len(nodes) == 1
        assert nodes[0].source_url == "https://www.originhq.com/blog/brainworm"

    def test_ingest_tweet_url(self):
        ingestor = ManualPasteIngestor()
        nodes = asyncio.run(
            ingestor.ingest("https://x.com/elder_plinius/status/2029317072765784156")
        )
        assert len(nodes) == 1
        assert nodes[0].source_author == "@elder_plinius"

    def test_ingest_text(self):
        ingestor = ManualPasteIngestor()
        nodes = asyncio.run(ingestor.ingest("AI safety is important"))
        assert len(nodes) == 1
        assert "AI safety" in nodes[0].title


class TestTwitterBookmarksIngestor:
    def test_parse_twitter_js(self):
        js_content = """window.YTD.bookmark.part0 = [
            {"bookmark": {"tweetId": "123", "fullText": "Test tweet about AI"}},
            {"bookmark": {"tweetId": "456", "fullText": "Another tweet"}}
        ]"""
        data = _parse_twitter_js(js_content)
        assert len(data) == 2
        assert data[0]["bookmark"]["tweetId"] == "123"

    def test_ingest_bookmarks_file(self, tmp_path):
        bookmarks_file = tmp_path / "bookmarks.js"
        bookmarks_file.write_text("""window.YTD.bookmark.part0 = [
            {"bookmark": {"tweetId": "111", "fullText": "AI safety research is critical for alignment", "screenName": "researcher1"}},
            {"bookmark": {"tweetId": "222", "fullText": "New paper on adversarial attacks against LLMs", "screenName": "researcher2"}}
        ]""")

        ingestor = TwitterBookmarksIngestor()
        nodes = asyncio.run(ingestor.ingest(str(bookmarks_file)))
        assert len(nodes) == 2
        assert all(n.source_type == "twitter_bookmark" for n in nodes)
        assert any("safety" in n.title.lower() for n in nodes)


# ---- Operations Tests ----


class TestAutoLink:
    def test_auto_link_similar_nodes(self, tmp_vault):
        graph = IdeaGraph(tmp_vault)
        n1 = IdeaNode(
            id="ic_a1",
            title="AI Safety and Prompt Injection",
            body="Prompt injection is a key AI safety concern",
            tags=["ai-security", "prompt-injection"],
        )
        n2 = IdeaNode(
            id="ic_a2",
            title="Defending Against Prompt Attacks",
            body="Multi-model consensus defends against prompt injection attacks",
            tags=["ai-security", "prompt-injection", "defense"],
        )
        n3 = IdeaNode(
            id="ic_a3",
            title="Cooking Recipes for Pasta",
            body="How to make great pasta from scratch",
            tags=["cooking", "recipes"],
        )
        graph.add_node(n1, persist=False)
        graph.add_node(n2, persist=False)
        graph.add_node(n3, persist=False)

        new_edges = ops.auto_link(graph, min_similarity=0.2)
        # n1 and n2 should be linked (similar), n3 should not
        linked_pairs = {(e.source_id, e.target_id) for e in new_edges}
        assert any(("ic_a1" in pair and "ic_a2" in pair) for pair in linked_pairs)


class TestAutoClustering:
    def test_cluster_connected_nodes(self, tmp_vault):
        graph = IdeaGraph(tmp_vault)
        n1 = IdeaNode(id="ic_c1", title="Node 1", tags=["ai", "security"])
        n2 = IdeaNode(id="ic_c2", title="Node 2", tags=["ai", "security"])
        n3 = IdeaNode(id="ic_c3", title="Node 3", tags=["cooking", "recipes"])
        graph.add_node(n1, persist=False)
        graph.add_node(n2, persist=False)
        graph.add_node(n3, persist=False)

        clusters = ops.auto_cluster(graph, min_cluster_size=2)
        # n1 and n2 share 2+ tags, should cluster; n3 should not
        assert len(clusters) >= 1
        cluster_node_sets = [set(c.node_ids) for c in clusters.values()]
        assert any({"ic_c1", "ic_c2"}.issubset(s) for s in cluster_node_sets)


# ---- IdeaCloud Core Tests ----


class TestIdeaCloud:
    def test_full_workflow(self, tmp_vault):
        """Test the complete workflow: ingest → search → cluster."""
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()

        # Ingest manually
        node = asyncio.run(
            cloud.ingest_manual(
                content="Brainworm malware lives in CLAUDE.md files and hijacks agent reasoning",
                title="Brainworm: CUA Malware via Context Injection",
                source_url="https://www.originhq.com/blog/brainworm",
                tags=["ai-security", "prompt-injection", "agent-safety"],
            )
        )
        assert node is not None

        # Search
        results = cloud.search("brainworm")
        assert len(results) > 0

        # Stats
        stats = cloud.stats
        assert stats["total_nodes"] == 1

    def test_three_tweets_integration(self, tmp_vault):
        """Integration test with the 3 tweets from today's conversation."""
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()

        # 1. Brainworm
        n1 = asyncio.run(
            cloud.ingest_manual(
                content=(
                    "Natural language malware that lives in CLAUDE.md files — "
                    "agent tool calls as the execution primitive. No binaries, no signatures.\n\n"
                    "Key insight: everything in a context window gets reasoned over "
                    "with equal authority. No internal mechanism marks tool results "
                    "as less trustworthy than system instructions."
                ),
                title="Brainworm: CUA Malware via Context Injection",
                source_url="https://www.originhq.com/blog/brainworm",
                source_author="Origin HQ",
                tags=["ai-security", "prompt-injection", "agent-safety", "supply-chain"],
            )
        )

        # 2. OBLITERATUS
        n2 = asyncio.run(
            cloud.ingest_manual(
                content=(
                    "Toolkit for removing refusal behaviors from open-weight LLMs "
                    "using SVD-based weight projection. 13 ablation methods. "
                    "Surgically identifies directions in weight space that encode "
                    "refusal and projects them out."
                ),
                title="OBLITERATUS: Open-Weight LLM Refusal Removal Toolkit",
                source_url="https://x.com/elder_plinius/status/2029317072765784156",
                source_author="@elder_plinius",
                tags=["ai-security", "model-modification", "open-weights", "alignment"],
            )
        )

        # 3. Capraro RLHF
        n3 = asyncio.run(
            cloud.ingest_manual(
                content=(
                    "GPT says torture is acceptable to prevent nuclear apocalypse "
                    "but harassment is absolutely not. Reversal appears only when "
                    "target is a woman. RLHF creates mechanical overgeneralization "
                    "of certain harm categories."
                ),
                title="RLHF Moral Inconsistency: Torture vs Harassment Gender Bias",
                source_url="https://x.com/ValerioCapraro/status/2029593915674771457",
                source_author="@ValerioCapraro",
                tags=["ai-security", "rlhf", "alignment", "bias"],
            )
        )

        assert n1 is not None
        assert n2 is not None
        assert n3 is not None

        # All 3 should be in the graph
        assert cloud.stats["total_nodes"] == 3

        # Search should find them
        assert len(cloud.search("brainworm")) > 0
        assert len(cloud.search("OBLITERATUS")) > 0
        assert len(cloud.search("RLHF")) > 0

        # Auto-link should find connections (shared ai-security tag)
        new_edges = cloud.auto_link(min_similarity=0.2)
        assert len(new_edges) > 0

        # Auto-cluster should group related ideas
        clusters = cloud.auto_cluster()
        assert len(clusters) >= 1

        # Verify markdown files exist on disk
        files = list(tmp_vault.glob("ic_*.md"))
        assert len(files) == 3

        # Verify round-trip: reload from disk
        cloud2 = IdeaCloud(vault_path=tmp_vault)
        loaded = cloud2.load()
        assert loaded == 3

        # Search still works after reload
        results = cloud2.search("prompt injection")
        assert len(results) > 0

        # Cluster summary should work
        if clusters:
            first_cluster_id = list(clusters.keys())[0]
            summary = cloud2.cluster_summary(first_cluster_id)
            assert len(summary) > 0

    def test_dedup_prevents_double_add(self, tmp_vault):
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()

        node = asyncio.run(
            cloud.ingest_manual(
                content="Test idea about something",
                title="Test Idea",
            )
        )
        assert node is not None

        # Adding the same content again should be rejected
        dupe = asyncio.run(
            cloud.ingest_manual(
                content="Test idea about something",
                title="Test Idea",
            )
        )
        assert dupe is None
        assert cloud.stats["total_nodes"] == 1
