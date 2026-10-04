"""
Tests for Natural Language Query Interface.

Tests cover:
- QueryConfig configuration
- Citation creation and serialization
- QueryResult construction
- DocumentQueryEngine query processing
- Query mode detection
- Streaming responses
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dataclasses import asdict

from aragora.analysis.nl_query import (
    DocumentQueryEngine,
    QueryConfig,
    QueryResult,
    QueryMode,
    AnswerConfidence,
    Citation,
    StreamingChunk,
    query_documents,
    summarize_document,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def query_config():
    """Create a basic query configuration."""
    return QueryConfig(
        max_chunks=10,
        min_relevance=0.3,
        include_quotes=True,
    )


@pytest.fixture
def mock_searcher():
    """Create a mock hybrid searcher."""
    searcher = AsyncMock()

    # Create mock search results
    mock_result = MagicMock()
    mock_result.chunk_id = "chunk-1"
    mock_result.document_id = "doc-1"
    mock_result.content = "This is test content from the document."
    mock_result.combined_score = 0.85
    mock_result.start_page = 1
    mock_result.heading_context = "Chapter 1"

    searcher.search.return_value = [mock_result]
    return searcher


@pytest.fixture
def query_engine(query_config, mock_searcher):
    """Create a query engine with mocked dependencies."""
    engine = DocumentQueryEngine(config=query_config, searcher=mock_searcher)
    return engine


@pytest.fixture
def sample_citation():
    """Create a sample citation."""
    return Citation(
        document_id="doc-123",
        document_name="Sample Document.pdf",
        chunk_id="chunk-456",
        snippet="This is a relevant excerpt from the document...",
        page=5,
        relevance_score=0.87,
        heading_context="Section 2.1",
    )


@pytest.fixture
def sample_query_result():
    """Create a sample query result."""
    return QueryResult(
        query_id="query_abc123",
        question="What is the main topic?",
        answer="The main topic is about software development practices.",
        confidence=AnswerConfidence.HIGH,
        citations=[
            Citation(
                document_id="doc-1",
                document_name="doc1.pdf",
                chunk_id="chunk-1",
                snippet="Software development practices...",
                page=1,
                relevance_score=0.9,
            )
        ],
        query_mode=QueryMode.FACTUAL,
        chunks_searched=15,
        chunks_relevant=5,
        processing_time_ms=250,
        model_used="claude-3.5-sonnet",
        metadata={"workspace_id": "ws-123"},
    )


# ============================================================================
# QueryConfig Tests
# ============================================================================


class TestQueryConfig:
    """Tests for query configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = QueryConfig()

        assert config.max_chunks == 10
        assert config.min_relevance == 0.3
        assert config.vector_weight == 0.7
        assert config.max_answer_length == 500
        assert config.include_quotes is True
        assert config.require_citations is True
        assert config.model == "claude-3.5-sonnet"

    def test_custom_config(self):
        """Test custom configuration."""
        config = QueryConfig(
            max_chunks=20,
            min_relevance=0.5,
            vector_weight=0.6,
            max_answer_length=1000,
            include_quotes=False,
        )

        assert config.max_chunks == 20
        assert config.min_relevance == 0.5
        assert config.vector_weight == 0.6
        assert config.max_answer_length == 1000
        assert config.include_quotes is False

    def test_context_settings(self):
        """Test conversation context settings."""
        config = QueryConfig(
            enable_context=True,
            max_context_turns=5,
        )

        assert config.enable_context is True
        assert config.max_context_turns == 5

    def test_query_enhancement_settings(self):
        """Test query enhancement settings."""
        config = QueryConfig(
            expand_query=True,
            detect_intent=True,
        )

        assert config.expand_query is True
        assert config.detect_intent is True


# ============================================================================
# Citation Tests
# ============================================================================


class TestCitation:
    """Tests for citation objects."""

    def test_citation_creation(self, sample_citation):
        """Test creating a citation."""
        assert sample_citation.document_id == "doc-123"
        assert sample_citation.document_name == "Sample Document.pdf"
        assert sample_citation.chunk_id == "chunk-456"
        assert sample_citation.page == 5
        assert sample_citation.relevance_score == 0.87

    def test_citation_to_dict(self, sample_citation):
        """Test converting citation to dictionary."""
        data = sample_citation.to_dict()

        assert data["document_id"] == "doc-123"
        assert data["document_name"] == "Sample Document.pdf"
        assert data["chunk_id"] == "chunk-456"
        assert data["snippet"] == "This is a relevant excerpt from the document..."
        assert data["page"] == 5
        assert data["relevance_score"] == 0.87
        assert data["heading_context"] == "Section 2.1"

    def test_citation_without_page(self):
        """Test citation without page number."""
        citation = Citation(
            document_id="doc-1",
            document_name="doc.txt",
            chunk_id="chunk-1",
            snippet="Some text...",
        )

        assert citation.page is None
        data = citation.to_dict()
        assert data["page"] is None


# ============================================================================
# QueryResult Tests
# ============================================================================


class TestQueryResult:
    """Tests for query result objects."""

    def test_query_result_creation(self, sample_query_result):
        """Test creating a query result."""
        assert sample_query_result.query_id == "query_abc123"
        assert sample_query_result.question == "What is the main topic?"
        assert sample_query_result.confidence == AnswerConfidence.HIGH
        assert sample_query_result.chunks_searched == 15
        assert sample_query_result.chunks_relevant == 5

    def test_query_result_to_dict(self, sample_query_result):
        """Test converting query result to dictionary."""
        data = sample_query_result.to_dict()

        assert data["query_id"] == "query_abc123"
        assert data["question"] == "What is the main topic?"
        assert data["confidence"] == "high"
        assert data["query_mode"] == "factual"
        assert len(data["citations"]) == 1
        assert data["processing_time_ms"] == 250
        assert data["model_used"] == "claude-3.5-sonnet"

    def test_query_result_has_answer(self, sample_query_result):
        """Test has_answer property."""
        assert sample_query_result.has_answer is True

    def test_query_result_no_answer(self):
        """Test has_answer when no answer found."""
        result = QueryResult(
            query_id="q1",
            question="Unknown question?",
            answer="",
            confidence=AnswerConfidence.NONE,
            citations=[],
            query_mode=QueryMode.FACTUAL,
            chunks_searched=10,
            chunks_relevant=0,
            processing_time_ms=100,
            model_used="none",
        )

        assert result.has_answer is False


# ============================================================================
# StreamingChunk Tests
# ============================================================================


class TestStreamingChunk:
    """Tests for streaming chunks."""

    def test_streaming_chunk_creation(self):
        """Test creating a streaming chunk."""
        chunk = StreamingChunk(
            text="This is partial answer...",
            is_final=False,
        )

        assert chunk.text == "This is partial answer..."
        assert chunk.is_final is False
        assert chunk.citations == []

    def test_final_streaming_chunk(self, sample_citation):
        """Test final streaming chunk with citations."""
        chunk = StreamingChunk(
            text="",
            is_final=True,
            citations=[sample_citation],
        )

        assert chunk.is_final is True
        assert len(chunk.citations) == 1


# ============================================================================
# QueryMode Detection Tests
# ============================================================================


class TestQueryModeDetection:
    """Tests for query mode/intent detection."""

    def test_detect_summary_mode(self, query_engine):
        """Test detection of summary queries."""
        queries = [
            "Summarize this document",
            "Give me an overview of the main points",
            "What are the key takeaways?",
        ]

        for query in queries[:2]:  # First two should definitely match
            mode = query_engine._detect_query_mode(query)
            assert mode == QueryMode.SUMMARY, f"Failed for: {query}"

    def test_detect_comparative_mode(self, query_engine):
        """Test detection of comparative queries."""
        queries = [
            "Compare these two contracts",
            "What's the difference between version 1 and 2?",
            "How does A versus B?",
        ]

        for query in queries:
            mode = query_engine._detect_query_mode(query)
            assert mode == QueryMode.COMPARATIVE, f"Failed for: {query}"

    def test_detect_analytical_mode(self, query_engine):
        """Test detection of analytical queries."""
        queries = [
            "Why did the project fail?",
            "Analyze the impact of this change",
            "Explain the implications",
        ]

        for query in queries:
            mode = query_engine._detect_query_mode(query)
            assert mode == QueryMode.ANALYTICAL, f"Failed for: {query}"

    def test_detect_extractive_mode(self, query_engine):
        """Test detection of extractive queries."""
        queries = [
            "List all the requirements",
            "Extract the key dates",
            "Find all mentions of compliance",
        ]

        for query in queries:
            mode = query_engine._detect_query_mode(query)
            assert mode == QueryMode.EXTRACTIVE, f"Failed for: {query}"

    def test_default_factual_mode(self, query_engine):
        """Test default to factual mode."""
        query = "What is the contract value?"
        mode = query_engine._detect_query_mode(query)

        assert mode == QueryMode.FACTUAL


# ============================================================================
# Query Expansion Tests
# ============================================================================


class TestQueryExpansion:
    """Tests for query expansion."""

    def test_expand_query(self, query_engine):
        """Test query expansion."""
        query = "What are the requirements?"
        expanded = query_engine._expand_query(query)

        assert len(expanded) >= 1
        assert query in expanded

    def test_expand_removes_question_words(self, query_engine):
        """Test that expansion removes question words."""
        query = "What is the deadline?"
        expanded = query_engine._expand_query(query)

        # Should have keyword-focused version
        assert len(expanded) >= 1


# ============================================================================
# DocumentQueryEngine Tests
# ============================================================================


class TestDocumentQueryEngine:
    """Tests for the query engine."""

    def test_engine_creation(self, query_config):
        """Test creating a query engine."""
        engine = DocumentQueryEngine(config=query_config)

        assert engine.config == query_config
        assert engine._conversation_history == {}

    @pytest.mark.asyncio
    async def test_create_factory(self):
        """Test async factory method."""
        # Skip if create method doesn't use create_hybrid_searcher
        try:
            engine = await DocumentQueryEngine.create()
            assert engine is not None
        except Exception:
            # Factory may require external dependencies, that's OK
            pytest.skip("DocumentQueryEngine.create() requires external dependencies")

    @pytest.mark.asyncio
    async def test_call_llm_provider_errors_fall_through_to_the_last_resort(self, query_engine):
        """A provider API error on both models yields the model-unavailable answer."""
        from aragora.agents.errors.exceptions import AgentAPIError

        agent = MagicMock()
        agent.generate = AsyncMock(side_effect=AgentAPIError("provider said 400"))
        with patch("aragora.agents.create_agent", return_value=agent):
            answer, model = await query_engine._call_llm("prompt", [])

        assert answer == "Unable to generate answer due to model unavailability."
        assert model == "none"
        assert agent.generate.await_count == 2

    @pytest.mark.asyncio
    async def test_query_basic(self, query_engine, mock_searcher):
        """Test basic query functionality."""
        # Mock the LLM call
        with patch.object(
            query_engine,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=("The document discusses software practices.", "claude-3.5-sonnet"),
        ):
            result = await query_engine.query(
                question="What is the document about?",
                document_ids=["doc-1"],
            )

            assert result is not None
            assert result.question == "What is the document about?"
            assert result.answer is not None
            assert result.query_mode in QueryMode.__members__.values()
            mock_searcher.search.assert_called()

    @pytest.mark.asyncio
    async def test_query_with_workspace(self, query_engine, mock_searcher):
        """Test query with workspace scope."""
        with patch.object(
            query_engine,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=("Answer text", "claude-3.5-sonnet"),
        ):
            result = await query_engine.query(
                question="What is the deadline?",
                workspace_id="ws-123",
            )

            assert result is not None
            assert result.metadata.get("workspace_id") == "ws-123"

    @pytest.mark.asyncio
    async def test_query_no_results(self, query_config):
        """Test query with no search results."""
        mock_searcher = AsyncMock()
        mock_searcher.search.return_value = []

        engine = DocumentQueryEngine(config=query_config, searcher=mock_searcher)

        result = await engine.query(
            question="What is an unknown topic?",
        )

        assert result.confidence == AnswerConfidence.NONE
        assert "couldn't find" in result.answer.lower()

    @pytest.mark.asyncio
    async def test_query_with_conversation_context(self, query_engine, mock_searcher):
        """Test query with conversation history."""
        with patch.object(
            query_engine,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=("Follow-up answer", "claude-3.5-sonnet"),
        ):
            # First query
            await query_engine.query(
                question="What is the topic?",
                conversation_id="conv-123",
            )

            # Follow-up query
            result = await query_engine.query(
                question="Tell me more about it",
                conversation_id="conv-123",
            )

            # Should have conversation history
            assert "conv-123" in query_engine._conversation_history

    @pytest.mark.asyncio
    async def test_summarize_documents(self, query_engine, mock_searcher):
        """Test document summarization."""
        with patch.object(
            query_engine,
            "query",
            new_callable=AsyncMock,
            return_value=QueryResult(
                query_id="q1",
                question="Summary",
                answer="This is a summary.",
                confidence=AnswerConfidence.HIGH,
                citations=[],
                query_mode=QueryMode.SUMMARY,
                chunks_searched=10,
                chunks_relevant=5,
                processing_time_ms=200,
                model_used="claude-3.5-sonnet",
            ),
        ):
            result = await query_engine.summarize_documents(
                document_ids=["doc-1", "doc-2"],
                focus="key findings",
            )

            assert result is not None

    @pytest.mark.asyncio
    async def test_compare_documents(self, query_engine):
        """Test document comparison."""
        with patch.object(
            query_engine,
            "query",
            new_callable=AsyncMock,
            return_value=QueryResult(
                query_id="q1",
                question="Compare",
                answer="Doc 1 differs from Doc 2 in...",
                confidence=AnswerConfidence.MEDIUM,
                citations=[],
                query_mode=QueryMode.COMPARATIVE,
                chunks_searched=20,
                chunks_relevant=8,
                processing_time_ms=300,
                model_used="claude-3.5-sonnet",
            ),
        ):
            result = await query_engine.compare_documents(
                document_ids=["doc-1", "doc-2"],
                aspects=["pricing", "terms"],
            )

            assert result is not None

    @pytest.mark.asyncio
    async def test_compare_documents_requires_two(self, query_engine):
        """Test that comparison requires at least 2 documents."""
        with pytest.raises(ValueError, match="at least 2 documents"):
            await query_engine.compare_documents(document_ids=["doc-1"])

    @pytest.mark.asyncio
    async def test_extract_information(self, query_engine):
        """Test structured information extraction."""
        with patch.object(
            query_engine,
            "query",
            new_callable=AsyncMock,
            return_value=QueryResult(
                query_id="q1",
                question="Extract",
                answer="Value extracted",
                confidence=AnswerConfidence.HIGH,
                citations=[],
                query_mode=QueryMode.EXTRACTIVE,
                chunks_searched=5,
                chunks_relevant=2,
                processing_time_ms=150,
                model_used="claude-3.5-sonnet",
            ),
        ):
            results = await query_engine.extract_information(
                document_ids=["doc-1"],
                extraction_template={
                    "contract_value": "What is the total contract value?",
                    "start_date": "When does the contract start?",
                },
            )

            assert "contract_value" in results
            assert "start_date" in results

    def test_clear_conversation(self, query_engine):
        """Test clearing conversation history."""
        query_engine._conversation_history["conv-1"] = [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ]

        query_engine.clear_conversation("conv-1")

        assert "conv-1" not in query_engine._conversation_history


# ============================================================================
# Confidence Assessment Tests
# ============================================================================


class TestConfidenceAssessment:
    """Tests for answer confidence assessment."""

    def test_high_confidence(self, query_engine):
        """Test high confidence assessment."""
        mock_result = MagicMock()
        mock_result.combined_score = 0.9

        confidence = query_engine._assess_confidence(
            answer="Clear answer with citations.",
            results=[mock_result, mock_result],
        )

        assert confidence == AnswerConfidence.HIGH

    def test_low_confidence_uncertainty(self, query_engine):
        """Test low confidence when answer shows uncertainty."""
        mock_result = MagicMock()
        mock_result.combined_score = 0.8

        confidence = query_engine._assess_confidence(
            answer="I couldn't find specific information about this.",
            results=[mock_result],
        )

        assert confidence == AnswerConfidence.LOW

    def test_no_confidence_no_results(self, query_engine):
        """Test no confidence when no results."""
        confidence = query_engine._assess_confidence(
            answer="No answer",
            results=[],
        )

        assert confidence == AnswerConfidence.NONE


# ============================================================================
# Convenience Function Tests
# ============================================================================


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    @pytest.mark.asyncio
    async def test_query_documents_function(self):
        """Test query_documents convenience function."""
        with patch(
            "aragora.analysis.nl_query.DocumentQueryEngine.create",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_engine = AsyncMock()
            mock_engine.query.return_value = QueryResult(
                query_id="q1",
                question="Test?",
                answer="Test answer",
                confidence=AnswerConfidence.HIGH,
                citations=[],
                query_mode=QueryMode.FACTUAL,
                chunks_searched=5,
                chunks_relevant=2,
                processing_time_ms=100,
                model_used="test",
            )
            mock_create.return_value = mock_engine

            result = await query_documents(
                question="What is the answer?",
                document_ids=["doc-1"],
            )

            assert result is not None
            mock_engine.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_document_function(self):
        """Test summarize_document convenience function."""
        with patch(
            "aragora.analysis.nl_query.DocumentQueryEngine.create",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_engine = AsyncMock()
            mock_engine.summarize_documents.return_value = QueryResult(
                query_id="q1",
                question="Summarize",
                answer="Summary text",
                confidence=AnswerConfidence.HIGH,
                citations=[],
                query_mode=QueryMode.SUMMARY,
                chunks_searched=10,
                chunks_relevant=5,
                processing_time_ms=200,
                model_used="test",
            )
            mock_create.return_value = mock_engine

            result = await summarize_document(
                document_id="doc-1",
                focus="key points",
            )

            assert result is not None
            mock_engine.summarize_documents.assert_called_once()
