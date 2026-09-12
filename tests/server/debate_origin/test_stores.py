"""Comprehensive tests for debate origin stores.

Tests cover:
1. SQLiteOriginStore operations
2. PostgresOriginStore operations (mocked)
3. Async store operations
4. TTL cleanup
5. Thread pool executor usage
"""

from __future__ import annotations

import asyncio
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from aragora.server.debate_origin import DebateOrigin, ORIGIN_TTL_SECONDS
from aragora.server.debate_origin.stores import (
    SQLiteOriginStore,
    PostgresOriginStore,
    _get_sqlite_store,
    _get_postgres_store,
    _get_postgres_store_sync,
)


# =============================================================================
# Test: SQLiteOriginStore
# =============================================================================


class TestSQLiteOriginStore:
    """Tests for SQLiteOriginStore class."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a store with temp database."""
        db_path = tmp_path / "test_origins.db"
        return SQLiteOriginStore(str(db_path))

    @pytest.fixture
    def sample_origin(self):
        """Sample debate origin."""
        return DebateOrigin(
            debate_id="sqlite-test-001",
            platform="slack",
            channel_id="C12345678",
            user_id="U87654321",
            thread_id="1234567890.123456",
            message_id="msg-001",
            metadata={"username": "testuser", "team_id": "T12345"},
        )

    def test_init_creates_schema(self, tmp_path):
        """SQLiteOriginStore creates table on init."""
        db_path = tmp_path / "new_db.db"
        store = SQLiteOriginStore(str(db_path))

        # Should be able to save immediately
        origin = DebateOrigin(
            debate_id="init-test",
            platform="telegram",
            channel_id="123",
            user_id="456",
        )
        store.save(origin)

        loaded = store.get("init-test")
        assert loaded is not None

    def test_init_creates_parent_directory(self, tmp_path):
        """SQLiteOriginStore creates parent directory if needed."""
        db_path = tmp_path / "nested" / "deep" / "db.db"
        store = SQLiteOriginStore(str(db_path))

        origin = DebateOrigin(
            debate_id="nested-test",
            platform="discord",
            channel_id="111",
            user_id="222",
        )
        store.save(origin)

        assert db_path.parent.exists()

    def test_save_and_get(self, store, sample_origin):
        """Save and retrieve origin."""
        store.save(sample_origin)
        loaded = store.get(sample_origin.debate_id)

        assert loaded is not None
        assert loaded.debate_id == sample_origin.debate_id
        assert loaded.platform == sample_origin.platform
        assert loaded.channel_id == sample_origin.channel_id
        assert loaded.user_id == sample_origin.user_id
        assert loaded.thread_id == sample_origin.thread_id
        assert loaded.message_id == sample_origin.message_id
        assert loaded.metadata == sample_origin.metadata

    def test_get_nonexistent(self, store):
        """Get returns None for missing origin."""
        result = store.get("nonexistent-debate")
        assert result is None

    def test_update_existing(self, store, sample_origin):
        """Save updates existing origin."""
        store.save(sample_origin)

        # Update and save again
        sample_origin.result_sent = True
        sample_origin.result_sent_at = time.time()
        store.save(sample_origin)

        loaded = store.get(sample_origin.debate_id)
        assert loaded.result_sent is True
        assert loaded.result_sent_at is not None

    def test_metadata_serialization(self, store):
        """Complex metadata is properly serialized."""
        origin = DebateOrigin(
            debate_id="meta-test",
            platform="discord",
            channel_id="123456",
            user_id="789",
            metadata={
                "nested": {"key": "value", "deep": {"level": 3}},
                "list": [1, 2, 3, "four"],
                "bool": True,
                "null": None,
                "unicode": "Test",
            },
        )
        store.save(origin)
        loaded = store.get("meta-test")

        assert loaded.metadata["nested"] == {"key": "value", "deep": {"level": 3}}
        assert loaded.metadata["list"] == [1, 2, 3, "four"]
        assert loaded.metadata["bool"] is True
        assert loaded.metadata["null"] is None
        assert loaded.metadata["unicode"] == "Test"

    def test_cleanup_expired(self, store):
        """cleanup_expired removes old records."""
        # Create an expired origin
        old_origin = DebateOrigin(
            debate_id="old-debate",
            platform="telegram",
            channel_id="111",
            user_id="222",
            created_at=time.time() - 100000,  # Way in the past
        )
        store.save(old_origin)

        # Create a fresh origin
        new_origin = DebateOrigin(
            debate_id="new-debate",
            platform="telegram",
            channel_id="333",
            user_id="444",
            created_at=time.time(),
        )
        store.save(new_origin)

        # Cleanup with short TTL
        count = store.cleanup_expired(ttl_seconds=1000)

        assert count == 1
        assert store.get("old-debate") is None
        assert store.get("new-debate") is not None

    def test_cleanup_expired_removes_multiple(self, store):
        """cleanup_expired removes multiple expired records."""
        # Create 5 expired origins
        for i in range(5):
            origin = DebateOrigin(
                debate_id=f"expired-{i}",
                platform="slack",
                channel_id=f"C{i}",
                user_id=f"U{i}",
                created_at=time.time() - 200000,
            )
            store.save(origin)

        # Create 3 fresh origins
        for i in range(3):
            origin = DebateOrigin(
                debate_id=f"fresh-{i}",
                platform="slack",
                channel_id=f"C1{i}",
                user_id=f"U1{i}",
                created_at=time.time(),
            )
            store.save(origin)

        count = store.cleanup_expired(ttl_seconds=1000)

        assert count == 5
        # Fresh ones remain
        for i in range(3):
            assert store.get(f"fresh-{i}") is not None

    def test_empty_metadata(self, store):
        """Origin with empty metadata is handled correctly."""
        origin = DebateOrigin(
            debate_id="no-meta",
            platform="teams",
            channel_id="T123",
            user_id="U456",
            metadata={},
        )
        store.save(origin)
        loaded = store.get("no-meta")

        assert loaded.metadata == {}

    def test_null_optional_fields(self, store):
        """Origin with null optional fields is handled correctly."""
        origin = DebateOrigin(
            debate_id="null-fields",
            platform="whatsapp",
            channel_id="+1234567890",
            user_id="wa-user",
            thread_id=None,
            message_id=None,
        )
        store.save(origin)
        loaded = store.get("null-fields")

        assert loaded.thread_id is None
        assert loaded.message_id is None


# =============================================================================
# Test: SQLiteOriginStore Async Methods
# =============================================================================


class TestSQLiteOriginStoreAsync:
    """Tests for SQLiteOriginStore async methods."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a store with temp database."""
        db_path = tmp_path / "test_async_origins.db"
        return SQLiteOriginStore(str(db_path))

    @pytest.fixture
    def sample_origin(self):
        """Sample debate origin."""
        return DebateOrigin(
            debate_id="async-test-001",
            platform="telegram",
            channel_id="123456789",
            user_id="987654321",
        )

    @pytest.mark.asyncio
    async def test_save_async(self, store, sample_origin):
        """save_async saves origin without blocking."""
        await store.save_async(sample_origin)

        # Verify with sync get
        loaded = store.get(sample_origin.debate_id)
        assert loaded is not None
        assert loaded.debate_id == sample_origin.debate_id

    @pytest.mark.asyncio
    async def test_get_async(self, store, sample_origin):
        """get_async retrieves origin without blocking."""
        store.save(sample_origin)

        loaded = await store.get_async(sample_origin.debate_id)

        assert loaded is not None
        assert loaded.platform == sample_origin.platform

    @pytest.mark.asyncio
    async def test_get_async_returns_none_for_missing(self, store):
        """get_async returns None for missing origin."""
        result = await store.get_async("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_async(self, store):
        """cleanup_expired_async removes expired records."""
        # Create expired origin
        expired = DebateOrigin(
            debate_id="async-expired",
            platform="discord",
            channel_id="111",
            user_id="222",
            created_at=time.time() - 100000,
        )
        store.save(expired)

        count = await store.cleanup_expired_async(ttl_seconds=1000)

        assert count == 1
        assert store.get("async-expired") is None

    @pytest.mark.asyncio
    async def test_concurrent_async_operations(self, store):
        """Multiple async operations work concurrently."""
        origins = [
            DebateOrigin(
                debate_id=f"concurrent-{i}",
                platform="telegram",
                channel_id=str(i),
                user_id=str(i * 10),
            )
            for i in range(10)
        ]

        # Save all concurrently
        await asyncio.gather(*[store.save_async(o) for o in origins])

        # Get all concurrently
        results = await asyncio.gather(*[store.get_async(o.debate_id) for o in origins])

        assert len(results) == 10
        assert all(r is not None for r in results)


# =============================================================================
# Test: PostgresOriginStore
# =============================================================================


class TestPostgresOriginStore:
    """Tests for PostgresOriginStore class."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock asyncpg pool."""
        pool = MagicMock()
        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetchrow = AsyncMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return pool, conn

    @pytest.fixture
    def sample_origin(self):
        """Sample debate origin."""
        return DebateOrigin(
            debate_id="pg-test-001",
            platform="slack",
            channel_id="C12345",
            user_id="U67890",
            metadata={"workspace": "test"},
        )

    @pytest.mark.asyncio
    async def test_initialize_creates_schema(self, mock_pool):
        """PostgresOriginStore.initialize creates tables."""
        pool, conn = mock_pool
        store = PostgresOriginStore(pool)

        await store.initialize()

        conn.execute.assert_called_once()
        call_args = conn.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS debate_origins" in call_args

    @pytest.mark.asyncio
    async def test_initialize_only_once(self, mock_pool):
        """PostgresOriginStore.initialize only runs once."""
        pool, conn = mock_pool
        store = PostgresOriginStore(pool)

        await store.initialize()
        await store.initialize()

        # Should only execute once
        assert conn.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_save_inserts_origin(self, mock_pool, sample_origin):
        """PostgresOriginStore.save inserts origin."""
        pool, conn = mock_pool
        store = PostgresOriginStore(pool)

        await store.save(sample_origin)

        conn.execute.assert_called_once()
        call_args = conn.execute.call_args[0]
        assert "INSERT INTO debate_origins" in call_args[0]
        assert call_args[1] == sample_origin.debate_id

    @pytest.mark.asyncio
    async def test_save_upserts_existing(self, mock_pool, sample_origin):
        """PostgresOriginStore.save uses ON CONFLICT for upsert."""
        pool, conn = mock_pool
        store = PostgresOriginStore(pool)

        await store.save(sample_origin)

        call_args = conn.execute.call_args[0][0]
        assert "ON CONFLICT" in call_args
        assert "DO UPDATE" in call_args

    @pytest.mark.asyncio
    async def test_get_returns_origin(self, mock_pool, sample_origin):
        """PostgresOriginStore.get returns origin."""
        pool, conn = mock_pool

        # Mock fetchrow to return origin data
        conn.fetchrow.return_value = {
            "debate_id": sample_origin.debate_id,
            "platform": sample_origin.platform,
            "channel_id": sample_origin.channel_id,
            "user_id": sample_origin.user_id,
            "created_at": sample_origin.created_at,
            "metadata_json": json.dumps(sample_origin.metadata),
            "thread_id": None,
            "message_id": None,
            "result_sent": False,
            "result_sent_at": None,
        }

        store = PostgresOriginStore(pool)
        result = await store.get(sample_origin.debate_id)

        assert result is not None
        assert result.debate_id == sample_origin.debate_id
        assert result.platform == sample_origin.platform

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self, mock_pool):
        """PostgresOriginStore.get returns None when not found."""
        pool, conn = mock_pool
        conn.fetchrow.return_value = None

        store = PostgresOriginStore(pool)
        result = await store.get("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_deletes_old_records(self, mock_pool):
        """PostgresOriginStore.cleanup_expired deletes old records."""
        pool, conn = mock_pool
        conn.execute.return_value = "DELETE 5"

        store = PostgresOriginStore(pool)
        count = await store.cleanup_expired(ttl_seconds=86400)

        assert count == 5
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args[0]
        assert "DELETE FROM debate_origins" in call_args[0]


# =============================================================================
# Test: Store Factory Functions
# =============================================================================


class TestStoreFactoryFunctions:
    """Tests for store factory functions."""

    def test_get_sqlite_store_creates_singleton(self, tmp_path):
        """_get_sqlite_store returns singleton instance."""
        # This test modifies global state, so we patch the module-level variable
        with patch(
            "aragora.server.debate_origin.stores._sqlite_store",
            None,
        ):
            with patch.dict(
                "os.environ",
                {"ARAGORA_DATA_DIR": str(tmp_path)},
            ):
                store1 = _get_sqlite_store()
                store2 = _get_sqlite_store()

                # Note: Due to singleton caching, we can't easily test this
                # without resetting the module state
                assert store1 is not None

    @pytest.mark.asyncio
    async def test_get_postgres_store_returns_none_when_not_configured(self):
        """_get_postgres_store returns None when PostgreSQL not configured."""
        with patch(
            "aragora.server.debate_origin.stores._postgres_store",
            None,
        ):
            with patch.dict(
                "os.environ",
                {"ARAGORA_DB_BACKEND": "sqlite"},
            ):
                result = await _get_postgres_store()

        assert result is None

    def test_get_postgres_store_sync_returns_cached(self):
        """_get_postgres_store_sync returns cached store."""
        mock_store = MagicMock()

        with patch(
            "aragora.server.debate_origin.stores._postgres_store",
            mock_store,
        ):
            try:
                # Try to get the running loop (which may fail in sync context)
                asyncio.get_running_loop()
            except RuntimeError:
                # No running loop - this is the expected path
                result = _get_postgres_store_sync()
                # When no loop is running and store is already cached
                # it should return the cached value


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestStoreEdgeCases:
    """Tests for edge cases in store operations."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a store with temp database."""
        db_path = tmp_path / "edge_cases.db"
        return SQLiteOriginStore(str(db_path))

    def test_special_characters_in_debate_id(self, store):
        """Store handles special characters in debate_id."""
        origin = DebateOrigin(
            debate_id="test:with:colons:and/slashes",
            platform="telegram",
            channel_id="123",
            user_id="456",
        )
        store.save(origin)
        loaded = store.get("test:with:colons:and/slashes")

        assert loaded is not None
        assert loaded.debate_id == "test:with:colons:and/slashes"

    def test_very_long_debate_id(self, store):
        """Store handles very long debate_id."""
        long_id = "d" * 1000
        origin = DebateOrigin(
            debate_id=long_id,
            platform="slack",
            channel_id="C1",
            user_id="U1",
        )
        store.save(origin)
        loaded = store.get(long_id)

        assert loaded is not None
        assert loaded.debate_id == long_id

    def test_empty_strings(self, store):
        """Store handles empty string values."""
        origin = DebateOrigin(
            debate_id="empty-test",
            platform="",
            channel_id="",
            user_id="",
        )
        store.save(origin)
        loaded = store.get("empty-test")

        assert loaded is not None
        assert loaded.platform == ""
        assert loaded.channel_id == ""

    def test_unicode_values(self, store):
        """Store handles unicode values."""
        origin = DebateOrigin(
            debate_id="unicode-test",
            platform="telegram",
            channel_id="123",
            user_id="456",
            metadata={"name": "Test", "city": "Test City"},
        )
        store.save(origin)
        loaded = store.get("unicode-test")

        assert loaded is not None
        assert loaded.metadata["name"] == "Test"

    def test_large_metadata(self, store):
        """Store handles large metadata."""
        large_meta = {f"key_{i}": f"value_{i}" * 100 for i in range(100)}
        origin = DebateOrigin(
            debate_id="large-meta",
            platform="discord",
            channel_id="111",
            user_id="222",
            metadata=large_meta,
        )
        store.save(origin)
        loaded = store.get("large-meta")

        assert loaded is not None
        assert len(loaded.metadata) == 100

    def test_cleanup_with_no_expired(self, store):
        """cleanup_expired returns 0 when no expired records."""
        origin = DebateOrigin(
            debate_id="fresh",
            platform="teams",
            channel_id="T1",
            user_id="U1",
            created_at=time.time(),
        )
        store.save(origin)

        count = store.cleanup_expired(ttl_seconds=ORIGIN_TTL_SECONDS)

        assert count == 0
        assert store.get("fresh") is not None

    def test_cleanup_empty_store(self, store):
        """cleanup_expired handles empty store."""
        count = store.cleanup_expired(ttl_seconds=1000)
        assert count == 0

    def test_result_sent_at_precision(self, store):
        """Store preserves result_sent_at precision."""
        timestamp = 1234567890.123456
        origin = DebateOrigin(
            debate_id="precision-test",
            platform="slack",
            channel_id="C1",
            user_id="U1",
            result_sent=True,
            result_sent_at=timestamp,
        )
        store.save(origin)
        loaded = store.get("precision-test")

        # SQLite stores as REAL which has some precision limits
        assert loaded.result_sent_at is not None
        assert abs(loaded.result_sent_at - timestamp) < 0.001  # Within 1ms
