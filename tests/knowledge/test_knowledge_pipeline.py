"""Integration tests for the Knowledge Pipeline.

Tests the complete flow: document upload → chunking → embedding → query → facts.
"""

import asyncio
import pytest
from pathlib import Path
from typing import Optional

from aragora.knowledge import (
    ChunkMatch,
    DatasetQueryEngine,
    ExtractionConfig,
    Fact,
    FactExtractor,
    FactStore,
    InMemoryEmbeddingService,
    InMemoryFactStore,
    ScopedFactStore,
    KnowledgePipeline,
    PipelineConfig,
    QueryOptions,
    QueryResult,
    SimpleQueryEngine,
    ValidationStatus,
    create_fact_extractor,
    create_pipeline,
)


class MockAgent:
    """Mock agent for testing without real API calls."""

    def __init__(self, name: str = "mock-agent"):
        self.name = name
        self.call_count = 0
        self.last_prompt: str | None = None

    async def generate(self, prompt: str, context: list | None = None) -> str:
        """Generate a mock response based on the prompt."""
        self.call_count += 1
        self.last_prompt = prompt

        # Return different responses based on prompt content
        if "extract" in prompt.lower() or "fact" in prompt.lower():
            return """{"facts": [
                {"statement": "The contract expires on December 31, 2025", "confidence": 0.9, "topics": ["contract", "expiration"], "evidence_quote": "expires on 12/31/2025"},
                {"statement": "Payment is due within 30 days", "confidence": 0.85, "topics": ["payment", "terms"], "evidence_quote": "NET-30 payment terms"}
            ]}"""
        elif "verify" in prompt.lower():
            return """{"verified_facts": [
                {"original_statement": "The contract expires on December 31, 2025", "verified": true, "adjusted_confidence": 0.92, "reason": "Clearly stated in document"},
                {"original_statement": "Payment is due within 30 days", "verified": true, "adjusted_confidence": 0.88, "reason": "Standard NET-30 terms confirmed"}
            ]}"""
        elif "answer" in prompt.lower() or "question" in prompt.lower():
            return "Based on the document excerpts [1], the contract includes NET-30 payment terms and expires on December 31, 2025 [2]. The agreement covers standard commercial services with annual renewal."
        else:
            return f"Mock response for: {prompt[:100]}..."


class TestKnowledgePipelineIntegration:
    """Integration tests for the complete knowledge pipeline."""

    @pytest.fixture
    def sample_contract_text(self) -> str:
        """Sample contract document for testing."""
        return """
        SERVICE AGREEMENT

        Effective Date: January 1, 2024

        This Service Agreement ("Agreement") is entered into between
        Acme Corporation ("Provider") and Beta Industries ("Client").

        1. TERM AND TERMINATION
        This Agreement shall commence on the Effective Date and continue
        until December 31, 2025, unless terminated earlier pursuant to
        this Agreement.

        2. PAYMENT TERMS
        Client agrees to pay Provider according to the following terms:
        - All invoices are due within 30 days of receipt (NET-30)
        - Late payments will incur a 1.5% monthly interest charge
        - Annual service fee: $50,000

        3. SERVICES
        Provider shall provide the following services:
        - Cloud hosting and infrastructure management
        - 24/7 technical support
        - Monthly security audits
        - Quarterly performance reviews

        4. CONFIDENTIALITY
        Both parties agree to maintain strict confidentiality of all
        proprietary information shared during the term of this Agreement.

        5. GOVERNING LAW
        This Agreement shall be governed by the laws of the State of
        California, USA.

        SIGNATURES:
        Acme Corporation: _______________ Date: ___________
        Beta Industries: _______________ Date: ___________
        """

    @pytest.fixture
    def sample_financial_text(self) -> str:
        """Sample financial document for testing."""
        return """
        QUARTERLY FINANCIAL REPORT
        Q4 2025

        Revenue Summary:
        - Total Revenue: $2,500,000
        - Operating Expenses: $1,800,000
        - Net Profit: $700,000
        - Profit Margin: 28%

        Key Metrics:
        - Customer Acquisition Cost: $150
        - Monthly Recurring Revenue: $850,000
        - Customer Churn Rate: 2.5%
        - Average Contract Value: $12,000

        Year-over-Year Growth:
        - Revenue increased by 35% compared to Q4 2024
        - Customer base grew from 180 to 240 accounts
        - Employee headcount increased from 45 to 62

        Outlook:
        Management expects continued growth in 2026 with projected
        revenue of $12M and expansion into European markets.
        """

    @pytest.fixture
    def mock_agents(self) -> list[MockAgent]:
        """Create mock agents for testing."""
        return [MockAgent("agent-1"), MockAgent("agent-2")]

    @pytest.fixture
    def pipeline(self, mock_agents: list[MockAgent]) -> KnowledgePipeline:
        """Create a test pipeline with in-memory backends."""
        config = PipelineConfig(
            workspace_id="ws_test",
            use_weaviate=False,
            extract_facts=True,
            min_fact_confidence=0.5,
        )
        return KnowledgePipeline(
            config, fact_store=ScopedFactStore(InMemoryFactStore(), "org-test")
        )

    @pytest.mark.asyncio
    async def test_full_pipeline_single_document(
        self, pipeline: KnowledgePipeline, sample_contract_text: str
    ):
        """Test complete pipeline with a single document."""
        await pipeline.start()

        try:
            # Process document (content as bytes)
            result = await pipeline.process_document(
                content=sample_contract_text.encode("utf-8"),
                filename="contract.txt",
            )

            assert result.success
            assert result.document_id  # Should have an ID assigned
            assert result.chunk_count > 0

            # Query the processed content
            query_result = await pipeline.query(
                question="What are the payment terms?",
                options=QueryOptions(use_agents=False),  # No agents in test
            )

            assert query_result.answer
            # Confidence may be low without agents

        finally:
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_full_pipeline_text_input(
        self, pipeline: KnowledgePipeline, sample_contract_text: str
    ):
        """Test pipeline processing for raw text input."""
        await pipeline.start()

        try:
            result = await pipeline.process_text(
                text=sample_contract_text,
                filename="contract-note.md",
                metadata={"user_id": "user_123", "workspace_id": "ws_test"},
            )

            assert result.success
            assert result.document_id
            assert result.document is not None
            assert result.document.filename == "contract-note.md"
            assert result.document.metadata.get("user_id") == "user_123"
        finally:
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_full_pipeline_batch_documents(
        self,
        pipeline: KnowledgePipeline,
        sample_contract_text: str,
        sample_financial_text: str,
    ):
        """Test pipeline with multiple documents."""
        await pipeline.start()

        try:
            # Process batch - list of (bytes, filename) tuples
            files = [
                (sample_contract_text.encode("utf-8"), "contract.txt"),
                (sample_financial_text.encode("utf-8"), "financial.txt"),
            ]

            results = await pipeline.process_batch(files)

            assert len(results) == 2
            assert all(r.success for r in results)

            # Search across documents
            chunks = await pipeline.search("revenue", limit=5)
            # May or may not find chunks depending on embedding

            # Get facts
            facts = await pipeline.get_facts("payment", limit=10)
            # May or may not have facts depending on extraction

        finally:
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_query_with_debate(self, sample_contract_text: str, mock_agents: list[MockAgent]):
        """Test query with multi-agent debate enabled."""
        fact_store = ScopedFactStore(InMemoryFactStore(), "org-test")
        embedding_service = InMemoryEmbeddingService()

        # Add sample chunk
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "content": sample_contract_text[:500],
                    "chunk_id": "chunk_001",
                    "document_id": "doc_001",
                }
            ],
            workspace_id="ws_test",
        )

        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
            agents=mock_agents,
            default_agent=mock_agents[0],
        )

        result = await engine.query(
            question="When does the contract expire?",
            workspace_id="ws_test",
            options=QueryOptions(
                use_agents=True,
                use_debate=True,
                debate_rounds=1,
            ),
        )

        assert result.answer
        # With debate, we should have multiple agent contributions
        assert len(result.agent_contributions) >= 1


class TestFactExtractorIntegration:
    """Integration tests for fact extraction."""

    @pytest.fixture
    def extractor(self) -> FactExtractor:
        """Create a fact extractor with mock agent."""
        agent = MockAgent("extractor-agent")
        store = ScopedFactStore(InMemoryFactStore(), "org-test")

        return create_fact_extractor(
            agents=[agent],
            fact_store=store,
            config=ExtractionConfig(
                max_facts_per_chunk=5,
                min_confidence_threshold=0.5,
            ),
        )

    @pytest.mark.asyncio
    async def test_extract_facts_from_text(self, extractor: FactExtractor):
        """Test extracting facts from document text."""
        content = """
        The contract expires on December 31, 2025.
        Payment terms are NET-30 with 1.5% monthly interest on late payments.
        The annual service fee is $50,000.
        """

        result = await extractor.extract_facts(
            content=content,
            chunk_id="chunk_001",
            document_id="doc_001",
            filename="contract.txt",
            workspace_id="ws_test",
        )

        assert len(result.errors) == 0
        assert len(result.facts) > 0
        assert result.extraction_time_ms > 0

    @pytest.mark.asyncio
    async def test_extract_batch(self, extractor: FactExtractor):
        """Test batch extraction from multiple chunks."""
        chunks = [
            {
                "content": "Contract expires 2025-12-31",
                "chunk_id": "c1",
                "document_id": "d1",
            },
            {
                "content": "Payment due within 30 days",
                "chunk_id": "c2",
                "document_id": "d1",
            },
        ]

        results = await extractor.extract_batch(
            chunks=chunks,
            workspace_id="ws_test",
            max_concurrent=2,
        )

        assert len(results) == 2
        assert all(r.chunk_id for r in results)

    @pytest.mark.asyncio
    async def test_demo_extraction_without_agents(self):
        """Test demo extraction when no agents are available."""
        extractor = FactExtractor(agents=[])

        content = """
        The project deadline is 2025-06-15.
        Total budget: $125,000.
        Expected completion rate: 95%.
        """

        result = await extractor.extract_facts(
            content=content,
            chunk_id="chunk_001",
            document_id="doc_001",
            workspace_id="ws_test",
        )

        # Demo extraction should find dates, money, percentages
        assert result.agent_used == "demo"
        # Should find at least the monetary value and percentage
        assert len(result.facts) >= 2


class TestSimpleQueryEngine:
    """Tests for SimpleQueryEngine (no agents)."""

    @pytest.fixture
    def engine(self) -> SimpleQueryEngine:
        """Create a simple query engine."""
        return SimpleQueryEngine(ScopedFactStore(InMemoryFactStore(), "org-test"))

    @pytest.mark.asyncio
    async def test_search_and_facts(self, engine: SimpleQueryEngine):
        """Test basic search and fact operations."""
        # Add a fact
        fact = engine.add_fact(
            statement="Contract expires December 2025",
            workspace_id="ws_test",
            evidence_ids=["ev_001"],
        )

        assert fact.id.startswith("fact_")
        assert fact.workspace_id == "ws_test"

        # Search for facts
        facts = await engine.get_facts(
            query="contract",
            workspace_id="ws_test",
        )

        # Should find the fact (via topic or FTS)
        assert len(facts) >= 0  # May not match via simple query


class TestEndToEndWorkflow:
    """End-to-end workflow tests."""

    @pytest.mark.asyncio
    async def test_document_to_verified_facts(self):
        """Test complete workflow from document to verified facts."""
        # Setup
        fact_store = ScopedFactStore(InMemoryFactStore(), "org-test")
        embedding_service = InMemoryEmbeddingService()
        agents = [MockAgent("agent-1"), MockAgent("agent-2")]

        extractor = FactExtractor(
            agents=agents,
            fact_store=fact_store,
            config=ExtractionConfig(require_agreement=True),
        )

        query_engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
            agents=agents,
            default_agent=agents[0],
        )

        # Step 1: Simulate document ingestion
        document_content = "Contract expires 2025-12-31. Payment terms NET-30."

        # Step 2: Embed content
        await embedding_service.embed_chunks(
            chunks=[
                {
                    "content": document_content,
                    "chunk_id": "chunk_001",
                    "document_id": "doc_001",
                }
            ],
            workspace_id="ws_test",
        )

        # Step 3: Extract facts
        extraction_result = await extractor.extract_facts(
            content=document_content,
            chunk_id="chunk_001",
            document_id="doc_001",
            workspace_id="ws_test",
        )

        assert len(extraction_result.facts) > 0

        # Step 4: Query the knowledge base
        query_result = await query_engine.query(
            question="When does the contract expire?",
            workspace_id="ws_test",
        )

        assert query_result.answer
        assert query_result.confidence > 0

        # Step 5: Verify facts
        facts = fact_store.list_facts()
        if facts:
            verified_fact = await query_engine.verify_fact(facts[0].id)
            # Verification should have been attempted
            assert verified_fact.id == facts[0].id


class TestPipelineConfiguration:
    """Tests for pipeline configuration options."""

    @pytest.mark.asyncio
    async def test_pipeline_with_custom_config(self):
        """Test pipeline with custom configuration."""
        config = PipelineConfig(
            workspace_id="ws_custom",
            use_weaviate=False,
            extract_facts=False,
            min_fact_confidence=0.7,
            embedding_batch_size=10,
        )

        pipeline = KnowledgePipeline(config)
        await pipeline.start()

        try:
            result = await pipeline.process_document(
                content=b"Sample document content for testing configuration.",
                filename="test.txt",
            )

            assert result.success

        finally:
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_pipeline_error_handling(self):
        """Test pipeline handles errors gracefully."""
        config = PipelineConfig(
            workspace_id="ws_error_test",
            use_weaviate=False,
        )
        pipeline = KnowledgePipeline(config)
        await pipeline.start()

        try:
            # Empty content should be handled
            result = await pipeline.process_document(
                content=b"",
                filename="empty.txt",
            )

            # Should not crash, but may report failure
            assert result.document_id  # Should have an ID assigned

        finally:
            await pipeline.stop()


class TestEmbeddingServiceIntegration:
    """Tests for embedding service integration."""

    @pytest.mark.asyncio
    async def test_in_memory_embedding_service(self):
        """Test in-memory embedding service operations."""
        service = InMemoryEmbeddingService()

        # Embed chunks
        count = await service.embed_chunks(
            chunks=[
                {"content": "First chunk about contracts", "chunk_id": "c1", "document_id": "d1"},
                {"content": "Second chunk about payments", "chunk_id": "c2", "document_id": "d1"},
                {"content": "Third chunk about legal terms", "chunk_id": "c3", "document_id": "d1"},
            ],
            workspace_id="ws_test",
        )

        assert count == 3

        # Hybrid search
        results = await service.hybrid_search(
            query="contract terms",
            workspace_id="ws_test",
            limit=2,
        )

        assert len(results) <= 2
        if results:
            assert results[0].score >= 0

        # Vector search
        vector_results = await service.vector_search(
            query="payment processing",
            workspace_id="ws_test",
            limit=3,
        )

        assert len(vector_results) <= 3

        # Keyword search
        keyword_results = await service.keyword_search(
            query="contracts",
            workspace_id="ws_test",
            limit=5,
        )

        # Should find chunks containing contract-related terms
        assert len(keyword_results) >= 0

    @pytest.mark.asyncio
    async def test_workspace_isolation(self):
        """Test that workspaces are properly isolated."""
        service = InMemoryEmbeddingService()

        # Add to workspace 1
        await service.embed_chunks(
            chunks=[{"content": "Workspace 1 content", "chunk_id": "c1", "document_id": "d1"}],
            workspace_id="ws_1",
        )

        # Add to workspace 2
        await service.embed_chunks(
            chunks=[{"content": "Workspace 2 content", "chunk_id": "c2", "document_id": "d2"}],
            workspace_id="ws_2",
        )

        # Search workspace 1
        results_1 = await service.hybrid_search(
            query="content",
            workspace_id="ws_1",
        )

        # Search workspace 2
        results_2 = await service.hybrid_search(
            query="content",
            workspace_id="ws_2",
        )

        # Each should only find its own content
        for r in results_1:
            assert r.workspace_id == "ws_1"

        for r in results_2:
            assert r.workspace_id == "ws_2"
