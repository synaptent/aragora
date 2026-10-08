"""
Unit tests for RLM compressor module.

Tests hierarchical compression internals, types, and cache behavior.

Run with:
    pytest tests/rlm/test_compressor.py -v
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import MagicMock, patch

# Import RLM modules
from aragora.rlm.compressor import (
    ChunkInfo,
    HierarchicalCompressor,
    clear_compression_cache,
    _compression_cache,
)
from aragora.rlm.types import (
    AbstractionLevel,
    AbstractionNode,
    CompressionResult,
    DecompositionStrategy,
    RLMConfig,
    RLMContext,
    RLMQuery,
    RLMResult,
)


# =============================================================================
# Type Tests
# =============================================================================


class TestAbstractionLevel:
    """Test AbstractionLevel enum."""

    def test_level_values(self):
        """Test abstraction level enum values."""
        assert AbstractionLevel.FULL.value == 0
        assert AbstractionLevel.DETAILED.value == 1
        assert AbstractionLevel.SUMMARY.value == 2
        assert AbstractionLevel.ABSTRACT.value == 3
        assert AbstractionLevel.METADATA.value == 4

    def test_level_ordering(self):
        """Test that levels can be compared by compression amount."""
        assert AbstractionLevel.FULL.value < AbstractionLevel.DETAILED.value
        assert AbstractionLevel.DETAILED.value < AbstractionLevel.SUMMARY.value
        assert AbstractionLevel.SUMMARY.value < AbstractionLevel.ABSTRACT.value
        assert AbstractionLevel.ABSTRACT.value < AbstractionLevel.METADATA.value


class TestDecompositionStrategy:
    """Test DecompositionStrategy enum."""

    def test_strategy_values(self):
        """Test strategy enum values."""
        assert DecompositionStrategy.PEEK.value == "peek"
        assert DecompositionStrategy.GREP.value == "grep"
        assert DecompositionStrategy.PARTITION_MAP.value == "partition_map"
        assert DecompositionStrategy.SUMMARIZE.value == "summarize"
        assert DecompositionStrategy.HIERARCHICAL.value == "hierarchical"
        assert DecompositionStrategy.AUTO.value == "auto"


class TestRLMConfig:
    """Test RLMConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = RLMConfig()

        assert config.root_model == "claude"
        assert config.sub_model == "gpt-4o-mini"
        assert config.max_depth == 2
        assert config.max_sub_calls == 10
        assert config.target_tokens == 8000
        assert config.overlap_tokens == 200
        assert config.compression_ratio == 0.3
        assert config.preserve_structure is True
        assert config.default_strategy == DecompositionStrategy.AUTO
        assert config.parallel_sub_calls is True
        assert config.cache_compressions is True
        assert config.cache_ttl_seconds == 3600
        assert config.include_citations is True
        assert config.citation_format == "[L{level}:{chunk}]"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = RLMConfig(
            root_model="gpt-4",
            sub_model="gpt-3.5-turbo",
            max_depth=5,
            target_tokens=8000,
            parallel_sub_calls=False,
            cache_compressions=False,
        )

        assert config.root_model == "gpt-4"
        assert config.sub_model == "gpt-3.5-turbo"
        assert config.max_depth == 5
        assert config.target_tokens == 8000
        assert config.parallel_sub_calls is False
        assert config.cache_compressions is False


class TestAbstractionNode:
    """Test AbstractionNode dataclass."""

    def test_node_creation(self):
        """Test basic node creation."""
        node = AbstractionNode(
            id="test_node",
            level=AbstractionLevel.SUMMARY,
            content="Test content",
            token_count=100,
        )

        assert node.id == "test_node"
        assert node.level == AbstractionLevel.SUMMARY
        assert node.content == "Test content"
        assert node.token_count == 100
        assert node.parent_id is None
        assert node.child_ids == []
        assert node.source_range == (0, 0)
        assert node.source_chunks == []
        assert node.key_topics == []
        assert node.confidence == 1.0

    def test_node_auto_id_generation(self):
        """Test that empty ID triggers auto-generation."""
        node = AbstractionNode(
            id="",
            level=AbstractionLevel.FULL,
            content="Content",
            token_count=50,
        )

        # Auto-generated ID should be 8 chars from UUID
        assert len(node.id) == 8

    def test_node_with_hierarchy(self):
        """Test node with parent and children."""
        node = AbstractionNode(
            id="parent_node",
            level=AbstractionLevel.SUMMARY,
            content="Summary",
            token_count=50,
            parent_id="grandparent",
            child_ids=["child1", "child2"],
            source_chunks=["chunk1", "chunk2"],
        )

        assert node.parent_id == "grandparent"
        assert node.child_ids == ["child1", "child2"]
        assert node.source_chunks == ["chunk1", "chunk2"]


class TestRLMContext:
    """Test RLMContext dataclass."""

    @pytest.fixture
    def sample_context(self) -> RLMContext:
        """Create a sample RLM context for testing."""
        context = RLMContext(
            original_content="Original long content here",
            original_tokens=100,
            source_type="text",
            created_at="2025-01-01T00:00:00Z",
        )

        # Add nodes at different levels
        full_node = AbstractionNode(
            id="L0_0",
            level=AbstractionLevel.FULL,
            content="Full content",
            token_count=100,
        )
        summary_node = AbstractionNode(
            id="L2_0",
            level=AbstractionLevel.SUMMARY,
            content="Summary content",
            token_count=30,
            child_ids=["L0_0"],
        )

        context.levels[AbstractionLevel.FULL] = [full_node]
        context.levels[AbstractionLevel.SUMMARY] = [summary_node]
        context.nodes_by_id["L0_0"] = full_node
        context.nodes_by_id["L2_0"] = summary_node

        return context

    def test_get_at_level_existing(self, sample_context: RLMContext):
        """Test getting content at an existing level."""
        content = sample_context.get_at_level(AbstractionLevel.SUMMARY)
        assert content == "Summary content"

    def test_get_at_level_missing(self, sample_context: RLMContext):
        """Test getting content at a missing level returns original."""
        content = sample_context.get_at_level(AbstractionLevel.ABSTRACT)
        assert content == "Original long content here"

    def test_get_node_existing(self, sample_context: RLMContext):
        """Test getting an existing node."""
        node = sample_context.get_node("L0_0")
        assert node is not None
        assert node.content == "Full content"

    def test_get_node_missing(self, sample_context: RLMContext):
        """Test getting a non-existent node."""
        node = sample_context.get_node("nonexistent")
        assert node is None

    def test_drill_down(self, sample_context: RLMContext):
        """Test drilling down to child nodes."""
        children = sample_context.drill_down("L2_0")
        assert len(children) == 1
        assert children[0].id == "L0_0"

    def test_drill_down_no_children(self, sample_context: RLMContext):
        """Test drilling down from a leaf node."""
        children = sample_context.drill_down("L0_0")
        assert children == []

    def test_drill_down_missing_node(self, sample_context: RLMContext):
        """Test drilling down from non-existent node."""
        children = sample_context.drill_down("nonexistent")
        assert children == []

    def test_total_tokens_at_level(self, sample_context: RLMContext):
        """Test getting total tokens at a level."""
        tokens = sample_context.total_tokens_at_level(AbstractionLevel.SUMMARY)
        assert tokens == 30

    def test_total_tokens_at_missing_level(self, sample_context: RLMContext):
        """Test getting total tokens at missing level returns original."""
        tokens = sample_context.total_tokens_at_level(AbstractionLevel.ABSTRACT)
        assert tokens == 100


class TestRLMQuery:
    """Test RLMQuery dataclass."""

    def test_default_values(self):
        """Test default query values."""
        query = RLMQuery(query="What is the main conclusion?")

        assert query.query == "What is the main conclusion?"
        assert query.preferred_strategy == DecompositionStrategy.AUTO
        assert query.start_level == AbstractionLevel.SUMMARY
        assert query.max_tokens_to_examine == 10000
        assert query.max_recursion_depth == 2
        assert query.require_citations is True
        assert query.output_format == "text"


class TestRLMResult:
    """Test RLMResult dataclass."""

    def test_result_creation(self):
        """Test result creation."""
        result = RLMResult(
            answer="The conclusion is X.",
            nodes_examined=["L2_0", "L0_0"],
            levels_traversed=[AbstractionLevel.SUMMARY, AbstractionLevel.FULL],
            citations=[{"level": 0, "chunk": 0, "content": "citation"}],
            tokens_processed=500,
            sub_calls_made=3,
            time_seconds=1.5,
            confidence=0.85,
            uncertainty_sources=["Some context may be missing"],
        )

        assert result.answer == "The conclusion is X."
        assert len(result.nodes_examined) == 2
        assert result.confidence == 0.85


# =============================================================================
# ChunkInfo Tests
# =============================================================================


class TestChunkInfo:
    """Test ChunkInfo dataclass."""

    def test_chunk_info_creation(self):
        """Test basic chunk info creation."""
        chunk = ChunkInfo(
            index=0,
            content="Test content",
            token_count=25,
            start_char=0,
            end_char=12,
        )

        assert chunk.index == 0
        assert chunk.content == "Test content"
        assert chunk.token_count == 25
        assert chunk.start_char == 0
        assert chunk.end_char == 12


# =============================================================================
# Compressor Tests
# =============================================================================


class TestHierarchicalCompressorInit:
    """Test HierarchicalCompressor initialization."""

    def test_default_init(self):
        """Test compressor with default config."""
        compressor = HierarchicalCompressor()

        assert compressor.config is not None
        assert compressor.config.target_tokens == 8000
        assert compressor.agent_call is None

    def test_custom_config(self):
        """Test compressor with custom config."""
        config = RLMConfig(target_tokens=8000)
        compressor = HierarchicalCompressor(config=config)

        assert compressor.config.target_tokens == 8000

    def test_with_agent_call(self):
        """Test compressor with agent callback."""

        def mock_call(prompt, model):
            return "mock response"

        compressor = HierarchicalCompressor(agent_call=mock_call)

        assert compressor.agent_call is not None


class TestCompressorInternals:
    """Test internal compressor methods."""

    @pytest.fixture
    def compressor(self) -> HierarchicalCompressor:
        """Create compressor for testing."""
        return HierarchicalCompressor()

    def test_count_tokens(self, compressor: HierarchicalCompressor):
        """Test token counting approximation."""
        # ~4 chars per token
        text = "a" * 100
        tokens = compressor._count_tokens(text)
        assert tokens == 25  # 100 / 4

    def test_count_tokens_empty(self, compressor: HierarchicalCompressor):
        """Test token counting for empty string."""
        tokens = compressor._count_tokens("")
        assert tokens == 0

    def test_cache_key_deterministic(self, compressor: HierarchicalCompressor):
        """Test that cache key is deterministic."""
        key1 = compressor._cache_key("content", "text", 4)
        key2 = compressor._cache_key("content", "text", 4)
        assert key1 == key2

    def test_cache_key_different_content(self, compressor: HierarchicalCompressor):
        """Test that different content produces different keys."""
        key1 = compressor._cache_key("content1", "text", 4)
        key2 = compressor._cache_key("content2", "text", 4)
        assert key1 != key2

    def test_cache_key_different_source_type(self, compressor: HierarchicalCompressor):
        """Test that different source type produces different keys."""
        key1 = compressor._cache_key("content", "text", 4)
        key2 = compressor._cache_key("content", "debate", 4)
        assert key1 != key2

    def test_cache_key_different_levels(self, compressor: HierarchicalCompressor):
        """Test that different max_levels produces different keys."""
        key1 = compressor._cache_key("content", "text", 3)
        key2 = compressor._cache_key("content", "text", 4)
        assert key1 != key2

    def test_estimate_fidelity_high_compression(self, compressor: HierarchicalCompressor):
        """Test fidelity estimation with high compression."""
        ratios = {
            AbstractionLevel.FULL: 1.0,
            AbstractionLevel.SUMMARY: 0.2,
            AbstractionLevel.ABSTRACT: 0.05,
        }
        fidelity = compressor._estimate_fidelity(ratios)

        # Min ratio is 0.05, formula: max(0.4, 0.8 + 0.2 * 0.05) = max(0.4, 0.81) = 0.81
        assert 0.4 <= fidelity <= 1.0

    def test_estimate_fidelity_no_compression(self, compressor: HierarchicalCompressor):
        """Test fidelity estimation with no compression."""
        ratios = {AbstractionLevel.FULL: 1.0}
        fidelity = compressor._estimate_fidelity(ratios)

        # 0.8 + 0.2 * 1.0 = 1.0
        assert fidelity == 1.0

    def test_estimate_fidelity_empty(self, compressor: HierarchicalCompressor):
        """Test fidelity estimation with empty ratios."""
        fidelity = compressor._estimate_fidelity({})
        assert fidelity == 1.0


class TestChunkContent:
    """Test content chunking logic."""

    @pytest.fixture
    def compressor(self) -> HierarchicalCompressor:
        """Create compressor for testing."""
        config = RLMConfig(target_tokens=100, overlap_tokens=20)
        return HierarchicalCompressor(config=config)

    def test_chunk_small_content(self, compressor: HierarchicalCompressor):
        """Test chunking content smaller than chunk size."""
        content = "Small content"
        chunks = compressor._chunk_content(content)

        assert len(chunks) == 1
        assert chunks[0].content == content
        assert chunks[0].index == 0
        assert chunks[0].start_char == 0
        assert chunks[0].end_char == len(content)

    def test_chunk_large_content(self, compressor: HierarchicalCompressor):
        """Test chunking content larger than chunk size."""
        # Create content larger than chunk size (100 tokens * 4 chars = 400 chars)
        content = "word " * 200  # 1000 chars
        chunks = compressor._chunk_content(content)

        assert len(chunks) > 1
        # First chunk should start at 0
        assert chunks[0].start_char == 0

    def test_chunk_preserves_boundaries(self, compressor: HierarchicalCompressor):
        """Test that chunks try to break at sentence boundaries."""
        content = "First sentence. Second sentence. Third sentence. Fourth sentence."
        chunks = compressor._chunk_content(content)

        # Chunks should try to end at sentence boundaries
        for chunk in chunks:
            # Most chunks should end with period+space or be the last chunk
            if chunk.end_char < len(content):
                # Should end at a boundary
                end_content = content[chunk.start_char : chunk.end_char]
                assert (
                    end_content.endswith(". ")
                    or end_content.endswith(".\n")
                    or end_content.endswith("\n")
                    or end_content.endswith(" ")
                    or chunk.end_char == len(content)
                ), f"Chunk ended at: {end_content[-10:]}"


class TestTruncationFallback:
    """Test truncation fallback when no LLM available."""

    @pytest.fixture
    def compressor(self) -> HierarchicalCompressor:
        """Create compressor without agent call."""
        return HierarchicalCompressor()

    def test_truncation_detailed(self, compressor: HierarchicalCompressor):
        """Test truncation at DETAILED level (50%)."""
        content = "A" * 1000
        source_nodes = [
            AbstractionNode(
                id="L0_0",
                level=AbstractionLevel.FULL,
                content=content,
                token_count=250,
            )
        ]

        context = RLMContext(
            original_content=content,
            original_tokens=250,
        )

        result = compressor._truncation_fallback(
            source_nodes,
            AbstractionLevel.DETAILED,
            context,
        )

        assert len(result) == 1
        # 50% compression means ~500 chars
        assert len(result[0].content) <= 503  # 500 + "..."

    def test_truncation_summary(self, compressor: HierarchicalCompressor):
        """Test truncation at SUMMARY level (20%)."""
        content = "B" * 1000
        source_nodes = [
            AbstractionNode(
                id="L0_0",
                level=AbstractionLevel.FULL,
                content=content,
                token_count=250,
            )
        ]

        context = RLMContext(
            original_content=content,
            original_tokens=250,
        )

        result = compressor._truncation_fallback(
            source_nodes,
            AbstractionLevel.SUMMARY,
            context,
        )

        assert len(result) == 1
        # 20% compression means ~200 chars
        assert len(result[0].content) <= 203

    def test_truncation_abstract(self, compressor: HierarchicalCompressor):
        """Test truncation at ABSTRACT level (5%)."""
        content = "C" * 1000
        source_nodes = [
            AbstractionNode(
                id="L0_0",
                level=AbstractionLevel.FULL,
                content=content,
                token_count=250,
            )
        ]

        context = RLMContext(
            original_content=content,
            original_tokens=250,
        )

        result = compressor._truncation_fallback(
            source_nodes,
            AbstractionLevel.ABSTRACT,
            context,
        )

        assert len(result) == 1
        # 5% compression means ~50 chars
        assert len(result[0].content) <= 53


# =============================================================================
# Compression Tests
# =============================================================================


class TestCompress:
    """Test main compress method."""

    @pytest.fixture
    def mock_agent_call(self):
        """Create mock agent call."""

        def agent_call(prompt: str, model: str) -> str:
            # Return compressed version
            return "Compressed summary of the content."

        return agent_call

    @pytest.fixture
    def compressor(self, mock_agent_call) -> HierarchicalCompressor:
        """Create compressor with mock agent."""
        config = RLMConfig(cache_compressions=False)
        return HierarchicalCompressor(config=config, agent_call=mock_agent_call)

    @pytest.mark.asyncio
    async def test_compress_creates_levels(self, compressor: HierarchicalCompressor):
        """Test that compression creates multiple abstraction levels."""
        content = "This is test content. " * 100

        result = await compressor.compress(content, source_type="text", max_levels=3)

        assert result is not None
        assert result.context is not None
        assert AbstractionLevel.FULL in result.context.levels

    @pytest.mark.asyncio
    async def test_compress_returns_stats(self, compressor: HierarchicalCompressor):
        """Test that compression returns proper stats."""
        content = "Test content for compression. " * 50

        result = await compressor.compress(content, source_type="text")

        assert result.original_tokens > 0
        assert result.time_seconds >= 0
        assert isinstance(result.key_topics_extracted, list)

    @pytest.mark.asyncio
    async def test_compress_debate_source_type(self, compressor: HierarchicalCompressor):
        """Test compression with debate source type."""
        content = """
        ## Round 1
        ### Claude's Proposal
        This is the proposal content.

        ### GPT's Critique
        This is the critique.
        """

        result = await compressor.compress(content, source_type="debate")

        assert result.context.source_type == "debate"


class TestCompressDebateHistory:
    """Test compress_debate_history method."""

    @pytest.fixture
    def compressor(self) -> HierarchicalCompressor:
        """Create compressor with mock agent."""

        def agent_call(prompt: str, model: str) -> str:
            return "Debate summary."

        config = RLMConfig(cache_compressions=False)
        return HierarchicalCompressor(config=config, agent_call=agent_call)

    @pytest.mark.asyncio
    async def test_compress_debate_rounds(self, compressor: HierarchicalCompressor):
        """Test compression of structured debate rounds."""
        rounds = [
            {
                "round_number": 1,
                "proposals": [
                    {"agent": "claude", "content": "First proposal"},
                    {"agent": "gpt", "content": "Second proposal"},
                ],
                "critiques": [
                    {"critic": "gpt", "target": "claude", "content": "Critique of first"},
                ],
                "votes": {"claude": 2, "gpt": 1},
            },
            {
                "round_number": 2,
                "proposals": [
                    {"agent": "claude", "content": "Revised proposal"},
                ],
                "critiques": [],
            },
        ]

        result = await compressor.compress_debate_history(rounds)

        assert result is not None
        assert result.context.source_type == "debate"


# =============================================================================
# Cache Tests
# =============================================================================


class TestCompressionCache:
    """Test compression caching behavior."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_compression_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        clear_compression_cache()

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Test that identical content uses cache."""
        config = RLMConfig(cache_compressions=True)
        compressor = HierarchicalCompressor(config=config)

        content = "Cacheable content."

        # First compression
        result1 = await compressor.compress(content, source_type="text", max_levels=2)

        # Second compression should be faster (cache hit)
        result2 = await compressor.compress(content, source_type="text", max_levels=2)

        assert result2.cache_hits == 1

    @pytest.mark.asyncio
    async def test_cache_miss_different_content(self):
        """Test that different content doesn't use cache."""
        config = RLMConfig(cache_compressions=True)
        compressor = HierarchicalCompressor(config=config)

        result1 = await compressor.compress("Content A", source_type="text")
        result2 = await compressor.compress("Content B", source_type="text")

        assert result2.cache_hits == 0

    def test_clear_cache(self):
        """Test cache clearing function."""
        from aragora.rlm import compressor as comp_module
        from aragora.rlm.types import RLMContext

        # Add to cache using the proper interface
        context = RLMContext(original_content="test", original_tokens=1)
        comp_module._compression_cache.set("test_key", context)

        assert comp_module._compression_cache.get_stats()["size"] > 0

        clear_compression_cache()

        assert comp_module._compression_cache.get_stats()["size"] == 0


# =============================================================================
# Prompt Tests
# =============================================================================


class TestCompressionPrompts:
    """Test compression prompt templates."""

    def test_standard_prompts_exist(self):
        """Test that standard prompts are defined for all levels."""
        prompts = HierarchicalCompressor.COMPRESSION_PROMPTS

        assert AbstractionLevel.DETAILED in prompts
        assert AbstractionLevel.SUMMARY in prompts
        assert AbstractionLevel.ABSTRACT in prompts
        assert AbstractionLevel.METADATA in prompts

    def test_debate_prompts_exist(self):
        """Test that debate-specific prompts are defined."""
        prompts = HierarchicalCompressor.DEBATE_COMPRESSION_PROMPTS

        assert AbstractionLevel.DETAILED in prompts
        assert AbstractionLevel.SUMMARY in prompts
        assert AbstractionLevel.ABSTRACT in prompts

    def test_prompts_have_content_placeholder(self):
        """Test that prompts have {content} placeholder."""
        for level, prompt in HierarchicalCompressor.COMPRESSION_PROMPTS.items():
            assert "{content}" in prompt, f"Missing placeholder in {level} prompt"

    def test_debate_prompts_have_content_placeholder(self):
        """Test that debate prompts have {content} placeholder."""
        for level, prompt in HierarchicalCompressor.DEBATE_COMPRESSION_PROMPTS.items():
            assert "{content}" in prompt, f"Missing placeholder in debate {level} prompt"


# =============================================================================
# Integration Tests
# =============================================================================


class TestCompressorIntegration:
    """Integration tests for full compression workflow."""

    @pytest.mark.asyncio
    async def test_full_compression_workflow_no_agent(self):
        """Test full workflow without agent (truncation fallback)."""
        compressor = HierarchicalCompressor()

        # Large content to ensure chunking
        content = "Sentence one. " * 500

        result = await compressor.compress(content, source_type="text", max_levels=3)

        # Should complete without errors
        assert result is not None
        assert result.context is not None

        # Should have FULL level at minimum
        assert AbstractionLevel.FULL in result.context.levels

        # Original tokens should be tracked
        assert result.original_tokens > 0

    @pytest.mark.asyncio
    async def test_full_compression_workflow_with_agent(self):
        """Test full workflow with mock agent."""
        call_count = [0]

        def counting_agent(prompt: str, model: str) -> str:
            call_count[0] += 1
            return f"Summary {call_count[0]}"

        config = RLMConfig(cache_compressions=False, parallel_sub_calls=False)
        compressor = HierarchicalCompressor(config=config, agent_call=counting_agent)

        content = "Test content. " * 200

        result = await compressor.compress(content, source_type="text", max_levels=3)

        assert result is not None
        assert result.sub_calls_made > 0 or call_count[0] > 0

    @pytest.mark.asyncio
    async def test_compression_preserves_original(self):
        """Test that original content is preserved in context."""
        compressor = HierarchicalCompressor()

        content = "Original content that should be preserved."

        result = await compressor.compress(content, source_type="text")

        assert result.context.original_content == content

    @pytest.mark.asyncio
    async def test_node_hierarchy_linking(self):
        """Test that parent-child relationships are set up correctly."""

        def agent_call(prompt: str, model: str) -> str:
            return "Compressed."

        config = RLMConfig(cache_compressions=False)
        compressor = HierarchicalCompressor(config=config, agent_call=agent_call)

        # Content large enough to have multiple chunks
        content = "Test chunk content. " * 300

        result = await compressor.compress(content, source_type="text", max_levels=2)

        # Check that we have hierarchy
        if AbstractionLevel.DETAILED in result.context.levels:
            for node in result.context.levels[AbstractionLevel.DETAILED]:
                # Higher level nodes should have source_chunks set
                if node.source_chunks:
                    # Verify source chunks exist
                    for chunk_id in node.source_chunks:
                        assert chunk_id in result.context.nodes_by_id


class TestCompressGroup:
    """Test _compress_group method."""

    @pytest.mark.asyncio
    async def test_missing_agent_call_does_not_acquire_semaphore(self):
        compressor = HierarchicalCompressor(config=RLMConfig(cache_compressions=False))
        nodes = [
            AbstractionNode(
                id="L0_0",
                level=AbstractionLevel.FULL,
                content="Chunk content",
                token_count=50,
            ),
        ]
        context = RLMContext(original_content="", original_tokens=50)

        with patch("aragora.rlm.compressor.get_call_semaphore") as get_semaphore:
            result, calls = await compressor._compress_group(
                nodes,
                0,
                AbstractionLevel.SUMMARY,
                HierarchicalCompressor.COMPRESSION_PROMPTS[AbstractionLevel.SUMMARY],
                context,
            )

        get_semaphore.assert_not_called()
        assert result is not None
        assert calls == 0

    @pytest.mark.asyncio
    async def test_compress_group_success(self):
        """Test successful group compression."""

        def agent_call(prompt: str, model: str) -> str:
            return "Group summary"

        config = RLMConfig(cache_compressions=False)
        compressor = HierarchicalCompressor(config=config, agent_call=agent_call)

        nodes = [
            AbstractionNode(
                id="L0_0",
                level=AbstractionLevel.FULL,
                content="First chunk content",
                token_count=50,
            ),
            AbstractionNode(
                id="L0_1",
                level=AbstractionLevel.FULL,
                content="Second chunk content",
                token_count=50,
            ),
        ]

        context = RLMContext(original_content="", original_tokens=100)

        result, calls = await compressor._compress_group(
            nodes,
            0,
            AbstractionLevel.SUMMARY,
            HierarchicalCompressor.COMPRESSION_PROMPTS[AbstractionLevel.SUMMARY],
            context,
        )

        assert result is not None
        assert result.content == "Group summary"
        assert calls == 1
        assert result.source_chunks == ["L0_0", "L0_1"]

    @pytest.mark.asyncio
    async def test_compress_group_failure_fallback(self):
        """Test group compression fallback on error."""

        def failing_agent(prompt: str, model: str) -> str:
            raise RuntimeError("API error")

        config = RLMConfig(cache_compressions=False)
        compressor = HierarchicalCompressor(config=config, agent_call=failing_agent)

        nodes = [
            AbstractionNode(
                id="L0_0",
                level=AbstractionLevel.FULL,
                content="Chunk content",
                token_count=50,
            ),
        ]

        context = RLMContext(original_content="", original_tokens=100)

        result, calls = await compressor._compress_group(
            nodes,
            0,
            AbstractionLevel.SUMMARY,
            HierarchicalCompressor.COMPRESSION_PROMPTS[AbstractionLevel.SUMMARY],
            context,
        )

        # Should fall back to truncation
        assert result is not None
        assert calls == 0  # No successful LLM call
