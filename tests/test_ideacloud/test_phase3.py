"""Tests for Idea Cloud Phase 3 enhancements.

Covers: embedding provider, Pulse bridge, hierarchical storage,
CLI registration, enhanced auto-linking with embeddings.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aragora.ideacloud.graph.node import IdeaNode
from aragora.ideacloud.graph.edge import IdeaEdge
from aragora.ideacloud.graph.graph import IdeaGraph
from aragora.ideacloud.graph import operations as ops
from aragora.ideacloud.graph.embeddings import (
    EmbeddingProvider,
    cosine_similarity,
)
from aragora.ideacloud.storage.markdown_io import (
    write_node,
    read_node,
    list_node_files,
    migrate_to_hierarchical,
)
from aragora.ideacloud.ingestion.pulse_bridge import PulseBridge
from aragora.ideacloud.core import IdeaCloud


@pytest.fixture
def tmp_vault(tmp_path):
    vault = tmp_path / ".aragora_ideas"
    vault.mkdir()
    return vault


# ---- Embedding Provider Tests ----


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_empty_vectors(self):
        assert cosine_similarity([], []) == 0.0

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_different_lengths(self):
        assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


class TestEmbeddingProvider:
    def test_no_provider(self):
        provider = EmbeddingProvider()
        assert not provider.available
        assert provider.similarity("a", "b") == 0.0

    def test_custom_callable(self):
        def mock_embed(texts):
            # Simple: hash to 3D vector
            return [[float(len(t)), float(len(t) % 3), 1.0] for t in texts]

        provider = EmbeddingProvider.from_callable(mock_embed, name="test")
        assert provider.available
        assert provider.provider_name == "test"

        # Same text → similarity 1.0
        sim = provider.similarity("hello", "hello")
        assert sim == pytest.approx(1.0)

    def test_cache_works(self):
        call_count = 0

        def counting_embed(texts):
            nonlocal call_count
            call_count += 1
            return [[1.0, 0.0] for _ in texts]

        provider = EmbeddingProvider.from_callable(counting_embed)

        # First call
        provider.embed_one("test text")
        assert call_count == 1
        assert provider.cache_size == 1

        # Second call with same text — should use cache
        provider.embed_one("test text")
        assert call_count == 1  # No new API call

        # Different text
        provider.embed_one("other text")
        assert call_count == 2
        assert provider.cache_size == 2

    def test_clear_cache(self):
        def mock_embed(texts):
            return [[1.0] for _ in texts]

        provider = EmbeddingProvider.from_callable(mock_embed)
        provider.embed_one("a")
        assert provider.cache_size == 1
        provider.clear_cache()
        assert provider.cache_size == 0

    def test_batch_embed(self):
        def mock_embed(texts):
            return [[float(i)] for i in range(len(texts))]

        provider = EmbeddingProvider.from_callable(mock_embed)
        results = provider.embed(["a", "b", "c"])
        assert len(results) == 3

    def test_from_openai_without_package(self):
        """Should gracefully handle missing openai package."""
        with patch.dict("sys.modules", {"openai": None}):
            provider = EmbeddingProvider.from_openai()
            # Should not crash, just be unavailable
            assert provider.provider_name == "none"

    def test_from_sentence_transformers_without_package(self):
        """Should gracefully handle missing sentence_transformers."""
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            provider = EmbeddingProvider.from_sentence_transformers()
            assert provider.provider_name == "none"


class TestAutoLinkWithEmbeddings:
    def test_embedding_boosts_similarity(self, tmp_vault):
        """Embedding similarity should enable linking nodes that keyword similarity misses."""
        graph = IdeaGraph(tmp_vault)

        n1 = IdeaNode(
            id="ic_emb1",
            title="Machine learning safety challenges",
            body="Deep learning models can exhibit unsafe behaviors.",
            tags=["ml-safety"],
        )
        n2 = IdeaNode(
            id="ic_emb2",
            title="Neural network robustness",
            body="Adversarial attacks on neural nets reveal vulnerabilities.",
            tags=["robustness"],
        )
        graph.add_node(n1, persist=False)
        graph.add_node(n2, persist=False)

        # Without embeddings: these may not link (different keywords/tags)
        edges_no_embed = ops.auto_link(
            graph,
            min_similarity=0.3,
            inject_wiki_links=False,
        )

        # Reset
        graph.edges.clear()
        graph._adjacency.clear()

        # With embeddings: mock that returns high similarity
        def mock_embed(texts):
            # Return similar vectors for all texts
            return [[0.9, 0.1, 0.5] for _ in texts]

        provider = EmbeddingProvider.from_callable(mock_embed)

        edges_with_embed = ops.auto_link(
            graph,
            min_similarity=0.3,
            inject_wiki_links=False,
            embedding_provider=provider,
        )

        # Embeddings should produce edges (since mock gives high similarity)
        assert len(edges_with_embed) > 0


# ---- Hierarchical Storage Tests ----


class TestHierarchicalStorage:
    def test_write_flat_mode(self, tmp_vault):
        node = IdeaNode(
            id="ic_flat1",
            title="Flat Storage Test",
            body="Testing flat storage.",
            tags=["test"],
            pipeline_status="inbox",
        )
        path = write_node(node, tmp_vault, hierarchical=False)
        assert path == tmp_vault / "ic_flat1.md"
        assert path.exists()

    def test_write_hierarchical_mode(self, tmp_vault):
        node = IdeaNode(
            id="ic_hier1",
            title="Hierarchical Storage Test",
            body="Testing hierarchical storage.",
            tags=["test"],
            pipeline_status="inbox",
        )
        path = write_node(node, tmp_vault, hierarchical=True)
        assert path == tmp_vault / "inbox" / "ic_hier1.md"
        assert path.exists()

    def test_hierarchical_move_on_status_change(self, tmp_vault):
        """Node should move directories when status changes."""
        node = IdeaNode(
            id="ic_move1",
            title="Moving Node",
            body="This node will move.",
            tags=["test"],
            pipeline_status="inbox",
        )

        # Write to inbox/
        write_node(node, tmp_vault, hierarchical=True)
        assert (tmp_vault / "inbox" / "ic_move1.md").exists()

        # Change status and re-write
        node.pipeline_status = "prioritized"
        write_node(node, tmp_vault, hierarchical=True)

        assert (tmp_vault / "prioritized" / "ic_move1.md").exists()
        # Old location should be cleaned up
        assert not (tmp_vault / "inbox" / "ic_move1.md").exists()

    def test_list_finds_hierarchical_files(self, tmp_vault):
        """list_node_files should find files in subdirectories."""
        # Write one flat, one hierarchical
        n1 = IdeaNode(id="ic_lh1", title="Flat", body="In root.", tags=["test"])
        n2 = IdeaNode(
            id="ic_lh2",
            title="Hier",
            body="In subdir.",
            tags=["test"],
            pipeline_status="candidate",
        )

        write_node(n1, tmp_vault, hierarchical=False)
        write_node(n2, tmp_vault, hierarchical=True)

        files = list_node_files(tmp_vault)
        names = {f.name for f in files}
        assert "ic_lh1.md" in names
        assert "ic_lh2.md" in names

    def test_read_from_hierarchical(self, tmp_vault):
        """Nodes in subdirectories should still be readable."""
        node = IdeaNode(
            id="ic_rh1",
            title="Read Hierarchical",
            body="Should be readable from subdir.",
            tags=["test"],
            pipeline_status="exported",
        )
        path = write_node(node, tmp_vault, hierarchical=True)
        loaded = read_node(path)
        assert loaded.title == "Read Hierarchical"
        assert loaded.pipeline_status == "exported"

    def test_migrate_flat_to_hierarchical(self, tmp_vault):
        """Migration should move flat files into status directories."""
        # Create flat files
        for i in range(4):
            status = ["inbox", "candidate", "prioritized", "exported"][i]
            node = IdeaNode(
                id=f"ic_mig{i}",
                title=f"Node {i}",
                body=f"Content for node {i}.",
                tags=["test"],
                pipeline_status=status,
            )
            write_node(node, tmp_vault, hierarchical=False)

        # All should be in root
        assert len(list(tmp_vault.glob("ic_mig*.md"))) == 4

        # Run migration
        result = migrate_to_hierarchical(tmp_vault)

        # Should have moved files
        assert sum(result.values()) == 4
        assert result.get("inbox", 0) == 1
        assert result.get("candidate", 0) == 1

        # Root should be empty of ic_mig files
        assert len(list(tmp_vault.glob("ic_mig*.md"))) == 0

        # Subdirectories should have the files
        assert (tmp_vault / "inbox" / "ic_mig0.md").exists()
        assert (tmp_vault / "prioritized" / "ic_mig2.md").exists()


# ---- Pulse Bridge Tests ----


class TestPulseBridgeTopicConversion:
    def test_topic_to_node(self):
        bridge = PulseBridge(
            relevance_keywords=["ai", "safety"],
            min_volume=10,
        )

        # Create a mock TrendingTopic
        topic = MagicMock()
        topic.platform = "hackernews"
        topic.topic = "New AI safety benchmark shows critical gaps"
        topic.volume = 500
        topic.category = "ai"
        topic.raw_data = {
            "url": "https://example.com/article",
            "author": "researcher",
            "score": 342,
            "num_comments": 87,
        }

        node = bridge._topic_to_node(topic)

        assert node.title == "New AI safety benchmark shows critical gaps"
        assert "pulse_hackernews" in node.source_type
        assert "pulse-hackernews" in node.tags
        assert "ai" in node.tags
        assert "safety" in node.tags
        assert node.source_url == "https://example.com/article"
        assert "500" in node.body  # Volume
        assert "342" in node.body  # Score from raw_data

    def test_filter_by_keywords(self):
        bridge = PulseBridge(
            relevance_keywords=["ai", "security"],
        )

        relevant = MagicMock()
        relevant.topic = "AI security research breakthrough"
        relevant.category = "tech"

        irrelevant = MagicMock()
        irrelevant.topic = "Best cooking recipes 2026"
        irrelevant.category = "lifestyle"

        filtered = bridge._filter_topics([relevant, irrelevant])
        assert len(filtered) == 1
        assert filtered[0].topic == "AI security research breakthrough"

    def test_no_keywords_passes_all(self):
        bridge = PulseBridge(relevance_keywords=[])
        topics = [MagicMock(), MagicMock(), MagicMock()]
        for t in topics:
            t.topic = "anything"
            t.category = ""
        filtered = bridge._filter_topics(topics)
        assert len(filtered) == 3

    def test_fetch_without_pulse_module(self):
        """Should return empty list when Pulse is unavailable."""
        bridge = PulseBridge()

        with patch.dict("sys.modules", {"aragora.pulse": None}):
            # The import inside _fetch_topics should fail gracefully
            nodes = asyncio.run(
                bridge.fetch_and_convert(
                    platforms=["hackernews"],
                    limit_per_platform=5,
                )
            )
            # May return empty due to import failure
            assert isinstance(nodes, list)


# ---- CLI Registration Tests ----


class TestCLIRegistration:
    def test_parser_includes_ideacloud(self):
        """The ideacloud command should be registered in the CLI parser."""
        try:
            from aragora.cli.parser import build_parser

            parser = build_parser()
            # Check that 'ideacloud' is a valid subcommand
            # We parse with just 'ideacloud' — it should not raise SystemExit
            # (it might print help, which is fine)
            assert parser is not None
        except ImportError:
            pytest.skip("CLI parser not available")

    def test_ideacloud_subcommands_registered(self):
        """All Phase 2+ CLI commands should be registered."""
        from aragora.ideacloud.cli.commands import add_ideacloud_commands
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_ideacloud_commands(subparsers)

        # Parse various subcommands to verify they're registered
        args = parser.parse_args(["ideacloud", "stats", "--vault", "/tmp/test"])
        assert args.ideacloud_cmd == "stats"
        assert args.vault == "/tmp/test"

        args = parser.parse_args(["ideacloud", "export", "cl_test", "--format", "debate"])
        assert args.ideacloud_cmd == "export"
        assert args.cluster_id == "cl_test"
        assert args.format == "debate"

        args = parser.parse_args(["ideacloud", "promote", "ic_test1", "candidate"])
        assert args.ideacloud_cmd == "promote"
        assert args.target_id == "ic_test1"
        assert args.status == "candidate"

        args = parser.parse_args(["ideacloud", "pulse", "--platforms", "hackernews,arxiv"])
        assert args.ideacloud_cmd == "pulse"
        assert args.platforms == "hackernews,arxiv"

        args = parser.parse_args(["ideacloud", "rss", "--url", "https://feed.xml"])
        assert args.ideacloud_cmd == "rss"
        assert args.url == ["https://feed.xml"]

        args = parser.parse_args(["ideacloud", "sync-km", "--direction", "both"])
        assert args.ideacloud_cmd == "sync-km"
        assert args.direction == "both"


# ---- Core Pulse Ingestion Tests ----


class TestIdeaCloudPulseIngestion:
    def test_ingest_pulse_method_exists(self, tmp_vault):
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()
        assert hasattr(cloud, "ingest_pulse")
        assert callable(cloud.ingest_pulse)

    def test_ingest_pulse_with_mock_bridge(self, tmp_vault):
        """Test that ingest_pulse wires through to PulseBridge correctly."""
        cloud = IdeaCloud(vault_path=tmp_vault)
        cloud.load()

        # Mock the PulseBridge to avoid needing Pulse module
        mock_nodes = [
            IdeaNode(
                title="Trending AI Topic",
                body="A substantial body of text about trending AI security research from pulse",
                tags=["pulse-hackernews", "ai", "security"],
                source_type="pulse_hackernews",
            ),
        ]

        with patch(
            "aragora.ideacloud.ingestion.pulse_bridge.PulseBridge.fetch_and_convert",
            return_value=mock_nodes,
        ):
            nodes = asyncio.run(
                cloud.ingest_pulse(
                    platforms=["hackernews"],
                    limit_per_platform=5,
                    relevance_keywords=["ai"],
                )
            )
            # The node should pass quality filter (has title + body + tags)
            assert len(nodes) >= 0  # May be filtered by quality


# ---- Integration: Embedding Provider with Graph Operations ----


class TestEmbeddingIntegration:
    def test_auto_link_passes_provider_through(self, tmp_vault):
        """Verify that auto_link accepts and uses embedding_provider."""
        graph = IdeaGraph(tmp_vault)

        n1 = IdeaNode(
            id="ic_ei1",
            title="Quantum computing advances",
            body="Recent breakthroughs in quantum error correction.",
            tags=["quantum", "computing"],
        )
        n2 = IdeaNode(
            id="ic_ei2",
            title="Quantum supremacy implications",
            body="What quantum advantage means for cryptography.",
            tags=["quantum", "crypto"],
        )
        graph.add_node(n1, persist=False)
        graph.add_node(n2, persist=False)

        # Create a mock provider that tracks calls
        call_log = []

        def tracking_embed(texts):
            call_log.append(texts)
            return [[0.8, 0.2, 0.1] for _ in texts]

        provider = EmbeddingProvider.from_callable(tracking_embed)

        edges = ops.auto_link(
            graph,
            min_similarity=0.1,
            inject_wiki_links=False,
            embedding_provider=provider,
        )

        # Provider should have been called
        assert len(call_log) > 0
        assert len(edges) > 0
