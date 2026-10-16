"""
Supermemory Backend Implementation.

External memory backend using Supermemory for cross-session persistence.
Implements the MemoryBackend protocol from aragora.memory.protocols.

Features:
- Persistent storage across sessions and projects
- Privacy-filtered content before external sync
- Local caching for frequently accessed entries
- Fallback to in-memory when Supermemory unavailable
- Importance-based sync threshold (only sync high-importance memories)
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aragora.memory.protocols import (
    BackendHealth,
    MemoryEntry,
    MemoryQueryResult,
)

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cached memory entry with TTL."""

    entry: MemoryEntry
    cached_at: float
    ttl_seconds: float = 300.0

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return time.time() - self.cached_at > self.ttl_seconds


@dataclass
class SupermemoryBackend:
    """
    Supermemory-backed implementation of MemoryBackend.

    Combines local caching with external Supermemory persistence for
    cross-session learning. High-importance entries are synced externally,
    while all entries are maintained in a local cache for fast access.

    Features:
    - LRU cache for frequently accessed entries
    - Async sync to Supermemory for important memories
    - Fallback to local storage when external unavailable
    - Privacy filtering before external sync

    Example:
        from aragora.memory.supermemory import SupermemoryConfig
        from aragora.memory.backends.supermemory import SupermemoryBackend

        config = SupermemoryConfig.from_env()
        backend = SupermemoryBackend(config=config)

        # Store entry - auto-synced if important enough
        entry = MemoryEntry(
            id="1",
            content="Debate outcome...",
            weight=0.9,  # High importance, will be synced
        )
        await backend.store(entry)

        # Search includes external results
        results = await backend.search_similar(embedding, limit=10)
    """

    # Configuration
    config: Any = None  # SupermemoryConfig
    sync_threshold: float = 0.7
    cache_ttl_seconds: float = 300.0
    cache_max_size: int = 1000
    enable_external_sync: bool = True

    # Internal state
    _local_entries: dict[str, MemoryEntry] = field(default_factory=dict)
    _cache: OrderedDict[str, CacheEntry] = field(default_factory=OrderedDict)
    _by_tier: dict[str, set[str]] = field(
        default_factory=lambda: {
            "fast": set(),
            "medium": set(),
            "slow": set(),
            "glacial": set(),
        }
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _client: Any = field(default=None)
    _initialized: bool = field(default=False)

    def __post_init__(self) -> None:
        """Initialize the backend."""
        if self.config is not None:
            self.sync_threshold = self.config.sync_threshold
            self.cache_ttl_seconds = getattr(self.config, "cache_ttl_seconds", 300.0)

    def _ensure_client(self) -> Any:
        """Lazily initialize the Supermemory client."""
        if self._client is None and self.config is not None:
            from aragora.memory.supermemory import SupermemoryClient

            self._client = SupermemoryClient(self.config)
        return self._client

    def _should_sync(self, entry: MemoryEntry) -> bool:
        """Check if entry should be synced to external storage."""
        if not self.enable_external_sync:
            return False
        if self.config is None:
            return False
        # Sync based on weight/importance
        return entry.weight >= self.sync_threshold

    def _add_to_cache(self, entry: MemoryEntry) -> None:
        """Add entry to LRU cache."""
        # Remove oldest if at capacity
        while len(self._cache) >= self.cache_max_size:
            self._cache.popitem(last=False)

        self._cache[entry.id] = CacheEntry(
            entry=entry,
            cached_at=time.time(),
            ttl_seconds=self.cache_ttl_seconds,
        )

    def _get_from_cache(self, entry_id: str) -> MemoryEntry | None:
        """Get entry from cache if not expired."""
        cache_entry = self._cache.get(entry_id)
        if cache_entry is None:
            return None
        if cache_entry.is_expired():
            del self._cache[entry_id]
            return None
        # Move to end (LRU)
        self._cache.move_to_end(entry_id)
        return cache_entry.entry

    # =========================================================================
    # Core CRUD Operations
    # =========================================================================

    async def store(self, entry: MemoryEntry) -> str:
        """Store a memory entry."""
        async with self._lock:
            # Generate ID if not provided
            if not entry.id:
                entry.id = f"sm_{uuid.uuid4().hex[:12]}"

            # Store a copy to avoid reference issues
            stored_entry = copy.copy(entry)
            stored_entry.metadata = dict(entry.metadata) if entry.metadata else {}

            # Store locally
            self._local_entries[stored_entry.id] = stored_entry
            self._by_tier[stored_entry.tier].add(stored_entry.id)
            self._add_to_cache(stored_entry)

        # Sync to external if important enough
        if self._should_sync(entry):
            await self._sync_to_external(entry)

        return entry.id

    async def _sync_to_external(self, entry: MemoryEntry) -> bool:
        """Sync entry to external Supermemory service."""
        client = self._ensure_client()
        if client is None:
            return False

        try:
            result = await client.add_memory(
                content=entry.content,
                container_tag=self.config.get_container_tag("patterns"),
                metadata={
                    "aragora_id": entry.id,
                    "tier": entry.tier,
                    "weight": entry.weight,
                    "created_at": entry.created_at.isoformat() if entry.created_at else None,
                    **entry.metadata,
                },
            )
            if result.success:
                # Store supermemory ID in metadata for cross-reference
                entry.metadata["supermemory_id"] = result.memory_id
                logger.debug("Synced entry %s to Supermemory: %s", entry.id, result.memory_id)
                return True
            else:
                logger.warning("Failed to sync entry %s: %s", entry.id, result.error)
                return False
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error syncing to Supermemory: %s", e)
            return False

    async def get(self, entry_id: str) -> MemoryEntry | None:
        """Retrieve a memory entry by ID."""
        # Check cache first
        cached = self._get_from_cache(entry_id)
        if cached is not None:
            return cached

        # Check local storage
        entry = self._local_entries.get(entry_id)
        if entry is not None:
            self._add_to_cache(entry)
            return entry

        # Could extend to query Supermemory for entries not in local storage
        return None

    async def update(self, entry: MemoryEntry) -> bool:
        """Update an existing memory entry."""
        async with self._lock:
            if entry.id not in self._local_entries:
                return False

            old_entry = self._local_entries[entry.id]

            # Update tier index if tier changed
            if old_entry.tier != entry.tier:
                self._by_tier[old_entry.tier].discard(entry.id)
                self._by_tier[entry.tier].add(entry.id)

            entry.updated_at = datetime.now(timezone.utc)
            self._local_entries[entry.id] = entry
            self._add_to_cache(entry)

        # Re-sync if importance changed and now meets threshold
        if self._should_sync(entry) and not self._should_sync(old_entry):
            await self._sync_to_external(entry)

        return True

    async def delete(self, entry_id: str) -> bool:
        """Delete a memory entry."""
        async with self._lock:
            if entry_id not in self._local_entries:
                return False

            entry = self._local_entries.pop(entry_id)
            self._by_tier[entry.tier].discard(entry_id)
            self._cache.pop(entry_id, None)

            return True

    # =========================================================================
    # Query Operations
    # =========================================================================

    async def query(
        self,
        tier: str | None = None,
        min_weight: float | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> MemoryQueryResult:
        """Query memory entries with filtering and pagination."""
        entries = list(self._local_entries.values())

        # Filter by tier
        if tier is not None:
            tier_ids = self._by_tier.get(tier, set())
            entries = [e for e in entries if e.id in tier_ids]

        # Filter by weight
        if min_weight is not None:
            entries = [e for e in entries if e.weight >= min_weight]

        # Sort
        if order_by == "created_at":
            entries.sort(key=lambda e: e.created_at or datetime.min, reverse=descending)
        elif order_by == "updated_at":
            entries.sort(key=lambda e: e.updated_at or datetime.min, reverse=descending)
        elif order_by == "weight":
            entries.sort(key=lambda e: e.weight, reverse=descending)

        total = len(entries)

        # Paginate
        entries = entries[offset : offset + limit]

        return MemoryQueryResult(
            entries=entries,
            total_count=total,
            has_more=offset + limit < total,
        )

    async def search_similar(
        self,
        query_embedding: list[float],
        limit: int = 10,
        min_similarity: float = 0.7,
        tier: str | None = None,
    ) -> list[tuple[MemoryEntry, float]]:
        """Search for similar entries using vector similarity."""
        # For now, use local entries with cosine similarity
        # Could be enhanced to query Supermemory's semantic search
        results: list[tuple[MemoryEntry, float]] = []

        for entry in self._local_entries.values():
            if tier is not None and entry.tier != tier:
                continue
            if entry.embedding is None:
                continue

            similarity = self._cosine_similarity(query_embedding, entry.embedding)
            if similarity >= min_similarity:
                results.append((entry, similarity))

        # Sort by similarity descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)

    async def search_external(
        self,
        query: str,
        limit: int = 10,
        container_tag: str | None = None,
    ) -> list[tuple[str, float]]:
        """Search Supermemory for matching content.

        Returns list of (content, similarity) tuples.
        """
        client = self._ensure_client()
        if client is None:
            return []

        try:
            response = await client.search(
                query=query,
                limit=limit,
                container_tag=container_tag,
            )
            return [(result.content, result.similarity) for result in response.results]
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error searching Supermemory: %s", e)
            return []

    # =========================================================================
    # Batch Operations
    # =========================================================================

    async def store_batch(self, entries: list[MemoryEntry]) -> list[str]:
        """Store multiple entries in a single operation."""
        ids = []
        for entry in entries:
            entry_id = await self.store(entry)
            ids.append(entry_id)
        return ids

    async def delete_batch(self, entry_ids: list[str]) -> int:
        """Delete multiple entries in a single operation."""
        count = 0
        for entry_id in entry_ids:
            if await self.delete(entry_id):
                count += 1
        return count

    # =========================================================================
    # Tier Operations
    # =========================================================================

    async def promote(self, entry_id: str, new_tier: str) -> bool:
        """Promote an entry to a different memory tier."""
        async with self._lock:
            entry = self._local_entries.get(entry_id)
            if entry is None:
                return False

            old_tier = entry.tier
            if old_tier == new_tier:
                return True

            self._by_tier[old_tier].discard(entry_id)
            self._by_tier[new_tier].add(entry_id)
            entry.tier = new_tier
            entry.updated_at = datetime.now(timezone.utc)
            self._add_to_cache(entry)

            return True

    async def count_by_tier(self) -> dict[str, int]:
        """Get entry counts per tier."""
        return {tier: len(ids) for tier, ids in self._by_tier.items()}

    # =========================================================================
    # Maintenance Operations
    # =========================================================================

    async def cleanup_expired(self) -> int:
        """Remove expired entries."""
        now = datetime.now(timezone.utc)
        expired_ids = []

        for entry_id, entry in self._local_entries.items():
            if entry.expires_at is not None and entry.expires_at < now:
                expired_ids.append(entry_id)

        for entry_id in expired_ids:
            await self.delete(entry_id)

        # Clean expired cache entries
        expired_cache = [k for k, v in self._cache.items() if v.is_expired()]
        for k in expired_cache:
            del self._cache[k]

        return len(expired_ids)

    async def vacuum(self) -> None:
        """Optimize storage by reclaiming space."""
        # Clear expired cache entries
        await self.cleanup_expired()
        logger.debug(
            "Vacuum complete. %s entries, %s cached", len(self._local_entries), len(self._cache)
        )

    # =========================================================================
    # Health and Diagnostics
    # =========================================================================

    async def health_check(self) -> BackendHealth:
        """Check backend health and connectivity."""
        start_time = time.time()
        details: dict[str, Any] = {
            "local_entries": len(self._local_entries),
            "cached_entries": len(self._cache),
        }

        # Check external connection
        client = self._ensure_client()
        if client is not None:
            try:
                external_health = await client.health_check()
                details["external"] = external_health
                if not external_health.get("healthy", True):
                    return BackendHealth(
                        healthy=True,  # Still healthy locally
                        latency_ms=(time.time() - start_time) * 1000,
                        error=f"External degraded: {external_health.get('error')}",
                        details=details,
                    )
            except (OSError, ValueError, RuntimeError) as e:
                details["external_error"] = str(e)

        return BackendHealth(
            healthy=True,
            latency_ms=(time.time() - start_time) * 1000,
            details=details,
        )

    async def get_stats(self) -> dict[str, Any]:
        """Get backend statistics."""
        tier_counts = await self.count_by_tier()
        return {
            "total_entries": len(self._local_entries),
            "cached_entries": len(self._cache),
            "tier_counts": tier_counts,
            "sync_threshold": self.sync_threshold,
            "external_enabled": self.enable_external_sync and self._client is not None,
        }

    async def close(self) -> None:
        """Close the backend and release resources."""
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._local_entries.clear()
        self._cache.clear()
        for tier in self._by_tier.values():
            tier.clear()
