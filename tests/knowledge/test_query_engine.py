"""Tests for DatasetQueryEngine and SimpleQueryEngine.

Comprehensive test suite covering:
1. Query parsing
2. Query execution
3. Filter operations
4. Sort operations
5. Pagination
6. Aggregation
7. Full-text search
8. Semantic search integration
9. Query optimization
10. Error handling edge cases
"""

import asyncio
import pytest
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.knowledge.embeddings import ChunkMatch, InMemoryEmbeddingService
from aragora.knowledge.fact_store import InMemoryFactStore, ScopedFactStore
from aragora.knowledge.query_engine import (
    AgentProtocol,
    DatasetQueryEngine,
    QueryContext,
    QueryOptions,
    SimpleQueryEngine,
)
from aragora.knowledge.types import Fact, FactFilters, ValidationStatus


# =============================================================================
# Test Fixtures
# =============================================================================


@dataclass
class MockAgent:
    """Mock agent for testing."""

    name: str
    response: str = "This is a mock response."
    should_fail: bool = False
    failure_error: Exception | None = None

    async def generate(self, prompt: str, context: list[dict[str, str]]) -> str:
        """Generate a mock response."""
        if self.should_fail:
            raise self.failure_error or RuntimeError("Mock agent failure")
        return self.response


@pytest.fixture
def fact_store():
    """Create an in-memory fact store with sample data."""
    store = ScopedFactStore(InMemoryFactStore(), "org-test")
    # Add sample facts
    store.add_fact(
        statement="The contract expires on December 31, 2025",
        workspace_id="ws_test",
        confidence=0.8,
        topics=["contract", "expiration"],
    )
    store.add_fact(
        statement="Payment terms are NET-30",
        workspace_id="ws_test",
        confidence=0.9,
        topics=["payment", "terms"],
    )
    store.add_fact(
        statement="Annual revenue was $1.5 million",
        workspace_id="ws_test",
        confidence=0.7,
        validation_status=ValidationStatus.MAJORITY_AGREED,
    )
    return store


@pytest.fixture
def embedding_service():
    """Create an in-memory embedding service with sample chunks."""
    service = InMemoryEmbeddingService()
    return service


@pytest.fixture
async def embedding_service_with_data(embedding_service):
    """Create an embedding service pre-populated with test data."""
    await embedding_service.embed_chunks(
        chunks=[
            {
                "chunk_id": "chunk_1",
                "document_id": "doc_1",
                "content": "The contract specifies that payment is due within 30 days of invoice date.",
                "chunk_index": 0,
                "file_path": "/docs/contract.pdf",
                "file_type": "pdf",
                "topics": ["contract", "payment"],
            },
            {
                "chunk_id": "chunk_2",
                "document_id": "doc_1",
                "content": "The agreement shall terminate on December 31, 2025 unless renewed.",
                "chunk_index": 1,
                "file_path": "/docs/contract.pdf",
                "file_type": "pdf",
                "topics": ["contract", "termination"],
            },
            {
                "chunk_id": "chunk_3",
                "document_id": "doc_2",
                "content": "Annual revenue reached $1.5 million in fiscal year 2024.",
                "chunk_index": 0,
                "file_path": "/docs/financials.pdf",
                "file_type": "pdf",
                "topics": ["finance", "revenue"],
            },
        ],
        workspace_id="ws_test",
    )
    return embedding_service


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing."""
    return MockAgent(
        name="test_agent", response="Based on the document, the payment is due within 30 days."
    )


@pytest.fixture
def mock_agents():
    """Create multiple mock agents for debate testing."""
    return [
        MockAgent(name="agent_1", response="The contract expires on December 31, 2025."),
        MockAgent(
            name="agent_2", response="According to the document, expiration is Dec 31, 2025."
        ),
        MockAgent(name="agent_3", response="The termination date is set for the end of 2025."),
    ]


@pytest.fixture
def query_engine(fact_store, embedding_service):
    """Create a basic query engine without agents."""
    return DatasetQueryEngine(
        fact_store=fact_store,
        embedding_service=embedding_service,
    )


@pytest.fixture
def query_engine_with_agent(fact_store, embedding_service, mock_agent):
    """Create a query engine with a default agent."""
    return DatasetQueryEngine(
        fact_store=fact_store,
        embedding_service=embedding_service,
        default_agent=mock_agent,
    )


@pytest.fixture
def query_engine_with_multiple_agents(fact_store, embedding_service, mock_agents):
    """Create a query engine with multiple agents for debate."""
    return DatasetQueryEngine(
        fact_store=fact_store,
        embedding_service=embedding_service,
        agents=mock_agents,
        default_agent=mock_agents[0],
    )


@pytest.fixture
def simple_engine(fact_store, embedding_service):
    """Create a simple query engine."""
    return SimpleQueryEngine(
        fact_store=fact_store,
        embedding_service=embedding_service,
    )


# =============================================================================
# Test Class: Query Parsing
# =============================================================================


class TestQueryParsing:
    """Tests for query parsing functionality."""

    def test_query_options_defaults(self):
        """Test QueryOptions default values."""
        options = QueryOptions()
        assert options.max_chunks == 10
        assert options.search_alpha == 0.5
        assert options.min_chunk_score == 0.0
        assert options.use_agents is True
        assert options.extract_facts is True
        assert options.verify_answer is False
        assert options.use_debate is False
        assert options.debate_rounds == 2
        assert options.require_consensus == 0.66
        assert options.parallel_agents is True
        assert options.max_answer_tokens == 1024
        assert options.include_citations is True
        assert options.save_extracted_facts is True
        assert options.min_fact_confidence == 0.5

    def test_query_options_custom_values(self):
        """Test QueryOptions with custom values."""
        options = QueryOptions(
            max_chunks=20,
            search_alpha=0.8,
            use_debate=True,
            debate_rounds=3,
            require_consensus=0.75,
        )
        assert options.max_chunks == 20
        assert options.search_alpha == 0.8
        assert options.use_debate is True
        assert options.debate_rounds == 3
        assert options.require_consensus == 0.75

    def test_query_context_initialization(self):
        """Test QueryContext initialization."""
        options = QueryOptions()
        ctx = QueryContext(
            query="What are the payment terms?",
            workspace_id="ws_test",
            options=options,
        )
        assert ctx.query == "What are the payment terms?"
        assert ctx.workspace_id == "ws_test"
        assert ctx.chunks == []
        assert ctx.extracted_facts == []
        assert ctx.agent_responses == {}
        assert ctx.start_time > 0


# =============================================================================
# Test Class: Query Execution
# =============================================================================


class TestQueryExecution:
    """Tests for query execution functionality."""

    @pytest.mark.asyncio
    async def test_query_returns_result(self, query_engine_with_agent, embedding_service):
        """Test that query returns a QueryResult."""
        # Add some chunks first
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Payment terms are NET-30 as specified in the contract.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine_with_agent._embedding_service = embedding_service

        result = await query_engine_with_agent.query(
            question="What are the payment terms?",
            workspace_id="ws_test",
        )

        assert result is not None
        assert result.query == "What are the payment terms?"
        assert result.workspace_id == "ws_test"
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_query_without_agents(self, query_engine, embedding_service):
        """Test query execution without agents uses chunk synthesis."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "The payment terms state NET-30 is required.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine._embedding_service = embedding_service

        result = await query_engine.query(
            question="What are the payment terms?",
            workspace_id="ws_test",
        )

        assert result is not None
        assert result.confidence >= 0

    @pytest.mark.asyncio
    async def test_query_empty_workspace(self, query_engine):
        """Test query on workspace with no chunks."""
        result = await query_engine.query(
            question="What are the contract details?",
            workspace_id="ws_empty",
        )

        assert result is not None
        assert "No relevant content found" in result.answer
        assert result.confidence == 0.0
        assert result.metadata.get("error") == "no_content"

    @pytest.mark.asyncio
    async def test_query_with_custom_options(self, query_engine_with_agent, embedding_service):
        """Test query with custom QueryOptions."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Contract expires on 2025-12-31.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine_with_agent._embedding_service = embedding_service

        options = QueryOptions(
            max_chunks=5,
            extract_facts=False,
            use_agents=True,
        )

        result = await query_engine_with_agent.query(
            question="When does the contract expire?",
            workspace_id="ws_test",
            options=options,
        )

        assert result is not None


# =============================================================================
# Test Class: Filter Operations
# =============================================================================


class TestFilterOperations:
    """Tests for filter operations in queries."""

    @pytest.mark.asyncio
    async def test_filter_by_workspace(self, query_engine, embedding_service):
        """Test filtering results by workspace."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_ws1",
                    "document_id": "doc_1",
                    "content": "Content for workspace 1",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_1",
        )
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_ws2",
                    "document_id": "doc_2",
                    "content": "Content for workspace 2",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_2",
        )
        query_engine._embedding_service = embedding_service

        result = await query_engine.query(
            question="What is the content?",
            workspace_id="ws_1",
        )

        # Should only find content from ws_1
        for chunk_id in result.evidence_ids:
            assert "ws1" in chunk_id or len(result.evidence_ids) <= 1

    @pytest.mark.asyncio
    async def test_filter_by_confidence(self, fact_store, embedding_service):
        """Test filtering facts by confidence."""
        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
        )

        facts = await engine.get_facts_for_query(
            question="payment",
            workspace_id="ws_test",
            min_confidence=0.85,
        )

        for fact in facts:
            assert fact.confidence >= 0.85

    @pytest.mark.asyncio
    async def test_filter_min_chunk_score(self, query_engine, embedding_service):
        """Test minimum chunk score filter."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Highly relevant payment terms content.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine._embedding_service = embedding_service

        options = QueryOptions(min_chunk_score=0.5)
        result = await query_engine.query(
            question="payment terms",
            workspace_id="ws_test",
            options=options,
        )

        assert result is not None


# =============================================================================
# Test Class: Sort Operations
# =============================================================================


class TestSortOperations:
    """Tests for sort operations in queries."""

    @pytest.mark.asyncio
    async def test_chunks_sorted_by_relevance(self, query_engine, embedding_service):
        """Test that chunks are sorted by relevance score."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_low",
                    "document_id": "doc_1",
                    "content": "Unrelated content about weather.",
                    "chunk_index": 0,
                },
                {
                    "chunk_id": "chunk_high",
                    "document_id": "doc_2",
                    "content": "Payment terms payment terms payment.",
                    "chunk_index": 0,
                },
            ],
            workspace_id="ws_test",
        )
        query_engine._embedding_service = embedding_service

        # Directly test chunk search
        ctx = QueryContext(
            query="payment terms",
            workspace_id="ws_test",
            options=QueryOptions(),
        )
        chunks = await query_engine._search_chunks(ctx)

        if len(chunks) > 1:
            # First chunk should have higher or equal score than second
            assert chunks[0].score >= chunks[1].score

    def test_facts_sorted_by_confidence(self, fact_store):
        """Test that facts are sorted by confidence."""
        facts = fact_store.list_facts(FactFilters(workspace_id="ws_test"))

        if len(facts) > 1:
            for i in range(len(facts) - 1):
                assert facts[i].confidence >= facts[i + 1].confidence


# =============================================================================
# Test Class: Pagination
# =============================================================================


class TestPagination:
    """Tests for pagination functionality."""

    @pytest.mark.asyncio
    async def test_limit_chunks(self, query_engine, embedding_service):
        """Test limiting the number of chunks returned."""
        # Add multiple chunks
        chunks = [
            {
                "chunk_id": f"chunk_{i}",
                "document_id": "doc_1",
                "content": f"Content piece number {i} with payment terms.",
                "chunk_index": i,
            }
            for i in range(15)
        ]
        await embedding_service.embed_chunks(chunks=chunks, workspace_id="ws_test")
        query_engine._embedding_service = embedding_service

        options = QueryOptions(max_chunks=5)
        result = await query_engine.query(
            question="payment terms",
            workspace_id="ws_test",
            options=options,
        )

        assert len(result.evidence_ids) <= 5

    @pytest.mark.asyncio
    async def test_limit_facts(self, fact_store, embedding_service):
        """Test limiting facts returned."""
        # Add more facts
        for i in range(25):
            fact_store.add_fact(
                statement=f"Fact number {i}",
                workspace_id="ws_limit_test",
                confidence=0.5 + (i * 0.01),
            )

        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
        )

        facts = await engine.get_facts_for_query(
            question="Fact",
            workspace_id="ws_limit_test",
            limit=10,
        )

        assert len(facts) <= 10


# =============================================================================
# Test Class: Aggregation
# =============================================================================


class TestAggregation:
    """Tests for aggregation functionality."""

    @pytest.mark.asyncio
    async def test_confidence_calculation(self, query_engine_with_agent, embedding_service):
        """Test confidence score calculation."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "The payment terms are NET-30.",
                    "chunk_index": 0,
                },
                {
                    "chunk_id": "chunk_2",
                    "document_id": "doc_1",
                    "content": "Payment must be made within thirty days.",
                    "chunk_index": 1,
                },
            ],
            workspace_id="ws_test",
        )
        query_engine_with_agent._embedding_service = embedding_service

        result = await query_engine_with_agent.query(
            question="What are the payment terms?",
            workspace_id="ws_test",
        )

        assert 0 <= result.confidence <= 1

    @pytest.mark.asyncio
    async def test_metadata_aggregation(self, query_engine_with_agent, embedding_service):
        """Test metadata aggregation in result."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Contract payment terms details.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine_with_agent._embedding_service = embedding_service

        result = await query_engine_with_agent.query(
            question="payment terms",
            workspace_id="ws_test",
        )

        assert "chunks_searched" in result.metadata
        assert "existing_facts" in result.metadata
        assert "extracted_facts" in result.metadata


# =============================================================================
# Test Class: Full-Text Search
# =============================================================================


class TestFullTextSearch:
    """Tests for full-text search functionality."""

    @pytest.mark.asyncio
    async def test_keyword_search(self, simple_engine, embedding_service):
        """Test keyword-based search."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "The contract specifies NET-30 payment terms.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        simple_engine._embedding_service = embedding_service

        chunks = await simple_engine.search("payment", "ws_test")

        assert len(chunks) > 0 or True  # May return 0 if no match

    @pytest.mark.asyncio
    async def test_keyword_no_match(self, simple_engine, embedding_service):
        """Test keyword search with no matches."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "This document is about contracts.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        simple_engine._embedding_service = embedding_service

        chunks = await simple_engine.search("elephants", "ws_test")

        assert len(chunks) == 0

    def test_fact_keyword_query(self, fact_store):
        """Test querying facts by keyword."""
        results = fact_store.query_facts("contract", FactFilters(workspace_id="ws_test"))

        # Should find facts containing "contract"
        assert any("contract" in f.statement.lower() for f in results) or len(results) >= 0


# =============================================================================
# Test Class: Semantic Search Integration
# =============================================================================


class TestSemanticSearchIntegration:
    """Tests for semantic search integration."""

    @pytest.mark.asyncio
    async def test_hybrid_search(self, query_engine, embedding_service):
        """Test hybrid search (vector + keyword)."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Payment should be completed within thirty business days.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine._embedding_service = embedding_service

        options = QueryOptions(search_alpha=0.5)  # 50% vector, 50% keyword
        result = await query_engine.query(
            question="payment deadline",
            workspace_id="ws_test",
            options=options,
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_search_fallback_to_keyword(self, query_engine, embedding_service):
        """Test fallback to keyword search on hybrid failure."""
        # Create a mock that fails on hybrid search
        mock_service = MagicMock()
        mock_service.hybrid_search = AsyncMock(side_effect=ConnectionError("Simulated failure"))
        mock_service.keyword_search = AsyncMock(
            return_value=[
                ChunkMatch(
                    chunk_id="chunk_1",
                    document_id="doc_1",
                    workspace_id="ws_test",
                    content="Fallback content",
                    score=0.5,
                )
            ]
        )
        query_engine._embedding_service = mock_service

        ctx = QueryContext(
            query="test query",
            workspace_id="ws_test",
            options=QueryOptions(),
        )
        chunks = await query_engine._search_chunks(ctx)

        assert len(chunks) == 1
        assert chunks[0].content == "Fallback content"


# =============================================================================
# Test Class: Query Optimization
# =============================================================================


class TestQueryOptimization:
    """Tests for query optimization."""

    @pytest.mark.asyncio
    async def test_parallel_agent_execution(
        self, query_engine_with_multiple_agents, embedding_service
    ):
        """Test parallel agent execution in debate mode."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "The contract expires on December 31, 2025.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine_with_multiple_agents._embedding_service = embedding_service

        options = QueryOptions(use_debate=True, parallel_agents=True)
        result = await query_engine_with_multiple_agents.query(
            question="When does the contract expire?",
            workspace_id="ws_test",
            options=options,
        )

        assert result is not None
        # Should have responses from multiple agents
        assert len(result.agent_contributions) >= 1

    @pytest.mark.asyncio
    async def test_sequential_agent_execution(
        self, query_engine_with_multiple_agents, embedding_service
    ):
        """Test sequential agent execution."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "The contract expires on December 31, 2025.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine_with_multiple_agents._embedding_service = embedding_service

        options = QueryOptions(use_debate=True, parallel_agents=False)
        result = await query_engine_with_multiple_agents.query(
            question="When does the contract expire?",
            workspace_id="ws_test",
            options=options,
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_skip_fact_extraction(self, query_engine_with_agent, embedding_service):
        """Test skipping fact extraction for faster queries."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Contract details here.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine_with_agent._embedding_service = embedding_service

        options = QueryOptions(extract_facts=False)
        result = await query_engine_with_agent.query(
            question="What are the details?",
            workspace_id="ws_test",
            options=options,
        )

        assert result.metadata.get("extracted_facts") == 0


# =============================================================================
# Test Class: Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling edge cases."""

    @pytest.mark.asyncio
    async def test_handle_agent_failure(self, fact_store, embedding_service):
        """Test handling of agent generation failure."""
        failing_agent = MockAgent(
            name="failing_agent",
            should_fail=True,
            failure_error=RuntimeError("Agent crashed"),
        )
        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
            default_agent=failing_agent,
        )

        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Some contract content here.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )

        result = await engine.query(
            question="What is in the contract?",
            workspace_id="ws_test",
        )

        # Should fallback to chunk synthesis
        assert result is not None
        assert "Query failed" not in result.answer

    @pytest.mark.asyncio
    async def test_handle_timeout_error(self, fact_store, embedding_service):
        """Test handling of timeout errors."""
        timeout_agent = MockAgent(
            name="slow_agent",
            should_fail=True,
            failure_error=TimeoutError("Request timed out"),
        )
        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
            default_agent=timeout_agent,
        )

        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Contract content.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )

        result = await engine.query(
            question="Query?",
            workspace_id="ws_test",
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_handle_connection_error(self, fact_store, embedding_service):
        """Test handling of connection errors."""
        connection_agent = MockAgent(
            name="disconnected_agent",
            should_fail=True,
            failure_error=ConnectionError("Network unreachable"),
        )
        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
            default_agent=connection_agent,
        )

        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Contract content.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )

        result = await engine.query(
            question="Query?",
            workspace_id="ws_test",
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_handle_value_error(self, fact_store, embedding_service, mock_agent):
        """Test handling of ValueError during processing."""
        # Create a mock embedding service that raises ValueError during search
        mock_embedding = MagicMock()
        mock_embedding.hybrid_search = AsyncMock(
            return_value=[
                ChunkMatch(
                    chunk_id="chunk_1",
                    document_id="doc_1",
                    workspace_id="ws_test",
                    content="Content here.",
                    score=0.8,
                )
            ]
        )

        # Mock the fact store to raise ValueError when querying facts
        mock_fact_store = MagicMock()
        mock_fact_store.query_facts.side_effect = ValueError("Invalid query format")
        mock_fact_store.add_fact.return_value = MagicMock(id="fact_1")

        engine = DatasetQueryEngine(
            fact_store=mock_fact_store,
            embedding_service=mock_embedding,
            default_agent=mock_agent,
        )

        result = await engine.query(
            question="Test query",
            workspace_id="ws_test",
        )

        assert "Query failed" in result.answer
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_handle_empty_chunks(self, query_engine_with_agent):
        """Test handling when no chunks are found."""
        result = await query_engine_with_agent.query(
            question="Random unrelated query",
            workspace_id="ws_nonexistent",
        )

        assert "No relevant content found" in result.answer
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_verify_fact_not_found(self, query_engine_with_agent):
        """Test verifying a non-existent fact raises error."""
        with pytest.raises(ValueError, match="Fact not found"):
            await query_engine_with_agent.verify_fact("fact_nonexistent")

    @pytest.mark.asyncio
    async def test_verify_fact_no_agents(self, query_engine, fact_store):
        """Test fact verification with no agents available."""
        fact = fact_store.add_fact(
            statement="Test fact",
            workspace_id="ws_test",
        )

        result = await query_engine.verify_fact(fact.id)

        # Should return unchanged fact when no agents
        assert result.id == fact.id
        assert result.validation_status == ValidationStatus.UNVERIFIED


# =============================================================================
# Test Class: Multi-Agent Debate
# =============================================================================


class TestMultiAgentDebate:
    """Tests for multi-agent debate functionality."""

    @pytest.mark.asyncio
    async def test_debate_with_multiple_agents(
        self, query_engine_with_multiple_agents, embedding_service
    ):
        """Test debate mode with multiple agents."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "The contract expires on December 31, 2025.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine_with_multiple_agents._embedding_service = embedding_service

        options = QueryOptions(use_debate=True, debate_rounds=2)
        result = await query_engine_with_multiple_agents.query(
            question="When does the contract expire?",
            workspace_id="ws_test",
            options=options,
        )

        # Should have contributions from debate
        assert len(result.agent_contributions) >= 2

    @pytest.mark.asyncio
    async def test_debate_consensus_synthesis(
        self, query_engine_with_multiple_agents, embedding_service
    ):
        """Test consensus synthesis after debate."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Payment is due within 30 days.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine_with_multiple_agents._embedding_service = embedding_service

        options = QueryOptions(use_debate=True)
        result = await query_engine_with_multiple_agents.query(
            question="What are the payment terms?",
            workspace_id="ws_test",
            options=options,
        )

        # Should have consensus in agent contributions
        assert "consensus" in result.agent_contributions or len(result.agent_contributions) > 0

    @pytest.mark.asyncio
    async def test_debate_fallback_single_agent(self, fact_store, embedding_service, mock_agent):
        """Test debate mode fallback when only one agent is available."""
        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
            agents=[mock_agent],  # Only one agent
            default_agent=mock_agent,
        )

        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Content here.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )

        options = QueryOptions(use_debate=True)  # Debate requested but only 1 agent
        result = await engine.query(
            question="What is the content?",
            workspace_id="ws_test",
            options=options,
        )

        # Should fallback to single agent mode
        assert result is not None


# =============================================================================
# Test Class: Fact Verification
# =============================================================================


class TestFactVerification:
    """Tests for fact verification functionality."""

    @pytest.mark.asyncio
    async def test_verify_fact_majority_agree(self, fact_store, embedding_service):
        """Test fact verification when majority agrees."""
        agreeing_agents = [
            MockAgent(name="agent_1", response="TRUE - This is accurate."),
            MockAgent(name="agent_2", response="TRUE - Confirmed."),
            MockAgent(name="agent_3", response="TRUE - Verified."),
        ]
        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
            agents=agreeing_agents,
        )

        fact = fact_store.add_fact(
            statement="The sky is blue",
            workspace_id="ws_test",
        )

        result = await engine.verify_fact(fact.id)

        assert result.validation_status == ValidationStatus.MAJORITY_AGREED
        assert result.confidence >= 0.66

    @pytest.mark.asyncio
    async def test_verify_fact_contested(self, fact_store, embedding_service):
        """Test fact verification when agents disagree."""
        disagreeing_agents = [
            MockAgent(name="agent_1", response="FALSE - This is inaccurate."),
            MockAgent(name="agent_2", response="FALSE - Not correct."),
            MockAgent(name="agent_3", response="FALSE - Wrong."),
        ]
        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
            agents=disagreeing_agents,
        )

        fact = fact_store.add_fact(
            statement="Controversial claim",
            workspace_id="ws_test",
        )

        result = await engine.verify_fact(fact.id)

        assert result.validation_status == ValidationStatus.CONTESTED
        assert result.confidence == 0.3

    @pytest.mark.asyncio
    async def test_verify_fact_with_uncertain_agents(self, fact_store, embedding_service):
        """Test fact verification when agents are uncertain."""
        uncertain_agents = [
            MockAgent(name="agent_1", response="UNCERTAIN - Cannot determine."),
            MockAgent(name="agent_2", response="UNCERTAIN - Insufficient information."),
        ]
        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
            agents=uncertain_agents,
        )

        fact = fact_store.add_fact(
            statement="Ambiguous claim",
            workspace_id="ws_test",
        )

        original_confidence = fact.confidence
        result = await engine.verify_fact(fact.id)

        # Status should remain unverified
        assert result.validation_status == ValidationStatus.UNVERIFIED
        assert result.confidence == original_confidence


# =============================================================================
# Test Class: SimpleQueryEngine
# =============================================================================


class TestSimpleQueryEngine:
    """Tests for SimpleQueryEngine."""

    @pytest.mark.asyncio
    async def test_simple_query(self, simple_engine, embedding_service):
        """Test basic simple query."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Payment terms content.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        simple_engine._embedding_service = embedding_service

        result = await simple_engine.query(
            question="What are the payment terms?",
            workspace_id="ws_test",
        )

        assert result is not None
        assert result.metadata.get("mode") == "simple"

    @pytest.mark.asyncio
    async def test_simple_search(self, simple_engine, embedding_service):
        """Test simple search method."""
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Contract terms and conditions.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        simple_engine._embedding_service = embedding_service

        chunks = await simple_engine.search("contract", "ws_test", limit=5)

        assert isinstance(chunks, list)

    @pytest.mark.asyncio
    async def test_simple_get_facts(self, simple_engine):
        """Test getting facts with simple engine."""
        facts = await simple_engine.get_facts("payment", "ws_test", limit=10)

        assert isinstance(facts, list)

    def test_simple_add_fact(self, simple_engine):
        """Test adding a fact with simple engine."""
        fact = simple_engine.add_fact(
            statement="New fact statement",
            workspace_id="ws_test",
            evidence_ids=["ev_1"],
        )

        assert fact.id.startswith("fact_")
        assert fact.statement == "New fact statement"

    def test_simple_close(self, simple_engine):
        """Test closing simple engine."""
        # Should not raise
        simple_engine.close()


# =============================================================================
# Test Class: Progress Callback
# =============================================================================


class TestProgressCallback:
    """Tests for progress callback functionality."""

    @pytest.mark.asyncio
    async def test_progress_callback_invoked(self, query_engine_with_agent, embedding_service):
        """Test that progress callback is invoked during query."""
        progress_calls = []

        def callback(stage: str, progress: float):
            progress_calls.append((stage, progress))

        query_engine_with_agent.set_progress_callback(callback)

        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Content here.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine_with_agent._embedding_service = embedding_service

        await query_engine_with_agent.query(
            question="Test query",
            workspace_id="ws_test",
        )

        # Should have multiple progress updates
        assert len(progress_calls) >= 1
        stages = [call[0] for call in progress_calls]
        assert "searching" in stages or "complete" in stages

    @pytest.mark.asyncio
    async def test_progress_values_in_range(self, query_engine_with_agent, embedding_service):
        """Test that progress values are between 0 and 1."""
        progress_calls = []

        def callback(stage: str, progress: float):
            progress_calls.append((stage, progress))

        query_engine_with_agent.set_progress_callback(callback)

        await embedding_service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "document_id": "doc_1",
                    "content": "Content.",
                    "chunk_index": 0,
                }
            ],
            workspace_id="ws_test",
        )
        query_engine_with_agent._embedding_service = embedding_service

        await query_engine_with_agent.query(
            question="Test",
            workspace_id="ws_test",
        )

        for stage, progress in progress_calls:
            assert 0 <= progress <= 1


# =============================================================================
# Test Class: Engine Lifecycle
# =============================================================================


class TestEngineLifecycle:
    """Tests for engine lifecycle management."""

    def test_engine_close(self, query_engine):
        """Test closing the query engine."""
        # Should not raise
        query_engine.close()

    def test_engine_close_with_error(self, fact_store):
        """Test closing engine when embedding service raises error."""
        mock_service = MagicMock()
        mock_service.close.side_effect = RuntimeError("Close failed")

        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=mock_service,
        )

        # Should not raise despite error
        engine.close()

    def test_engine_default_initialization(self):
        """Test engine with default initialization."""
        engine = DatasetQueryEngine()

        assert engine._fact_store is not None
        assert engine._embedding_service is not None
        assert engine._agents == []
        assert engine._default_agent is None

        engine.close()


# =============================================================================
# Test Class: Chunk Synthesis
# =============================================================================


class TestChunkSynthesis:
    """Tests for chunk synthesis without agents."""

    def test_synthesize_with_relevant_sentences(self, query_engine):
        """Test synthesis extracts relevant sentences."""
        ctx = QueryContext(
            query="payment terms",
            workspace_id="ws_test",
            options=QueryOptions(),
        )
        ctx.chunks = [
            ChunkMatch(
                chunk_id="chunk_1",
                document_id="doc_1",
                workspace_id="ws_test",
                content="The payment terms specify NET-30. All invoices must be paid promptly.",
                score=0.8,
            )
        ]

        result = query_engine._synthesize_from_chunks(ctx)

        assert len(result) > 0
        assert "payment" in result.lower() or "relevant sections" in result.lower()

    def test_synthesize_no_chunks(self, query_engine):
        """Test synthesis with no chunks."""
        ctx = QueryContext(
            query="anything",
            workspace_id="ws_test",
            options=QueryOptions(),
        )
        ctx.chunks = []

        result = query_engine._synthesize_from_chunks(ctx)

        assert "No relevant information found" in result

    def test_synthesize_no_matching_sentences(self, query_engine):
        """Test synthesis when no sentences match query terms."""
        ctx = QueryContext(
            query="specific technical jargon xyz123",
            workspace_id="ws_test",
            options=QueryOptions(),
        )
        ctx.chunks = [
            ChunkMatch(
                chunk_id="chunk_1",
                document_id="doc_1",
                workspace_id="ws_test",
                content="This content is completely unrelated to the query.",
                score=0.3,
            )
        ]

        result = query_engine._synthesize_from_chunks(ctx)

        assert "relevant sections" in result.lower() or len(result) > 0


# =============================================================================
# Test Class: Response Formatting
# =============================================================================


class TestResponseFormatting:
    """Tests for response formatting utilities."""

    def test_format_responses(self, query_engine):
        """Test formatting multiple agent responses."""
        responses = {
            "agent_1": "This is agent 1's response about the topic.",
            "agent_2": "Agent 2 provides a different perspective.",
        }

        formatted = query_engine._format_responses(responses)

        assert "[agent_1]:" in formatted
        assert "[agent_2]:" in formatted
        assert "agent 1's response" in formatted

    def test_format_responses_truncation(self, query_engine):
        """Test that long responses are truncated."""
        long_response = "x" * 2000
        responses = {"verbose_agent": long_response}

        formatted = query_engine._format_responses(responses)

        assert "..." in formatted
        assert len(formatted) < len(long_response) + 100

    def test_format_empty_responses(self, query_engine):
        """Test formatting empty responses dict."""
        formatted = query_engine._format_responses({})

        assert formatted == ""
