"""
Continuum Memory Glacial Operations.

Extracted from continuum.py for maintainability.
Provides glacial tier access for cross-session learning patterns.

The glacial tier is designed for long-term pattern retention with:
- 30-day half-life for confidence decay
- Cross-session learning persistence
- Foundational knowledge that informs debates
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Generator

if TYPE_CHECKING:
    from aragora.memory.continuum import ContinuumMemoryEntry
    from aragora.memory.tier_manager import MemoryTier

logger = logging.getLogger(__name__)

# Glacial tier constants
GLACIAL_HALF_LIFE_DAYS = 30
GLACIAL_HALF_LIFE_HOURS = GLACIAL_HALF_LIFE_DAYS * 24


class ContinuumGlacialMixin:
    """
    Mixin providing glacial tier operations for ContinuumMemory.

    Enables cross-session learning by retrieving long-term patterns
    from the glacial tier (30-day half-life foundational knowledge).

    The mixin provides two modes of operation:
    1. As a mixin to ContinuumMemory: Uses host class's connection() and retrieve()
    2. Standalone: Uses its own _glacial_connection() and _glacial_retrieve()

    Requirements when used as mixin:
        The host class must provide:
        - connection(): Context manager returning sqlite3.Connection
        - retrieve(): Memory retrieval with tier filtering
        - hyperparams: Dict containing tier configuration
    """

    # These must be provided by the main class
    hyperparams: dict[str, Any]

    # Optional standalone database path for glacial tier
    _glacial_db_path: str | Path | None = None

    def connection(self) -> Any:
        """Get database connection context manager.

        When used as a mixin with ContinuumMemory, this is provided by SQLiteStore.
        When used standalone, delegates to _glacial_connection().

        Returns a context manager yielding sqlite3.Connection.
        """
        # Check if we have a host class providing connection (via MRO)
        # If not, use standalone glacial connection
        if hasattr(super(), "connection"):
            # Mixin pattern: super() delegates to host class via MRO; mypy cannot resolve this
            return super().connection()  # type: ignore[misc]
        return self._glacial_connection()

    @contextmanager
    def _glacial_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a standalone SQLite connection for glacial tier storage.

        Supports both SQLite (local development) and can be extended
        for PostgreSQL (production) via environment configuration.

        Yields:
            sqlite3.Connection configured for glacial tier storage
        """
        # Get database path from instance, environment, or default
        db_path = self._glacial_db_path
        if db_path is None:
            db_path = os.environ.get("ARAGORA_GLACIAL_DB_PATH")
        if db_path is None:
            from aragora.persistence.db_config import get_db_path, DatabaseType

            db_path = get_db_path(DatabaseType.CONTINUUM_MEMORY)

        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
        finally:
            conn.close()

    def retrieve(
        self,
        query: str | None = None,
        tiers: list[MemoryTier] | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
        include_glacial: bool = True,
        tier: Any | None = None,
    ) -> list[ContinuumMemoryEntry]:
        """Retrieve memories matching criteria.

        When used as a mixin, delegates to ContinuumMemory.retrieve().
        When used standalone, uses _glacial_retrieve() for glacial-only access.

        Args:
            query: Optional keyword filter
            tiers: Filter to specific memory tiers
            limit: Maximum entries to return
            min_importance: Minimum importance threshold
            include_glacial: Whether to include glacial tier
            tier: Single tier filter (alternative to tiers list)

        Returns:
            List of matching ContinuumMemoryEntry objects
        """
        # Check if we have a host class providing retrieve (via MRO)
        if hasattr(super(), "retrieve"):
            # Mixin pattern: super() delegates to host class via MRO; mypy cannot resolve this
            return super().retrieve(  # type: ignore[misc]
                query=query,
                tiers=tiers,
                limit=limit,
                min_importance=min_importance,
                include_glacial=include_glacial,
                tier=tier,
            )
        # Standalone mode: only glacial tier access
        return self._glacial_retrieve(
            query=query,
            limit=limit,
            min_importance=min_importance,
        )

    def _glacial_retrieve(
        self,
        query: str | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> list[ContinuumMemoryEntry]:
        """Retrieve memories from glacial tier with 30-day confidence decay.

        This method applies time-based confidence decay specific to the
        glacial tier's 30-day half-life. Older memories have reduced
        effective importance, simulating natural forgetting while
        preserving foundational knowledge.

        Args:
            query: Optional keyword filter for content
            limit: Maximum entries to return
            min_importance: Minimum importance threshold (before decay)

        Returns:
            List of ContinuumMemoryEntry objects with decay-adjusted scoring
        """
        from aragora.memory.continuum import ContinuumMemoryEntry
        from aragora.memory.tier_manager import MemoryTier
        from aragora.utils.json_helpers import safe_json_loads

        # Use self.connection() to ensure we use the same database as host class
        with self.connection() as conn:
            cursor = conn.cursor()

            # Build query with keyword filter if provided
            keyword_clause = ""
            keyword_params: list[str] = []
            if query:
                keywords = [kw.strip().lower() for kw in query.split()[:50] if kw.strip()]
                if keywords:
                    keyword_conditions = ["INSTR(LOWER(content), ?) > 0" for _ in keywords]
                    keyword_clause = f" AND ({' OR '.join(keyword_conditions)})"
                    keyword_params = keywords

            # Query glacial tier entries
            # Score includes: importance * (1 + surprise) * decay_factor
            # decay_factor = 0.5^(days_elapsed / 30)
            cursor.execute(
                f"""
                SELECT id, tier, content, importance, surprise_score, consolidation_score,
                       update_count, success_count, failure_count, created_at, updated_at, metadata,
                       COALESCE(red_line, 0), COALESCE(red_line_reason, ''),
                       (importance * (1 + surprise_score) *
                        POWER(0.5, (julianday('now') - julianday(updated_at)) / {GLACIAL_HALF_LIFE_DAYS})) as score
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

        return entries

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

        return math.pow(0.5, days_elapsed / GLACIAL_HALF_LIFE_DAYS)

    def get_glacial_insights(
        self,
        topic: str | None = None,
        limit: int = 10,
        min_importance: float = 0.3,
    ) -> list[ContinuumMemoryEntry]:
        """
        Retrieve long-term patterns from the glacial tier for cross-session learning.

        The glacial tier stores foundational knowledge that persists across cycles
        (30-day half-life). This method provides targeted access to these insights
        for context gathering in debates and nomic cycles.

        Args:
            topic: Optional topic/query to filter relevant insights
            limit: Maximum entries to return (default 10)
            min_importance: Minimum importance threshold (default 0.3)

        Returns:
            List of glacial tier entries sorted by importance and relevance

        Example:
            # In debate orchestrator context phase:
            insights = await cms.get_glacial_insights_async(topic="error handling")
            for insight in insights:
                context.add_background(insight.content)
        """
        from aragora.memory.tier_manager import MemoryTier

        return self.retrieve(
            query=topic,
            tiers=[MemoryTier.GLACIAL],
            limit=limit,
            min_importance=min_importance,
            include_glacial=True,
        )

    async def get_glacial_insights_async(
        self,
        topic: str | None = None,
        limit: int = 10,
        min_importance: float = 0.3,
    ) -> list[ContinuumMemoryEntry]:
        """Async wrapper for get_glacial_insights() for use in async contexts."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.get_glacial_insights(
                topic=topic,
                limit=limit,
                min_importance=min_importance,
            ),
        )

    def get_cross_session_patterns(
        self,
        domain: str | None = None,
        include_slow: bool = True,
        limit: int = 20,
    ) -> list[ContinuumMemoryEntry]:
        """
        Get patterns that persist across sessions (slow + glacial tiers).

        Useful for:
        - Nomic loop context gathering (cross-cycle learning)
        - Agent team selection (historical performance patterns)
        - Debate strategy (recurring themes and successful approaches)

        Args:
            domain: Optional domain filter (e.g., 'code', 'research', 'creative')
            include_slow: Include slow tier in addition to glacial
            limit: Maximum entries to return

        Returns:
            Combined list from slow and glacial tiers, sorted by importance
        """
        from aragora.memory.tier_manager import MemoryTier

        tiers = [MemoryTier.GLACIAL]
        if include_slow:
            tiers.append(MemoryTier.SLOW)

        entries = self.retrieve(
            query=domain,
            tiers=tiers,
            limit=limit,
            min_importance=0.2,
            include_glacial=True,
        )

        # Sort by importance (highest first)
        return sorted(entries, key=lambda e: e.importance, reverse=True)

    async def get_cross_session_patterns_async(
        self,
        domain: str | None = None,
        include_slow: bool = True,
        limit: int = 20,
    ) -> list[ContinuumMemoryEntry]:
        """Async wrapper for get_cross_session_patterns()."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.get_cross_session_patterns(
                domain=domain,
                include_slow=include_slow,
                limit=limit,
            ),
        )

    def get_glacial_tier_stats(self) -> dict[str, Any]:
        """
        Get statistics specifically for the glacial tier.

        Useful for monitoring long-term memory health and deciding
        when to promote entries from slow to glacial tier.
        """
        from aragora.utils.json_helpers import safe_json_loads

        with self.connection() as conn:
            cursor = conn.cursor()

            # Get counts and averages for glacial tier
            cursor.execute("""
                SELECT
                    COUNT(*) as count,
                    AVG(importance) as avg_importance,
                    AVG(surprise_score) as avg_surprise,
                    AVG(consolidation_score) as avg_consolidation,
                    AVG(update_count) as avg_updates,
                    SUM(CASE WHEN red_line = 1 THEN 1 ELSE 0 END) as red_line_count,
                    MIN(created_at) as oldest_entry,
                    MAX(updated_at) as newest_update
                FROM continuum_memory
                WHERE tier = 'glacial'
                """)
            row = cursor.fetchone()

            # Get top tags in glacial tier
            cursor.execute("""
                SELECT metadata FROM continuum_memory
                WHERE tier = 'glacial'
                LIMIT 100
                """)
            tag_counts: dict[str, int] = {}
            for (metadata_json,) in cursor.fetchall():
                metadata: dict[str, Any] = safe_json_loads(metadata_json, {})
                for tag in metadata.get("tags", []):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

            top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "tier": "glacial",
            "count": row[0] or 0,
            "avg_importance": round(row[1] or 0, 3),
            "avg_surprise": round(row[2] or 0, 3),
            "avg_consolidation": round(row[3] or 0, 3),
            "avg_updates": round(row[4] or 0, 1),
            "red_line_count": row[5] or 0,
            "oldest_entry": row[6],
            "newest_update": row[7],
            "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
            "max_entries": self.hyperparams["max_entries_per_tier"]["glacial"],
            "utilization": round(
                (row[0] or 0) / self.hyperparams["max_entries_per_tier"]["glacial"], 3
            ),
        }


__all__ = ["ContinuumGlacialMixin"]
