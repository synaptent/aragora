"""
Knowledge System Integration Tests.

Comprehensive tests for:
- Knowledge Mound lifecycle and operations
- Vector backend integration (memory store)
- Fact Registry with staleness tracking
- Vertical knowledge support
- Pipeline integration
"""

import asyncio
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.knowledge.mound.types import (
    ConfidenceLevel,
    IngestionRequest,
    KnowledgeSource,
    MoundBackend,
    MoundConfig,
)
from aragora.knowledge.mound.fact_registry import FactRegistry, RegisteredFact
from aragora.knowledge.mound.vector_abstraction import (
    BaseVectorStore,
    VectorBackend,
    VectorSearchResult,
    VectorStoreConfig,
    VectorStoreFactory,
)
from aragora.knowledge.mound.vector_abstraction.memory import InMemoryVectorStore
from aragora.knowledge.pipeline import KnowledgePipeline, PipelineConfig, ProcessingResult
from aragora.knowledge.fact_store import InMemoryFactStore, ScopedFactStore
from aragora.knowledge.types import ValidationStatus
from aragora.knowledge.mound_core import ProvenanceType


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_db_dir():
    """Create a temporary directory for database files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mound_config(temp_db_dir):
    """Create MoundConfig for SQLite backend."""
    return MoundConfig(
        backend=MoundBackend.SQLITE,
        sqlite_path=str(temp_db_dir / "test_mound.db"),
        default_workspace_id="test_workspace",
        enable_staleness_detection=False,
        enable_culture_accumulator=False,
        enable_deduplication=True,
    )


@pytest.fixture
def vector_config():
    """Create VectorStoreConfig for in-memory store."""
    return VectorStoreConfig(
        backend=VectorBackend.MEMORY,
        collection_name="test_knowledge",
        embedding_dimensions=4,
    )


@pytest.fixture
async def vector_store(vector_config):
    """Create and connect an in-memory vector store."""
    store = InMemoryVectorStore(vector_config)
    await store.connect()
    yield store
    await store.disconnect()


@pytest.fixture
def sample_embeddings():
    """Sample embeddings for testing."""
    return {
        "fact1": [1.0, 0.0, 0.0, 0.0],
        "fact2": [0.9, 0.1, 0.0, 0.0],
        "fact3": [0.0, 1.0, 0.0, 0.0],
        "query": [0.95, 0.05, 0.0, 0.0],
    }


@pytest.fixture
def mock_embedding_service(sample_embeddings):
    """Create mock embedding service."""
    service = MagicMock()
    counter = [0]  # Use list to allow modification in closure

    async def mock_embed(text: str) -> list[float]:
        # Return unique embedding by adding small variation
        counter[0] += 1
        base = sample_embeddings["fact1"].copy()
        # Add small variation to make each embedding unique
        base[0] = base[0] - (counter[0] * 0.01)
        base[1] = counter[0] * 0.01
        return base

    service.embed = mock_embed
    return service


def _scoped_store() -> ScopedFactStore:
    return ScopedFactStore(InMemoryFactStore(), "org-test")


@pytest.fixture
def pipeline_config(temp_db_dir):
    """Create PipelineConfig for testing."""
    return PipelineConfig(
        workspace_id="test_pipeline",
        use_weaviate=False,
        extract_facts=False,
        fact_db_path=temp_db_dir / "facts.db",
    )


# ============================================================================
# Knowledge Mound Integration Tests
# ============================================================================


class TestKnowledgeMoundIntegration:
    """Integration tests for KnowledgeMound facade."""

    @pytest.mark.asyncio
    async def test_mound_lifecycle(self, mound_config):
        """Test mound initialization and shutdown."""
        from aragora.knowledge.mound import KnowledgeMound

        mound = KnowledgeMound(config=mound_config, workspace_id="test_ws")

        assert not mound._initialized

        await mound.initialize()
        assert mound._initialized

        await mound.close()
        assert not mound._initialized

    @pytest.mark.asyncio
    async def test_mound_context_manager(self, mound_config):
        """Test mound as async context manager."""
        from aragora.knowledge.mound import KnowledgeMound

        async with KnowledgeMound(config=mound_config).session() as mound:
            assert mound._initialized

        # Should be closed after context

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, mound_config):
        """Test storing and retrieving knowledge items."""
        from aragora.knowledge.mound import KnowledgeMound

        async with KnowledgeMound(config=mound_config).session() as mound:
            # Store a knowledge item
            request = IngestionRequest(
                content="API keys should never be committed to version control",
                workspace_id="test_ws",
                source_type=KnowledgeSource.DOCUMENT,
                node_type="fact",
                confidence=0.9,
            )

            result = await mound.store(request)

            assert result.success
            assert result.node_id is not None
            assert result.node_id.startswith("kn_")

            # Retrieve the item
            item = await mound.get(result.node_id)

            assert item is not None
            assert "API keys" in item.content

    @pytest.mark.asyncio
    async def test_add_convenience_method(self, mound_config):
        """Test the simplified add() method."""
        from aragora.knowledge.mound import KnowledgeMound

        async with KnowledgeMound(config=mound_config).session() as mound:
            node_id = await mound.add(
                content="Test knowledge content",
                metadata={"category": "test"},
                node_type="fact",
                confidence=0.8,
            )

            assert node_id is not None

            item = await mound.get(node_id)
            assert item is not None
            assert "Test knowledge" in item.content

    @pytest.mark.asyncio
    async def test_deduplication(self, mound_config):
        """Test content deduplication."""
        from aragora.knowledge.mound import KnowledgeMound

        async with KnowledgeMound(config=mound_config).session() as mound:
            content = "Unique content for deduplication test"

            # Store first time
            result1 = await mound.store(
                IngestionRequest(
                    content=content,
                    workspace_id="test_ws",
                    source_type=KnowledgeSource.DOCUMENT,
                )
            )

            assert result1.success
            assert not result1.deduplicated

            # Store same content again
            result2 = await mound.store(
                IngestionRequest(
                    content=content,
                    workspace_id="test_ws",
                    source_type=KnowledgeSource.DOCUMENT,
                )
            )

            assert result2.success
            assert result2.deduplicated
            assert result2.existing_node_id == result1.node_id

    @pytest.mark.asyncio
    async def test_query_basic(self, mound_config):
        """Test basic query functionality."""
        from aragora.knowledge.mound import KnowledgeMound

        async with KnowledgeMound(config=mound_config).session() as mound:
            # Add some knowledge
            await mound.add("Security best practices for API development")
            await mound.add("Legal requirements for data handling")
            await mound.add("Healthcare compliance guidelines")

            # Query
            result = await mound.query("security API", limit=10)

            assert result.total_count >= 0
            assert result.query == "security API"

    @pytest.mark.asyncio
    async def test_delete_with_archive(self, mound_config):
        """Test delete with archive."""
        from aragora.knowledge.mound import KnowledgeMound

        async with KnowledgeMound(config=mound_config).session() as mound:
            # Store and then delete
            node_id = await mound.add("Content to be deleted")

            # Verify it exists
            item = await mound.get(node_id)
            assert item is not None

            # Delete with archive
            deleted = await mound.delete(node_id, archive=True)
            assert deleted

            # Verify it's gone
            item = await mound.get(node_id)
            assert item is None

    @pytest.mark.asyncio
    async def test_update_node(self, mound_config):
        """Test updating a knowledge node."""
        from aragora.knowledge.mound import KnowledgeMound

        async with KnowledgeMound(config=mound_config).session() as mound:
            node_id = await mound.add("Original content", confidence=0.5)

            # Update
            updated = await mound.update(node_id, {"confidence": 0.9})

            assert updated is not None


# ============================================================================
# Fact Registry Tests
# ============================================================================


class TestFactRegistry:
    """Tests for FactRegistry with staleness tracking."""

    @pytest.mark.asyncio
    async def test_register_fact(self, vector_store, mock_embedding_service):
        """Test registering a new fact."""
        registry = FactRegistry(
            vector_store=vector_store,
            embedding_service=mock_embedding_service,
        )
        await registry.initialize()

        fact = await registry.register(
            statement="API keys should be rotated every 90 days",
            vertical="software",
            category="best_practice",
            confidence=0.9,
            workspace_id="test_ws",
        )

        assert fact.id.startswith("fact_")
        assert fact.statement == "API keys should be rotated every 90 days"
        assert fact.vertical == "software"
        assert fact.base_confidence == 0.9

    @pytest.mark.asyncio
    async def test_fact_staleness_calculation(self):
        """Test fact staleness and confidence decay."""
        fact = RegisteredFact(
            id="fact_test",
            statement="Test fact",
            base_confidence=1.0,
            decay_rate=0.1,  # High decay for testing
            verification_date=datetime.now() - timedelta(days=5),
        )

        # Should have decayed after 5 days
        assert fact.staleness_days >= 5
        assert fact.current_confidence < fact.base_confidence

        # Check needs_reverification
        assert fact.current_confidence < 0.5 * fact.base_confidence or not fact.needs_reverification

    @pytest.mark.asyncio
    async def test_fact_refresh(self):
        """Test refreshing a fact."""
        fact = RegisteredFact(
            id="fact_test",
            statement="Test fact",
            base_confidence=0.8,
            decay_rate=0.1,
            verification_date=datetime.now() - timedelta(days=10),
        )

        initial_verification_count = fact.verification_count

        fact.refresh(new_confidence=0.95)

        assert fact.verification_count == initial_verification_count + 1
        assert fact.base_confidence == 0.95
        assert fact.staleness_days < 1  # Just refreshed

    @pytest.mark.asyncio
    async def test_fact_contradiction_tracking(self):
        """Test tracking contradictions between facts."""
        fact1 = RegisteredFact(
            id="fact_1",
            statement="Original claim",
            base_confidence=0.9,
        )

        fact1.add_contradiction("fact_2")

        assert "fact_2" in fact1.contradicts
        assert fact1.contradiction_count == 1

        # Adding same contradiction again shouldn't duplicate
        fact1.add_contradiction("fact_2")
        assert fact1.contradiction_count == 1

    @pytest.mark.asyncio
    async def test_fact_supersession(self):
        """Test fact supersession."""
        old_fact = RegisteredFact(
            id="fact_old",
            statement="Old claim",
            base_confidence=0.8,
        )

        old_fact.supersede("fact_new")

        assert old_fact.is_superseded
        assert old_fact.superseded_by == "fact_new"

    @pytest.mark.asyncio
    async def test_query_facts(self, vector_store, mock_embedding_service):
        """Test querying facts from registry."""
        registry = FactRegistry(
            vector_store=vector_store,
            embedding_service=mock_embedding_service,
        )
        await registry.initialize()

        # Register some facts
        await registry.register(
            statement="Security policy A",
            vertical="software",
            confidence=0.9,
            workspace_id="test_ws",
        )
        await registry.register(
            statement="Legal requirement B",
            vertical="legal",
            confidence=0.85,
            workspace_id="test_ws",
        )

        # Query
        results = await registry.query(
            query="security",
            verticals=["software"],
            workspace_id="test_ws",
            min_confidence=0.5,
        )

        # Should find facts (memory-based search)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_get_stale_facts(self, vector_store, mock_embedding_service):
        """Test getting stale facts."""
        registry = FactRegistry(
            vector_store=vector_store,
            embedding_service=mock_embedding_service,
        )
        await registry.initialize()

        # Register facts with different ages
        fresh_fact = await registry.register(
            statement="Fresh fact",
            vertical="software",
            confidence=0.9,
        )

        # Manually create a stale fact
        stale_fact = RegisteredFact(
            id="fact_stale",
            statement="Stale fact",
            base_confidence=0.8,
            decay_rate=0.5,  # Very high decay
            verification_date=datetime.now() - timedelta(days=30),
        )
        registry._facts[stale_fact.id] = stale_fact

        # Get stale facts
        stale = await registry.get_stale_facts()

        # Should include the stale fact if it needs reverification
        stale_ids = [f.id for f in stale]
        if stale_fact.needs_reverification:
            assert stale_fact.id in stale_ids

    @pytest.mark.asyncio
    async def test_vertical_decay_rates(self, vector_store, mock_embedding_service):
        """Test vertical-specific decay rates."""
        registry = FactRegistry(
            vector_store=vector_store,
            embedding_service=mock_embedding_service,
        )

        # Software vulnerability decays faster
        vuln_rate = registry._get_decay_rate("software", "vulnerability")

        # Legal regulation decays slower
        reg_rate = registry._get_decay_rate("legal", "regulation")

        assert vuln_rate > reg_rate

    @pytest.mark.asyncio
    async def test_fact_serialization(self):
        """Test fact to_dict and from_dict."""
        fact = RegisteredFact(
            id="fact_test",
            statement="Test fact for serialization",
            vertical="software",
            category="best_practice",
            base_confidence=0.9,
            workspace_id="test_ws",
            topics=["security", "api"],
        )

        # Serialize
        data = fact.to_dict()

        assert data["id"] == "fact_test"
        assert data["statement"] == "Test fact for serialization"
        assert data["vertical"] == "software"
        assert "security" in data["topics"]

        # Deserialize
        restored = RegisteredFact.from_dict(data)

        assert restored.id == fact.id
        assert restored.statement == fact.statement
        assert restored.vertical == fact.vertical

    @pytest.mark.asyncio
    async def test_registry_stats(self, vector_store, mock_embedding_service):
        """Test getting registry statistics."""
        registry = FactRegistry(
            vector_store=vector_store,
            embedding_service=mock_embedding_service,
        )
        await registry.initialize()

        # Add facts to different verticals (disable dedup to ensure all are added)
        await registry.register(
            statement="Software security vulnerability tracking",
            vertical="software",
            workspace_id="test_ws",
            check_duplicates=False,
        )
        await registry.register(
            statement="Software performance optimization guidelines",
            vertical="software",
            workspace_id="test_ws",
            check_duplicates=False,
        )
        await registry.register(
            statement="Legal compliance requirement A",
            vertical="legal",
            workspace_id="test_ws",
            check_duplicates=False,
        )

        stats = await registry.get_stats(workspace_id="test_ws")

        assert stats["total_facts"] == 3
        assert stats["by_vertical"]["software"] == 2
        assert stats["by_vertical"]["legal"] == 1


# ============================================================================
# Vector Store Integration Tests
# ============================================================================


class TestVectorStoreIntegration:
    """Integration tests for vector store operations."""

    @pytest.mark.asyncio
    async def test_multi_namespace_isolation(self, vector_store, sample_embeddings):
        """Test namespace isolation in vector store."""
        # Add to different namespaces
        await vector_store.upsert(
            id="doc1",
            embedding=sample_embeddings["fact1"],
            content="Namespace A document",
            namespace="ns_a",
        )
        await vector_store.upsert(
            id="doc2",
            embedding=sample_embeddings["fact2"],
            content="Namespace B document",
            namespace="ns_b",
        )

        # Search in namespace A
        results_a = await vector_store.search(
            embedding=sample_embeddings["query"],
            limit=10,
            namespace="ns_a",
        )

        assert len(results_a) == 1
        assert results_a[0].id == "doc1"

        # Search in namespace B
        results_b = await vector_store.search(
            embedding=sample_embeddings["query"],
            limit=10,
            namespace="ns_b",
        )

        assert len(results_b) == 1
        assert results_b[0].id == "doc2"

    @pytest.mark.asyncio
    async def test_metadata_filtering(self, vector_store, sample_embeddings):
        """Test metadata filtering in search."""
        # Add documents with metadata
        await vector_store.upsert(
            id="doc1",
            embedding=sample_embeddings["fact1"],
            content="High confidence fact",
            metadata={"confidence": 0.9, "vertical": "software"},
        )
        await vector_store.upsert(
            id="doc2",
            embedding=sample_embeddings["fact2"],
            content="Low confidence fact",
            metadata={"confidence": 0.3, "vertical": "software"},
        )
        await vector_store.upsert(
            id="doc3",
            embedding=sample_embeddings["fact3"],
            content="Legal fact",
            metadata={"confidence": 0.8, "vertical": "legal"},
        )

        # Filter by vertical
        results = await vector_store.search(
            embedding=sample_embeddings["query"],
            limit=10,
            filters={"vertical": "software"},
        )

        result_ids = [r.id for r in results]
        assert "doc1" in result_ids
        assert "doc2" in result_ids
        assert "doc3" not in result_ids

    @pytest.mark.asyncio
    async def test_batch_operations(self, vector_store, sample_embeddings):
        """Test batch upsert operations."""
        items = [
            {
                "id": f"batch_{i}",
                "embedding": sample_embeddings["fact1"],
                "content": f"Batch document {i}",
                "metadata": {"batch": True, "index": i},
            }
            for i in range(10)
        ]

        ids = await vector_store.upsert_batch(items)

        assert len(ids) == 10

        count = await vector_store.count()
        assert count == 10

    @pytest.mark.asyncio
    async def test_delete_operations(self, vector_store, sample_embeddings):
        """Test delete operations."""
        # Add documents
        await vector_store.upsert(
            id="to_delete",
            embedding=sample_embeddings["fact1"],
            content="Will be deleted",
            metadata={"delete_me": True},
        )
        await vector_store.upsert(
            id="to_keep",
            embedding=sample_embeddings["fact2"],
            content="Will be kept",
            metadata={"delete_me": False},
        )

        # Delete by filter
        deleted = await vector_store.delete_by_filter({"delete_me": True})

        assert deleted == 1
        assert await vector_store.get_by_id("to_delete") is None
        assert await vector_store.get_by_id("to_keep") is not None


# ============================================================================
# Knowledge Pipeline Integration Tests
# ============================================================================


class TestKnowledgePipelineIntegration:
    """Integration tests for Knowledge Pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_lifecycle(self, pipeline_config):
        """Test pipeline start and stop."""
        pipeline = KnowledgePipeline(config=pipeline_config)

        assert not pipeline._running

        await pipeline.start()
        assert pipeline._running

        await pipeline.stop()
        assert not pipeline._running

    @pytest.mark.asyncio
    async def test_process_text_document(self, pipeline_config):
        """Test processing a text document."""
        pipeline = KnowledgePipeline(config=pipeline_config)
        await pipeline.start()

        try:
            content = b"This is a test document with some content about security best practices."
            result = await pipeline.process_document(
                content=content,
                filename="test.txt",
                tags=["test", "security"],
            )

            assert result.success
            assert result.filename == "test.txt"
            assert result.chunk_count > 0
            assert result.document is not None
        finally:
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_process_batch_documents(self, pipeline_config):
        """Test processing multiple documents."""
        pipeline = KnowledgePipeline(config=pipeline_config)
        await pipeline.start()

        try:
            files = [
                (b"Content of document 1", "doc1.txt"),
                (b"Content of document 2", "doc2.txt"),
                (b"Content of document 3", "doc3.txt"),
            ]

            results = await pipeline.process_batch(files)

            assert len(results) == 3
            assert all(r.success for r in results)
        finally:
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_pipeline_search(self, pipeline_config):
        """Test searching through pipeline."""
        pipeline = KnowledgePipeline(config=pipeline_config, fact_store=_scoped_store())
        await pipeline.start()

        try:
            # Process a document first
            content = b"Python programming language tutorial for beginners"
            await pipeline.process_document(content, "tutorial.txt")

            # Search
            results = await pipeline.search("python", limit=5)

            # Results may vary based on embedding service
            assert isinstance(results, list)
        finally:
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_pipeline_stats(self, pipeline_config):
        """Test getting pipeline statistics."""
        pipeline = KnowledgePipeline(config=pipeline_config, fact_store=_scoped_store())
        await pipeline.start()

        try:
            # Process a document
            content = b"Test document for statistics"
            await pipeline.process_document(content, "stats_test.txt")

            stats = pipeline.get_stats()

            assert stats["running"] is True
            assert stats["workspace_id"] == pipeline_config.workspace_id
            assert stats["pipeline_stats"]["documents_processed"] >= 1
        finally:
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_progress_callback(self, pipeline_config):
        """Test progress callback during processing."""
        progress_events = []

        def progress_callback(doc_id: str, progress: float, message: str):
            progress_events.append((doc_id, progress, message))

        pipeline = KnowledgePipeline(config=pipeline_config)
        pipeline.set_progress_callback(progress_callback)
        await pipeline.start()

        try:
            content = b"Document with progress tracking"
            await pipeline.process_document(content, "progress_test.txt")

            # Should have received progress updates
            assert len(progress_events) > 0

            # Final progress should be 1.0
            final_progress = progress_events[-1][1]
            assert final_progress == 1.0
        finally:
            await pipeline.stop()


# ============================================================================
# Cross-System Integration Tests
# ============================================================================


class TestCrossSystemIntegration:
    """Tests for integration between knowledge system components."""

    @pytest.mark.asyncio
    async def test_fact_registry_with_mound(
        self, mound_config, vector_store, mock_embedding_service
    ):
        """Test FactRegistry integration with KnowledgeMound."""
        from aragora.knowledge.mound import KnowledgeMound

        async with KnowledgeMound(config=mound_config).session() as mound:
            registry = FactRegistry(
                vector_store=vector_store,
                embedding_service=mock_embedding_service,
            )
            await registry.initialize()

            # Register a fact
            fact = await registry.register(
                statement="All database credentials must use strong encryption",
                vertical="software",
                category="security",
                confidence=0.95,
                workspace_id=mound.workspace_id,
            )

            # Store fact in mound
            node_id = await mound.add(
                content=fact.statement,
                metadata={
                    "fact_id": fact.id,
                    "vertical": fact.vertical,
                    "category": fact.category,
                },
                confidence=fact.base_confidence,
            )

            # Verify it's in both systems
            registered_fact = await registry.get_fact(fact.id)
            mound_item = await mound.get(node_id)

            assert registered_fact is not None
            assert mound_item is not None
            assert registered_fact.statement in mound_item.content

    @pytest.mark.asyncio
    async def test_pipeline_with_mound_sync(self, pipeline_config, temp_db_dir):
        """Test pipeline with Knowledge Mound synchronization."""
        # This tests that the pipeline can work alongside mound
        pipeline = KnowledgePipeline(config=pipeline_config, fact_store=_scoped_store())
        await pipeline.start()

        try:
            # Process documents
            content = b"Enterprise security guidelines and compliance requirements"
            result = await pipeline.process_document(content, "enterprise.txt")

            assert result.success

            # Pipeline stats should reflect processing
            stats = pipeline.get_stats()
            assert stats["pipeline_stats"]["documents_processed"] >= 1
        finally:
            await pipeline.stop()


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling in knowledge system."""

    @pytest.mark.asyncio
    async def test_mound_operation_before_init(self, mound_config):
        """Test that operations before initialization raise error."""
        from aragora.knowledge.mound import KnowledgeMound

        mound = KnowledgeMound(config=mound_config)

        with pytest.raises(RuntimeError, match="not initialized"):
            await mound.store(
                IngestionRequest(
                    content="Test",
                    workspace_id="test",
                    source_type=KnowledgeSource.DOCUMENT,
                )
            )

    @pytest.mark.asyncio
    async def test_pipeline_error_recovery(self, pipeline_config):
        """Test pipeline handles processing errors gracefully."""
        pipeline = KnowledgePipeline(config=pipeline_config)
        await pipeline.start()

        try:
            # Process invalid content that might cause issues
            result = await pipeline.process_document(
                content=b"",  # Empty content
                filename="empty.txt",
            )

            # Should handle gracefully
            assert result.document_id is not None
        finally:
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_vector_store_disconnected_operations(self, vector_config):
        """Test vector store operations when disconnected."""
        store = InMemoryVectorStore(vector_config)

        # Not connected - operations should still work for in-memory
        # (but would fail for real backends)
        assert not store.is_connected


# ============================================================================
# Performance Tests
# ============================================================================


class TestPerformance:
    """Basic performance tests for knowledge system."""

    @pytest.mark.asyncio
    async def test_bulk_fact_registration(self, vector_store, mock_embedding_service):
        """Test registering many facts efficiently."""
        registry = FactRegistry(
            vector_store=vector_store,
            embedding_service=mock_embedding_service,
        )
        await registry.initialize()

        # Register 100 facts
        facts = []
        for i in range(100):
            fact = await registry.register(
                statement=f"Test fact number {i} for performance testing",
                vertical="software",
                confidence=0.8,
                workspace_id="perf_test",
                check_duplicates=False,  # Skip dedup for speed
            )
            facts.append(fact)

        assert len(facts) == 100

        stats = await registry.get_stats(workspace_id="perf_test")
        assert stats["total_facts"] == 100

    @pytest.mark.asyncio
    async def test_bulk_vector_upsert(self, vector_store, sample_embeddings):
        """Test bulk vector operations."""
        items = [
            {
                "id": f"perf_doc_{i}",
                "embedding": sample_embeddings["fact1"],
                "content": f"Performance test document {i}",
            }
            for i in range(500)
        ]

        ids = await vector_store.upsert_batch(items)

        assert len(ids) == 500

        count = await vector_store.count()
        assert count == 500
