"""
Continuum Memory System - Glacial Tier Operations.

The glacial tier is designed for foundational knowledge with:
- 30 day half-life for confidence decay
- Very low learning rate with minimal decay
- Monthly update frequency

TTL: 1 week (long-term patterns)
Use case: Foundational knowledge, long-term patterns, cross-cycle learning

Note: This module provides tier-specific operations. For the full glacial
mixin with cross-session learning capabilities, see continuum_glacial.py
in the parent directory.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aragora.memory.tier_manager import MemoryTier
from aragora.resilience.retry import PROVIDER_RETRY_POLICIES, with_retry
from aragora.utils.datetime_helpers import utc_now_iso_naive

if TYPE_CHECKING:
    from aragora.memory.continuum.base import ContinuumMemoryEntry

logger = logging.getLogger(__name__)

# Retry configuration for memory operations
_MEMORY_RETRY_CONFIG = PROVIDER_RETRY_POLICIES["memory"]

# Glacial tier constants
GLACIAL_TIER_HALF_LIFE_HOURS = 720  # 30 days half-life
GLACIAL_TIER_HALF_LIFE_DAYS = 30
GLACIAL_TIER_TTL_WEEKS = 1  # 1 week TTL for long-term patterns
GLACIAL_TIER_DECAY_RATE = 0.03  # Decay coefficient (~monthly decay)


class GlacialTierMixin:
    """
    Mixin providing glacial tier operations for ContinuumMemory.

    The glacial tier handles foundational knowledge and long-term patterns with:
    - 30-day half-life for very slow decay
    - Very low learning rate
    - Monthly-level granularity

    This mixin provides tier-specific storage and retrieval. For cross-session
    learning capabilities (get_glacial_insights, get_cross_session_patterns),
    see ContinuumGlacialMixin in continuum_glacial.py.

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

    def store_glacial(
        self,
        id: str,
        content: str,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> ContinuumMemoryEntry:
        """
        Store a memory in the glacial tier.

        Glacial tier entries have:
        - 30-day half-life
        - Very low learning rate
        - Foundational knowledge storage

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
                    MemoryTier.GLACIAL.value,
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
            tier=MemoryTier.GLACIAL,
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
                    tier=MemoryTier.GLACIAL.value,
                    importance=importance,
                    content_length=len(content),
                )
            except (ImportError, AttributeError, TypeError):
                pass

        return entry

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def store_glacial_async(
        self,
        id: str,
        content: str,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> ContinuumMemoryEntry:
        """Async wrapper for store_glacial()."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.store_glacial(id, content, importance, metadata),
        )

    def retrieve_glacial(
        self,
        query: str | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> list[ContinuumMemoryEntry]:
        """
        Retrieve memories from the glacial tier with 30-day decay.

        Glacial tier memories decay monthly, preserving foundational
        knowledge across long time periods.

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

            # Glacial tier decay: 0.03x coefficient (decays monthly)
            cursor.execute(
                f"""
                SELECT id, tier, content, importance, surprise_score, consolidation_score,
                       update_count, success_count, failure_count, created_at, updated_at, metadata,
                       COALESCE(red_line, 0), COALESCE(red_line_reason, ''),
                       (importance * (1 + surprise_score) *
                        (1.0 / (1 + (julianday('now') - julianday(updated_at)) * {GLACIAL_TIER_DECAY_RATE}))) as score
                FROM continuum_memory
                WHERE tier = 'glacial'
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
                surprise_score=row[4] or 0.0,
                consolidation_score=row[5] or 0.0,
                update_count=row[6] or 1,
                success_count=row[7] or 0,
                failure_count=row[8] or 0,
                created_at=row[9],
                updated_at=row[10],
                metadata=safe_json_loads(row[11], {}),
                red_line=bool(row[12]),
                red_line_reason=row[13],
            )
            entries.append(entry)

        return AwaitableList(entries)

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def retrieve_glacial_async(
        self,
        query: str | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> list[ContinuumMemoryEntry]:
        """Async wrapper for retrieve_glacial()."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.retrieve_glacial(query, limit, min_importance),
        )

    def calculate_glacial_decay(self, updated_at: str | datetime) -> float:
        """Calculate the confidence decay factor for a glacial tier memory.

        Uses exponential decay with 30-day half-life:
        decay_factor = 0.5^(days_elapsed / 30)

        Args:
            updated_at: Timestamp of last update (ISO string or datetime)

        Returns:
            Decay factor between 0 and 1 (1 = no decay, 0.5 = 30 days old)
        """
        if isinstance(updated_at, str):
            updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        else:
            updated_dt = updated_at

        # Rows are stamped with naive-UTC strings, so age against naive-UTC now
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if updated_dt.tzinfo is not None:
            updated_dt = updated_dt.astimezone(timezone.utc).replace(tzinfo=None)

        days_elapsed = (now - updated_dt).total_seconds() / 86400
        if days_elapsed <= 0:
            return 1.0

        return math.pow(0.5, days_elapsed / GLACIAL_TIER_HALF_LIFE_DAYS)


__all__ = [
    "GlacialTierMixin",
    "GLACIAL_TIER_HALF_LIFE_HOURS",
    "GLACIAL_TIER_HALF_LIFE_DAYS",
    "GLACIAL_TIER_TTL_WEEKS",
    "GLACIAL_TIER_DECAY_RATE",
]
