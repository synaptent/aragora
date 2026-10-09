"""
Tests for context management service.
"""

import pytest
from unittest.mock import MagicMock

from aragora.documents.chunking.context_manager import (
    ContextManager,
    ContextWindow,
    ContextConfig,
    ContextStrategy,
    get_context_manager,
)
from aragora.documents.models import DocumentChunk, ChunkType


class TestContextConfig:
    """Tests for ContextConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        from aragora.config.model_pins import GPT6_ASTRA_DIRECT

        config = ContextConfig()
        assert config.model == GPT6_ASTRA_DIRECT
        assert config.max_tokens is None
        assert config.strategy is None
        assert config.rag_top_k == 20
        assert config.output_reserve_tokens == 4096

    def test_custom_config(self):
        """Test custom configuration."""
        config = ContextConfig(
            model="gemini-3-pro",
            max_tokens=500000,
            strategy=ContextStrategy.FULL,
            include_metadata=False,
        )
        assert config.model == "gemini-3-pro"
        assert config.max_tokens == 500000
        assert config.strategy == ContextStrategy.FULL
        assert config.include_metadata is False

    def test_rag_settings(self):
        """Test RAG-specific settings."""
        config = ContextConfig(
            rag_top_k=50,
            rag_min_score=0.7,
        )
        assert config.rag_top_k == 50
        assert config.rag_min_score == 0.7


class TestContextWindow:
    """Tests for ContextWindow dataclass."""

    def test_create_context_window(self):
        """Test creating a context window."""
        window = ContextWindow(
            content="Test content",
            token_count=100,
            model="gpt-4",
            strategy=ContextStrategy.FULL,
            document_ids=["doc1"],
            chunk_ids=["chunk1", "chunk2"],
        )
        assert window.content == "Test content"
        assert window.token_count == 100
        assert len(window.chunk_ids) == 2

    def test_utilization_calculation(self):
        """Test context utilization calculation."""
        window = ContextWindow(
            content="Test",
            token_count=100000,
            model="claude-3.5-sonnet",  # 200K limit
            strategy=ContextStrategy.FULL,
            document_ids=[],
            chunk_ids=[],
        )
        # 100k out of 200k = 0.5 utilization
        assert window.utilization == 0.5

    def test_to_dict(self):
        """Test serialization to dictionary."""
        window = ContextWindow(
            content="Test",
            token_count=50,
            model="gpt-4",
            strategy=ContextStrategy.RAG,
            document_ids=["doc1"],
            chunk_ids=["c1"],
            metadata={"query": "test"},
        )
        data = window.to_dict()
        assert data["content"] == "Test"
        assert data["strategy"] == "rag"
        assert "utilization" in data


class TestContextStrategy:
    """Tests for ContextStrategy enum."""

    def test_strategy_values(self):
        """Test all strategy values."""
        assert ContextStrategy.FULL.value == "full"
        assert ContextStrategy.RAG.value == "rag"
        assert ContextStrategy.HYBRID.value == "hybrid"
        assert ContextStrategy.CHUNKED.value == "chunked"
        assert ContextStrategy.AUTO.value == "auto"


class TestContextManager:
    """Tests for ContextManager class."""

    @pytest.fixture
    def manager(self):
        """Create a context manager instance."""
        return ContextManager()

    @pytest.fixture
    def sample_chunks(self):
        """Create sample document chunks."""
        return [
            DocumentChunk(
                id="chunk1",
                document_id="doc1",
                sequence=0,
                content="This is the first section about security.",
                chunk_type=ChunkType.TEXT,
                heading_context="Introduction",
                start_page=1,
                end_page=1,
                token_count=10,
            ),
            DocumentChunk(
                id="chunk2",
                document_id="doc1",
                sequence=1,
                content="This section discusses compliance requirements.",
                chunk_type=ChunkType.TEXT,
                heading_context="Compliance",
                start_page=2,
                end_page=2,
                token_count=8,
            ),
            DocumentChunk(
                id="chunk3",
                document_id="doc1",
                sequence=2,
                content="Here we cover risk assessment procedures.",
                chunk_type=ChunkType.TEXT,
                heading_context="Risk Assessment",
                start_page=3,
                end_page=3,
                token_count=9,
            ),
        ]

    def test_select_strategy_full_for_small_docs(self, manager):
        """Test strategy selection for small documents."""
        # 1000 tokens should fit in most models
        strategy = manager.select_strategy(
            total_tokens=1000,
            model="gpt-4-turbo",
        )
        assert strategy == ContextStrategy.FULL

    def test_select_strategy_rag_for_large_docs(self, manager):
        """Test strategy selection for large documents."""
        # 200K tokens won't fit in 128K context
        strategy = manager.select_strategy(
            total_tokens=200000,
            model="gpt-4-turbo",
        )
        # Should recommend RAG or CHUNKED for oversized docs
        assert strategy in [ContextStrategy.RAG, ContextStrategy.CHUNKED]

    def test_select_strategy_full_for_gemini_large(self, manager):
        """Test Gemini 3 Pro can handle large contexts."""
        # 500K tokens should fit in Gemini 3 Pro (1M limit)
        strategy = manager.select_strategy(
            total_tokens=500000,
            model="gemini-3-pro",
        )
        assert strategy == ContextStrategy.FULL

    def test_select_strategy_respects_override(self, manager):
        """Test explicit strategy override."""
        config = ContextConfig(
            model="gpt-4",
            strategy=ContextStrategy.RAG,
        )
        strategy = manager.select_strategy(
            total_tokens=100,  # Small enough for FULL
            model="gpt-4",
            config=config,
        )
        assert strategy == ContextStrategy.RAG

    def test_recommend_model_small_docs(self, manager):
        """Test model recommendation for small documents."""
        model = manager.recommend_model(total_tokens=10000)
        # Should recommend efficient model for small docs
        assert model in ["gpt-4-turbo", "claude-3.5-sonnet", "gemini-3-pro"]

    def test_recommend_model_large_docs(self, manager):
        """Test model recommendation for large documents."""
        model = manager.recommend_model(total_tokens=600000)
        # Should recommend Gemini 3 Pro for very large docs
        assert model == "gemini-3-pro"

    def test_recommend_model_prefers_reasoning(self, manager):
        """Test model recommendation with reasoning preference."""
        model = manager.recommend_model(
            total_tokens=50000,
            prefer_reasoning=True,
        )
        assert model == "claude-3.5-sonnet"

    @pytest.mark.asyncio
    async def test_build_context_full(self, manager, sample_chunks):
        """Test building full context from chunks."""
        config = ContextConfig(model="gpt-4-turbo")
        window = await manager.build_context(
            chunks=sample_chunks,
            config=config,
        )

        assert window.token_count > 0
        assert len(window.chunk_ids) == 3
        assert window.strategy == ContextStrategy.FULL
        assert "security" in window.content.lower()

    @pytest.mark.asyncio
    async def test_build_context_preserves_order(self, manager, sample_chunks):
        """Test that context preserves document order."""
        config = ContextConfig(
            model="gpt-4-turbo",
            preserve_document_order=True,
        )
        window = await manager.build_context(
            chunks=sample_chunks[::-1],  # Reverse order
            config=config,
        )

        # Content should be in document order (by sequence)
        assert window.chunk_ids == ["chunk1", "chunk2", "chunk3"]

    @pytest.mark.asyncio
    async def test_build_context_includes_metadata(self, manager, sample_chunks):
        """Test that metadata is included when enabled."""
        config = ContextConfig(
            model="gpt-4-turbo",
            include_metadata=True,
            include_page_numbers=True,
        )
        window = await manager.build_context(
            chunks=sample_chunks,
            config=config,
        )

        assert "[Section:" in window.content or "[Page" in window.content

    @pytest.mark.asyncio
    async def test_build_context_truncates_when_needed(self, manager):
        """Test that context is truncated to fit token limit."""
        # Create many chunks
        chunks = [
            DocumentChunk(
                id=f"chunk{i}",
                document_id="doc1",
                sequence=i,
                content="This is a test chunk with some content. " * 50,
                chunk_type=ChunkType.TEXT,
                token_count=500,
            )
            for i in range(100)
        ]

        config = ContextConfig(
            model="gpt-4",  # 8K limit
            max_tokens=8000,
        )
        window = await manager.build_context(
            chunks=chunks,
            config=config,
        )

        # Should have truncated - not all 100 chunks included
        assert len(window.chunk_ids) < 100
        assert window.metadata.get("truncated", False) is True

    def test_estimate_cost(self, manager):
        """Test cost estimation."""
        cost = manager.estimate_cost(
            total_tokens=100000,
            model="gpt-4-turbo",
        )

        assert "input_tokens" in cost
        assert "input_cost_usd" in cost
        assert "output_cost_usd" in cost
        assert "total_cost_usd" in cost
        assert cost["total_cost_usd"] > 0


class TestGlobalContextManager:
    """Tests for global context manager instance."""

    def test_get_context_manager_singleton(self):
        """Test that global manager is a singleton."""
        manager1 = get_context_manager()
        manager2 = get_context_manager()
        assert manager1 is manager2

    def test_global_manager_has_methods(self):
        """Test global manager has expected methods."""
        manager = get_context_manager()
        assert hasattr(manager, "build_context")
        assert hasattr(manager, "select_strategy")
        assert hasattr(manager, "recommend_model")


class TestDefaultModelIsLiveWithoutAnUpgrade:
    """The config's default must name an active catalog row directly.

    "gpt-4-turbo" is an UPGRADES key: the default depended on the upgrade
    map to name anything live at all, and carried gpt-4-turbo's 128K
    context limit into every window this config sized (2026-09-05
    merge-gate addendum on #9989).
    """

    def test_default_model_is_an_active_catalog_row(self):
        from aragora.models.catalog import spec_or_none
        from aragora.models.upgrade_map import UPGRADES

        model = ContextConfig().model
        assert model not in UPGRADES
        spec = spec_or_none(model)
        assert spec is not None and not spec.retired

    def test_default_model_context_window_is_the_frontier_one(self):
        from aragora.models.catalog import spec_or_none

        spec = spec_or_none(ContextConfig().model)
        assert spec is not None
        assert spec.context_window >= 1_000_000
