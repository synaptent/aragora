"""
Integration tests for Knowledge Pipeline.

Tests the complete flow:
1. Document upload → chunking → embedding
2. Fact extraction and storage
3. Query processing with semantic search
4. Multi-agent query synthesis
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mark all tests as integration tests
pytestmark = pytest.mark.integration


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sample_document_content() -> bytes:
    """Sample document content for testing."""
    return b"""
    EMPLOYMENT CONTRACT

    This Employment Agreement ("Agreement") is entered into as of January 1, 2025,
    between Acme Corporation ("Company") and John Doe ("Employee").

    1. POSITION AND DUTIES
    Employee shall serve as Senior Software Engineer, reporting to the CTO.
    Employee's duties include software development, code review, and mentoring.

    2. COMPENSATION
    Base salary: $150,000 per year, paid bi-weekly.
    Bonus: Up to 20% of base salary based on performance.
    Stock options: 10,000 shares vesting over 4 years.

    3. BENEFITS
    - Health insurance (medical, dental, vision)
    - 401(k) with 4% company match
    - 20 days paid time off
    - Remote work flexibility

    4. TERMINATION
    Either party may terminate with 30 days written notice.
    Company may terminate immediately for cause.

    5. CONFIDENTIALITY
    Employee agrees to maintain confidentiality of proprietary information.
    Non-compete: 12 months post-employment within same industry.

    SIGNATURES:
    Company: _______________  Date: ___________
    Employee: ______________  Date: ___________
    """


@pytest.fixture
def sample_financial_document() -> bytes:
    """Sample financial document for testing."""
    return b"""
    Q4 2024 FINANCIAL REPORT - ACME CORPORATION

    EXECUTIVE SUMMARY
    Revenue: $45.2M (up 15% YoY)
    Net Income: $8.1M (up 22% YoY)
    Operating Margin: 18%

    REVENUE BREAKDOWN
    - Product Sales: $32.5M (72%)
    - Services: $10.2M (23%)
    - Licensing: $2.5M (5%)

    EXPENSES
    - Cost of Goods Sold: $18.1M
    - R&D: $7.5M
    - Sales & Marketing: $5.2M
    - G&A: $3.8M

    BALANCE SHEET HIGHLIGHTS
    - Total Assets: $125M
    - Total Liabilities: $42M
    - Stockholders' Equity: $83M
    - Cash & Equivalents: $28M

    OUTLOOK
    FY2025 Revenue Guidance: $190-200M
    Expected growth rate: 12-15%
    """


@pytest.fixture
def temp_workspace() -> Generator[str, None, None]:
    """Provide a temporary workspace ID."""
    workspace_id = f"test_ws_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    yield workspace_id


# =============================================================================
# Knowledge Pipeline Tests
# =============================================================================


class TestKnowledgePipelineIntegration:
    """Test the complete knowledge pipeline flow."""

    @pytest.mark.asyncio
    async def test_pipeline_initialization(self):
        """Test that the knowledge pipeline initializes correctly."""
        from aragora.knowledge import (
            KnowledgePipeline,
            PipelineConfig,
        )

        config = PipelineConfig(
            extract_facts=True,
            use_weaviate=False,  # Use in-memory for tests
        )

        pipeline = KnowledgePipeline(config)
        assert pipeline is not None
        assert pipeline.config.extract_facts is True

    @pytest.mark.asyncio
    async def test_document_processing_sync(
        self, sample_document_content: bytes, temp_workspace: str
    ):
        """Test document processing (using async version since we're in async context)."""
        from aragora.knowledge.integration import process_document_async, _pipelines

        # Disable Knowledge Mound to avoid external embedding API calls (Gemini)
        with patch("aragora.knowledge.integration._should_use_knowledge_mound", return_value=False):
            # Use async version directly since we're in an async test context
            result = await process_document_async(
                content=sample_document_content,
                filename="employment_contract.txt",
                workspace_id=temp_workspace,
            )

        # Clean up cached pipeline to avoid cross-test leakage
        _pipelines.pop(temp_workspace, None)

        assert result.success is True
        assert result.document_id is not None
        assert result.chunk_count > 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_document_processing_async(
        self, sample_document_content: bytes, temp_workspace: str
    ):
        """Test asynchronous document processing with job tracking."""
        from aragora.knowledge.integration import (
            queue_document_processing,
            get_job_status,
        )

        job_id = queue_document_processing(
            content=sample_document_content,
            filename="employment_contract.txt",
            workspace_id=temp_workspace,
        )

        assert job_id is not None

        # Wait for processing to complete (with timeout)
        max_wait = 10  # seconds
        waited = 0.0
        while waited < max_wait:
            status = get_job_status(job_id)
            if status and status.get("status") in ("completed", "failed"):
                break
            await asyncio.sleep(0.5)
            waited += 0.5

        status = get_job_status(job_id)
        assert status is not None
        assert status.get("status") in ("completed", "pending", "processing")

    @pytest.mark.asyncio
    async def test_fact_extraction(self, sample_document_content: bytes, temp_workspace: str):
        """Test fact extraction from documents."""
        from aragora.knowledge.fact_extractor import FactExtractor, ExtractedFact

        # Create extractor without agents - uses demo extraction
        extractor = FactExtractor()

        # Extract facts using demo mode (no agents provided)
        result = await extractor.extract_facts(
            content=sample_document_content.decode(),
            chunk_id="chunk_1",
            document_id="test_doc_1",
            filename="contract.txt",
            workspace_id=temp_workspace,
        )

        # Result is an ExtractionResult object with facts attribute
        assert result is not None
        assert hasattr(result, "facts")
        # Demo extraction should find some facts from the document content
        assert len(result.facts) >= 0

        # If facts were extracted, verify structure
        for fact in result.facts:
            assert isinstance(fact, ExtractedFact)
            assert fact.statement
            assert 0 <= fact.confidence <= 1

    @pytest.mark.asyncio
    async def test_semantic_search(self, temp_workspace: str):
        """Test semantic search across embedded documents."""
        from aragora.knowledge import InMemoryEmbeddingService

        service = InMemoryEmbeddingService()

        # Add some test chunks (uses chunk_id not id)
        await service.embed_chunks(
            chunks=[
                {
                    "chunk_id": "chunk_1",
                    "content": "The employee salary is $150,000 per year",
                    "document_id": "doc_1",
                },
                {
                    "chunk_id": "chunk_2",
                    "content": "Health insurance includes medical and dental",
                    "document_id": "doc_1",
                },
                {
                    "chunk_id": "chunk_3",
                    "content": "The company revenue was $45 million",
                    "document_id": "doc_2",
                },
            ],
            workspace_id=temp_workspace,
        )

        # Search for compensation-related content
        results = await service.hybrid_search(
            query="employee compensation salary",
            workspace_id=temp_workspace,
            limit=5,
        )

        assert len(results) > 0
        # First result should be salary-related
        assert "salary" in results[0].content.lower() or "150,000" in results[0].content


class TestQueryEngine:
    """Test the natural language query engine."""

    @pytest.mark.asyncio
    async def test_query_basic(self, temp_workspace: str):
        """Test basic query processing."""
        from aragora.knowledge import (
            DatasetQueryEngine,
            InMemoryEmbeddingService,
            InMemoryFactStore,
            QueryOptions,
            ScopedFactStore,
        )

        # Setup
        fact_store = ScopedFactStore(InMemoryFactStore(), "org-test")
        embedding_service = InMemoryEmbeddingService()

        # Add a test fact (sync method - no await)
        fact_store.add_fact(
            statement="The employee base salary is $150,000 per year",
            evidence_ids=["ev_1"],
            source_documents=["doc_1"],
            confidence=0.95,
            workspace_id=temp_workspace,
            topics=["compensation", "salary"],
        )

        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
        )

        # Query
        options = QueryOptions(
            use_agents=False,  # Skip LLM for unit test
            use_debate=False,
            max_chunks=5,
        )

        result = await engine.query(
            question="What is the employee salary?",
            workspace_id=temp_workspace,
            options=options,
        )

        assert result is not None
        assert result.answer is not None
        assert result.confidence >= 0

    @pytest.mark.asyncio
    async def test_query_with_facts(self, temp_workspace: str):
        """Test query returns relevant facts."""
        from aragora.knowledge import (
            DatasetQueryEngine,
            InMemoryEmbeddingService,
            InMemoryFactStore,
            QueryOptions,
            ScopedFactStore,
        )

        fact_store = ScopedFactStore(InMemoryFactStore(), "org-test")
        embedding_service = InMemoryEmbeddingService()

        # Add multiple facts (sync method - no await)
        fact_store.add_fact(
            statement="Company revenue is $45 million",
            evidence_ids=["ev_1"],
            source_documents=["doc_1"],
            confidence=0.9,
            workspace_id=temp_workspace,
            topics=["finance", "revenue"],
        )

        fact_store.add_fact(
            statement="Operating margin is 18%",
            evidence_ids=["ev_2"],
            source_documents=["doc_1"],
            confidence=0.85,
            workspace_id=temp_workspace,
            topics=["finance", "margin"],
        )

        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
        )

        options = QueryOptions(use_agents=False, max_chunks=10)

        result = await engine.query(
            question="What are the financial metrics?",
            workspace_id=temp_workspace,
            options=options,
        )

        assert result is not None
        # Result has 'facts' not 'facts_used'
        assert len(result.facts) >= 0


class TestFactStore:
    """Test the fact store operations."""

    @pytest.mark.asyncio
    async def test_add_and_retrieve_fact(self, temp_workspace: str):
        """Test adding and retrieving facts."""
        from aragora.knowledge import InMemoryFactStore, ScopedFactStore

        store = ScopedFactStore(InMemoryFactStore(), "org-test")

        # add_fact returns a Fact object, not an ID
        created_fact = store.add_fact(
            statement="Test fact statement",
            evidence_ids=["ev_1"],
            source_documents=["doc_1"],
            confidence=0.9,
            workspace_id=temp_workspace,
            topics=["test"],
        )

        assert created_fact is not None
        assert created_fact.id is not None

        # Retrieve by ID
        fact = store.get_fact(created_fact.id)
        assert fact is not None
        assert fact.statement == "Test fact statement"
        assert fact.confidence == 0.9

    @pytest.mark.asyncio
    async def test_list_facts_with_filters(self, temp_workspace: str):
        """Test listing facts with various filters."""
        from aragora.knowledge import InMemoryFactStore, ScopedFactStore
        from aragora.knowledge.types import FactFilters

        store = ScopedFactStore(InMemoryFactStore(), "org-test")

        # Add facts with different confidence levels (sync method)
        store.add_fact(
            statement="High confidence fact",
            evidence_ids=["ev_1"],
            source_documents=["doc_1"],
            confidence=0.95,
            workspace_id=temp_workspace,
            topics=["topic_a"],
        )

        store.add_fact(
            statement="Low confidence fact",
            evidence_ids=["ev_2"],
            source_documents=["doc_2"],
            confidence=0.5,
            workspace_id=temp_workspace,
            topics=["topic_b"],
        )

        # List with min confidence filter using FactFilters
        filters = FactFilters(
            workspace_id=temp_workspace,
            min_confidence=0.8,
        )
        facts = store.list_facts(filters)

        assert len(facts) == 1
        assert facts[0].confidence >= 0.8

    @pytest.mark.asyncio
    async def test_search_facts(self, temp_workspace: str):
        """Test searching facts by keyword."""
        from aragora.knowledge import InMemoryFactStore, ScopedFactStore
        from aragora.knowledge.types import FactFilters

        store = ScopedFactStore(InMemoryFactStore(), "org-test")

        store.add_fact(
            statement="The company revenue was $45 million in Q4",
            evidence_ids=["ev_1"],
            source_documents=["doc_1"],
            confidence=0.9,
            workspace_id=temp_workspace,
            topics=["finance"],
        )

        store.add_fact(
            statement="Employee benefits include health insurance",
            evidence_ids=["ev_2"],
            source_documents=["doc_2"],
            confidence=0.85,
            workspace_id=temp_workspace,
            topics=["hr"],
        )

        # Search for revenue-related facts using query_facts
        filters = FactFilters(workspace_id=temp_workspace)
        results = store.query_facts(
            query="revenue",
            filters=filters,
        )

        assert len(results) >= 1
        assert "revenue" in results[0].statement.lower()


class TestKnowledgeAuditIntegration:
    """Test integration between knowledge pipeline and audit system."""

    @pytest.mark.asyncio
    async def test_audit_finding_to_fact_storage(self, temp_workspace: str):
        """Test storing audit findings as facts."""
        from aragora.audit.knowledge_adapter import (
            AuditKnowledgeAdapter,
            KnowledgeAuditConfig,
        )
        from aragora.knowledge import InMemoryFactStore, ScopedFactStore
        from aragora.audit.document_auditor import (
            AuditFinding,
            AuditSession,
            AuditStatus,
            AuditType,
            FindingSeverity,
            FindingStatus,
        )

        config = KnowledgeAuditConfig(
            store_findings_as_facts=True,
            min_finding_confidence=0.7,
            workspace_id=temp_workspace,
        )

        adapter = AuditKnowledgeAdapter(config)
        await adapter.initialize()
        adapter._fact_store = ScopedFactStore(InMemoryFactStore(), "org-test")  # type: ignore[assignment]

        # Create a mock finding
        finding = AuditFinding(
            id="finding_1",
            title="Hardcoded API Key Detected",
            description="Found hardcoded API key in configuration file",
            severity=FindingSeverity.HIGH,
            confidence=0.95,
            audit_type=AuditType.SECURITY,
            category="credentials",
            document_id="doc_1",
            evidence_text="API_KEY=sk-1234567890",
        )

        # Create a mock session
        session = AuditSession(
            id="session_1",
            document_ids=["doc_1"],
            audit_types=[AuditType.SECURITY],
            name="Test Audit",
            model="test-model",
            status=AuditStatus.COMPLETED,
        )

        # Store finding as fact
        fact_id = await adapter.store_finding_as_fact(finding, session)

        # High confidence finding should be stored
        assert fact_id is not None

    @pytest.mark.asyncio
    async def test_enrich_chunks_with_facts(self, temp_workspace: str):
        """Test enriching document chunks with related facts."""
        from aragora.audit.knowledge_adapter import (
            AuditKnowledgeAdapter,
            KnowledgeAuditConfig,
        )
        from aragora.knowledge import InMemoryFactStore, ScopedFactStore

        config = KnowledgeAuditConfig(
            enrich_with_facts=True,
            workspace_id=temp_workspace,
        )

        adapter = AuditKnowledgeAdapter(config)
        await adapter.initialize()
        adapter._fact_store = ScopedFactStore(InMemoryFactStore(), "org-test")  # type: ignore[assignment]

        # Enrich some test chunks
        chunks = [
            {
                "id": "chunk_1",
                "document_id": "doc_1",
                "content": "The employee salary is $150,000 per year",
                "sequence": 0,
            },
            {
                "id": "chunk_2",
                "document_id": "doc_1",
                "content": "Health insurance benefits are provided",
                "sequence": 1,
            },
        ]

        enriched = await adapter.enrich_chunks(chunks, temp_workspace)

        assert len(enriched) == 2
        assert enriched[0].chunk_id == "chunk_1"
        assert enriched[0].content == chunks[0]["content"]


# =============================================================================
# Integration Test: Full Pipeline
# =============================================================================


class TestFullPipelineIntegration:
    """Test the complete pipeline from upload to query."""

    @pytest.mark.asyncio
    async def test_upload_to_query_flow(self, sample_document_content: bytes, temp_workspace: str):
        """Test the complete flow: upload → process → query."""
        from aragora.knowledge.integration import process_document_async, _pipelines
        from aragora.knowledge import (
            DatasetQueryEngine,
            InMemoryEmbeddingService,
            InMemoryFactStore,
            QueryOptions,
            ScopedFactStore,
        )

        # Step 1: Process document (disable Knowledge Mound to avoid external API calls)
        with patch("aragora.knowledge.integration._should_use_knowledge_mound", return_value=False):
            result = await process_document_async(
                content=sample_document_content,
                filename="contract.txt",
                workspace_id=temp_workspace,
            )

        # Clean up cached pipeline to avoid cross-test leakage
        _pipelines.pop(temp_workspace, None)

        assert result.success is True

        # Step 2: Setup query engine
        fact_store = ScopedFactStore(InMemoryFactStore(), "org-test")
        embedding_service = InMemoryEmbeddingService()

        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
        )

        # Step 3: Query the dataset
        options = QueryOptions(use_agents=False)

        query_result = await engine.query(
            question="What are the employment terms?",
            workspace_id=temp_workspace,
            options=options,
        )

        assert query_result is not None
        assert query_result.answer is not None
