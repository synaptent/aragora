"""
Continuum Memory System - Medium Tier Operations.

The medium tier is designed for tactical learning with:
- 24 hour half-life for confidence decay
- Moderate learning rate with gradual decay
- Per-debate-round update frequency

TTL: 1 hour (session memory)
Use case: Session memory, debate round context
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from aragora.memory.tier_manager import MemoryTier
from aragora.resilience.retry import PROVIDER_RETRY_POLICIES, with_retry
from aragora.utils.datetime_helpers import utc_now_iso_naive

if TYPE_CHECKING:
    from aragora.memory.continuum.base import ContinuumMemoryEntry

logger = logging.getLogger(__name__)

# Retry configuration for memory operations
_MEMORY_RETRY_CONFIG = PROVIDER_RETRY_POLICIES["memory"]

# Medium tier constants
MEDIUM_TIER_HALF_LIFE_HOURS = 24  # 24 hour (1 day) half-life
MEDIUM_TIER_TTL_HOURS = 1  # 1 hour TTL for session memory
MEDIUM_TIER_DECAY_RATE = 1  # Decay coefficient (1 = daily decay)


class MediumTierMixin:
    """
    Mixin providing medium tier operations for ContinuumMemory.

    The medium tier handles tactical learning and session context with:
    - 24-hour half-life for moderate decay
    - Balanced learning rate
    - Debate-round level granularity

    Requirements when used as mixin:
        The host class must provide:
        - connection(): Context manager returning sqlite3.Connection
        - event_emitter: Optional EventEmitterProtocol for events
        - hyperparams: Dict containing tier configuration
    """

    # These must be provided by the main class
    hyperparams: dict[str, Any]
    event_emitter: Any

    def connection(self) -> Any:
        """Get database connection context manager."""
        ...

    def store_medium(
        self,
        id: str,
        content: str,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> ContinuumMemoryEntry:
        """
        Store a memory in the medium tier.

        Medium tier entries have:
        - 24-hour half-life
        - Moderate learning rate
        - Tactical pattern recognition

        Args:
            id: Unique identifier for the memory
            content: The memory content
            importance: 0-1 importance score
            metadata: Optional additional data

        Returns:
            The created memory entry
        """
        from aragora.memory.continuum.base import ContinuumMemoryEntry

        now: str = utc_now_iso_naive()

        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO continuum_memory
                (id, tier, content, importance, surprise_score, consolidation_score,
                 update_count, success_count, failure_count, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, 0.0, 0.0, 1, 0, 0, ?, ?, ?)
                """,
                (
                    id,
                    MemoryTier.MEDIUM.value,
                    content,
                    importance,
                    now,
                    now,
                    json.dumps(metadata or {}),
                ),
            )
            conn.commit()

        entry = ContinuumMemoryEntry(
            id=id,
            tier=MemoryTier.MEDIUM,
            content=content,
            importance=importance,
            surprise_score=0.0,
            consolidation_score=0.0,
            update_count=1,
            success_count=0,
            failure_count=0,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        # Emit event for cross-subsystem tracking
        if self.event_emitter:
            try:
                self.event_emitter.emit_sync(
                    event_type="memory_stored",
                    debate_id="",
                    memory_id=id,
                    tier=MemoryTier.MEDIUM.value,
                    importance=importance,
                    content_length=len(content),
                )
            except (ImportError, AttributeError, TypeError):
                pass

        return entry

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def store_medium_async(
        self,
        id: str,
        content: str,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> ContinuumMemoryEntry:
        """Async wrapper for store_medium()."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.store_medium(id, content, importance, metadata),
        )

    def retrieve_medium(
        self,
        query: str | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> list[ContinuumMemoryEntry]:
        """
        Retrieve memories from the medium tier with 24-hour decay.

        Medium tier memories decay at a daily rate, balancing
        recency with persistence.

        Args:
            query: Optional keyword filter for content
            limit: Maximum entries to return
            min_importance: Minimum importance threshold

        Returns:
            List of ContinuumMemoryEntry objects sorted by decay-adjusted score
        """
        from aragora.memory.continuum.base import AwaitableList, ContinuumMemoryEntry
        from aragora.utils.json_helpers import safe_json_loads

        # Build keyword filter clause for SQL
        keyword_clause: str = ""
        keyword_params: list[str] = []
        if query:
            MAX_QUERY_KEYWORDS: int = 50
            keywords: list[str] = [
                kw.strip().lower() for kw in query.split()[:MAX_QUERY_KEYWORDS] if kw.strip()
            ]
            if keywords:
                keyword_conditions: list[str] = ["INSTR(LOWER(content), ?) > 0" for _ in keywords]
                keyword_clause = f" AND ({' OR '.join(keyword_conditions)})"
                keyword_params = keywords

        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()

            # Medium tier decay: 1x coefficient (decays daily)
            cursor.execute(
                f"""
                SELECT id, tier, content, importance, surprise_score, consolidation_score,
                       update_count, success_count, failure_count, created_at, updated_at, metadata,
                       (importance * (1 + surprise_score) *
                        (1.0 / (1 + (julianday('now') - julianday(updated_at)) * {MEDIUM_TIER_DECAY_RATE}))) as score
                FROM continuum_memory
                WHERE tier = 'medium'
                  AND importance >= ?
                  {keyword_clause}
                ORDER BY score DESC
                LIMIT ?
                """,  # noqa: S608 -- dynamic clause from internal state
                (min_importance, *keyword_params, limit),
            )

            rows = cursor.fetchall()

        entries: list[ContinuumMemoryEntry] = []
        for row in rows:
            entry = ContinuumMemoryEntry(
                id=row[0],
                tier=MemoryTier(row[1]),
                content=row[2],
                importance=row[3],
                surprise_score=row[4],
                consolidation_score=row[5],
                update_count=row[6],
                success_count=row[7],
                failure_count=row[8],
                created_at=row[9],
                updated_at=row[10],
                metadata=safe_json_loads(row[11], {}),
            )
            entries.append(entry)

        return AwaitableList(entries)

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def retrieve_medium_async(
        self,
        query: str | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> list[ContinuumMemoryEntry]:
        """Async wrapper for retrieve_medium()."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.retrieve_medium(query, limit, min_importance),
        )

    def get_medium_tier_stats(self) -> dict[str, Any]:
        """
        Get statistics specifically for the medium tier.

        Returns:
            Dict with count, averages, and utilization metrics
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as count,
                    AVG(importance) as avg_importance,
                    AVG(surprise_score) as avg_surprise,
                    AVG(consolidation_score) as avg_consolidation,
                    AVG(update_count) as avg_updates,
                    MIN(created_at) as oldest_entry,
                    MAX(updated_at) as newest_update
                FROM continuum_memory
                WHERE tier = 'medium'
                """)
            row = cursor.fetchone()

        max_entries = self.hyperparams["max_entries_per_tier"]["medium"]
        count = row[0] or 0

        return {
            "tier": "medium",
            "half_life_hours": MEDIUM_TIER_HALF_LIFE_HOURS,
            "ttl_hours": MEDIUM_TIER_TTL_HOURS,
            "count": count,
            "avg_importance": round(row[1] or 0, 3),
            "avg_surprise": round(row[2] or 0, 3),
            "avg_consolidation": round(row[3] or 0, 3),
            "avg_updates": round(row[4] or 0, 1),
            "oldest_entry": row[5],
            "newest_update": row[6],
            "max_entries": max_entries,
            "utilization": round(count / max_entries, 3) if max_entries > 0 else 0.0,
        }


__all__ = [
    "MediumTierMixin",
    "MEDIUM_TIER_HALF_LIFE_HOURS",
    "MEDIUM_TIER_TTL_HOURS",
    "MEDIUM_TIER_DECAY_RATE",
]
