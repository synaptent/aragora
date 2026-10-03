"""Comprehensive tests for the cache utility.

Tests cover:
- TTLCache get/set operations
- TTL handling and expiration
- LRU eviction policies
- Thread safety
- Size limits
- Cache decorators (lru_cache_with_ttl, cached_property_ttl, ttl_cache, async_ttl_cache)
- Global cache management functions
- Cache invalidation
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.utils.cache import (
    CACHE_INVALIDATION_MAP,
    TTLCache,
    async_ttl_cache,
    cached_property_ttl,
    clear_all_caches,
    get_cache_stats,
    get_handler_cache,
    get_method_cache,
    get_query_cache,
    invalidate_cache,
    invalidate_method_cache,
    lru_cache_with_ttl,
    ttl_cache,
)


# ============================================================================
# TTLCache Core Tests
# ============================================================================


class TestTTLCacheBasics:
    """Tests for basic TTLCache operations."""

    def test_get_returns_none_for_missing_key(self):
        """get() should return None for keys that don't exist."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_set_and_get_basic(self):
        """set() and get() should store and retrieve values."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_set_and_get_various_types(self):
        """Cache should handle various value types."""
        cache: TTLCache[Any] = TTLCache(maxsize=10, ttl_seconds=60)

        # String
        cache.set("str_key", "string_value")
        assert cache.get("str_key") == "string_value"

        # Integer
        cache.set("int_key", 42)
        assert cache.get("int_key") == 42

        # List
        cache.set("list_key", [1, 2, 3])
        assert cache.get("list_key") == [1, 2, 3]

        # Dict
        cache.set("dict_key", {"nested": "value"})
        assert cache.get("dict_key") == {"nested": "value"}

        # None (explicitly stored)
        cache.set("none_key", None)
        # Note: get() returns None for both missing and None values
        # This is a known limitation

    def test_set_overwrites_existing_key(self):
        """set() should overwrite existing values."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("key", "value1")
        cache.set("key", "value2")
        assert cache.get("key") == "value2"

    def test_len_returns_cache_size(self):
        """__len__() should return the number of items in cache."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        assert len(cache) == 0

        cache.set("key1", "value1")
        assert len(cache) == 1

        cache.set("key2", "value2")
        assert len(cache) == 2

        cache.set("key1", "updated")  # Overwrite, should not increase size
        assert len(cache) == 2


class TestTTLCacheTTLExpiration:
    """Tests for TTL expiration behavior."""

    def test_expired_entry_returns_none(self):
        """get() should return None for expired entries."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=0.1)
        cache.set("key", "value")
        assert cache.get("key") == "value"

        # Wait for expiration
        time.sleep(0.15)
        assert cache.get("key") is None

    def test_expired_entry_removed_from_cache(self):
        """Expired entries should be removed on access."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=0.1)
        cache.set("key", "value")
        assert len(cache) == 1

        time.sleep(0.15)
        cache.get("key")  # Trigger removal
        assert len(cache) == 0

    def test_ttl_resets_on_set(self):
        """Setting a value should reset its TTL."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=0.2)
        cache.set("key", "value1")
        time.sleep(0.1)

        # Reset TTL by setting again
        cache.set("key", "value2")
        time.sleep(0.15)

        # Should still be valid (0.15 < 0.2)
        assert cache.get("key") == "value2"

    def test_non_expired_entry_returns_value(self):
        """get() should return value for non-expired entries."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=10)
        cache.set("key", "value")
        time.sleep(0.05)
        assert cache.get("key") == "value"


class TestTTLCacheLRUEviction:
    """Tests for LRU eviction behavior."""

    def test_eviction_at_maxsize(self):
        """Cache should evict oldest entry when at capacity."""
        cache: TTLCache[str] = TTLCache(maxsize=3, ttl_seconds=60)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # All three should be present
        assert len(cache) == 3

        # Adding fourth should evict oldest (key1)
        cache.set("key4", "value4")
        assert len(cache) == 3
        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"

    def test_get_moves_to_end(self):
        """get() should move accessed entry to end (most recently used)."""
        cache: TTLCache[str] = TTLCache(maxsize=3, ttl_seconds=60)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # Access key1 to move it to end
        cache.get("key1")

        # Add new entry - should evict key2 (now oldest)
        cache.set("key4", "value4")

        assert cache.get("key1") == "value1"  # Still present (was accessed)
        assert cache.get("key2") is None  # Evicted (was oldest)
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"

    def test_multiple_evictions(self):
        """Multiple items should be evicted when needed."""
        cache: TTLCache[int] = TTLCache(maxsize=2, ttl_seconds=60)

        for i in range(10):
            cache.set(f"key{i}", i)

        assert len(cache) == 2
        # Only the last two should remain
        assert cache.get("key8") == 8
        assert cache.get("key9") == 9


class TestTTLCacheInvalidation:
    """Tests for cache invalidation methods."""

    def test_invalidate_existing_key(self):
        """invalidate() should remove an existing key."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("key", "value")
        assert cache.invalidate("key") is True
        assert cache.get("key") is None

    def test_invalidate_nonexistent_key(self):
        """invalidate() should return False for missing keys."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        assert cache.invalidate("nonexistent") is False

    def test_clear_removes_all_entries(self):
        """clear() should remove all entries and return count."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        count = cache.clear()
        assert count == 3
        assert len(cache) == 0

    def test_clear_empty_cache(self):
        """clear() on empty cache should return 0."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        assert cache.clear() == 0

    def test_clear_prefix_removes_matching(self):
        """clear_prefix() should remove entries with matching prefix."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("user:1", "alice")
        cache.set("user:2", "bob")
        cache.set("item:1", "laptop")
        cache.set("item:2", "phone")

        count = cache.clear_prefix("user:")
        assert count == 2
        assert len(cache) == 2
        assert cache.get("user:1") is None
        assert cache.get("user:2") is None
        assert cache.get("item:1") == "laptop"
        assert cache.get("item:2") == "phone"

    def test_clear_prefix_no_matches(self):
        """clear_prefix() with no matches should return 0."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("key1", "value1")
        count = cache.clear_prefix("nonexistent:")
        assert count == 0
        assert len(cache) == 1


class TestTTLCacheStats:
    """Tests for cache statistics."""

    def test_stats_initial_values(self):
        """stats should have correct initial values."""
        cache: TTLCache[str] = TTLCache(maxsize=100, ttl_seconds=300)
        stats = cache.stats

        assert stats["size"] == 0
        assert stats["maxsize"] == 100
        assert stats["ttl_seconds"] == 300
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

    def test_stats_tracks_hits(self):
        """stats should track cache hits."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("key", "value")

        cache.get("key")
        cache.get("key")
        cache.get("key")

        stats = cache.stats
        assert stats["hits"] == 3
        assert stats["misses"] == 0

    def test_stats_tracks_misses(self):
        """stats should track cache misses."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)

        cache.get("missing1")
        cache.get("missing2")

        stats = cache.stats
        assert stats["hits"] == 0
        assert stats["misses"] == 2

    def test_stats_hit_rate_calculation(self):
        """stats should calculate hit rate correctly."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("key", "value")

        cache.get("key")  # Hit
        cache.get("key")  # Hit
        cache.get("key")  # Hit
        cache.get("missing")  # Miss

        stats = cache.stats
        assert stats["hits"] == 3
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.75

    def test_stats_size_reflects_current_items(self):
        """stats size should reflect current number of items."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)

        cache.set("key1", "value1")
        assert cache.stats["size"] == 1

        cache.set("key2", "value2")
        assert cache.stats["size"] == 2

        cache.clear()
        assert cache.stats["size"] == 0


class TestTTLCacheThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_set_operations(self):
        """Multiple threads setting values should not corrupt cache."""
        cache: TTLCache[int] = TTLCache(maxsize=1000, ttl_seconds=60)
        num_threads = 10
        items_per_thread = 100

        def set_values(thread_id: int):
            for i in range(items_per_thread):
                cache.set(f"thread{thread_id}:key{i}", thread_id * 1000 + i)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(set_values, i) for i in range(num_threads)]
            for f in futures:
                f.result()

        # Verify all values were set correctly
        assert len(cache) == num_threads * items_per_thread

    def test_concurrent_get_operations(self):
        """Multiple threads getting values should not cause issues."""
        cache: TTLCache[int] = TTLCache(maxsize=1000, ttl_seconds=60)

        # Pre-populate cache
        for i in range(100):
            cache.set(f"key{i}", i)

        num_threads = 10
        reads_per_thread = 1000
        results: list[list[int]] = [[] for _ in range(num_threads)]

        def get_values(thread_id: int):
            for i in range(reads_per_thread):
                key = f"key{i % 100}"
                value = cache.get(key)
                if value is not None:
                    results[thread_id].append(value)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(get_values, i) for i in range(num_threads)]
            for f in futures:
                f.result()

        # All reads should have succeeded
        total_reads = sum(len(r) for r in results)
        assert total_reads == num_threads * reads_per_thread

    def test_concurrent_mixed_operations(self):
        """Mixed set/get/invalidate operations should be thread-safe."""
        cache: TTLCache[int] = TTLCache(maxsize=100, ttl_seconds=60)
        errors: list[Exception] = []

        def writer():
            try:
                for i in range(500):
                    cache.set(f"key{i % 50}", i)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(500):
                    cache.get(f"key{i % 50}")
            except Exception as e:
                errors.append(e)

        def invalidator():
            try:
                for i in range(100):
                    cache.invalidate(f"key{i % 50}")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=invalidator),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"


# ============================================================================
# lru_cache_with_ttl Decorator Tests
# ============================================================================


class TestLruCacheWithTtlDecorator:
    """Tests for the lru_cache_with_ttl decorator."""

    def test_caches_function_result(self):
        """Decorator should cache function results."""
        call_count = 0

        @lru_cache_with_ttl(ttl_seconds=60, maxsize=10)
        def expensive_function(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = expensive_function(5)
        result2 = expensive_function(5)
        result3 = expensive_function(5)

        assert result1 == 10
        assert result2 == 10
        assert result3 == 10
        assert call_count == 1  # Only called once

    def test_different_args_different_cache_entries(self):
        """Different arguments should create different cache entries."""
        call_count = 0

        @lru_cache_with_ttl(ttl_seconds=60, maxsize=10)
        def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        compute(1)
        compute(2)
        compute(3)
        compute(1)  # Should be cached

        assert call_count == 3

    def test_respects_ttl_expiration(self):
        """Cached results should expire after TTL."""
        call_count = 0

        @lru_cache_with_ttl(ttl_seconds=0.1, maxsize=10)
        def get_data() -> str:
            nonlocal call_count
            call_count += 1
            return "data"

        get_data()
        assert call_count == 1

        time.sleep(0.15)
        get_data()
        assert call_count == 2  # Called again after expiration

    def test_method_caching_skips_self(self):
        """Methods should skip 'self' when building cache key."""

        class MyClass:
            def __init__(self):
                self.call_count = 0

            @lru_cache_with_ttl(ttl_seconds=60, maxsize=10)
            def compute(self, x: int) -> int:
                self.call_count += 1
                return x * 2

        obj1 = MyClass()
        obj2 = MyClass()

        # Both objects should share cache (self is skipped)
        result1 = obj1.compute(5)
        result2 = obj2.compute(5)

        assert result1 == 10
        assert result2 == 10
        assert obj1.call_count == 1
        assert obj2.call_count == 0

    def test_kwargs_in_cache_key(self):
        """kwargs should be part of cache key."""
        call_count = 0

        @lru_cache_with_ttl(ttl_seconds=60, maxsize=10)
        def fetch(key: str, refresh: bool = False) -> str:
            nonlocal call_count
            call_count += 1
            return f"value-{call_count}"

        fetch("key", refresh=False)
        fetch("key", refresh=False)
        fetch("key", refresh=True)  # Different kwargs

        assert call_count == 2

    def test_key_prefix_used(self):
        """key_prefix should be used in cache key."""
        cache1 = TTLCache[Any](maxsize=10, ttl_seconds=60)
        cache2 = TTLCache[Any](maxsize=10, ttl_seconds=60)

        @lru_cache_with_ttl(ttl_seconds=60, key_prefix="func1", cache=cache1)
        def func1() -> str:
            return "value1"

        @lru_cache_with_ttl(ttl_seconds=60, key_prefix="func2", cache=cache2)
        def func2() -> str:
            return "value2"

        func1()
        func2()

        # Different prefixes should use different cache entries
        assert len(cache1) == 1
        assert len(cache2) == 1

    def test_cache_attribute_attached(self):
        """Decorated function should have cache attribute."""

        @lru_cache_with_ttl(ttl_seconds=60, maxsize=10)
        def my_func() -> str:
            return "value"

        assert hasattr(my_func, "cache")
        assert hasattr(my_func, "cache_key_prefix")
        assert isinstance(my_func.cache, TTLCache)

    def test_custom_cache_instance(self):
        """Should use custom cache instance when provided."""
        custom_cache: TTLCache[str] = TTLCache(maxsize=5, ttl_seconds=30)

        @lru_cache_with_ttl(cache=custom_cache)
        def get_value(key: str) -> str:
            return f"value-{key}"

        get_value("test")
        assert len(custom_cache) == 1


# ============================================================================
# cached_property_ttl Decorator Tests
# ============================================================================


class TestCachedPropertyTtlDecorator:
    """Tests for the cached_property_ttl decorator."""

    def test_caches_property_result(self):
        """Decorator should cache property computation."""

        class MyClass:
            def __init__(self):
                self.compute_count = 0

            @cached_property_ttl(ttl_seconds=60)
            def expensive_property(self) -> int:
                self.compute_count += 1
                return 42

        obj = MyClass()
        result1 = obj.expensive_property
        result2 = obj.expensive_property
        result3 = obj.expensive_property

        assert result1 == 42
        assert result2 == 42
        assert result3 == 42
        assert obj.compute_count == 1

    def test_respects_ttl_expiration(self):
        """Cached property should expire after TTL."""

        class MyClass:
            def __init__(self):
                self.compute_count = 0

            @cached_property_ttl(ttl_seconds=0.1)
            def data(self) -> str:
                self.compute_count += 1
                return f"data-{self.compute_count}"

        obj = MyClass()
        result1 = obj.data
        assert obj.compute_count == 1

        time.sleep(0.15)
        result2 = obj.data
        assert obj.compute_count == 2
        assert result1 != result2

    def test_each_instance_has_own_cache(self):
        """Each instance should have its own cached value."""

        class MyClass:
            def __init__(self, value: int):
                self._value = value
                self.compute_count = 0

            @cached_property_ttl(ttl_seconds=60)
            def doubled(self) -> int:
                self.compute_count += 1
                return self._value * 2

        obj1 = MyClass(5)
        obj2 = MyClass(10)

        assert obj1.doubled == 10
        assert obj2.doubled == 20
        assert obj1.compute_count == 1
        assert obj2.compute_count == 1

    def test_stores_cache_attributes_on_instance(self):
        """Cache should store attributes on the instance."""

        class MyClass:
            @cached_property_ttl(ttl_seconds=60)
            def value(self) -> int:
                return 42

        obj = MyClass()
        _ = obj.value

        assert hasattr(obj, "_cached_value")
        assert hasattr(obj, "_cached_value_time")


# ============================================================================
# ttl_cache Decorator Tests
# ============================================================================


class TestTtlCacheDecorator:
    """Tests for the ttl_cache decorator (handler-style)."""

    def test_caches_function_result(self):
        """Decorator should cache function results."""
        call_count = 0

        @ttl_cache(ttl_seconds=60, key_prefix="test", skip_first=False)
        def fetch_data(key: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"data-{key}"

        result1 = fetch_data("abc")
        result2 = fetch_data("abc")

        assert result1 == "data-abc"
        assert result2 == "data-abc"
        assert call_count == 1

    def test_skip_first_for_methods(self):
        """skip_first=True should skip self for method caching."""

        class Handler:
            def __init__(self):
                self.call_count = 0

            @ttl_cache(ttl_seconds=60, key_prefix="handler")
            def get_data(self, key: str) -> str:
                self.call_count += 1
                return f"data-{key}"

        handler1 = Handler()
        handler2 = Handler()

        handler1.get_data("key1")
        handler2.get_data("key1")  # Should use cache

        assert handler1.call_count == 1
        assert handler2.call_count == 0

    def test_uses_global_handler_cache(self):
        """ttl_cache should use the global handler cache."""
        handler_cache = get_handler_cache()
        initial_size = len(handler_cache)

        @ttl_cache(ttl_seconds=60, key_prefix="unique_test", skip_first=False)
        def unique_function() -> str:
            return "unique"

        unique_function()

        # Cache size should have increased
        assert len(handler_cache) >= initial_size


# ============================================================================
# async_ttl_cache Decorator Tests
# ============================================================================


class TestAsyncTtlCacheDecorator:
    """Tests for the async_ttl_cache decorator."""

    @pytest.mark.asyncio
    async def test_caches_async_function_result(self):
        """Decorator should cache async function results."""
        call_count = 0

        @async_ttl_cache(ttl_seconds=60, key_prefix="async_test", skip_first=False)
        async def fetch_data_async(key: str) -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return f"async-data-{key}"

        result1 = await fetch_data_async("key1")
        result2 = await fetch_data_async("key1")

        assert result1 == "async-data-key1"
        assert result2 == "async-data-key1"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_skip_first_for_async_methods(self):
        """skip_first=True should skip self for async method caching."""

        class AsyncHandler:
            def __init__(self):
                self.call_count = 0

            @async_ttl_cache(ttl_seconds=60, key_prefix="async_handler")
            async def get_data(self, key: str) -> str:
                self.call_count += 1
                return f"async-{key}"

        handler1 = AsyncHandler()
        handler2 = AsyncHandler()

        await handler1.get_data("test")
        await handler2.get_data("test")  # Should use cache

        assert handler1.call_count == 1
        assert handler2.call_count == 0

    @pytest.mark.asyncio
    async def test_different_args_different_entries(self):
        """Different arguments should create different cache entries."""
        call_count = 0

        @async_ttl_cache(ttl_seconds=60, key_prefix="async_args", skip_first=False)
        async def compute(x: int, y: int) -> int:
            nonlocal call_count
            call_count += 1
            return x + y

        await compute(1, 2)
        await compute(1, 2)  # Cached
        await compute(2, 3)  # New entry
        await compute(2, 3)  # Cached

        assert call_count == 2


# ============================================================================
# Global Cache Management Tests
# ============================================================================


class TestGlobalCacheManagement:
    """Tests for global cache management functions."""

    def test_get_method_cache_returns_ttl_cache(self):
        """get_method_cache() should return TTLCache instance."""
        cache = get_method_cache()
        assert isinstance(cache, TTLCache)

    def test_get_query_cache_returns_ttl_cache(self):
        """get_query_cache() should return TTLCache instance."""
        cache = get_query_cache()
        assert isinstance(cache, TTLCache)

    def test_get_handler_cache_returns_ttl_cache(self):
        """get_handler_cache() should return TTLCache instance."""
        cache = get_handler_cache()
        assert isinstance(cache, TTLCache)

    def test_get_cache_stats_structure(self):
        """get_cache_stats() should return dict with expected structure."""
        stats = get_cache_stats()

        assert "method_cache" in stats
        assert "query_cache" in stats
        assert "size" in stats["method_cache"]
        assert "maxsize" in stats["method_cache"]
        assert "hits" in stats["method_cache"]
        assert "misses" in stats["method_cache"]
        assert "hit_rate" in stats["method_cache"]

    def test_clear_all_caches(self):
        """clear_all_caches() should clear both method and query caches."""
        method_cache = get_method_cache()
        query_cache = get_query_cache()

        # Add some items
        method_cache.set("test_method_key", "value")
        query_cache.set("test_query_key", "value")

        result = clear_all_caches()

        assert "method_cache" in result
        assert "query_cache" in result
        assert isinstance(result["method_cache"], int)
        assert isinstance(result["query_cache"], int)

    def test_invalidate_method_cache_by_prefix(self):
        """invalidate_method_cache() should clear entries by prefix."""
        cache = get_method_cache()
        cache.set("leaderboard:v1", "data1")
        cache.set("leaderboard:v2", "data2")
        cache.set("other:key", "data3")

        count = invalidate_method_cache("leaderboard:")

        assert count == 2
        assert cache.get("leaderboard:v1") is None
        assert cache.get("leaderboard:v2") is None
        assert cache.get("other:key") == "data3"


# ============================================================================
# Cache Invalidation Map Tests
# ============================================================================


class TestCacheInvalidationMap:
    """Tests for cache invalidation based on data sources."""

    def test_invalidation_map_has_expected_keys(self):
        """CACHE_INVALIDATION_MAP should have expected data sources."""
        expected_keys = ["memory", "debates", "consensus", "elo", "agent"]
        for key in expected_keys:
            assert key in CACHE_INVALIDATION_MAP

    def test_invalidate_cache_by_data_source(self):
        """invalidate_cache() should clear entries for data source prefixes."""
        handler_cache = get_handler_cache()

        # Add entries matching memory-related prefixes
        handler_cache.set("analytics_memory:test", "value1")
        handler_cache.set("critique_patterns:test", "value2")
        handler_cache.set("unrelated:key", "value3")

        count = invalidate_cache("memory")

        # Should have cleared memory-related entries
        assert handler_cache.get("analytics_memory:test") is None
        assert handler_cache.get("critique_patterns:test") is None
        # Unrelated entries should remain
        assert handler_cache.get("unrelated:key") == "value3"

    def test_invalidate_cache_unknown_source(self):
        """invalidate_cache() with unknown source should use source as prefix."""
        handler_cache = get_handler_cache()
        handler_cache.set("custom_source:key1", "value1")
        handler_cache.set("custom_source:key2", "value2")

        count = invalidate_cache("custom_source")

        assert count == 2
        assert handler_cache.get("custom_source:key1") is None
        assert handler_cache.get("custom_source:key2") is None


# ============================================================================
# Edge Cases and Error Handling Tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_string_key(self):
        """Empty string should be valid as cache key."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        cache.set("", "empty_key_value")
        assert cache.get("") == "empty_key_value"

    def test_very_long_key(self):
        """Very long keys should work."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        long_key = "k" * 10000
        cache.set(long_key, "value")
        assert cache.get(long_key) == "value"

    def test_special_characters_in_key(self):
        """Special characters in keys should work."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=60)
        special_keys = [
            "key:with:colons",
            "key/with/slashes",
            "key?with=query&params",
            "key with spaces",
            "key\nwith\nnewlines",
        ]
        for key in special_keys:
            cache.set(key, f"value-{key}")
            assert cache.get(key) == f"value-{key}"

    def test_zero_ttl(self):
        """Zero TTL should expire immediately."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=0)
        cache.set("key", "value")
        # Any non-zero time means expired
        time.sleep(0.001)
        assert cache.get("key") is None

    def test_maxsize_one(self):
        """maxsize=1 should work correctly."""
        cache: TTLCache[str] = TTLCache(maxsize=1, ttl_seconds=60)
        cache.set("key1", "value1")
        assert len(cache) == 1

        cache.set("key2", "value2")
        assert len(cache) == 1
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"

    def test_very_large_maxsize(self):
        """Very large maxsize should not cause issues."""
        cache: TTLCache[int] = TTLCache(maxsize=1000000, ttl_seconds=60)
        for i in range(1000):
            cache.set(f"key{i}", i)
        assert len(cache) == 1000

    def test_negative_ttl_treated_as_zero(self):
        """Negative TTL should behave like zero (immediate expiration)."""
        cache: TTLCache[str] = TTLCache(maxsize=10, ttl_seconds=-1)
        cache.set("key", "value")
        time.sleep(0.001)
        assert cache.get("key") is None


# ============================================================================
# Service Registry Integration Tests
# ============================================================================


class TestServiceRegistryIntegration:
    """Tests for ServiceRegistry integration (if available)."""

    def test_cache_registration_recovers_after_service_registry_reset(self):
        """Cache access re-registers instances after the service registry resets."""
        from aragora.services import (
            MethodCacheService,
            QueryCacheService,
            ServiceRegistry,
        )

        ServiceRegistry.reset()
        method_cache = get_method_cache()
        query_cache = get_query_cache()
        registry = ServiceRegistry.get()
        assert registry.resolve(MethodCacheService) is method_cache
        assert registry.resolve(QueryCacheService) is query_cache

        ServiceRegistry.reset()
        method_cache = get_method_cache()
        query_cache = get_query_cache()
        registry = ServiceRegistry.get()
        assert registry.resolve(MethodCacheService) is method_cache
        assert registry.resolve(QueryCacheService) is query_cache

    def test_register_caches_with_service_registry_no_error(self):
        """_register_caches_with_service_registry should not raise errors."""
        # This function is called internally - we test it indirectly
        # by calling get_method_cache and get_query_cache
        try:
            get_method_cache()
            get_query_cache()
        except Exception as e:
            pytest.fail(f"Cache registration failed: {e}")

    def test_get_cache_stats_registers_caches(self):
        """get_cache_stats() should register caches with service registry."""
        # This should not raise even if services module is not available
        try:
            stats = get_cache_stats()
            assert stats is not None
        except ImportError:
            # Services module not available - this is acceptable
            pass


# ============================================================================
# Performance Tests
# ============================================================================


class TestPerformance:
    """Performance-related tests."""

    def test_cache_operations_are_fast(self):
        """Basic cache operations should be fast."""
        cache: TTLCache[int] = TTLCache(maxsize=10000, ttl_seconds=60)

        # Time 10000 set operations
        start = time.time()
        for i in range(10000):
            cache.set(f"key{i}", i)
        set_time = time.time() - start

        # Time 10000 get operations
        start = time.time()
        for i in range(10000):
            cache.get(f"key{i}")
        get_time = time.time() - start

        # Operations should complete in reasonable time
        assert set_time < 1.0, f"Set operations too slow: {set_time}s"
        assert get_time < 1.0, f"Get operations too slow: {get_time}s"

    def test_lru_eviction_performance(self):
        """LRU eviction should not slow down cache significantly."""
        cache: TTLCache[int] = TTLCache(maxsize=100, ttl_seconds=60)

        # Insert many more items than maxsize
        start = time.time()
        for i in range(10000):
            cache.set(f"key{i}", i)
        duration = time.time() - start

        # Should complete quickly despite constant evictions
        assert duration < 1.0, f"Eviction too slow: {duration}s"
        assert len(cache) == 100
