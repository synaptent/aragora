"""
Decision Cache and Request Deduplication.

Provides caching and deduplication for decision requests to:
- Avoid re-processing identical requests within a TTL window
- Deduplicate concurrent identical requests (wait for first to complete)
- Cache decision results for quick retrieval

Usage:
    from aragora.core.decision_cache import DecisionCache, get_decision_cache

    cache = get_decision_cache()

    # Check for cached result
    cached = await cache.get(request)
    if cached:
        return cached

    # Check if request is in-flight
    if await cache.is_in_flight(request):
        return await cache.wait_for_result(request)

    # Mark as in-flight and process
    await cache.mark_in_flight(request)
    try:
        result = await process(request)
        await cache.set(request, result)
        return result
    finally:
        await cache.clear_in_flight(request)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from aragora.config import DEFAULT_ROUNDS

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached decision result."""

    result: Any
    created_at: float
    expires_at: float
    hit_count: int = 0
    request_hash: str = ""


@dataclass
class InFlightRequest:
    """Tracks an in-flight request for deduplication."""

    request_hash: str
    started_at: float
    event: asyncio.Event = field(default_factory=asyncio.Event)
    result: Any | None = None
    error: Exception | None = None
    waiters: int = 0


@dataclass
class CacheConfig:
    """Configuration for decision cache."""

    # Cache settings
    enabled: bool = True
    ttl_seconds: float = 3600.0  # 1 hour default
    max_entries: int = 10000

    # Deduplication settings
    dedup_enabled: bool = True
    dedup_timeout_seconds: float = 300.0  # 5 minutes max wait

    # What to include in cache key
    include_content: bool = True
    include_decision_type: bool = True
    include_config: bool = True
    include_agents: bool = True

    # Metrics
    track_metrics: bool = True


class DecisionCache:
    """
    Cache for decision results with request deduplication.

    Features:
    - LRU-style eviction when max entries reached
    - TTL-based expiration
    - In-flight request deduplication
    - Thread-safe async operations
    """

    def __init__(self, config: CacheConfig | None = None):
        """Initialize the cache."""
        self.config = config or CacheConfig()
        self._cache: dict[str, CacheEntry] = {}
        self._in_flight: dict[str, InFlightRequest] = {}
        self._lock = asyncio.Lock()

        # Metrics
        self._hits = 0
        self._misses = 0
        self._dedup_hits = 0
        self._evictions = 0

    def _compute_hash(self, request: Any) -> str:
        """Compute a hash for the request to use as cache key."""
        key_parts = []

        if self.config.include_content:
            content = getattr(request, "content", "")
            key_parts.append(f"content:{content}")

        if self.config.include_decision_type:
            dt = getattr(request, "decision_type", None)
            if dt:
                key_parts.append(f"type:{dt.value if hasattr(dt, 'value') else dt}")

        if self.config.include_config:
            config = getattr(request, "config", None)
            if config:
                # Include key config fields
                rounds = getattr(config, "rounds", DEFAULT_ROUNDS)
                consensus = getattr(config, "consensus", "majority")
                key_parts.append(f"rounds:{rounds}")
                key_parts.append(f"consensus:{consensus}")

        if self.config.include_agents:
            config = getattr(request, "config", None)
            if config:
                agents = getattr(config, "agents", [])
                if agents:
                    key_parts.append(f"agents:{','.join(sorted(agents))}")

        # Results carry tenant data (including document-grounded answers), so
        # an entry or an in-flight wait is never shared across orgs or document
        # sets, whatever the config says. JSON keeps the parts unambiguous.
        context = getattr(request, "context", None)
        key_parts.append(f"org:{getattr(context, 'workspace_id', None) or ''}")
        key_parts.append(f"tenant:{getattr(context, 'tenant_id', None) or ''}")
        documents = getattr(request, "documents", None) or []
        key_parts.append(f"documents:{json.dumps(sorted(str(d) for d in documents))}")

        key_str = json.dumps(key_parts)
        return hashlib.sha256(key_str.encode()).hexdigest()[:32]

    async def get(self, request: Any) -> Any | None:
        """
        Get cached result for a request.

        Args:
            request: DecisionRequest to look up

        Returns:
            Cached DecisionResult or None if not found/expired
        """
        if not self.config.enabled:
            return None

        request_hash = self._compute_hash(request)
        now = time.time()

        async with self._lock:
            entry = self._cache.get(request_hash)
            if entry is None:
                self._misses += 1
                return None

            # Check expiration
            if now > entry.expires_at:
                del self._cache[request_hash]
                self._misses += 1
                return None

            # Update hit count
            entry.hit_count += 1
            self._hits += 1

            logger.debug("Cache hit for request hash %s", request_hash[:8])
            return entry.result

    async def set(
        self,
        request: Any,
        result: Any,
        ttl_seconds: float | None = None,
    ) -> None:
        """
        Cache a result for a request.

        Args:
            request: The DecisionRequest
            result: The DecisionResult to cache
            ttl_seconds: Optional custom TTL (uses config default if not provided)
        """
        if not self.config.enabled:
            return

        request_hash = self._compute_hash(request)
        now = time.time()
        ttl = ttl_seconds or self.config.ttl_seconds

        async with self._lock:
            # Evict if at capacity
            if len(self._cache) >= self.config.max_entries:
                await self._evict_oldest()

            self._cache[request_hash] = CacheEntry(
                result=result,
                created_at=now,
                expires_at=now + ttl,
                request_hash=request_hash,
            )

        logger.debug("Cached result for request hash %s, TTL=%ss", request_hash[:8], ttl)

    async def _evict_oldest(self) -> None:
        """Evict oldest entries to make room. Called with lock held."""
        if not self._cache:
            return

        # Sort by created_at and remove oldest 10%
        sorted_entries = sorted(
            self._cache.items(),
            key=lambda x: x[1].created_at,
        )
        evict_count = max(1, len(sorted_entries) // 10)

        for hash_key, _ in sorted_entries[:evict_count]:
            del self._cache[hash_key]
            self._evictions += 1

    async def invalidate(self, request: Any) -> bool:
        """
        Invalidate cached result for a request.

        Args:
            request: The DecisionRequest to invalidate

        Returns:
            True if an entry was invalidated
        """
        request_hash = self._compute_hash(request)

        async with self._lock:
            if request_hash in self._cache:
                del self._cache[request_hash]
                return True
            return False

    async def clear(self) -> int:
        """
        Clear all cached entries.

        Returns:
            Number of entries cleared
        """
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    # =========================================================================
    # Request Deduplication
    # =========================================================================

    async def is_in_flight(self, request: Any) -> bool:
        """Check if an identical request is currently being processed."""
        if not self.config.dedup_enabled:
            return False

        request_hash = self._compute_hash(request)

        async with self._lock:
            in_flight = self._in_flight.get(request_hash)
            if in_flight is None:
                return False

            # Check if timed out
            elapsed = time.time() - in_flight.started_at
            if elapsed > self.config.dedup_timeout_seconds:
                # Timed out, clean up
                del self._in_flight[request_hash]
                return False

            return True

    async def mark_in_flight(self, request: Any) -> str:
        """
        Mark a request as in-flight for deduplication.

        Args:
            request: The DecisionRequest being processed

        Returns:
            The request hash
        """
        if not self.config.dedup_enabled:
            return ""

        request_hash = self._compute_hash(request)

        async with self._lock:
            self._in_flight[request_hash] = InFlightRequest(
                request_hash=request_hash,
                started_at=time.time(),
            )

        return request_hash

    async def complete_in_flight(
        self,
        request: Any,
        result: Any | None = None,
        error: Exception | None = None,
    ) -> None:
        """
        Mark an in-flight request as complete and notify waiters.

        Args:
            request: The DecisionRequest that completed
            result: The result if successful
            error: The error if failed
        """
        if not self.config.dedup_enabled:
            return

        request_hash = self._compute_hash(request)

        async with self._lock:
            in_flight = self._in_flight.get(request_hash)
            if in_flight:
                in_flight.result = result
                in_flight.error = error
                in_flight.event.set()
                # Keep entry briefly so waiters can get result
                # Will be cleaned up on next access or timeout

    async def clear_in_flight(self, request: Any) -> None:
        """
        Clear in-flight status after a delay (allows waiters to get result).

        Args:
            request: The DecisionRequest to clear
        """
        if not self.config.dedup_enabled:
            return

        request_hash = self._compute_hash(request)

        # Delay cleanup to allow waiters to retrieve result
        await asyncio.sleep(0.1)

        async with self._lock:
            if request_hash in self._in_flight:
                del self._in_flight[request_hash]

    async def wait_for_result(
        self,
        request: Any,
        timeout: float | None = None,
    ) -> Any | None:
        """
        Wait for an in-flight request to complete and get its result.

        Args:
            request: The DecisionRequest to wait for
            timeout: Optional timeout in seconds

        Returns:
            The result if successful, None if timed out

        Raises:
            Exception if the original request failed
        """
        if not self.config.dedup_enabled:
            return None

        request_hash = self._compute_hash(request)
        timeout = timeout or self.config.dedup_timeout_seconds

        async with self._lock:
            in_flight = self._in_flight.get(request_hash)
            if not in_flight:
                return None
            in_flight.waiters += 1
            event = in_flight.event

        try:
            # Wait for completion
            await asyncio.wait_for(event.wait(), timeout=timeout)
            self._dedup_hits += 1

            async with self._lock:
                in_flight = self._in_flight.get(request_hash)
                if in_flight:
                    if in_flight.error:
                        raise in_flight.error
                    return in_flight.result

            return None

        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for in-flight request %s", request_hash[:8])
            return None

    # =========================================================================
    # Metrics
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0.0

        return {
            "enabled": self.config.enabled,
            "dedup_enabled": self.config.dedup_enabled,
            "entries": len(self._cache),
            "max_entries": self.config.max_entries,
            "in_flight": len(self._in_flight),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
            "dedup_hits": self._dedup_hits,
            "evictions": self._evictions,
            "ttl_seconds": self.config.ttl_seconds,
        }

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        self._hits = 0
        self._misses = 0
        self._dedup_hits = 0
        self._evictions = 0


# =============================================================================
# Singleton
# =============================================================================

_decision_cache_instance: DecisionCache | None = None


def get_decision_cache(config: CacheConfig | None = None) -> DecisionCache:
    """
    Get the singleton decision cache instance.

    Args:
        config: Optional configuration (only used on first call)

    Returns:
        The DecisionCache instance
    """
    global _decision_cache_instance
    if _decision_cache_instance is None:
        _decision_cache_instance = DecisionCache(config=config)
    return _decision_cache_instance


def reset_decision_cache() -> None:
    """Reset the singleton instance (for testing)."""
    global _decision_cache_instance
    _decision_cache_instance = None


__all__ = [
    "DecisionCache",
    "CacheConfig",
    "CacheEntry",
    "InFlightRequest",
    "get_decision_cache",
    "reset_decision_cache",
]
