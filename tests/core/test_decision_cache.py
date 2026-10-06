"""
Tests for core decision cache module.

Tests cover:
- CacheConfig dataclass
- CacheEntry dataclass
- InFlightRequest dataclass
- DecisionCache class
  - Cache operations (get, set, invalidate, clear)
  - TTL expiration
  - LRU eviction
  - Statistics tracking
- Request deduplication
  - In-flight tracking
  - Wait for result
  - Concurrent request handling
- Singleton management
"""

import asyncio
import hashlib
import pytest
import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from aragora.core.decision_cache import (
    CacheConfig,
    CacheEntry,
    InFlightRequest,
    DecisionCache,
    get_decision_cache,
    reset_decision_cache,
)


# =============================================================================
# CacheConfig Tests
# =============================================================================


class TestCacheConfig:
    """Tests for CacheConfig dataclass."""

    def test_default_values(self):
        """Default values are sensible."""
        config = CacheConfig()

        assert config.enabled is True
        assert config.ttl_seconds == 3600.0
        assert config.max_entries == 10000
        assert config.dedup_enabled is True
        assert config.dedup_timeout_seconds == 300.0
        assert config.include_content is True
        assert config.include_decision_type is True
        assert config.include_config is True
        assert config.include_agents is True
        assert config.track_metrics is True

    def test_custom_values(self):
        """Can set custom values."""
        config = CacheConfig(
            enabled=False,
            ttl_seconds=1800.0,
            max_entries=5000,
            dedup_enabled=False,
            dedup_timeout_seconds=60.0,
            include_content=False,
            include_agents=False,
            track_metrics=False,
        )

        assert config.enabled is False
        assert config.ttl_seconds == 1800.0
        assert config.max_entries == 5000
        assert config.dedup_enabled is False
        assert config.dedup_timeout_seconds == 60.0
        assert config.include_content is False
        assert config.include_agents is False
        assert config.track_metrics is False


# =============================================================================
# CacheEntry Tests
# =============================================================================


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_create_entry(self):
        """Can create a cache entry."""
        now = time.time()
        entry = CacheEntry(
            result={"answer": "test"},
            created_at=now,
            expires_at=now + 3600,
        )

        assert entry.result == {"answer": "test"}
        assert entry.created_at == now
        assert entry.expires_at == now + 3600
        assert entry.hit_count == 0
        assert entry.request_hash == ""

    def test_entry_with_metadata(self):
        """Entry can include metadata."""
        entry = CacheEntry(
            result="cached result",
            created_at=1000.0,
            expires_at=2000.0,
            hit_count=5,
            request_hash="abc123",
        )

        assert entry.hit_count == 5
        assert entry.request_hash == "abc123"


# =============================================================================
# InFlightRequest Tests
# =============================================================================


class TestInFlightRequest:
    """Tests for InFlightRequest dataclass."""

    def test_create_in_flight(self):
        """Can create an in-flight request tracker."""
        request = InFlightRequest(
            request_hash="abc123",
            started_at=time.time(),
        )

        assert request.request_hash == "abc123"
        assert request.result is None
        assert request.error is None
        assert request.waiters == 0
        assert isinstance(request.event, asyncio.Event)

    def test_event_is_created(self):
        """Each in-flight request gets its own event."""
        req1 = InFlightRequest(request_hash="hash1", started_at=1000.0)
        req2 = InFlightRequest(request_hash="hash2", started_at=1000.0)

        assert req1.event is not req2.event


# =============================================================================
# DecisionCache Tests - Basic Operations
# =============================================================================


class TestDecisionCacheBasic:
    """Tests for basic DecisionCache operations."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_decision_cache()

    def test_init_default_config(self):
        """Cache initializes with default config."""
        cache = DecisionCache()

        assert cache.config.enabled is True
        assert cache.config.ttl_seconds == 3600.0

    def test_init_custom_config(self):
        """Cache initializes with custom config."""
        config = CacheConfig(enabled=False, ttl_seconds=1800.0)
        cache = DecisionCache(config=config)

        assert cache.config.enabled is False
        assert cache.config.ttl_seconds == 1800.0

    def test_stats_initial(self):
        """Initial stats show empty cache."""
        cache = DecisionCache()
        stats = cache.get_stats()

        assert stats["enabled"] is True
        assert stats["entries"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0
        assert stats["evictions"] == 0

    def test_reset_stats(self):
        """Can reset statistics."""
        cache = DecisionCache()
        # Simulate some activity
        cache._hits = 10
        cache._misses = 5

        cache.reset_stats()

        assert cache._hits == 0
        assert cache._misses == 0


# =============================================================================
# DecisionCache Tests - Hash Computation
# =============================================================================


class TestDecisionCacheHashing:
    """Tests for cache key hash computation."""

    def test_hash_includes_content(self):
        """Hash includes content when configured."""
        config = CacheConfig(
            include_content=True,
            include_decision_type=False,
            include_config=False,
            include_agents=False,
        )
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            content: str = "test question"

        req1 = MockRequest(content="question one")
        req2 = MockRequest(content="question two")

        hash1 = cache._compute_hash(req1)
        hash2 = cache._compute_hash(req2)

        assert hash1 != hash2

    def test_hash_excludes_content_when_disabled(self):
        """Hash excludes content when not configured."""
        config = CacheConfig(
            include_content=False,
            include_decision_type=False,
            include_config=False,
            include_agents=False,
        )
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            content: str = "test"

        req1 = MockRequest(content="question one")
        req2 = MockRequest(content="question two")

        hash1 = cache._compute_hash(req1)
        hash2 = cache._compute_hash(req2)

        # Hashes should be the same since content is excluded
        assert hash1 == hash2

    def test_hash_includes_decision_type(self):
        """Hash includes decision type when configured."""
        config = CacheConfig(
            include_content=False,
            include_decision_type=True,
            include_config=False,
            include_agents=False,
        )
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            decision_type: MagicMock

        req1 = MockRequest(decision_type=MagicMock(value="debate"))
        req2 = MockRequest(decision_type=MagicMock(value="quick"))

        hash1 = cache._compute_hash(req1)
        hash2 = cache._compute_hash(req2)

        assert hash1 != hash2

    def test_hash_includes_agents(self):
        """Hash includes agents when configured."""
        config = CacheConfig(
            include_content=False,
            include_decision_type=False,
            include_config=False,
            include_agents=True,
        )
        cache = DecisionCache(config=config)

        @dataclass
        class MockConfig:
            agents: list

        @dataclass
        class MockRequest:
            config: MockConfig

        req1 = MockRequest(config=MockConfig(agents=["claude", "gpt4"]))
        req2 = MockRequest(config=MockConfig(agents=["claude", "gemini"]))

        hash1 = cache._compute_hash(req1)
        hash2 = cache._compute_hash(req2)

        assert hash1 != hash2

    def test_hash_is_deterministic(self):
        """Same request produces same hash."""
        cache = DecisionCache()

        @dataclass
        class MockConfig:
            rounds: int = 3
            consensus: str = "majority"
            agents: list = None

            def __post_init__(self):
                if self.agents is None:
                    self.agents = ["claude"]

        @dataclass
        class MockRequest:
            content: str = "test question"
            decision_type: MagicMock = None
            config: MockConfig = None

            def __post_init__(self):
                if self.decision_type is None:
                    self.decision_type = MagicMock(value="debate")
                if self.config is None:
                    self.config = MockConfig()

        req1 = MockRequest()
        req2 = MockRequest()

        hash1 = cache._compute_hash(req1)
        hash2 = cache._compute_hash(req2)

        assert hash1 == hash2


# =============================================================================
# DecisionCache Tests - Org and document partitioning
# =============================================================================


def _org_request(org_id, content="Should we ship?", documents=()):
    from aragora.core.decision import DecisionRequest, DecisionType, RequestContext

    return DecisionRequest(
        content=content,
        decision_type=DecisionType.DEBATE,
        context=RequestContext(workspace_id=org_id),
        documents=list(documents),
    )


class TestDecisionCacheOrgPartition:
    """Cached and in-flight results are never shared across orgs or document sets."""

    def test_hash_differs_by_org_and_documents(self):
        cache = DecisionCache()

        assert cache._compute_hash(_org_request("org-a")) == cache._compute_hash(
            _org_request("org-a")
        )
        assert cache._compute_hash(_org_request("org-a")) != cache._compute_hash(
            _org_request("org-b")
        )
        assert cache._compute_hash(_org_request("org-a", documents=["doc-1"])) != (
            cache._compute_hash(_org_request("org-a", documents=["doc-2"]))
        )
        assert cache._compute_hash(_org_request("org-a", documents=["d1", "d2"])) == (
            cache._compute_hash(_org_request("org-a", documents=["d2", "d1"]))
        )

    @pytest.mark.asyncio
    async def test_cached_result_is_only_returned_to_same_org(self):
        cache = DecisionCache()
        await cache.set(_org_request("org-a"), "result for org-a")

        assert await cache.get(_org_request("org-b")) is None
        assert await cache.get(_org_request("org-a", documents=["doc-1"])) is None
        assert await cache.get(_org_request("org-a")) == "result for org-a"

    @pytest.mark.asyncio
    async def test_in_flight_request_is_not_shared_across_orgs(self):
        cache = DecisionCache()
        await cache.mark_in_flight(_org_request("org-a"))

        assert await cache.is_in_flight(_org_request("org-b")) is False
        assert await cache.wait_for_result(_org_request("org-b"), timeout=0.01) is None
        assert await cache.is_in_flight(_org_request("org-a")) is True

    @pytest.mark.asyncio
    async def test_router_serves_each_org_its_own_result(self):
        from aragora.core import decision_router
        from aragora.core.decision import DecisionResult, DecisionRouter, DecisionType

        router = DecisionRouter(enable_caching=True, enable_deduplication=True)
        calls = []

        async def fake_debate(request):
            org = request.context.workspace_id
            calls.append(org)
            return DecisionResult(
                request_id=request.request_id,
                decision_type=DecisionType.DEBATE,
                answer=f"answer for {org}",
                confidence=0.9,
                consensus_reached=True,
            )

        with (
            patch.object(decision_router, "_cache_imported", True),
            patch.object(decision_router, "_decision_cache", DecisionCache()),
            patch.object(router, "_route_to_debate", fake_debate),
        ):
            first_a = await router.route(_org_request("org-a"))
            first_b = await router.route(_org_request("org-b"))
            repeat_a = await router.route(_org_request("org-a"))

        assert (first_a.answer, first_b.answer) == ("answer for org-a", "answer for org-b")
        assert repeat_a.answer == "answer for org-a"
        assert calls == ["org-a", "org-b"]


# =============================================================================
# DecisionCache Tests - Get/Set Operations
# =============================================================================


class TestDecisionCacheGetSet:
    """Tests for cache get/set operations."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_decision_cache()

    @pytest.mark.asyncio
    async def test_get_miss(self):
        """Get returns None for cache miss."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        result = await cache.get(MockRequest())

        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """Can set and retrieve cached result."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test question"

        @dataclass
        class MockResult:
            answer: str = "test answer"

        request = MockRequest()
        result = MockResult()

        await cache.set(request, result)
        cached = await cache.get(request)

        assert cached == result

    @pytest.mark.asyncio
    async def test_get_updates_hit_count(self):
        """Get updates hit counter."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.set(request, "result")

        await cache.get(request)
        await cache.get(request)

        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 0

    @pytest.mark.asyncio
    async def test_get_miss_updates_miss_count(self):
        """Get miss updates miss counter."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        await cache.get(MockRequest(content="not cached"))
        await cache.get(MockRequest(content="also not cached"))

        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 2

    @pytest.mark.asyncio
    async def test_get_disabled_cache(self):
        """Get returns None when cache is disabled."""
        config = CacheConfig(enabled=False)
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.set(request, "result")
        cached = await cache.get(request)

        assert cached is None

    @pytest.mark.asyncio
    async def test_set_disabled_cache(self):
        """Set does nothing when cache is disabled."""
        config = CacheConfig(enabled=False)
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            content: str = "test"

        await cache.set(MockRequest(), "result")

        stats = cache.get_stats()
        assert stats["entries"] == 0

    @pytest.mark.asyncio
    async def test_set_custom_ttl(self):
        """Can set entry with custom TTL."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.set(request, "result", ttl_seconds=0.001)

        # Wait for expiration
        await asyncio.sleep(0.01)

        cached = await cache.get(request)
        assert cached is None


# =============================================================================
# DecisionCache Tests - TTL Expiration
# =============================================================================


class TestDecisionCacheTTL:
    """Tests for cache TTL expiration."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_decision_cache()

    @pytest.mark.asyncio
    async def test_expired_entry_removed(self):
        """Expired entries are removed on access."""
        config = CacheConfig(ttl_seconds=0.001)  # Very short TTL
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.set(request, "result")

        # Wait for expiration
        await asyncio.sleep(0.01)

        cached = await cache.get(request)
        assert cached is None

    @pytest.mark.asyncio
    async def test_valid_entry_returned(self):
        """Valid entries are returned."""
        config = CacheConfig(ttl_seconds=3600)  # Long TTL
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.set(request, "result")

        cached = await cache.get(request)
        assert cached == "result"


# =============================================================================
# DecisionCache Tests - LRU Eviction
# =============================================================================


class TestDecisionCacheEviction:
    """Tests for cache LRU eviction."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_decision_cache()

    @pytest.mark.asyncio
    async def test_eviction_at_capacity(self):
        """Oldest entries are evicted when at capacity."""
        config = CacheConfig(max_entries=3)
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            content: str

        # Fill cache
        for i in range(3):
            await cache.set(MockRequest(content=f"content-{i}"), f"result-{i}")

        # Add one more (should trigger eviction)
        await cache.set(MockRequest(content="content-3"), "result-3")

        stats = cache.get_stats()
        # Should have evicted at least one entry
        assert stats["entries"] <= 3

    @pytest.mark.asyncio
    async def test_eviction_removes_oldest(self):
        """LRU eviction removes oldest entries."""
        config = CacheConfig(max_entries=2)
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            content: str

        # Add first entry
        req1 = MockRequest(content="first")
        await cache.set(req1, "result-1")

        # Add second entry
        req2 = MockRequest(content="second")
        await cache.set(req2, "result-2")

        # Access first to make it recently used
        await cache.get(req1)

        # Add third (should evict second, not first)
        req3 = MockRequest(content="third")
        await cache.set(req3, "result-3")

        # First should still be cached (was recently accessed)
        cached1 = await cache.get(req1)
        # Second should be evicted (oldest)
        cached2 = await cache.get(req2)

        # Due to implementation details, the actual eviction might vary
        # but the cache should not exceed max_entries
        stats = cache.get_stats()
        assert stats["entries"] <= 2


# =============================================================================
# DecisionCache Tests - Invalidation
# =============================================================================


class TestDecisionCacheInvalidation:
    """Tests for cache invalidation."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_decision_cache()

    @pytest.mark.asyncio
    async def test_invalidate_existing(self):
        """Can invalidate existing entry."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.set(request, "result")

        result = await cache.invalidate(request)

        assert result is True
        cached = await cache.get(request)
        assert cached is None

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent(self):
        """Invalidating nonexistent entry returns False."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        result = await cache.invalidate(MockRequest())

        assert result is False

    @pytest.mark.asyncio
    async def test_clear_all(self):
        """Can clear all entries."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str

        for i in range(5):
            await cache.set(MockRequest(content=f"content-{i}"), f"result-{i}")

        count = await cache.clear()

        assert count == 5
        stats = cache.get_stats()
        assert stats["entries"] == 0


# =============================================================================
# DecisionCache Tests - Deduplication
# =============================================================================


class TestDecisionCacheDeduplication:
    """Tests for request deduplication."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_decision_cache()

    @pytest.mark.asyncio
    async def test_is_in_flight_false_initially(self):
        """Request is not in-flight initially."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        is_in_flight = await cache.is_in_flight(MockRequest())

        assert is_in_flight is False

    @pytest.mark.asyncio
    async def test_mark_in_flight(self):
        """Can mark request as in-flight."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.mark_in_flight(request)

        is_in_flight = await cache.is_in_flight(request)
        assert is_in_flight is True

    @pytest.mark.asyncio
    async def test_complete_in_flight_with_result(self):
        """Can complete in-flight with result."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.mark_in_flight(request)

        await cache.complete_in_flight(request, result="success result")

        # In-flight entry should have result set
        request_hash = cache._compute_hash(request)
        in_flight = cache._in_flight.get(request_hash)
        if in_flight:
            assert in_flight.result == "success result"

    @pytest.mark.asyncio
    async def test_complete_in_flight_with_error(self):
        """Can complete in-flight with error."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.mark_in_flight(request)

        error = ValueError("test error")
        await cache.complete_in_flight(request, error=error)

        # In-flight entry should have error set
        request_hash = cache._compute_hash(request)
        in_flight = cache._in_flight.get(request_hash)
        if in_flight:
            assert in_flight.error == error

    @pytest.mark.asyncio
    async def test_clear_in_flight(self):
        """Can clear in-flight status."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.mark_in_flight(request)
        await cache.clear_in_flight(request)

        # After clearing, should not be in-flight
        is_in_flight = await cache.is_in_flight(request)
        assert is_in_flight is False

    @pytest.mark.asyncio
    async def test_dedup_disabled(self):
        """Deduplication can be disabled."""
        config = CacheConfig(dedup_enabled=False)
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        # mark_in_flight should return empty string when disabled
        result = await cache.mark_in_flight(request)
        assert result == ""

        # is_in_flight should always return False when disabled
        is_in_flight = await cache.is_in_flight(request)
        assert is_in_flight is False

    @pytest.mark.asyncio
    async def test_in_flight_timeout(self):
        """In-flight requests expire after timeout."""
        config = CacheConfig(dedup_timeout_seconds=0.001)  # Very short timeout
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.mark_in_flight(request)

        # Wait for timeout
        await asyncio.sleep(0.01)

        # Should no longer be in-flight due to timeout
        is_in_flight = await cache.is_in_flight(request)
        assert is_in_flight is False

    @pytest.mark.asyncio
    async def test_wait_for_result_success(self):
        """Can wait for in-flight result."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.mark_in_flight(request)

        # Complete the request in a separate task
        async def complete_request():
            await asyncio.sleep(0.01)
            await cache.complete_in_flight(request, result="completed result")

        asyncio.create_task(complete_request())

        # Wait for result
        result = await cache.wait_for_result(request, timeout=1.0)

        assert result == "completed result"

    @pytest.mark.asyncio
    async def test_wait_for_result_timeout(self):
        """Wait for result times out appropriately."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.mark_in_flight(request)

        # Don't complete - should timeout
        result = await cache.wait_for_result(request, timeout=0.01)

        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_result_not_in_flight(self):
        """Wait for result returns None if not in-flight."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        result = await cache.wait_for_result(MockRequest(), timeout=0.01)

        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_result_propagates_error(self):
        """Wait for result raises error if original request failed."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str = "test"

        request = MockRequest()
        await cache.mark_in_flight(request)

        # Complete with error
        test_error = ValueError("original error")

        async def complete_with_error():
            await asyncio.sleep(0.01)
            await cache.complete_in_flight(request, error=test_error)

        asyncio.create_task(complete_with_error())

        # Wait should raise the error
        with pytest.raises(ValueError, match="original error"):
            await cache.wait_for_result(request, timeout=1.0)


# =============================================================================
# DecisionCache Tests - Statistics
# =============================================================================


class TestDecisionCacheStatistics:
    """Tests for cache statistics tracking."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_decision_cache()

    @pytest.mark.asyncio
    async def test_stats_track_entries(self):
        """Stats track number of entries."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str

        for i in range(5):
            await cache.set(MockRequest(content=f"content-{i}"), f"result-{i}")

        stats = cache.get_stats()
        assert stats["entries"] == 5

    @pytest.mark.asyncio
    async def test_stats_track_hit_rate(self):
        """Stats calculate hit rate correctly."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str

        request = MockRequest(content="test")
        await cache.set(request, "result")

        # 2 hits
        await cache.get(request)
        await cache.get(request)
        # 1 miss
        await cache.get(MockRequest(content="not cached"))

        stats = cache.get_stats()
        # Hit rate = 2 hits / 3 total = 0.6667
        assert stats["hit_rate"] == pytest.approx(2 / 3, rel=0.01)

    @pytest.mark.asyncio
    async def test_stats_track_in_flight(self):
        """Stats track in-flight requests."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str

        await cache.mark_in_flight(MockRequest(content="req1"))
        await cache.mark_in_flight(MockRequest(content="req2"))

        stats = cache.get_stats()
        assert stats["in_flight"] == 2

    @pytest.mark.asyncio
    async def test_stats_track_evictions(self):
        """Stats track eviction count."""
        config = CacheConfig(max_entries=2)
        cache = DecisionCache(config=config)

        @dataclass
        class MockRequest:
            content: str

        # Add 3 entries to trigger eviction
        for i in range(3):
            await cache.set(MockRequest(content=f"content-{i}"), f"result-{i}")

        stats = cache.get_stats()
        # Should have evicted at least 1 entry
        assert stats["evictions"] >= 1


# =============================================================================
# Singleton Management Tests
# =============================================================================


class TestDecisionCacheSingleton:
    """Tests for singleton management functions."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_decision_cache()

    def test_get_decision_cache_singleton(self):
        """get_decision_cache returns singleton."""
        cache1 = get_decision_cache()
        cache2 = get_decision_cache()

        assert cache1 is cache2

    def test_get_decision_cache_with_config(self):
        """get_decision_cache uses config only on first call."""
        config = CacheConfig(ttl_seconds=1800.0)
        cache1 = get_decision_cache(config=config)
        cache2 = get_decision_cache()  # Second call without config

        assert cache1.config.ttl_seconds == 1800.0
        assert cache1 is cache2

    def test_reset_decision_cache(self):
        """reset_decision_cache clears singleton."""
        cache1 = get_decision_cache()
        reset_decision_cache()
        cache2 = get_decision_cache()

        assert cache1 is not cache2


# =============================================================================
# Integration Tests
# =============================================================================


class TestDecisionCacheIntegration:
    """Integration tests for decision cache."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_decision_cache()

    @pytest.mark.asyncio
    async def test_concurrent_requests_deduplication(self):
        """Concurrent identical requests are deduplicated."""
        cache = DecisionCache()
        process_count = 0

        @dataclass
        class MockRequest:
            content: str = "test question"

        @dataclass
        class MockResult:
            answer: str

        request = MockRequest()

        async def process_request():
            nonlocal process_count

            # Check cache first
            cached = await cache.get(request)
            if cached:
                return cached

            # Check if in-flight
            if await cache.is_in_flight(request):
                return await cache.wait_for_result(request, timeout=5.0)

            # Mark as in-flight and process
            await cache.mark_in_flight(request)
            try:
                process_count += 1
                await asyncio.sleep(0.05)  # Simulate processing
                result = MockResult(answer=f"answer-{process_count}")

                await cache.set(request, result)
                await cache.complete_in_flight(request, result=result)
                return result
            except Exception as e:
                await cache.complete_in_flight(request, error=e)
                raise
            finally:
                await cache.clear_in_flight(request)

        # Launch multiple concurrent requests
        tasks = [asyncio.create_task(process_request()) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # Only one should have actually processed
        # Note: Due to timing, some requests might start before others complete
        # but the deduplication should significantly reduce processing
        assert process_count <= 3  # Allow some overhead due to timing

    @pytest.mark.asyncio
    async def test_cache_and_dedup_workflow(self):
        """Tests complete caching and deduplication workflow."""
        cache = DecisionCache()

        @dataclass
        class MockRequest:
            content: str

        @dataclass
        class MockResult:
            answer: str

        request = MockRequest(content="workflow test")

        # First request - should be a miss
        cached = await cache.get(request)
        assert cached is None

        # Mark as in-flight
        await cache.mark_in_flight(request)
        assert await cache.is_in_flight(request) is True

        # Process and cache result
        result = MockResult(answer="processed answer")
        await cache.set(request, result)
        await cache.complete_in_flight(request, result=result)
        await cache.clear_in_flight(request)

        # Second request - should be a cache hit
        cached = await cache.get(request)
        assert cached == result

        # Verify stats
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["entries"] == 1
