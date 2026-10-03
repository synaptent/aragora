"""
Knowledge Mound integration mixin for ContinuumMemory.

Provides bidirectional integration with Knowledge Mound including
similarity queries, pre-warming, and reference invalidation.
"""
# mypy: disable-error-code="misc"
# Mixin classes use self: "ContinuumMemory" type hints which mypy doesn't understand

from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from aragora.utils.cache import TTLCache
from aragora.utils.datetime_helpers import utc_now_iso_naive
from aragora.utils.json_helpers import safe_json_loads

from .entry import ContinuumMemoryEntry

if TYPE_CHECKING:
    from aragora.knowledge.mound.adapters.continuum_adapter import ContinuumAdapter
    from .core import ContinuumMemory

logger = logging.getLogger(__name__)

# Cache for KM similarity queries (5 min TTL, 1000 entries)
_km_similarity_cache: TTLCache[list] = TTLCache(maxsize=1000, ttl_seconds=300)


class KMIntegrationMixin:
    """Mixin providing Knowledge Mound integration for ContinuumMemory."""

    _km_adapter: ContinuumAdapter | None

    def set_km_adapter(self: ContinuumMemory, adapter: ContinuumAdapter) -> None:
        """Set the Knowledge Mound adapter for bidirectional sync.

        Args:
            adapter: ContinuumAdapter instance for KM integration
        """
        self._km_adapter = adapter

    def query_km_for_similar(
        self: ContinuumMemory,
        content: str,
        limit: int = 5,
        min_similarity: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Query Knowledge Mound for similar memories (reverse flow).

        Uses TTL caching to avoid redundant queries for same content.

        Args:
            content: Content to find similar memories for
            limit: Maximum results
            min_similarity: Minimum similarity threshold

        Returns:
            List of similar memory items from KM
        """
        if not self._km_adapter:
            return []

        # Generate cache key from content hash + params
        import hashlib

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        cache_key = f"{content_hash}:{limit}:{min_similarity}"

        # Check cache first
        cached = _km_similarity_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            results = self._km_adapter.search_similar(
                content=content,
                limit=limit,
                min_similarity=min_similarity,
            )
            # Cache the results
            _km_similarity_cache.set(cache_key, results)
            return results
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Failed to query KM for similar memories (network): %s", e)
            return []
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Failed to query KM for similar memories (data): %s", e)
            return []
        except (RuntimeError, AttributeError) as e:
            logger.warning("Unexpected error querying KM for similar memories: %s", e)
            return []

    def prewarm_for_query(
        self: ContinuumMemory,
        query: str,
        workspace_id: str | None = None,
        limit: int = 20,
    ) -> int:
        """
        Pre-warm the memory cache for a given query.

        Called by KM->Memory cross-subscriber when Knowledge Mound is queried.
        This ensures related memories are loaded into faster access patterns.

        Args:
            query: The search query to pre-warm for
            workspace_id: Optional workspace filter
            limit: Maximum entries to pre-warm

        Returns:
            Number of entries pre-warmed
        """
        if not query:
            return 0

        try:
            # Retrieve relevant memories to warm cache
            entries: list[ContinuumMemoryEntry] = self.retrieve(
                query=query,
                limit=limit,
                min_importance=0.3,  # Only cache moderately important memories
            )

            if not entries:
                return 0

            # Batch update all entries in a single transaction using executemany
            prewarm_time: str = utc_now_iso_naive()
            current_time: str = utc_now_iso_naive()

            # Prepare batch update data
            update_data: list[tuple[str, str, str]] = []
            for entry in entries:
                if entry.metadata is None:
                    entry.metadata = {}
                entry.metadata["last_prewarm"] = prewarm_time
                metadata_json: str = json.dumps(entry.metadata)
                update_data.append((metadata_json, current_time, entry.id))

            with self.connection() as conn:
                cursor: sqlite3.Cursor = conn.cursor()
                # Use executemany for batch update (more efficient than N individual queries)
                cursor.executemany(
                    """
                    UPDATE continuum_memory
                    SET metadata = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    update_data,
                )
                conn.commit()

            count: int = len(entries)
            logger.debug("Pre-warmed %s memories for query: '%s...'", count, query[:50])
            return count

        except sqlite3.Error as e:
            logger.warning("Memory pre-warm failed (database): %s", e)
            return 0
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Memory pre-warm failed (network): %s", e)
            return 0
        except (RuntimeError, AttributeError, ValueError, TypeError) as e:
            logger.warning("Unexpected error during memory pre-warm: %s", e)
            return 0

    def invalidate_reference(self: ContinuumMemory, node_id: str) -> bool:
        """
        Invalidate any memory references to a KM node.

        Called when a KM node is deleted to clear stale cross-references.

        Args:
            node_id: The Knowledge Mound node ID to invalidate

        Returns:
            True if any references were invalidated
        """
        try:
            updated_count: int = 0
            # Find entries that reference this node and batch update
            with self.connection() as conn:
                cursor: sqlite3.Cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, metadata FROM continuum_memory
                    WHERE metadata LIKE ?
                    """,
                    (f"%{node_id}%",),
                )

                rows: list[tuple[Any, ...]] = cursor.fetchall()

                # Collect updates to perform in batch
                updates: list[tuple[str, str]] = []

                for row in rows:
                    entry_id: str = row[0]
                    metadata: dict[str, Any] = safe_json_loads(row[1], {})
                    modified: bool = False

                    # Remove km_node_id reference if present
                    if metadata.get("km_node_id") == node_id:
                        del metadata["km_node_id"]
                        metadata["km_synced"] = False
                        modified = True

                    # Remove from cross_references if present
                    # Use try/except (EAFP) to avoid O(n) in check + O(n) remove
                    cross_refs: list[str] = metadata.get("cross_references", [])
                    try:
                        cross_refs.remove(node_id)
                        metadata["cross_references"] = cross_refs
                        modified = True
                    except ValueError:
                        pass  # node_id was not in cross_refs

                    if modified:
                        updates.append((json.dumps(metadata), entry_id))
                        updated_count += 1

                # Batch update all modified entries in single transaction
                if updates:
                    cursor.executemany(
                        """
                        UPDATE continuum_memory
                        SET metadata = ?
                        WHERE id = ?
                        """,
                        updates,
                    )
                    conn.commit()

            if updated_count > 0:
                logger.debug("Invalidated %s references to KM node %s", updated_count, node_id)

            return updated_count > 0

        except sqlite3.Error as e:
            logger.warning("Failed to invalidate KM reference %s (database): %s", node_id, e)
            return False
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Failed to invalidate KM reference %s (data): %s", node_id, e)
            return False
        except (RuntimeError, AttributeError) as e:
            logger.warning("Unexpected error invalidating KM reference %s: %s", node_id, e)
            return False


__all__ = ["KMIntegrationMixin", "_km_similarity_cache"]
