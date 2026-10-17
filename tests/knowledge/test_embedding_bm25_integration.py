"""
Tests for BM25 integration in InMemoryEmbeddingService.

Verifies that the embedding service properly uses BM25 for hybrid search
instead of naive keyword matching.
"""

import pytest
from aragora.knowledge.embeddings import InMemoryEmbeddingService, ChunkMatch


class TestInMemoryEmbeddingServiceBM25:
    """Tests for BM25 integration in InMemoryEmbeddingService."""

    @pytest.fixture
    def service(self):
        """Create a fresh embedding service."""
        return InMemoryEmbeddingService()

    @pytest.fixture
    async def service_with_data(self, service):
        """Create service with test documents."""
        chunks = [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "content": "Python is a programming language used for web development",
            },
            {
                "chunk_id": "chunk-2",
                "document_id": "doc-1",
                "content": "JavaScript is popular for frontend web development",
            },
            {
                "chunk_id": "chunk-3",
                "document_id": "doc-2",
                "content": "Machine learning with Python and TensorFlow",
            },
            {
                "chunk_id": "chunk-4",
                "document_id": "doc-2",
                "content": "Data science involves statistics and programming",
            },
        ]
        await service.embed_chunks(chunks, "workspace-1")
        return service

    @pytest.mark.asyncio
    async def test_bm25_index_created_on_embed(self, service):
        """BM25 index is created when chunks are embedded."""
        chunks = [{"chunk_id": "c1", "content": "test content"}]
        await service.embed_chunks(chunks, "ws-1")

        assert "ws-1" in service._bm25_indices
        index = service._bm25_indices["ws-1"]
        assert index._total_docs == 1

    @pytest.mark.asyncio
    async def test_hybrid_search_returns_bm25_scored_results(self, service_with_data):
        """Hybrid search uses BM25 scoring."""
        results = await service_with_data.hybrid_search(
            query="Python programming",
            workspace_id="workspace-1",
            limit=10,
        )

        assert len(results) > 0
        # Results should be ChunkMatch instances
        assert all(isinstance(r, ChunkMatch) for r in results)
        # Python chunks should rank higher
        top_result = results[0]
        assert "python" in top_result.content.lower()

    @pytest.mark.asyncio
    async def test_alpha_parameter_affects_results(self, service_with_data):
        """Alpha parameter changes the balance between BM25 and keyword matching."""
        # Pure BM25 (alpha=0 means more weight on BM25 in HybridSearcher)
        results_bm25 = await service_with_data.hybrid_search(
            query="Python",
            workspace_id="workspace-1",
            alpha=0.0,
            limit=10,
        )

        # Pure keyword (alpha=1 means more weight on keyword in HybridSearcher)
        results_kw = await service_with_data.hybrid_search(
            query="Python",
            workspace_id="workspace-1",
            alpha=1.0,
            limit=10,
        )

        # Both should return results
        assert len(results_bm25) > 0
        assert len(results_kw) > 0

    @pytest.mark.asyncio
    async def test_workspace_isolation(self, service):
        """Each workspace has separate BM25 indices."""
        await service.embed_chunks([{"chunk_id": "c1", "content": "Python programming"}], "ws-1")
        await service.embed_chunks([{"chunk_id": "c2", "content": "JavaScript coding"}], "ws-2")

        # Search in ws-1 should only find Python
        results_1 = await service.hybrid_search("Python", "ws-1", limit=10)
        assert len(results_1) == 1
        assert results_1[0].chunk_id == "c1"

        # Search in ws-2 should only find JavaScript
        results_2 = await service.hybrid_search("JavaScript", "ws-2", limit=10)
        assert len(results_2) == 1
        assert results_2[0].chunk_id == "c2"

        # Cross-workspace search should not find results
        results_cross = await service.hybrid_search("Python", "ws-2", limit=10)
        assert len(results_cross) == 0

    @pytest.mark.asyncio
    async def test_delete_workspace_removes_bm25_index(self, service_with_data):
        """Deleting workspace also removes BM25 index."""
        assert "workspace-1" in service_with_data._bm25_indices

        await service_with_data.delete_workspace_chunks("workspace-1")

        assert "workspace-1" not in service_with_data._bm25_indices

    @pytest.mark.asyncio
    async def test_delete_document_updates_bm25_index(self, service_with_data):
        """Deleting document removes chunks from BM25 index."""
        index = service_with_data._bm25_indices["workspace-1"]
        initial_count = index._total_docs

        await service_with_data.delete_document_chunks("doc-1", "workspace-1")

        # Two chunks from doc-1 should be removed
        assert index._total_docs == initial_count - 2

    @pytest.mark.asyncio
    async def test_min_score_filters_results(self, service_with_data):
        """Min score parameter filters low-scoring results."""
        # High min_score should filter out weak matches
        results = await service_with_data.hybrid_search(
            query="Python",
            workspace_id="workspace-1",
            min_score=0.9,  # Very high threshold
            limit=10,
        )

        # All results should meet the threshold
        assert all(r.score >= 0.9 for r in results)

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, service_with_data):
        """Empty query returns empty results."""
        results = await service_with_data.hybrid_search(
            query="",
            workspace_id="workspace-1",
            limit=10,
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty(self, service_with_data):
        """Query with no matches returns empty list."""
        results = await service_with_data.hybrid_search(
            query="xyznonexistent",
            workspace_id="workspace-1",
            limit=10,
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_bm25_improves_relevance(self, service):
        """BM25 scoring improves relevance over naive keyword matching."""
        # Create documents where BM25 IDF weighting matters
        chunks = [
            {"chunk_id": "c1", "content": "the the the the python"},  # Lots of stopwords
            {"chunk_id": "c2", "content": "python programming language"},  # Focused
            {"chunk_id": "c3", "content": "the quick brown fox"},  # No python
        ]
        await service.embed_chunks(chunks, "ws-1")

        results = await service.hybrid_search("python", "ws-1", limit=10)

        # Both Python documents should be found
        result_ids = [r.chunk_id for r in results]
        assert "c1" in result_ids
        assert "c2" in result_ids
        assert "c3" not in result_ids

    @pytest.mark.asyncio
    async def test_limit_parameter_works(self, service_with_data):
        """Limit parameter restricts number of results."""
        results = await service_with_data.hybrid_search(
            query="programming development",
            workspace_id="workspace-1",
            limit=2,
        )
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_result_has_correct_fields(self, service_with_data):
        """Results have all required ChunkMatch fields."""
        results = await service_with_data.hybrid_search(
            query="Python",
            workspace_id="workspace-1",
            limit=1,
        )

        assert len(results) == 1
        result = results[0]

        assert result.chunk_id is not None
        assert result.workspace_id == "workspace-1"
        assert result.content is not None
        assert isinstance(result.score, float)
        assert result.score >= 0
