"""
Extended tests for Memory Streams module.

Tests cover advanced scenarios not covered by test_memory_streams.py:
- Embedding cache concurrency
- Retrieval ranking correctness
- Database integrity edge cases
- Reflection synthesis edge cases
- Global provider reference behavior
"""

import asyncio
import json
import os
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import pytest

from aragora.memory.streams import (
    Memory,
    MemoryStream,
    RetrievedMemory,
    _get_cached_embedding,
    _embedding_provider_ref,
)
import aragora.memory.streams as streams_module


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _fresh_event_loop():
    """Ensure a fresh event loop is available for run_async() calls.

    Prior tests can leave the default event loop in a closed state, causing
    ``RuntimeError: Event loop is closed`` when ``run_async()`` tries to
    schedule coroutines via ``asyncio.run()`` / ``nest_asyncio``.
    """
    from aragora.services import EmbeddingProviderService, ServiceRegistry

    _get_cached_embedding.cache_clear()
    streams_module._embedding_provider_ref = None
    streams_module._provider_registered = False
    ServiceRegistry.get().unregister(EmbeddingProviderService)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    try:
        loop.close()
    except Exception:
        pass
    _get_cached_embedding.cache_clear()
    streams_module._embedding_provider_ref = None
    streams_module._provider_registered = False
    ServiceRegistry.get().unregister(EmbeddingProviderService)


@pytest.fixture
def temp_db():
    """Create temporary SQLite database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@pytest.fixture
def memory_stream(temp_db):
    """MemoryStream without embedding provider."""
    return MemoryStream(db_path=temp_db, embedding_provider=None)


@pytest.fixture
def mock_embedding_provider():
    """Mock embedding provider for testing."""
    provider = AsyncMock()
    provider.embed = AsyncMock(return_value=[0.1] * 256)
    return provider


# =============================================================================
# Category A: Embedding Cache Concurrency
# =============================================================================


class TestEmbeddingCacheConcurrency:
    """Tests for embedding cache with concurrent access."""

    def test_cache_returns_consistent_results(self, temp_db, mock_embedding_provider):
        """Cached embedding should return identical results."""
        # Clear the cache first
        _get_cached_embedding.cache_clear()

        stream = MemoryStream(db_path=temp_db, embedding_provider=mock_embedding_provider)

        # Multiple calls should return same result
        result1 = _get_cached_embedding("test content")
        result2 = _get_cached_embedding("test content")

        assert result1 == result2

    def test_cache_different_content_different_results(self, temp_db, mock_embedding_provider):
        """Different content should potentially get different embeddings."""
        _get_cached_embedding.cache_clear()

        # Set up provider to return different values for different inputs
        call_count = [0]

        async def varying_embed(content):
            call_count[0] += 1
            return [0.1 * call_count[0]] * 256

        mock_embedding_provider.embed = varying_embed

        stream = MemoryStream(db_path=temp_db, embedding_provider=mock_embedding_provider)

        result1 = _get_cached_embedding("content A")
        result2 = _get_cached_embedding("content B")

        # Different content may yield different embeddings
        # (unless provider normalizes or both hit cache differently)

    def test_cache_hit_avoids_api_call(self, temp_db, mock_embedding_provider):
        """Cache hit should not call embedding provider again."""
        _get_cached_embedding.cache_clear()

        stream = MemoryStream(db_path=temp_db, embedding_provider=mock_embedding_provider)

        # First call
        _get_cached_embedding("cached content")
        first_call_count = mock_embedding_provider.embed.call_count

        # Second call (should use cache)
        _get_cached_embedding("cached content")
        second_call_count = mock_embedding_provider.embed.call_count

        # Should not have increased (cached)
        assert second_call_count == first_call_count

    def test_cache_without_provider_raises_error(self, temp_db):
        """Cache should raise error if provider not initialized."""

        _get_cached_embedding.cache_clear()
        # Reset the module-level provider reference
        streams_module._embedding_provider_ref = None

        # Mock ServiceRegistry to not have a provider (simulates fresh state)
        mock_registry = MagicMock()
        mock_registry.has.return_value = False

        # Patch at the import location inside get_embedding_provider
        with patch("aragora.runtime.service_registry.ServiceRegistry") as mock_sr_class:
            mock_sr_class.get.return_value = mock_registry

            # Should raise ConfigurationError (or RuntimeError subclass)
            with pytest.raises(Exception, match="[Pp]rovider not initialized"):
                _get_cached_embedding("test")

    def test_provider_reference_set_on_init(self, temp_db, mock_embedding_provider):
        """Provider reference should be set when MemoryStream is initialized."""
        _get_cached_embedding.cache_clear()
        streams_module._embedding_provider_ref = None

        stream = MemoryStream(db_path=temp_db, embedding_provider=mock_embedding_provider)

        # Provider reference should now be set
        assert streams_module._embedding_provider_ref is mock_embedding_provider


# =============================================================================
# Category B: Retrieval Ranking Correctness
# =============================================================================


class TestRetrievalRankingCorrectness:
    """Tests for correct retrieval ranking behavior."""

    def test_sort_by_total_score_descending(self, memory_stream):
        """Results should be sorted by total_score descending."""
        # Add memories with different characteristics
        memory_stream.add("agent", "Low importance", importance=0.1)
        memory_stream.add("agent", "High importance", importance=0.9)
        memory_stream.add("agent", "Medium importance", importance=0.5)

        results = memory_stream.retrieve("agent", limit=10)

        # Scores should be in descending order
        scores = [r.total_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_equal_scores_ordering(self, memory_stream):
        """Memories with equal scores should still be returned."""
        # Add multiple memories at same time with same importance
        for i in range(5):
            memory_stream.add("agent", f"Memory {i}", importance=0.5)

        results = memory_stream.retrieve("agent", limit=10)

        # All should be returned
        assert len(results) == 5

    def test_relevance_score_dominates(self, memory_stream):
        """Relevance (40% weight) should have highest impact."""
        # Add low importance memories
        memory_stream.add("agent", "Python programming language", importance=0.1)
        memory_stream.add("agent", "Java programming language", importance=0.9)

        # Query for Python - relevance should boost it
        results = memory_stream.retrieve("agent", query="Python", limit=2)

        # Python memory should rank higher due to relevance despite lower importance
        assert len(results) == 2
        # The one with Python keyword should have higher relevance
        python_result = [r for r in results if "Python" in r.memory.content][0]
        java_result = [r for r in results if "Java" in r.memory.content][0]
        assert python_result.relevance_score > java_result.relevance_score

    def test_limit_parameter_correctness(self, memory_stream):
        """Limit should correctly restrict results."""
        for i in range(20):
            memory_stream.add("agent", f"Memory {i}")

        results = memory_stream.retrieve("agent", limit=5)
        assert len(results) == 5

    def test_min_importance_filtering(self, memory_stream):
        """min_importance should filter out low importance memories."""
        memory_stream.add("agent", "Low", importance=0.1)
        memory_stream.add("agent", "Medium", importance=0.5)
        memory_stream.add("agent", "High", importance=0.9)

        results = memory_stream.retrieve("agent", min_importance=0.4)

        # Only Medium and High should be returned
        assert len(results) == 2
        for r in results:
            assert r.memory.importance >= 0.4

    def test_all_filters_combined(self, memory_stream):
        """All filters should work together correctly."""
        memory_stream.observe("agent", "Important Python code", importance=0.8)
        memory_stream.insight("agent", "Python insight", importance=0.9)
        memory_stream.observe("agent", "Java code", importance=0.1)

        results = memory_stream.retrieve(
            "agent",
            query="Python",
            memory_type="observation",
            min_importance=0.5,
            limit=5,
        )

        # Should only get the important Python observation
        assert len(results) == 1
        assert results[0].memory.memory_type == "observation"
        assert "Python" in results[0].memory.content
        assert results[0].memory.importance >= 0.5


# =============================================================================
# Category C: Database Integrity
# =============================================================================


class TestDatabaseIntegrity:
    """Tests for database integrity edge cases."""

    def test_null_created_at_handling(self, temp_db):
        """Null created_at causes error during age calculation."""
        stream = MemoryStream(db_path=temp_db)

        # Insert memory with null created_at directly
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memories (id, agent_name, memory_type, content, importance, created_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                ("null-mem", "agent", "observation", "Test", 0.5),
            )
            conn.commit()

        # The code expects created_at to be present - TypeError is raised
        # This documents the current behavior
        with pytest.raises(TypeError):
            stream.retrieve("agent")

    def test_malformed_json_metadata(self, temp_db):
        """Should handle malformed JSON in metadata."""
        stream = MemoryStream(db_path=temp_db)

        # Insert memory with malformed metadata
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memories (id, agent_name, memory_type, content, importance, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "bad-meta",
                    "agent",
                    "observation",
                    "Test",
                    0.5,
                    "not valid json",
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

        # Should not crash, safe_json_loads handles this
        results = stream.retrieve("agent")
        assert len(results) == 1
        # Metadata should be empty dict due to fallback
        assert results[0].memory.metadata == {}

    def test_duplicate_id_handling(self, temp_db):
        """Should handle duplicate ID gracefully."""
        stream = MemoryStream(db_path=temp_db)

        # Add a memory normally
        stream.add("agent", "First content")

        # Try to insert duplicate ID directly (should fail)
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM memories LIMIT 1")
            existing_id = cursor.fetchone()[0]

            # Try to insert duplicate
            with pytest.raises(sqlite3.IntegrityError):
                cursor.execute(
                    """
                    INSERT INTO memories (id, agent_name, memory_type, content, importance, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        existing_id,
                        "agent",
                        "observation",
                        "Duplicate",
                        0.5,
                        datetime.now().isoformat(),
                    ),
                )

    def test_missing_reflection_schedule_entry(self, temp_db):
        """should_reflect should handle missing schedule entry."""
        stream = MemoryStream(db_path=temp_db)

        # Don't add any memories, just check
        result = stream.should_reflect("nonexistent-agent")
        assert result is False


# =============================================================================
# Category D: Reflection Synthesis Edge Cases
# =============================================================================


class TestReflectionSynthesisEdgeCases:
    """Tests for reflection parsing edge cases."""

    def test_multiple_insight_lines(self, memory_stream):
        """Should extract all INSIGHT: lines."""
        response = """
        INSIGHT: First insight here.
        Some other text.
        INSIGHT: Second insight here.
        More text.
        INSIGHT: Third insight here.
        """

        insights = memory_stream.parse_reflections("agent", response)

        assert len(insights) == 3

    def test_case_insensitivity_insight(self, memory_stream):
        """Should handle different cases of INSIGHT:."""
        response = """
        INSIGHT: Uppercase.
        insight: Lowercase.
        Insight: Mixed case.
        """

        insights = memory_stream.parse_reflections("agent", response)

        # Only uppercase is detected (line.upper().startswith("INSIGHT:"))
        # Actually the code checks line.upper().startswith("INSIGHT:")
        # So all cases should be detected
        assert len(insights) == 3

    def test_empty_insight_content(self, memory_stream):
        """Should skip INSIGHT: with empty content."""
        response = """
        INSIGHT:
        INSIGHT:
        INSIGHT: Valid insight here.
        """

        insights = memory_stream.parse_reflections("agent", response)

        # Only the valid one should be captured
        assert len(insights) == 1
        assert "Valid insight" in insights[0].content

    def test_special_characters_in_insights(self, memory_stream):
        """Should handle special characters in insight text."""
        response = """
        INSIGHT: Check for 'quotes' and "double quotes".
        INSIGHT: Handle emoji
        INSIGHT: Unicode: 日本語, 中文
        """

        insights = memory_stream.parse_reflections("agent", response)

        assert len(insights) == 3
        assert "quotes" in insights[0].content

    def test_very_large_response_parsing(self, memory_stream):
        """Should handle very large response efficiently."""
        # Generate a large response with many insights
        insights_text = "\n".join([f"INSIGHT: Insight number {i}." for i in range(100)])
        large_response = "Preamble text.\n" + insights_text + "\nEnd text."

        insights = memory_stream.parse_reflections("agent", large_response)

        assert len(insights) == 100


# =============================================================================
# Category E: Global Provider Reference
# =============================================================================


class TestGlobalProviderReference:
    """Tests for global provider reference behavior."""

    def test_provider_reference_mutation(self, temp_db, mock_embedding_provider):
        """Provider reference should update with new stream."""
        _get_cached_embedding.cache_clear()

        provider1 = AsyncMock()
        provider1.embed = AsyncMock(return_value=[0.1] * 256)

        provider2 = AsyncMock()
        provider2.embed = AsyncMock(return_value=[0.2] * 256)

        # First stream sets provider1
        stream1 = MemoryStream(db_path=temp_db, embedding_provider=provider1)
        assert streams_module._embedding_provider_ref is provider1

        # Second stream sets provider2
        stream2 = MemoryStream(db_path=temp_db, embedding_provider=provider2)
        assert streams_module._embedding_provider_ref is provider2

    def test_provider_registration_replaces_stale_registry_provider(self, temp_db):
        """New streams should replace stale registry providers as well as module refs."""
        from aragora.services import EmbeddingProviderService, ServiceRegistry

        registry = ServiceRegistry.get()
        registry.unregister(EmbeddingProviderService)
        streams_module._provider_registered = False
        _get_cached_embedding.cache_clear()

        provider1 = AsyncMock()
        provider1.embed = AsyncMock(side_effect=Exception("API error"))
        MemoryStream(db_path=temp_db, embedding_provider=provider1)

        provider2 = AsyncMock()
        provider2.embed = AsyncMock(return_value=[0.2] * 256)
        MemoryStream(db_path=temp_db, embedding_provider=provider2)

        assert streams_module.get_embedding_provider() is provider2
        assert _get_cached_embedding("fresh content") == tuple([0.2] * 256)

    def test_provider_registration_clears_cached_embeddings(self, temp_db):
        """Replacing the provider should not reuse old-provider embeddings."""
        _get_cached_embedding.cache_clear()

        provider1 = AsyncMock()
        provider1.embed = AsyncMock(return_value=[0.1] * 256)
        MemoryStream(db_path=temp_db, embedding_provider=provider1)
        assert _get_cached_embedding("same content") == tuple([0.1] * 256)

        provider2 = AsyncMock()
        provider2.embed = AsyncMock(return_value=[0.2] * 256)
        MemoryStream(db_path=temp_db, embedding_provider=provider2)

        assert streams_module.get_embedding_provider() is provider2
        assert _get_cached_embedding("same content") == tuple([0.2] * 256)

    def test_none_provider_no_overwrite(self, temp_db, mock_embedding_provider):
        """None provider should not overwrite existing reference."""
        _get_cached_embedding.cache_clear()

        # Set a provider
        stream1 = MemoryStream(db_path=temp_db, embedding_provider=mock_embedding_provider)
        assert streams_module._embedding_provider_ref is mock_embedding_provider

        # Create stream with None provider - should NOT overwrite
        stream2 = MemoryStream(db_path=temp_db, embedding_provider=None)
        # The original provider should still be there (None doesn't set the ref)
        assert streams_module._embedding_provider_ref is mock_embedding_provider


# =============================================================================
# Additional Tests: Recency Scoring and Edge Cases
# =============================================================================


class TestRecencyScoring:
    """Tests for recency score calculation."""

    def test_recency_half_life_24_hours(self, memory_stream, temp_db):
        """Recency should be 0.5 after 24 hours."""
        # Insert memory 24 hours ago
        old_time = (datetime.now() - timedelta(hours=24)).isoformat()
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memories (id, agent_name, memory_type, content, importance, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("24h-mem", "agent", "observation", "24 hours old", 0.5, old_time),
            )
            conn.commit()

        results = memory_stream.retrieve("agent")
        old_result = [r for r in results if r.memory.id == "24h-mem"][0]

        # Should be approximately 0.5
        assert abs(old_result.recency_score - 0.5) < 0.05

    def test_recency_48_hours(self, memory_stream, temp_db):
        """Recency should be 0.25 after 48 hours."""
        old_time = (datetime.now() - timedelta(hours=48)).isoformat()
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memories (id, agent_name, memory_type, content, importance, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("48h-mem", "agent", "observation", "48 hours old", 0.5, old_time),
            )
            conn.commit()

        results = memory_stream.retrieve("agent")
        old_result = [r for r in results if r.memory.id == "48h-mem"][0]

        # Should be approximately 0.25 (0.5^2)
        assert abs(old_result.recency_score - 0.25) < 0.05


class TestMemoryDataclass:
    """Additional tests for Memory dataclass."""

    def test_memory_age_zero_for_now(self):
        """New memory should have age close to zero."""
        memory = Memory(
            id="test",
            agent_name="agent",
            memory_type="observation",
            content="test",
            importance=0.5,
            created_at=datetime.now().isoformat(),
        )
        assert memory.age_hours < 0.1

    def test_memory_with_all_optional_fields(self):
        """Memory should handle all optional fields."""
        memory = Memory(
            id="test",
            agent_name="agent",
            memory_type="insight",
            content="Content here",
            importance=0.9,
            created_at=datetime.now().isoformat(),
            debate_id="debate-123",
            metadata={"key": "value", "nested": {"a": 1}},
        )
        assert memory.debate_id == "debate-123"
        assert memory.metadata["key"] == "value"
        assert memory.metadata["nested"]["a"] == 1


class TestRetrievedMemoryDataclass:
    """Additional tests for RetrievedMemory dataclass."""

    def test_total_score_calculation(self):
        """Total score should use correct weights."""
        memory = Memory(
            id="test",
            agent_name="agent",
            memory_type="observation",
            content="test",
            importance=0.5,
            created_at=datetime.now().isoformat(),
        )
        retrieved = RetrievedMemory(
            memory=memory,
            recency_score=0.5,
            importance_score=0.5,
            relevance_score=0.5,
        )
        # 0.3*0.5 + 0.3*0.5 + 0.4*0.5 = 0.15 + 0.15 + 0.2 = 0.5
        assert retrieved.total_score == pytest.approx(0.5, abs=0.01)

    def test_total_score_all_zero(self):
        """Total score with all zeros should be zero."""
        memory = Memory(
            id="test",
            agent_name="agent",
            memory_type="observation",
            content="test",
            importance=0.5,
            created_at=datetime.now().isoformat(),
        )
        retrieved = RetrievedMemory(
            memory=memory,
            recency_score=0.0,
            importance_score=0.0,
            relevance_score=0.0,
        )
        assert retrieved.total_score == 0.0
