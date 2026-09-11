"""
Tests for the EmbeddingCache LRU module.

Tests cover:
- Cache operations (get, put, evict)
- LRU eviction order
- Size limits
- Persistence loading/saving
- Thread safety
- EmbeddingCacheManager for per-debate isolation
- Module-level convenience functions
- Edge cases (empty cache, single item)
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import numpy as np


@pytest.fixture
def embedding_cache():
    """Create a fresh embedding cache for testing."""
    from aragora.debate.cache.embeddings_lru import EmbeddingCache

    cache = EmbeddingCache(max_size=10, persist=False)
    yield cache
    cache.clear()


@pytest.fixture
def small_cache():
    """Create a small cache for testing eviction."""
    from aragora.debate.cache.embeddings_lru import EmbeddingCache

    cache = EmbeddingCache(max_size=3, persist=False)
    yield cache
    cache.clear()


@pytest.fixture
def temp_db():
    """Create a temporary database file for persistence tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Create the embeddings table
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS embeddings (
            id TEXT PRIMARY KEY,
            text_hash TEXT UNIQUE NOT NULL,
            text TEXT,
            embedding BLOB,
            provider TEXT,
            created_at TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def persistent_cache(temp_db):
    """Create a cache with persistence enabled."""
    from aragora.debate.cache.embeddings_lru import EmbeddingCache

    cache = EmbeddingCache(max_size=10, persist=True, db_path=temp_db)
    yield cache
    cache.clear()


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset global cache state before and after each test."""
    from aragora.debate.cache.embeddings_lru import reset_embedding_cache

    reset_embedding_cache()
    yield
    reset_embedding_cache()


class TestEmbeddingCacheInit:
    """Tests for EmbeddingCache initialization."""

    def test_init_default_values(self):
        """Test initialization with default values."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCache

        cache = EmbeddingCache()
        assert cache.max_size == 1024
        assert cache.persist is False
        assert cache.db_path is None

    def test_init_custom_max_size(self):
        """Test initialization with custom max size."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCache

        cache = EmbeddingCache(max_size=100)
        assert cache.max_size == 100

    def test_init_with_persistence(self, temp_db):
        """Test initialization with persistence enabled."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCache

        cache = EmbeddingCache(persist=True, db_path=temp_db)
        assert cache.persist is True
        assert cache.db_path == temp_db

    def test_init_stats_zero(self):
        """Test that stats start at zero."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCache

        cache = EmbeddingCache()
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["size"] == 0


class TestCacheGetPut:
    """Tests for cache get and put operations."""

    def test_put_and_get(self, embedding_cache):
        """Test basic put and get operations."""
        text = "Hello world"
        embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)

        embedding_cache.put(text, embedding)
        result = embedding_cache.get(text)

        assert result is not None
        np.testing.assert_array_equal(result, embedding)

    def test_get_missing_returns_none(self, embedding_cache):
        """Test that getting missing key returns None."""
        result = embedding_cache.get("nonexistent")
        assert result is None

    def test_get_increments_miss_counter(self, embedding_cache):
        """Test that cache miss increments counter."""
        embedding_cache.get("nonexistent")
        stats = embedding_cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    def test_get_increments_hit_counter(self, embedding_cache):
        """Test that cache hit increments counter."""
        text = "test text"
        embedding = np.array([1.0, 2.0], dtype=np.float32)

        embedding_cache.put(text, embedding)
        embedding_cache.get(text)

        stats = embedding_cache.get_stats()
        assert stats["hits"] == 1

    def test_put_overwrites_existing(self, embedding_cache):
        """Test that put overwrites existing entry."""
        text = "same text"
        embedding1 = np.array([1.0, 2.0], dtype=np.float32)
        embedding2 = np.array([3.0, 4.0], dtype=np.float32)

        embedding_cache.put(text, embedding1)
        embedding_cache.put(text, embedding2)

        result = embedding_cache.get(text)
        np.testing.assert_array_equal(result, embedding2)

    def test_different_texts_different_keys(self, embedding_cache):
        """Test that different texts have different cache keys."""
        text1 = "text one"
        text2 = "text two"
        embedding1 = np.array([1.0], dtype=np.float32)
        embedding2 = np.array([2.0], dtype=np.float32)

        embedding_cache.put(text1, embedding1)
        embedding_cache.put(text2, embedding2)

        result1 = embedding_cache.get(text1)
        result2 = embedding_cache.get(text2)

        np.testing.assert_array_equal(result1, embedding1)
        np.testing.assert_array_equal(result2, embedding2)

    def test_unicode_text(self, embedding_cache):
        """Test cache works with unicode text."""
        text = "Hello \u4e16\u754c \u0417\u0434\u0440\u0430\u0432\u0441\u0442\u0432\u0443\u0439"
        embedding = np.array([0.5, 0.6], dtype=np.float32)

        embedding_cache.put(text, embedding)
        result = embedding_cache.get(text)

        np.testing.assert_array_equal(result, embedding)

    def test_empty_text(self, embedding_cache):
        """Test cache works with empty text."""
        text = ""
        embedding = np.array([0.0], dtype=np.float32)

        embedding_cache.put(text, embedding)
        result = embedding_cache.get(text)

        np.testing.assert_array_equal(result, embedding)


class TestLRUEviction:
    """Tests for LRU eviction behavior."""

    def test_evicts_oldest_when_full(self, small_cache):
        """Test that oldest entry is evicted when cache is full."""
        # Fill cache to capacity (max_size=3)
        small_cache.put("text1", np.array([1.0], dtype=np.float32))
        small_cache.put("text2", np.array([2.0], dtype=np.float32))
        small_cache.put("text3", np.array([3.0], dtype=np.float32))

        # Add one more, should evict text1
        small_cache.put("text4", np.array([4.0], dtype=np.float32))

        # text1 should be evicted
        assert small_cache.get("text1") is None
        # Others should exist
        assert small_cache.get("text2") is not None
        assert small_cache.get("text3") is not None
        assert small_cache.get("text4") is not None

    def test_get_updates_lru_order(self, small_cache):
        """Test that get() moves entry to end of LRU queue."""
        small_cache.put("text1", np.array([1.0], dtype=np.float32))
        small_cache.put("text2", np.array([2.0], dtype=np.float32))
        small_cache.put("text3", np.array([3.0], dtype=np.float32))

        # Access text1 to make it recently used
        small_cache.get("text1")

        # Add new entry, should evict text2 (oldest not-recently-accessed)
        small_cache.put("text4", np.array([4.0], dtype=np.float32))

        # text2 should be evicted
        assert small_cache.get("text2") is None
        # text1 should still exist (was recently accessed)
        assert small_cache.get("text1") is not None

    def test_multiple_evictions(self, small_cache):
        """Test multiple evictions maintain LRU order."""
        # Fill cache
        for i in range(3):
            small_cache.put(f"text{i}", np.array([float(i)], dtype=np.float32))

        # Add 3 more, evicting all original entries
        for i in range(3, 6):
            small_cache.put(f"text{i}", np.array([float(i)], dtype=np.float32))

        # Original entries should be evicted
        for i in range(3):
            assert small_cache.get(f"text{i}") is None

        # New entries should exist
        for i in range(3, 6):
            assert small_cache.get(f"text{i}") is not None


class TestSizeLimits:
    """Tests for cache size limits."""

    def test_cache_respects_max_size(self, small_cache):
        """Test that cache never exceeds max_size."""
        for i in range(10):
            small_cache.put(f"text{i}", np.array([float(i)], dtype=np.float32))

        stats = small_cache.get_stats()
        assert stats["size"] <= 3  # max_size=3

    def test_single_item_cache(self):
        """Test cache with max_size=1."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCache

        cache = EmbeddingCache(max_size=1)

        cache.put("text1", np.array([1.0], dtype=np.float32))
        cache.put("text2", np.array([2.0], dtype=np.float32))

        # Only text2 should exist
        assert cache.get("text1") is None
        assert cache.get("text2") is not None

    def test_zero_size_cache(self):
        """Test edge case with max_size=0 raises KeyError (degenerate case).

        Note: max_size=0 is a degenerate case that causes an error in the
        current implementation when trying to evict from an empty cache.
        This test documents the current behavior.
        """
        from aragora.debate.cache.embeddings_lru import EmbeddingCache

        # max_size=0 means nothing can be stored
        cache = EmbeddingCache(max_size=0)

        # The implementation tries to evict when len(cache) >= max_size (0 >= 0),
        # but the cache is empty, so popitem fails
        with pytest.raises(KeyError):
            cache.put("text1", np.array([1.0], dtype=np.float32))


class TestCacheStats:
    """Tests for cache statistics."""

    def test_hit_rate_calculation(self, embedding_cache):
        """Test hit rate is calculated correctly."""
        embedding_cache.put("text1", np.array([1.0], dtype=np.float32))

        # 2 hits
        embedding_cache.get("text1")
        embedding_cache.get("text1")

        # 1 miss
        embedding_cache.get("nonexistent")

        stats = embedding_cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(2 / 3)

    def test_hit_rate_zero_total(self, embedding_cache):
        """Test hit rate is 0 when no accesses."""
        stats = embedding_cache.get_stats()
        assert stats["hit_rate"] == 0.0

    def test_stats_include_max_size(self, embedding_cache):
        """Test stats include max_size."""
        stats = embedding_cache.get_stats()
        assert stats["max_size"] == 10

    def test_stats_size_updates(self, embedding_cache):
        """Test stats size updates with cache contents."""
        assert embedding_cache.get_stats()["size"] == 0

        embedding_cache.put("text1", np.array([1.0], dtype=np.float32))
        assert embedding_cache.get_stats()["size"] == 1

        embedding_cache.put("text2", np.array([2.0], dtype=np.float32))
        assert embedding_cache.get_stats()["size"] == 2


class TestCacheClear:
    """Tests for cache clear operation."""

    def test_clear_removes_all_entries(self, embedding_cache):
        """Test clear removes all entries."""
        embedding_cache.put("text1", np.array([1.0], dtype=np.float32))
        embedding_cache.put("text2", np.array([2.0], dtype=np.float32))

        embedding_cache.clear()

        assert embedding_cache.get("text1") is None
        assert embedding_cache.get("text2") is None
        assert embedding_cache.get_stats()["size"] == 0

    def test_clear_resets_stats(self, embedding_cache):
        """Test clear resets statistics."""
        embedding_cache.put("text1", np.array([1.0], dtype=np.float32))
        embedding_cache.get("text1")  # hit
        embedding_cache.get("miss")  # miss

        embedding_cache.clear()

        stats = embedding_cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_clear_empty_cache(self, embedding_cache):
        """Test clear on empty cache doesn't error."""
        embedding_cache.clear()  # Should not raise
        assert embedding_cache.get_stats()["size"] == 0


class TestPersistence:
    """Tests for database persistence."""

    def test_save_to_db(self, persistent_cache, temp_db):
        """Test that entries are saved to database."""
        text = "persistent text"
        embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)

        persistent_cache.put(text, embedding)

        # Verify in database
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM embeddings")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 1

    def test_load_from_db(self, temp_db):
        """Test that entries can be loaded from database."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCache

        text = "preloaded text"
        embedding = np.array([0.5, 0.6], dtype=np.float32)

        # Insert directly into DB
        text_hash = "test_hash_12345678901234567890"
        conn = sqlite3.connect(temp_db)
        conn.execute(
            """
            INSERT INTO embeddings (id, text_hash, text, embedding, provider, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            ("id1", text_hash, text, embedding.tobytes(), "test"),
        )
        conn.commit()
        conn.close()

        # Create cache and patch _hash_text to return our known hash
        cache = EmbeddingCache(persist=True, db_path=temp_db)
        with patch.object(cache, "_hash_text", return_value=text_hash):
            result = cache.get(text)

        assert result is not None
        np.testing.assert_array_equal(result, embedding)

    def test_db_load_populates_memory_cache(self, persistent_cache, temp_db):
        """Test that DB load also stores in memory cache."""
        text = "memory and db"
        embedding = np.array([0.7, 0.8], dtype=np.float32)

        persistent_cache.put(text, embedding)
        persistent_cache.clear()  # Clear memory cache

        # First get loads from DB
        result1 = persistent_cache.get(text)
        assert result1 is not None

        # Second get should be from memory (hit counter increases)
        result2 = persistent_cache.get(text)
        assert result2 is not None

        stats = persistent_cache.get_stats()
        assert stats["hits"] == 2  # Both should be hits (DB hit + memory hit)

    def test_persistence_disabled(self, embedding_cache):
        """Test that persistence can be disabled."""
        text = "non-persistent"
        embedding = np.array([1.0], dtype=np.float32)

        embedding_cache.put(text, embedding)

        # No DB operations should occur
        assert embedding_cache.persist is False
        assert embedding_cache.db_path is None

    def test_handles_missing_db_gracefully(self):
        """Test that missing DB file is handled gracefully."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCache

        cache = EmbeddingCache(persist=True, db_path="/nonexistent/path/db.sqlite")

        # Should not raise, just return None
        result = cache.get("some text")
        assert result is None

    def test_handles_db_error_on_save(self, temp_db):
        """Test that DB errors on save are handled gracefully."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCache

        cache = EmbeddingCache(persist=True, db_path=temp_db)

        # Drop the table to cause an error
        conn = sqlite3.connect(temp_db)
        conn.execute("DROP TABLE embeddings")
        conn.commit()
        conn.close()

        # Should not raise, just log
        cache.put("text", np.array([1.0], dtype=np.float32))  # Should not raise

    def test_truncates_long_text(self, persistent_cache, temp_db):
        """Test that long text is truncated before saving."""
        long_text = "x" * 2000  # Longer than 1000 char limit
        embedding = np.array([0.1], dtype=np.float32)

        persistent_cache.put(long_text, embedding)

        # Check DB has truncated text
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("SELECT text FROM embeddings")
        row = cursor.fetchone()
        conn.close()

        assert len(row[0]) == 1000


class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_puts(self):
        """Every concurrent write survives when all keys fit in the cache."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCache

        expected = [np.array([i, i + 0.5, -i], dtype=np.float32) for i in range(20)]
        cache = EmbeddingCache(max_size=len(expected), persist=False)
        start = threading.Barrier(len(expected))
        errors = []
        results = []

        def put_item(i: int):
            try:
                start.wait(timeout=10)
                cache.put(f"text_{i}", expected[i].copy())
                results.append(i)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(len(expected)):
            t = threading.Thread(target=put_item, args=(i,), daemon=True)
            threads.append(t)
            t.start()

        deadline = time.monotonic() + 10
        for t in threads:
            t.join(timeout=max(0, deadline - time.monotonic()))

        assert not any(t.is_alive() for t in threads), "Writers did not finish"
        assert not errors, f"Worker errors: {errors}"
        assert sorted(results) == list(range(len(expected)))
        for i, embedding in enumerate(expected):
            result = cache.get(f"text_{i}")
            assert result is not None, f"Missing cached vector for text_{i}"
            np.testing.assert_array_equal(result, embedding)

    def test_concurrent_gets(self, embedding_cache):
        """Concurrent readers receive the exact vector for their requested key."""
        expected = [np.array([i, i + 0.5, -i], dtype=np.float32) for i in range(5)]
        # All keys fit: a missing result cannot be explained by eviction.
        for i, embedding in enumerate(expected):
            embedding_cache.put(f"text_{i}", embedding.copy())

        errors = []
        results = []
        start = threading.Barrier(50)

        def get_item(i: int):
            try:
                start.wait(timeout=10)
                result = embedding_cache.get(f"text_{i % 5}")
                results.append((i, result))
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(50):
            t = threading.Thread(target=get_item, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert not errors, f"Worker errors: {errors}"
        assert len(results) == 50
        assert {i for i, _ in results} == set(range(50))
        for i, result in results:
            assert result is not None, f"Missing cached vector for text_{i % 5}"
            np.testing.assert_array_equal(result, expected[i % 5])

    def test_concurrent_put_get(self):
        """Readers see written versions, and every writer's final value survives."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCache

        cache = EmbeddingCache(max_size=10, persist=False)
        expected = [
            [np.array([i, version, -i], dtype=np.float32) for version in range(-1, 100)]
            for i in range(5)
        ]
        # One writer per key; all keys remain resident throughout the race.
        for i, versions in enumerate(expected):
            cache.put(f"text_{i}", versions[0].copy())
        start = threading.Barrier(10)
        errors = []
        writers_done = []
        results = [[] for _ in expected]

        def writer(i: int):
            try:
                start.wait(timeout=10)
                for embedding in expected[i][1:]:
                    cache.put(f"text_{i}", embedding.copy())
                writers_done.append(i)
            except Exception as e:
                errors.append(e)

        def reader(i: int):
            try:
                start.wait(timeout=10)
                for _ in range(100):
                    result = cache.get(f"text_{i}")
                    results[i].append(result.copy() if result is not None else None)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(len(expected)):
            threads.append(threading.Thread(target=writer, args=(i,), daemon=True))
            threads.append(threading.Thread(target=reader, args=(i,), daemon=True))

        for t in threads:
            t.start()
        deadline = time.monotonic() + 10
        for t in threads:
            t.join(timeout=max(0, deadline - time.monotonic()))

        assert not any(t.is_alive() for t in threads), "Readers/writers did not finish"
        assert not errors, f"Worker errors: {errors}"
        assert sorted(writers_done) == list(range(len(expected)))
        for i, reads in enumerate(results):
            assert len(reads) == 100
            for result in reads:
                assert result is not None, f"Missing cached vector for text_{i}"
                assert any(np.array_equal(result, value) for value in expected[i]), (
                    f"Unexpected vector for text_{i}: {result}"
                )
            np.testing.assert_array_equal(cache.get(f"text_{i}"), expected[i][-1])

    def test_concurrent_eviction(self, small_cache):
        """Test that concurrent evictions don't cause errors."""
        errors = []

        def rapid_put(offset: int):
            try:
                for i in range(50):
                    small_cache.put(f"text_{offset}_{i}", np.array([float(i)], dtype=np.float32))
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(10):
            t = threading.Thread(target=rapid_put, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        # Cache should still be at or below max size
        assert small_cache.get_stats()["size"] <= 3


class TestEmbeddingCacheManager:
    """Tests for EmbeddingCacheManager."""

    def test_get_cache_creates_new(self):
        """Test get_cache creates new cache for unknown debate."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCacheManager

        manager = EmbeddingCacheManager()
        cache = manager.get_cache("debate-123")

        assert cache is not None
        assert manager.get_stats()["active_debates"] == 1

    def test_get_cache_returns_existing(self):
        """Test get_cache returns same cache for same debate."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCacheManager

        manager = EmbeddingCacheManager()

        cache1 = manager.get_cache("debate-123")
        cache2 = manager.get_cache("debate-123")

        assert cache1 is cache2

    def test_different_debates_different_caches(self):
        """Test different debates get isolated caches."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCacheManager

        manager = EmbeddingCacheManager()

        cache1 = manager.get_cache("debate-1")
        cache2 = manager.get_cache("debate-2")

        assert cache1 is not cache2

        # Put in cache1 should not affect cache2
        cache1.put("text", np.array([1.0], dtype=np.float32))
        assert cache1.get("text") is not None
        assert cache2.get("text") is None

    def test_cleanup_removes_cache(self):
        """Test cleanup removes the cache."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCacheManager

        manager = EmbeddingCacheManager()

        cache = manager.get_cache("debate-123")
        cache.put("text", np.array([1.0], dtype=np.float32))

        manager.cleanup("debate-123")

        assert manager.get_stats()["active_debates"] == 0

        # Getting again creates new cache
        new_cache = manager.get_cache("debate-123")
        assert new_cache.get("text") is None  # Old data gone

    def test_cleanup_nonexistent_no_error(self):
        """Test cleanup of nonexistent debate doesn't error."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCacheManager

        manager = EmbeddingCacheManager()
        manager.cleanup("nonexistent")  # Should not raise

    def test_configure_affects_new_caches(self):
        """Test configure changes defaults for new caches."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCacheManager

        manager = EmbeddingCacheManager()
        manager.configure(max_size=50)

        cache = manager.get_cache("debate-123")
        assert cache.max_size == 50

    def test_get_stats_returns_all_debates(self):
        """Test get_stats returns stats for all active debates."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCacheManager

        manager = EmbeddingCacheManager()

        manager.get_cache("debate-1")
        manager.get_cache("debate-2")

        stats = manager.get_stats()
        assert stats["active_debates"] == 2
        assert "debate-1" in stats["debates"]
        assert "debate-2" in stats["debates"]

    def test_clear_all(self):
        """Test clear_all removes all caches."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCacheManager

        manager = EmbeddingCacheManager()

        for i in range(5):
            cache = manager.get_cache(f"debate-{i}")
            cache.put("text", np.array([float(i)], dtype=np.float32))

        manager.clear_all()

        assert manager.get_stats()["active_debates"] == 0


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_scoped_embedding_cache(self):
        """Test get_scoped_embedding_cache returns debate-specific cache."""
        from aragora.debate.cache.embeddings_lru import get_scoped_embedding_cache

        cache1 = get_scoped_embedding_cache("debate-1")
        cache2 = get_scoped_embedding_cache("debate-2")

        assert cache1 is not cache2

    def test_cleanup_embedding_cache(self):
        """Test cleanup_embedding_cache removes debate cache."""
        from aragora.debate.cache.embeddings_lru import (
            cleanup_embedding_cache,
            get_scoped_embedding_cache,
        )

        cache = get_scoped_embedding_cache("debate-123")
        cache.put("text", np.array([1.0], dtype=np.float32))

        cleanup_embedding_cache("debate-123")

        # New cache should be empty
        new_cache = get_scoped_embedding_cache("debate-123")
        assert new_cache.get("text") is None

    def test_get_embedding_cache_deprecated(self):
        """Test get_embedding_cache returns global cache with warning."""
        from aragora.debate.cache.embeddings_lru import get_embedding_cache

        with patch("aragora.debate.cache.embeddings_lru.logger") as mock_logger:
            cache = get_embedding_cache()

            assert cache is not None
            # Should log warning about using global cache
            mock_logger.warning.assert_called()

    def test_get_embedding_cache_singleton(self):
        """Test get_embedding_cache returns same instance."""
        from aragora.debate.cache.embeddings_lru import get_embedding_cache

        # Suppress warning for test
        with patch("aragora.debate.cache.embeddings_lru.logger"):
            cache1 = get_embedding_cache()
            cache2 = get_embedding_cache()

        assert cache1 is cache2

    def test_reset_embedding_cache(self):
        """Test reset_embedding_cache clears global and manager caches."""
        from aragora.debate.cache.embeddings_lru import (
            get_embedding_cache,
            get_scoped_embedding_cache,
            reset_embedding_cache,
        )

        with patch("aragora.debate.cache.embeddings_lru.logger"):
            global_cache = get_embedding_cache()
            global_cache.put("text", np.array([1.0], dtype=np.float32))

        scoped_cache = get_scoped_embedding_cache("debate-123")
        scoped_cache.put("text", np.array([2.0], dtype=np.float32))

        reset_embedding_cache()

        # After reset, getting global cache creates new one
        with patch("aragora.debate.cache.embeddings_lru.logger"):
            new_global = get_embedding_cache()
            assert new_global.get("text") is None

        new_scoped = get_scoped_embedding_cache("debate-123")
        assert new_scoped.get("text") is None


class TestHashText:
    """Tests for text hashing."""

    def test_hash_is_deterministic(self, embedding_cache):
        """Test that same text produces same hash."""
        text = "consistent text"
        hash1 = embedding_cache._hash_text(text)
        hash2 = embedding_cache._hash_text(text)
        assert hash1 == hash2

    def test_hash_length(self, embedding_cache):
        """Test hash is truncated to 32 chars."""
        text = "some text to hash"
        hash_value = embedding_cache._hash_text(text)
        assert len(hash_value) == 32

    def test_different_texts_different_hashes(self, embedding_cache):
        """Test different texts produce different hashes."""
        hash1 = embedding_cache._hash_text("text one")
        hash2 = embedding_cache._hash_text("text two")
        assert hash1 != hash2


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_cache_stats(self, embedding_cache):
        """Test stats on empty cache."""
        stats = embedding_cache.get_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

    def test_very_large_embedding(self, embedding_cache):
        """Test cache handles large embeddings."""
        text = "large embedding"
        embedding = np.random.rand(4096).astype(np.float32)  # Large embedding

        embedding_cache.put(text, embedding)
        result = embedding_cache.get(text)

        np.testing.assert_array_equal(result, embedding)

    def test_very_long_text(self, embedding_cache):
        """Test cache handles very long text."""
        text = "x" * 100000  # 100K characters
        embedding = np.array([1.0], dtype=np.float32)

        embedding_cache.put(text, embedding)
        result = embedding_cache.get(text)

        np.testing.assert_array_equal(result, embedding)

    def test_special_characters_in_text(self, embedding_cache):
        """Test cache handles special characters."""
        text = "tab\ttab\nnewline\r\nwindows\x00null"
        embedding = np.array([1.0], dtype=np.float32)

        embedding_cache.put(text, embedding)
        result = embedding_cache.get(text)

        np.testing.assert_array_equal(result, embedding)

    def test_numeric_embedding_types(self, embedding_cache):
        """Test cache works with different numpy dtypes."""
        text = "dtype test"

        # float64
        embedding64 = np.array([1.0, 2.0], dtype=np.float64)
        embedding_cache.put(text, embedding64)
        result = embedding_cache.get(text)
        np.testing.assert_array_equal(result, embedding64)

    def test_multidimensional_embedding(self, embedding_cache):
        """Test cache handles multi-dimensional arrays."""
        text = "2d array"
        embedding = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)

        embedding_cache.put(text, embedding)
        result = embedding_cache.get(text)

        np.testing.assert_array_equal(result, embedding)


class TestNumpyRequirement:
    """Tests for numpy requirement handling."""

    def test_require_numpy_function(self):
        """Test _require_numpy raises when numpy not available."""
        from aragora.debate.cache.embeddings_lru import _require_numpy

        # This should not raise when numpy is available
        _require_numpy("test operation")

    def test_require_numpy_raises_without_numpy(self):
        """Test _require_numpy raises ImportError when numpy unavailable."""
        from aragora.debate.cache import embeddings_lru

        original_has_numpy = embeddings_lru.HAS_NUMPY
        try:
            embeddings_lru.HAS_NUMPY = False
            with pytest.raises(ImportError, match="numpy is required"):
                embeddings_lru._require_numpy("test operation")
        finally:
            embeddings_lru.HAS_NUMPY = original_has_numpy


class TestCacheManagerConcurrency:
    """Tests for EmbeddingCacheManager thread safety."""

    def test_concurrent_get_cache(self):
        """Test concurrent get_cache calls are thread-safe."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCacheManager

        manager = EmbeddingCacheManager()
        caches = []
        errors = []

        def get_cache(debate_id: str):
            try:
                cache = manager.get_cache(debate_id)
                caches.append((debate_id, cache))
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(20):
            t = threading.Thread(target=get_cache, args=(f"debate-{i % 5}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(caches) == 20

        # Same debate_id should return same cache
        debate_caches = {}
        for debate_id, cache in caches:
            if debate_id not in debate_caches:
                debate_caches[debate_id] = cache
            else:
                assert debate_caches[debate_id] is cache

    def test_concurrent_cleanup(self):
        """Test concurrent cleanup operations are thread-safe."""
        from aragora.debate.cache.embeddings_lru import EmbeddingCacheManager

        manager = EmbeddingCacheManager()

        # Create some caches
        for i in range(10):
            manager.get_cache(f"debate-{i}")

        errors = []

        def cleanup_cache(debate_id: str):
            try:
                manager.cleanup(debate_id)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(10):
            t = threading.Thread(target=cleanup_cache, args=(f"debate-{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        assert manager.get_stats()["active_debates"] == 0


class TestModuleExports:
    """Tests for module __all__ exports."""

    def test_all_exports_exist(self):
        """Test all exported names exist in module."""
        from aragora.debate.cache import embeddings_lru

        for name in embeddings_lru.__all__:
            assert hasattr(embeddings_lru, name), f"Missing export: {name}"

    def test_expected_exports(self):
        """Test expected names are exported."""
        from aragora.debate.cache.embeddings_lru import __all__

        expected = [
            "EmbeddingCache",
            "EmbeddingCacheManager",
            "get_embedding_cache",
            "get_scoped_embedding_cache",
            "cleanup_embedding_cache",
            "reset_embedding_cache",
        ]
        for name in expected:
            assert name in __all__, f"Missing expected export: {name}"
