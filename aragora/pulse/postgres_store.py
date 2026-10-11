"""
PostgreSQL persistence for scheduled debate outcomes.

Enables:
- Duplicate detection across scheduler runs
- Analytics on which topics generate good debates
- Historical trending topic tracking
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from aragora.storage.postgres_store import PostgresStore
from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)


@dataclass
class ScheduledDebateRecord:
    """Record of a scheduled debate from a trending topic."""

    id: str
    topic_hash: str
    topic_text: str
    platform: str
    category: str
    volume: int
    debate_id: str | None
    created_at: float
    consensus_reached: bool | None
    confidence: float | None
    rounds_used: int
    scheduler_run_id: str

    @property
    def hours_ago(self) -> float:
        """Hours since this debate was created."""
        return (time.time() - self.created_at) / 3600


class PostgresScheduledDebateStore(PostgresStore):
    """PostgreSQL persistence for scheduled debate outcomes.

    Tracks all debates created by the PulseDebateScheduler for:
    - Duplicate detection (avoid re-debating recent topics)
    - Analytics on trending topic debate success rates
    - Historical tracking of scheduler activity
    """

    SCHEMA_NAME = "scheduled_debates"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS scheduled_debates (
            id TEXT PRIMARY KEY,
            topic_hash TEXT NOT NULL,
            topic_text TEXT NOT NULL,
            platform TEXT NOT NULL,
            category TEXT,
            volume INTEGER DEFAULT 0,
            debate_id TEXT,
            created_at DOUBLE PRECISION NOT NULL,
            consensus_reached BOOLEAN,
            confidence REAL,
            rounds_used INTEGER DEFAULT 0,
            scheduler_run_id TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_scheduled_topic_hash
        ON scheduled_debates(topic_hash);

        CREATE INDEX IF NOT EXISTS idx_scheduled_created_at
        ON scheduled_debates(created_at);

        CREATE INDEX IF NOT EXISTS idx_scheduled_platform
        ON scheduled_debates(platform);

        CREATE INDEX IF NOT EXISTS idx_scheduled_category
        ON scheduled_debates(category);

        CREATE INDEX IF NOT EXISTS idx_scheduled_debate_id
        ON scheduled_debates(debate_id);

        CREATE INDEX IF NOT EXISTS idx_scheduled_pending
        ON scheduled_debates(debate_id, consensus_reached)
        WHERE debate_id IS NOT NULL AND consensus_reached IS NULL;
    """

    @staticmethod
    def hash_topic(topic_text: str) -> str:
        """Generate a hash for a topic for deduplication."""
        normalized = " ".join(topic_text.lower().strip().split())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    # =========================================================================
    # Sync wrappers for compatibility
    # =========================================================================

    def record_scheduled_debate(self, record: ScheduledDebateRecord) -> None:
        """Persist a scheduled debate record (sync wrapper)."""
        run_async(self.record_scheduled_debate_async(record))

    def get_recent_topics(self, hours: int = 24) -> list[ScheduledDebateRecord]:
        """Get topics debated within the last N hours (sync wrapper)."""
        return run_async(self.get_recent_topics_async(hours))

    def is_duplicate(self, topic_text: str, hours: int = 24) -> bool:
        """Check if a topic was recently debated (sync wrapper)."""
        return run_async(self.is_duplicate_async(topic_text, hours))

    def get_history(
        self,
        limit: int = 50,
        offset: int = 0,
        platform: str | None = None,
        category: str | None = None,
    ) -> list[ScheduledDebateRecord]:
        """Get historical scheduled debates (sync wrapper)."""
        return run_async(self.get_history_async(limit, offset, platform, category))

    def count_total(self) -> int:
        """Get total count of scheduled debates (sync wrapper)."""
        return run_async(self.count_total_async())

    def get_analytics(self) -> dict[str, Any]:
        """Get analytics on scheduled debates (sync wrapper)."""
        return run_async(self.get_analytics_async())

    def finalize_debate_outcome(
        self,
        debate_id: str,
        consensus_reached: bool,
        confidence: float,
        rounds_used: int,
    ) -> bool:
        """Update a scheduled debate with its final outcome (sync wrapper)."""
        return run_async(
            self.finalize_debate_outcome_async(
                debate_id, consensus_reached, confidence, rounds_used
            )
        )

    def get_pending_outcomes(self, limit: int = 100) -> list[ScheduledDebateRecord]:
        """Get debates that have a debate_id but no outcome recorded (sync wrapper)."""
        return run_async(self.get_pending_outcomes_async(limit))

    def cleanup_old(self, days: int = 30) -> int:
        """Remove records older than N days (sync wrapper)."""
        return run_async(self.cleanup_old_async(days))

    # =========================================================================
    # Async implementations
    # =========================================================================

    async def record_scheduled_debate_async(self, record: ScheduledDebateRecord) -> None:
        """Persist a scheduled debate record asynchronously."""
        async with self.connection() as conn:
            await conn.execute(
                """
                INSERT INTO scheduled_debates (
                    id, topic_hash, topic_text, platform, category, volume,
                    debate_id, created_at, consensus_reached, confidence,
                    rounds_used, scheduler_run_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (id) DO UPDATE SET
                    topic_hash = EXCLUDED.topic_hash,
                    topic_text = EXCLUDED.topic_text,
                    platform = EXCLUDED.platform,
                    category = EXCLUDED.category,
                    volume = EXCLUDED.volume,
                    debate_id = EXCLUDED.debate_id,
                    created_at = EXCLUDED.created_at,
                    consensus_reached = EXCLUDED.consensus_reached,
                    confidence = EXCLUDED.confidence,
                    rounds_used = EXCLUDED.rounds_used,
                    scheduler_run_id = EXCLUDED.scheduler_run_id
                """,
                record.id,
                record.topic_hash,
                record.topic_text,
                record.platform,
                record.category,
                record.volume,
                record.debate_id,
                record.created_at,
                record.consensus_reached,
                record.confidence,
                record.rounds_used,
                record.scheduler_run_id,
            )

        logger.debug("Recorded scheduled debate: %s...", record.topic_text[:50])

    async def get_recent_topics_async(self, hours: int = 24) -> list[ScheduledDebateRecord]:
        """Get topics debated within the last N hours asynchronously."""
        cutoff = time.time() - (hours * 3600)

        async with self.connection() as conn:
            rows = await conn.fetch(
                """
                SELECT id, topic_hash, topic_text, platform, category, volume,
                       debate_id, created_at, consensus_reached, confidence,
                       rounds_used, scheduler_run_id
                FROM scheduled_debates
                WHERE created_at >= $1
                ORDER BY created_at DESC
                """,
                cutoff,
            )

        return [self._row_to_record(row) for row in rows]

    async def is_duplicate_async(self, topic_text: str, hours: int = 24) -> bool:
        """Check if a topic was recently debated asynchronously."""
        topic_hash = self.hash_topic(topic_text)
        cutoff = time.time() - (hours * 3600)

        async with self.connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM scheduled_debates
                WHERE topic_hash = $1 AND created_at >= $2
                LIMIT 1
                """,
                topic_hash,
                cutoff,
            )

        return row is not None

    async def get_history_async(
        self,
        limit: int = 50,
        offset: int = 0,
        platform: str | None = None,
        category: str | None = None,
    ) -> list[ScheduledDebateRecord]:
        """Get historical scheduled debates asynchronously."""
        sql = """
            SELECT id, topic_hash, topic_text, platform, category, volume,
                   debate_id, created_at, consensus_reached, confidence,
                   rounds_used, scheduler_run_id
            FROM scheduled_debates
            WHERE 1=1
        """
        params: list[Any] = []
        param_num = 1

        if platform:
            sql += f" AND platform = ${param_num}"
            params.append(platform)
            param_num += 1

        if category:
            sql += f" AND category = ${param_num}"
            params.append(category)
            param_num += 1

        sql += f" ORDER BY created_at DESC LIMIT ${param_num} OFFSET ${param_num + 1}"
        params.extend([limit, offset])

        async with self.connection() as conn:
            rows = await conn.fetch(sql, *params)

        return [self._row_to_record(row) for row in rows]

    async def count_total_async(self) -> int:
        """Get total count of scheduled debates asynchronously."""
        async with self.connection() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) as count FROM scheduled_debates")
        return row["count"] if row else 0

    async def get_analytics_async(self) -> dict[str, Any]:
        """Get analytics on scheduled debates asynchronously."""
        analytics: dict[str, Any] = {}

        async with self.connection() as conn:
            # Total count
            row = await conn.fetchrow("SELECT COUNT(*) as count FROM scheduled_debates")
            analytics["total"] = row["count"] if row else 0

            # Consensus rate
            row = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total,
                    COALESCE(SUM(CASE WHEN consensus_reached THEN 1 ELSE 0 END), 0) as consensus_count,
                    AVG(confidence) as avg_confidence,
                    AVG(rounds_used) as avg_rounds
                FROM scheduled_debates
                WHERE debate_id IS NOT NULL
                """)
            if row and row["total"] > 0:
                analytics["completed_debates"] = row["total"]
                analytics["consensus_rate"] = (
                    row["consensus_count"] / row["total"] if row["total"] > 0 else 0
                )
                analytics["avg_confidence"] = float(row["avg_confidence"] or 0)
                analytics["avg_rounds"] = float(row["avg_rounds"] or 0)

            # By platform
            rows = await conn.fetch("""
                SELECT platform, COUNT(*) as count,
                       COALESCE(SUM(CASE WHEN consensus_reached THEN 1 ELSE 0 END), 0) as consensus_count
                FROM scheduled_debates
                GROUP BY platform
                """)
            analytics["by_platform"] = {
                row["platform"]: {
                    "total": row["count"],
                    "consensus_count": row["consensus_count"],
                }
                for row in rows
            }

            # By category
            rows = await conn.fetch("""
                SELECT category, COUNT(*) as count,
                       COALESCE(SUM(CASE WHEN consensus_reached THEN 1 ELSE 0 END), 0) as consensus_count
                FROM scheduled_debates
                WHERE category IS NOT NULL AND category != ''
                GROUP BY category
                """)
            analytics["by_category"] = {
                row["category"]: {
                    "total": row["count"],
                    "consensus_count": row["consensus_count"],
                }
                for row in rows
            }

            # Recent activity (last 7 days by day)
            rows = await conn.fetch(
                """
                SELECT DATE(TO_TIMESTAMP(created_at)) as day, COUNT(*) as count
                FROM scheduled_debates
                WHERE created_at >= $1
                GROUP BY day
                ORDER BY day DESC
                """,
                time.time() - 7 * 24 * 3600,
            )
            analytics["daily_counts"] = {str(row["day"]): row["count"] for row in rows}

        return analytics

    async def finalize_debate_outcome_async(
        self,
        debate_id: str,
        consensus_reached: bool,
        confidence: float,
        rounds_used: int,
    ) -> bool:
        """Update a scheduled debate with its final outcome asynchronously."""
        async with self.connection() as conn:
            result = await conn.execute(
                """
                UPDATE scheduled_debates
                SET consensus_reached = $1,
                    confidence = $2,
                    rounds_used = $3
                WHERE debate_id = $4
                """,
                consensus_reached,
                confidence,
                rounds_used,
                debate_id,
            )
            updated = result != "UPDATE 0"

        if updated:
            logger.info(
                "Finalized debate outcome: %s (consensus=%s, confidence=%.2f)",
                debate_id,
                consensus_reached,
                confidence,
            )
        else:
            logger.warning("No scheduled debate found for debate_id: %s", debate_id)

        return updated

    async def get_pending_outcomes_async(self, limit: int = 100) -> list[ScheduledDebateRecord]:
        """Get debates that have a debate_id but no outcome recorded."""
        async with self.connection() as conn:
            rows = await conn.fetch(
                """
                SELECT id, topic_hash, topic_text, platform, category, volume,
                       debate_id, created_at, consensus_reached, confidence,
                       rounds_used, scheduler_run_id
                FROM scheduled_debates
                WHERE debate_id IS NOT NULL AND consensus_reached IS NULL
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )

        return [self._row_to_record(row) for row in rows]

    async def cleanup_old_async(self, days: int = 30) -> int:
        """Remove records older than N days asynchronously."""
        cutoff = time.time() - (days * 24 * 3600)

        async with self.connection() as conn:
            result = await conn.execute(
                "DELETE FROM scheduled_debates WHERE created_at < $1",
                cutoff,
            )
            # Parse result like "DELETE 5" to get count
            try:
                removed = int(result.split()[-1])
            except (IndexError, ValueError):
                removed = 0

        if removed > 0:
            logger.info("Cleaned up %s old scheduled debate records", removed)

        return removed

    # =========================================================================
    # Helper methods
    # =========================================================================

    def _row_to_record(self, row: Any) -> ScheduledDebateRecord:
        """Convert a database row to a ScheduledDebateRecord."""
        return ScheduledDebateRecord(
            id=row["id"],
            topic_hash=row["topic_hash"],
            topic_text=row["topic_text"],
            platform=row["platform"],
            category=row["category"] or "",
            volume=row["volume"] or 0,
            debate_id=row["debate_id"],
            created_at=row["created_at"],
            consensus_reached=row["consensus_reached"],
            confidence=row["confidence"],
            rounds_used=row["rounds_used"] or 0,
            scheduler_run_id=row["scheduler_run_id"] or "",
        )

    def close(self) -> None:
        """No-op for pool-based store (pool managed externally)."""
        pass


__all__ = ["PostgresScheduledDebateStore", "ScheduledDebateRecord"]
