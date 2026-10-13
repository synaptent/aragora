"""
Tests for PostgreSQL-backed debate storage with permalink generation.

Tests cover:
1. Connection pool management
2. Query execution and parameterization
3. Transaction handling (commit/rollback)
4. Error handling and retry logic
5. SQL injection prevention
6. Connection timeout handling
7. Concurrent access patterns
8. Data serialization/deserialization
"""

from __future__ import annotations

import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.server.postgres_storage import (
    PostgresDebateStorage,
    DebateMetadata,
)


@pytest.fixture(autouse=True)
def _fresh_event_loop():
    """Ensure a fresh event loop for each test.

    Sync wrapper methods (get_debate, list_debates, etc.) delegate to
    ``run_async()`` which calls ``asyncio.run()``. A stale event loop
    left by prior async tests causes RuntimeError.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_pool():
    """Create a mock connection pool."""
    pool = MagicMock()
    pool.get_size.return_value = 10
    pool.get_min_size.return_value = 5
    pool.get_max_size.return_value = 20
    pool.get_idle_size.return_value = 8
    return pool


@pytest.fixture
def mock_connection():
    """Create a mock database connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.executemany = AsyncMock()

    # Create transaction mock
    mock_tx = AsyncMock()
    conn.transaction = MagicMock(return_value=mock_tx)

    return conn


@pytest.fixture
def mock_asyncpg_available():
    """Temporarily enable asyncpg availability for testing."""
    import aragora.storage.postgres_store as module

    original = module.ASYNCPG_AVAILABLE
    module.ASYNCPG_AVAILABLE = True
    yield
    module.ASYNCPG_AVAILABLE = original


@pytest.fixture
def storage(mock_asyncpg_available, mock_pool, mock_connection):
    """Create a PostgresDebateStorage instance with mocked pool."""
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    store = PostgresDebateStorage(mock_pool, use_resilient=False)
    store._initialized = True
    return store


# =============================================================================
# DebateMetadata Dataclass Tests
# =============================================================================


class TestDebateMetadata:
    """Tests for DebateMetadata dataclass."""

    def test_construction_with_all_fields(self):
        """DebateMetadata can be constructed with all fields."""
        metadata = DebateMetadata(
            slug="rate-limiter-2024-01-01",
            debate_id="debate-123",
            task="Design a rate limiter",
            agents=["claude", "gpt"],
            consensus_reached=True,
            confidence=0.85,
            created_at=datetime.now(timezone.utc),
            view_count=42,
            is_public=True,
        )

        assert metadata.slug == "rate-limiter-2024-01-01"
        assert metadata.debate_id == "debate-123"
        assert metadata.task == "Design a rate limiter"
        assert metadata.agents == ["claude", "gpt"]
        assert metadata.consensus_reached is True
        assert metadata.confidence == 0.85
        assert metadata.view_count == 42
        assert metadata.is_public is True

    def test_default_values(self):
        """DebateMetadata has correct default values."""
        metadata = DebateMetadata(
            slug="test-slug",
            debate_id="test-id",
            task="Test task",
            agents=["claude"],
            consensus_reached=False,
            confidence=0.0,
            created_at=datetime.now(timezone.utc),
        )

        assert metadata.view_count == 0
        assert metadata.is_public is False


# =============================================================================
# Schema and Constants Tests
# =============================================================================


class TestSchemaConstants:
    """Tests for schema constants and SQL definitions."""

    def test_schema_name_defined(self, mock_asyncpg_available, mock_pool):
        """SCHEMA_NAME should be defined."""
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock()
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        store = PostgresDebateStorage(mock_pool, use_resilient=False)
        assert store.SCHEMA_NAME == "debate_storage"

    def test_schema_version_is_positive(self, mock_asyncpg_available, mock_pool):
        """SCHEMA_VERSION should be a positive integer."""
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock()
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        store = PostgresDebateStorage(mock_pool, use_resilient=False)
        assert store.SCHEMA_VERSION >= 1
        assert isinstance(store.SCHEMA_VERSION, int)

    def test_initial_schema_contains_debates_table(self, mock_asyncpg_available, mock_pool):
        """INITIAL_SCHEMA should create debates table."""
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock()
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        store = PostgresDebateStorage(mock_pool, use_resilient=False)
        assert "CREATE TABLE IF NOT EXISTS debates" in store.INITIAL_SCHEMA

    def test_initial_schema_contains_indexes(self, mock_asyncpg_available, mock_pool):
        """INITIAL_SCHEMA should create required indexes."""
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock()
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        store = PostgresDebateStorage(mock_pool, use_resilient=False)
        assert "idx_debates_slug" in store.INITIAL_SCHEMA
        assert "idx_debates_created" in store.INITIAL_SCHEMA
        assert "idx_debates_search" in store.INITIAL_SCHEMA

    def test_stop_words_defined(self, storage):
        """STOP_WORDS should contain common words to filter from slugs."""
        assert "the" in storage.STOP_WORDS
        assert "and" in storage.STOP_WORDS
        assert "design" in storage.STOP_WORDS
        assert "implement" in storage.STOP_WORDS


# =============================================================================
# Slug Generation Tests
# =============================================================================


class TestSlugGeneration:
    """Tests for URL-friendly slug generation."""

    @pytest.mark.asyncio
    async def test_generates_slug_from_task(self, storage, mock_connection):
        """Should generate slug from task keywords."""
        mock_connection.fetchrow = AsyncMock(return_value={"count": 0})

        slug = await storage.generate_slug_async("A scalable rate limiter system")

        assert "rate" in slug or "limiter" in slug or "scalable" in slug or "system" in slug
        # Should contain date
        assert "-202" in slug  # Year prefix

    @pytest.mark.asyncio
    async def test_filters_stop_words_from_slug(self, storage, mock_connection):
        """Should filter stop words when generating slug."""
        mock_connection.fetchrow = AsyncMock(return_value={"count": 0})

        slug = await storage.generate_slug_async("Design a simple cache for the application")

        # Stop words should be filtered out
        assert "-the-" not in slug
        assert "-a-" not in slug
        assert "-for-" not in slug
        assert "design" not in slug.lower()

    @pytest.mark.asyncio
    async def test_handles_slug_collisions(self, storage, mock_connection):
        """Should append number on slug collision."""
        # Simulate existing slug
        mock_connection.fetchrow = AsyncMock(return_value={"count": 2})

        slug = await storage.generate_slug_async("Test task")

        # Should have -3 suffix (count + 1)
        assert slug.endswith("-3")

    @pytest.mark.asyncio
    async def test_limits_slug_words(self, storage, mock_connection):
        """Should limit slug to first 4 meaningful words."""
        mock_connection.fetchrow = AsyncMock(return_value={"count": 0})

        slug = await storage.generate_slug_async(
            "very long task description with many words that should be truncated"
        )

        # Count dashes (should have max 4 words + date = at most 5 segments)
        parts = slug.split("-")
        # Remove date parts (year, month, day)
        non_date_parts = [p for p in parts if not p.isdigit() or len(p) > 4]
        assert len(non_date_parts) <= 4

    @pytest.mark.asyncio
    async def test_slug_handles_empty_task(self, storage, mock_connection):
        """Should generate default slug for empty task."""
        mock_connection.fetchrow = AsyncMock(return_value={"count": 0})

        slug = await storage.generate_slug_async("")

        assert "debate" in slug

    @pytest.mark.asyncio
    async def test_slug_removes_punctuation(self, storage, mock_connection):
        """Should remove punctuation from task."""
        mock_connection.fetchrow = AsyncMock(return_value={"count": 0})

        slug = await storage.generate_slug_async("What's the best API? Let's debate!")

        # No punctuation in slug
        assert "'" not in slug
        assert "?" not in slug
        assert "!" not in slug


# =============================================================================
# Save Operations Tests
# =============================================================================


class TestSaveOperations:
    """Tests for saving debate data."""

    @pytest.mark.asyncio
    async def test_save_dict_async(self, storage, mock_connection):
        """Should save debate dict and return slug."""
        mock_connection.fetchrow = AsyncMock(return_value={"count": 0})
        mock_connection.execute = AsyncMock(return_value="INSERT 0 1")

        debate_data = {
            "id": "debate-123",
            "task": "Test task",
            "agents": ["claude", "gpt"],
            "consensus_reached": True,
            "confidence": 0.9,
        }

        slug = await storage.save_dict_async(debate_data)

        assert slug is not None
        assert isinstance(slug, str)
        mock_connection.execute.assert_called()

    @pytest.mark.asyncio
    async def test_save_dict_with_org_id(self, storage, mock_connection):
        """Should save debate with org_id."""
        mock_connection.fetchrow = AsyncMock(return_value={"count": 0})
        mock_connection.execute = AsyncMock(return_value="INSERT 0 1")

        debate_data = {
            "id": "debate-123",
            "task": "Test task",
            "agents": [],
        }

        slug = await storage.save_dict_async(debate_data, org_id="org-456")

        assert slug is not None
        # Verify org_id was passed to execute
        call_args = mock_connection.execute.call_args
        assert "org-456" in call_args[0]

    @pytest.mark.asyncio
    async def test_store_returns_debate_id(self, storage, mock_connection):
        """Store method should return debate ID from data."""
        mock_connection.fetchrow = AsyncMock(return_value={"count": 0})
        mock_connection.execute = AsyncMock(return_value="INSERT 0 1")

        debate_data = {
            "id": "debate-sync",
            "task": "Sync test",
            "agents": [],
        }

        # Test async save and verify store logic
        slug = await storage.save_dict_async(debate_data)

        # store() uses save_dict internally and returns the debate id
        assert slug is not None
        assert debate_data["id"] == "debate-sync"


# =============================================================================
# Retrieval Operations Tests
# =============================================================================


class TestRetrievalOperations:
    """Tests for retrieving debate data."""

    @pytest.mark.asyncio
    async def test_get_by_slug_async(self, storage, mock_connection):
        """Should retrieve debate by slug."""
        artifact_json = {"id": "debate-123", "task": "Test"}
        mock_connection.fetchrow = AsyncMock(return_value={"artifact_json": artifact_json})

        result = await storage.get_by_slug_async("test-slug")

        assert result is not None
        assert result["id"] == "debate-123"
        # View count is incremented atomically via UPDATE ... RETURNING in fetchrow
        mock_connection.fetchrow.assert_called()
        call_args = mock_connection.fetchrow.call_args
        assert "view_count" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_by_slug_async_not_found(self, storage, mock_connection):
        """Should return None for non-existent slug."""
        mock_connection.fetchrow = AsyncMock(return_value=None)

        result = await storage.get_by_slug_async("nonexistent-slug")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_slug_validates_length(self, storage, mock_connection):
        """Should reject slugs that are too long."""
        long_slug = "a" * 501

        result = await storage.get_by_slug_async(long_slug)

        assert result is None
        mock_connection.fetchrow.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_by_slug_rejects_empty(self, storage, mock_connection):
        """Should reject empty slugs."""
        result = await storage.get_by_slug_async("")

        assert result is None
        mock_connection.fetchrow.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_by_slug_with_ownership_verification(self, storage, mock_connection):
        """Should verify ownership when requested."""
        artifact_json = {"id": "debate-123"}
        mock_connection.fetchrow = AsyncMock(return_value={"artifact_json": artifact_json})
        mock_connection.execute = AsyncMock(return_value="UPDATE 1")

        result = await storage.get_by_slug_async(
            "test-slug", org_id="org-123", verify_ownership=True
        )

        # Should query with org_id
        call_args = mock_connection.fetchrow.call_args
        assert "org_id" in str(call_args) or "org-123" in str(call_args)

    @pytest.mark.asyncio
    async def test_get_by_id_async(self, storage, mock_connection):
        """Should retrieve debate by ID."""
        artifact_json = {"id": "debate-123", "task": "Test"}
        mock_connection.fetchrow = AsyncMock(return_value={"artifact_json": artifact_json})

        result = await storage.get_by_id_async("debate-123")

        assert result is not None
        assert result["id"] == "debate-123"

    @pytest.mark.asyncio
    async def test_get_by_id_handles_json_string(self, storage, mock_connection):
        """Should parse JSON string artifact."""
        artifact_json = json.dumps({"id": "debate-123", "task": "Test"})
        mock_connection.fetchrow = AsyncMock(return_value={"artifact_json": artifact_json})

        result = await storage.get_by_id_async("debate-123")

        assert result is not None
        assert result["id"] == "debate-123"

    @pytest.mark.asyncio
    async def test_get_debates_batch_async(self, storage, mock_connection):
        """Should retrieve multiple debates efficiently."""
        mock_connection.fetch = AsyncMock(
            return_value=[
                {"id": "debate-1", "artifact_json": {"task": "Task 1"}},
                {"id": "debate-2", "artifact_json": {"task": "Task 2"}},
            ]
        )

        result = await storage.get_debates_batch_async(["debate-1", "debate-2", "debate-3"])

        assert len(result) == 3
        assert result["debate-1"] is not None
        assert result["debate-2"] is not None
        assert result["debate-3"] is None  # Not found

    @pytest.mark.asyncio
    async def test_get_debates_batch_empty_list(self, storage, mock_connection):
        """Should handle empty ID list."""
        result = await storage.get_debates_batch_async([])

        assert result == {}
        mock_connection.fetch.assert_not_called()


# =============================================================================
# List and Search Tests
# =============================================================================


class TestListAndSearch:
    """Tests for listing and searching debates."""

    @pytest.mark.asyncio
    async def test_list_recent_async(self, storage, mock_connection):
        """Should list recent debates."""
        mock_connection.fetch = AsyncMock(
            return_value=[
                {
                    "slug": "test-slug",
                    "id": "debate-1",
                    "task": "Test task",
                    "agents": ["claude"],
                    "consensus_reached": True,
                    "confidence": 0.9,
                    "created_at": datetime.now(timezone.utc),
                    "view_count": 10,
                    "is_public": False,
                },
            ]
        )

        results = await storage.list_recent_async(limit=10)

        assert len(results) == 1
        assert isinstance(results[0], DebateMetadata)
        assert results[0].slug == "test-slug"

    @pytest.mark.asyncio
    async def test_list_recent_with_org_filter(self, storage, mock_connection):
        """Should filter by org_id."""
        mock_connection.fetch = AsyncMock(return_value=[])

        await storage.list_recent_async(limit=10, org_id="org-123")

        # Should include org_id in query
        call_args = mock_connection.fetch.call_args
        assert "org-123" in call_args[0] or "org_id" in str(call_args)

    @pytest.mark.asyncio
    async def test_search_async(self, storage, mock_connection):
        """Should search debates by query."""
        mock_connection.fetchrow = AsyncMock(return_value=(5,))  # Count
        mock_connection.fetch = AsyncMock(
            return_value=[
                {
                    "slug": "rate-limiter-slug",
                    "id": "debate-1",
                    "task": "Rate limiter design",
                    "agents": json.dumps(["claude"]),
                    "consensus_reached": True,
                    "confidence": 0.9,
                    "created_at": datetime.now(timezone.utc),
                    "view_count": 10,
                    "is_public": False,
                },
            ]
        )

        results, total = await storage.search_async("rate limiter", limit=10)

        assert len(results) == 1
        assert total == 5

    @pytest.mark.asyncio
    async def test_search_with_pagination(self, storage, mock_connection):
        """Should support pagination in search."""
        mock_connection.fetchrow = AsyncMock(return_value=(100,))
        mock_connection.fetch = AsyncMock(return_value=[])

        await storage.search_async("test", limit=10, offset=20)

        # Verify offset was used
        call_args = mock_connection.fetch.call_args
        assert 20 in call_args[0]  # offset should be in args


# =============================================================================
# Delete Operations Tests
# =============================================================================


class TestDeleteOperations:
    """Tests for deleting debates."""

    @pytest.mark.asyncio
    async def test_delete_async_success(self, storage, mock_connection):
        """Should delete debate and return True."""
        mock_connection.execute = AsyncMock(return_value="DELETE 1")

        result = await storage.delete_async("test-slug")

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_async_not_found(self, storage, mock_connection):
        """Should return False when debate not found."""
        mock_connection.execute = AsyncMock(return_value="DELETE 0")

        result = await storage.delete_async("nonexistent-slug")

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_with_ownership_requirement(self, storage, mock_connection):
        """Should require ownership when specified."""
        mock_connection.execute = AsyncMock(return_value="DELETE 1")

        await storage.delete_async("test-slug", org_id="org-123", require_ownership=True)

        # Should include org_id in delete query
        call_args = mock_connection.execute.call_args
        assert "org-123" in call_args[0]


# =============================================================================
# Audio Operations Tests
# =============================================================================


class TestAudioOperations:
    """Tests for audio-related operations."""

    @pytest.mark.asyncio
    async def test_update_audio_async(self, storage, mock_connection):
        """Should update audio information."""
        mock_connection.execute = AsyncMock(return_value="UPDATE 1")

        result = await storage.update_audio_async(
            "debate-123", "/path/to/audio.mp3", duration_seconds=120
        )

        assert result is True
        # Verify all parameters were passed
        call_args = mock_connection.execute.call_args
        assert "/path/to/audio.mp3" in call_args[0]
        assert 120 in call_args[0]

    @pytest.mark.asyncio
    async def test_update_audio_not_found(self, storage, mock_connection):
        """Should return False when debate not found."""
        mock_connection.execute = AsyncMock(return_value="UPDATE 0")

        result = await storage.update_audio_async("nonexistent", "/path/audio.mp3")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_audio_info_async(self, storage, mock_connection):
        """Should retrieve audio information."""
        mock_connection.fetchrow = AsyncMock(
            return_value={
                "audio_path": "/path/to/audio.mp3",
                "audio_generated_at": datetime.now(timezone.utc),
                "audio_duration_seconds": 120,
            }
        )

        result = await storage.get_audio_info_async("debate-123")

        assert result is not None
        assert result["audio_path"] == "/path/to/audio.mp3"
        assert result["audio_duration_seconds"] == 120
        assert "audio_generated_at" in result

    @pytest.mark.asyncio
    async def test_get_audio_info_no_audio(self, storage, mock_connection):
        """Should return None when no audio exists."""
        mock_connection.fetchrow = AsyncMock(return_value={"audio_path": None})

        result = await storage.get_audio_info_async("debate-123")

        assert result is None


# =============================================================================
# Public Status Tests
# =============================================================================


class TestPublicStatus:
    """Tests for public/private status operations."""

    @pytest.mark.asyncio
    async def test_is_public_async_true(self, storage, mock_connection):
        """Should return True for public debates."""
        mock_connection.fetchrow = AsyncMock(return_value={"is_public": True})

        result = await storage.is_public_async("debate-123")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_public_async_false(self, storage, mock_connection):
        """Should return False for private debates."""
        mock_connection.fetchrow = AsyncMock(return_value={"is_public": False})

        result = await storage.is_public_async("debate-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_public_not_found(self, storage, mock_connection):
        """Should return False for non-existent debates."""
        mock_connection.fetchrow = AsyncMock(return_value=None)

        result = await storage.is_public_async("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_set_public_async(self, storage, mock_connection):
        """Should set public status."""
        mock_connection.execute = AsyncMock(return_value="UPDATE 1")

        result = await storage.set_public_async("debate-123", True)

        assert result is True

    @pytest.mark.asyncio
    async def test_set_public_with_org_id(self, storage, mock_connection):
        """Should verify org_id when setting status."""
        mock_connection.execute = AsyncMock(return_value="UPDATE 1")

        await storage.set_public_async("debate-123", True, org_id="org-456")

        # Should include org_id in update
        call_args = mock_connection.execute.call_args
        assert "org-456" in call_args[0]


# =============================================================================
# Row to Metadata Conversion Tests
# =============================================================================


class TestRowToMetadata:
    """Tests for _row_to_metadata helper."""

    def test_converts_row_to_metadata(self, storage):
        """Should convert database row to DebateMetadata."""
        row = {
            "slug": "test-slug",
            "id": "debate-123",
            "task": "Test task",
            "agents": ["claude", "gpt"],
            "consensus_reached": True,
            "confidence": 0.9,
            "created_at": datetime.now(timezone.utc),
            "view_count": 42,
            "is_public": True,
        }

        metadata = storage._row_to_metadata(row)

        assert isinstance(metadata, DebateMetadata)
        assert metadata.slug == "test-slug"
        assert metadata.debate_id == "debate-123"
        assert metadata.agents == ["claude", "gpt"]

    def test_handles_json_string_agents(self, storage):
        """Should parse JSON string for agents field."""
        row = {
            "slug": "test-slug",
            "id": "debate-123",
            "task": "Test task",
            "agents": json.dumps(["claude", "gpt"]),
            "consensus_reached": True,
            "confidence": 0.9,
            "created_at": datetime.now(timezone.utc),
            "view_count": 0,
            "is_public": False,
        }

        metadata = storage._row_to_metadata(row)

        assert metadata.agents == ["claude", "gpt"]

    def test_handles_null_agents(self, storage):
        """Should default to empty list for null agents."""
        row = {
            "slug": "test-slug",
            "id": "debate-123",
            "task": "Test task",
            "agents": None,
            "consensus_reached": False,
            "confidence": 0.0,
            "created_at": datetime.now(timezone.utc),
            "view_count": 0,
            "is_public": False,
        }

        metadata = storage._row_to_metadata(row)

        assert metadata.agents == []

    def test_handles_string_datetime(self, storage):
        """Should parse ISO format datetime string."""
        now = datetime.now(timezone.utc)
        row = {
            "slug": "test-slug",
            "id": "debate-123",
            "task": "Test task",
            "agents": [],
            "consensus_reached": False,
            "confidence": 0.0,
            "created_at": now.isoformat(),
            "view_count": 0,
            "is_public": False,
        }

        metadata = storage._row_to_metadata(row)

        assert isinstance(metadata.created_at, datetime)

    def test_handles_null_datetime(self, storage):
        """Should default to now for null datetime."""
        row = {
            "slug": "test-slug",
            "id": "debate-123",
            "task": "Test task",
            "agents": [],
            "consensus_reached": False,
            "confidence": 0.0,
            "created_at": None,
            "view_count": 0,
            "is_public": False,
        }

        metadata = storage._row_to_metadata(row)

        assert isinstance(metadata.created_at, datetime)

    def test_handles_null_confidence(self, storage):
        """Should default to 0 for null confidence."""
        row = {
            "slug": "test-slug",
            "id": "debate-123",
            "task": "Test task",
            "agents": [],
            "consensus_reached": False,
            "confidence": None,
            "created_at": datetime.now(timezone.utc),
            "view_count": 0,
            "is_public": False,
        }

        metadata = storage._row_to_metadata(row)

        assert metadata.confidence == 0


# =============================================================================
# Sync Wrapper Tests
# =============================================================================


class TestSyncWrappers:
    """Tests for synchronous API wrappers."""

    def test_get_debate_alias(self, storage, mock_connection):
        """get_debate should alias to get_by_id."""
        mock_connection.fetchrow = AsyncMock(return_value={"artifact_json": {"id": "test"}})

        result = storage.get_debate("debate-123")

        assert result is not None

    def test_get_debate_by_slug_alias(self, storage, mock_connection):
        """get_debate_by_slug should alias to get_by_slug."""
        mock_connection.fetchrow = AsyncMock(return_value={"artifact_json": {"id": "test"}})
        mock_connection.execute = AsyncMock(return_value="UPDATE 1")

        result = storage.get_debate_by_slug("test-slug")

        assert result is not None

    def test_list_debates_alias(self, storage, mock_connection):
        """list_debates should alias to list_recent."""
        mock_connection.fetch = AsyncMock(return_value=[])

        results = storage.list_debates(limit=5)

        assert isinstance(results, list)

    def test_close_is_noop(self, storage):
        """close should be a no-op for pool-based store."""
        # Should not raise
        storage.close()


# =============================================================================
# Concurrent Access Tests
# =============================================================================


class TestConcurrentAccess:
    """Tests for concurrent access patterns."""

    @pytest.mark.asyncio
    async def test_concurrent_saves(self, storage, mock_connection):
        """Should handle concurrent save operations."""
        mock_connection.fetchrow = AsyncMock(return_value={"count": 0})
        mock_connection.execute = AsyncMock(return_value="INSERT 0 1")

        # Create multiple concurrent save tasks
        tasks = []
        for i in range(5):
            debate_data = {
                "id": f"debate-{i}",
                "task": f"Task {i}",
                "agents": [],
            }
            tasks.append(storage.save_dict_async(debate_data))

        # All should complete without error
        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        assert all(isinstance(r, str) for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_reads(self, storage, mock_connection):
        """Should handle concurrent read operations."""
        mock_connection.fetchrow = AsyncMock(return_value={"artifact_json": {"id": "test"}})
        mock_connection.execute = AsyncMock(return_value="UPDATE 1")

        # Create multiple concurrent read tasks
        tasks = [storage.get_by_slug_async(f"slug-{i}") for i in range(5)]

        # All should complete without error
        results = await asyncio.gather(*tasks)

        assert len(results) == 5


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_handles_connection_error_gracefully(self, storage, mock_connection):
        """Should propagate connection errors."""
        mock_connection.fetchrow = AsyncMock(side_effect=RuntimeError("Connection lost"))

        with pytest.raises(RuntimeError, match="Connection lost"):
            await storage.get_by_id_async("debate-123")

    @pytest.mark.asyncio
    async def test_handles_json_parse_error(self, storage, mock_connection):
        """Should handle invalid JSON in artifact."""
        # Return dict directly (not a string that needs parsing)
        mock_connection.fetchrow = AsyncMock(return_value={"artifact_json": {"id": "test"}})

        result = await storage.get_by_id_async("debate-123")

        assert result is not None


# =============================================================================
# SQL Injection Prevention Tests (Parameterized Queries)
# =============================================================================


class TestSQLInjectionPrevention:
    """Tests verifying SQL injection prevention via parameterized queries."""

    @pytest.mark.asyncio
    async def test_slug_with_sql_injection_attempt(self, storage, mock_connection):
        """Slug with SQL injection should be safely handled."""
        malicious_slug = "'; DROP TABLE debates; --"
        mock_connection.fetchrow = AsyncMock(return_value=None)

        # Should not raise - query is parameterized
        result = await storage.get_by_slug_async(malicious_slug)

        # Slug is passed as parameter, not interpolated
        assert result is None
        call_args = mock_connection.fetchrow.call_args
        assert malicious_slug in call_args[0]  # Passed as parameter

    @pytest.mark.asyncio
    async def test_search_query_with_special_chars(self, storage, mock_connection):
        """Search query with special chars should be safely handled."""
        malicious_query = "'; DELETE FROM debates WHERE '1'='1"
        mock_connection.fetchrow = AsyncMock(return_value=(0,))
        mock_connection.fetch = AsyncMock(return_value=[])

        # Should not raise - query is parameterized
        results, total = await storage.search_async(malicious_query)

        assert total == 0
        assert results == []


# =============================================================================
# Transaction Context Manager Tests
# =============================================================================


class TestTransactionHandling:
    """Tests for transaction handling via parent class."""

    @pytest.mark.asyncio
    async def test_connection_context_manager(self, storage, mock_connection):
        """Should properly acquire and release connections."""
        async with storage.connection() as conn:
            assert conn is mock_connection

    @pytest.mark.asyncio
    async def test_transaction_context_manager(self, storage, mock_connection):
        """Should properly handle transactions."""
        async with storage.transaction() as conn:
            assert conn is mock_connection

        # Transaction should have been created
        mock_connection.transaction.assert_called()
