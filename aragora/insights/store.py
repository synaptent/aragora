"""
Insight Store - SQLite persistence for debate insights.

Stores and retrieves insights with:
- Full-text search capabilities
- Aggregation queries
- Pattern clustering
"""

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from aragora.config import resolve_db_path
from aragora.insights.extractor import DebateInsights, Insight, InsightType
from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.storage.base_store import SQLiteStore
from aragora.storage.schema import SchemaManager
from aragora.utils.json_helpers import safe_json_loads

# Type checking import for KM adapter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.knowledge.mound.adapters.insights_adapter import InsightsAdapter

logger = logging.getLogger(__name__)

# Schema version for InsightStore migrations
INSIGHT_STORE_SCHEMA_VERSION = 2

INSIGHT_INITIAL_SCHEMA = """
    -- Insights table
    CREATE TABLE IF NOT EXISTS insights (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        confidence REAL DEFAULT 0.5,
        debate_id TEXT NOT NULL,
        agents_involved TEXT,  -- JSON array
        evidence TEXT,  -- JSON array
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        metadata TEXT  -- JSON object
    );

    -- Debate summaries table
    CREATE TABLE IF NOT EXISTS debate_summaries (
        debate_id TEXT PRIMARY KEY,
        task TEXT,
        consensus_reached INTEGER,
        duration_seconds REAL,
        total_insights INTEGER,
        key_takeaway TEXT,
        agent_performances TEXT,  -- JSON array
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    -- Agent performance history
    CREATE TABLE IF NOT EXISTS agent_performance_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_name TEXT NOT NULL,
        debate_id TEXT NOT NULL,
        proposals_made INTEGER DEFAULT 0,
        critiques_given INTEGER DEFAULT 0,
        critiques_received INTEGER DEFAULT 0,
        proposal_accepted INTEGER DEFAULT 0,
        vote_aligned INTEGER DEFAULT 0,
        avg_critique_severity REAL DEFAULT 0.0,
        contribution_score REAL DEFAULT 0.5,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (debate_id) REFERENCES debate_summaries(debate_id)
    );

    -- Pattern clusters (aggregated from pattern insights)
    CREATE TABLE IF NOT EXISTS pattern_clusters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        pattern_text TEXT NOT NULL,
        occurrence_count INTEGER DEFAULT 1,
        avg_severity REAL DEFAULT 0.5,
        debate_ids TEXT,  -- JSON array
        first_seen TEXT,
        last_seen TEXT,
        UNIQUE(category, pattern_text)
    );

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_insights_type ON insights(type);
    CREATE INDEX IF NOT EXISTS idx_insights_debate ON insights(debate_id);
    CREATE INDEX IF NOT EXISTS idx_agent_perf_name ON agent_performance_history(agent_name);
    CREATE INDEX IF NOT EXISTS idx_pattern_category ON pattern_clusters(category);
"""

INSIGHT_INDEX_MIGRATION = """
    -- Index for confidence-based queries (filtering high-confidence insights)
    CREATE INDEX IF NOT EXISTS idx_insights_confidence
    ON insights(confidence DESC);

    -- Composite index for type + confidence filtering
    CREATE INDEX IF NOT EXISTS idx_insights_type_confidence
    ON insights(type, confidence DESC);

    -- Index for agent performance by debate (join optimization)
    CREATE INDEX IF NOT EXISTS idx_agent_perf_debate
    ON agent_performance_history(debate_id);

    -- Composite index for agent performance lookups
    CREATE INDEX IF NOT EXISTS idx_agent_perf_name_debate
    ON agent_performance_history(agent_name, debate_id);

    -- Index for time-based queries on debate summaries
    CREATE INDEX IF NOT EXISTS idx_debate_summaries_created
    ON debate_summaries(created_at DESC);

    -- Index for pattern recency queries
    CREATE INDEX IF NOT EXISTS idx_pattern_last_seen
    ON pattern_clusters(last_seen DESC);
"""

# Explicit column list for SELECT queries - must match _row_to_insight() order
INSIGHT_COLUMNS = """id, type, title, description, confidence,
    debate_id, agents_involved, evidence, created_at, metadata"""

# Import from centralized location (defined here for backwards compatibility)
from aragora.utils.sql_helpers import _escape_like_pattern


class InsightStore(SQLiteStore):
    """
    SQLite-based storage for debate insights.

    Enables:
    - Storing insights from completed debates
    - Searching insights by type, agent, or content
    - Aggregating patterns across multiple debates
    - Tracking agent performance history

    Usage:
        store = InsightStore("insights.db")
        await store.store_debate_insights(insights)

        # Search
        results = await store.search("convergence", limit=10)

        # Aggregate
        patterns = await store.get_common_patterns(min_occurrences=3)
    """

    SCHEMA_NAME = "insight_store"
    SCHEMA_VERSION = INSIGHT_STORE_SCHEMA_VERSION
    INITIAL_SCHEMA = INSIGHT_INITIAL_SCHEMA

    def __init__(
        self,
        db_path: str | Path | None = None,
        km_adapter: Optional["InsightsAdapter"] = None,
        km_min_confidence: float = 0.7,
    ):
        if db_path is None:
            db_path = get_db_path(DatabaseType.INSIGHTS)
        super().__init__(resolve_db_path(str(db_path)))
        self._km_adapter = km_adapter
        self._km_min_confidence = km_min_confidence

    def set_km_adapter(self, adapter: "InsightsAdapter") -> None:
        """Set the Knowledge Mound adapter for bidirectional sync.

        Args:
            adapter: InsightsAdapter instance for KM integration
        """
        self._km_adapter = adapter

    def register_migrations(self, manager: SchemaManager) -> None:
        """Register InsightStore schema migrations."""
        manager.register_migration(
            from_version=1,
            to_version=2,
            sql=INSIGHT_INDEX_MIGRATION,
            description="Add performance indexes for common query patterns",
        )

    def _sync_store_debate_insights(self, insights: DebateInsights) -> int:
        """Sync helper: Store debate insights."""
        with self.connection() as conn:
            cursor = conn.cursor()

            # Store debate summary
            cursor.execute(
                """
                INSERT OR REPLACE INTO debate_summaries
                (debate_id, task, consensus_reached, duration_seconds,
                 total_insights, key_takeaway, agent_performances)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    insights.debate_id,
                    insights.task,
                    1 if insights.consensus_reached else 0,
                    insights.duration_seconds,
                    insights.total_insights,
                    insights.key_takeaway,
                    json.dumps(
                        [
                            {
                                "agent": p.agent_name,
                                "proposals": p.proposals_made,
                                "accepted": p.proposal_accepted,
                                "score": p.contribution_score,
                            }
                            for p in insights.agent_performances
                        ]
                    ),
                ),
            )

            # Store all insights in batch
            all_insights = list(insights.all_insights())
            stored_count = 0
            if all_insights:
                try:
                    cursor.executemany(
                        """
                        INSERT OR REPLACE INTO insights
                        (id, type, title, description, confidence, debate_id,
                         agents_involved, evidence, created_at, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                insight.id,
                                insight.type.value,
                                insight.title,
                                insight.description,
                                insight.confidence,
                                insight.debate_id,
                                json.dumps(insight.agents_involved),
                                json.dumps(insight.evidence),
                                insight.created_at,
                                json.dumps(insight.metadata),
                            )
                            for insight in all_insights
                        ],
                    )
                    stored_count = len(all_insights)
                except (sqlite3.Error, TypeError, ValueError) as e:
                    logger.error("Error batch storing insights: %s", e)

            # Store agent performances in batch
            if insights.agent_performances:
                cursor.executemany(
                    """
                    INSERT INTO agent_performance_history
                    (agent_name, debate_id, proposals_made, critiques_given,
                     critiques_received, proposal_accepted, vote_aligned,
                     avg_critique_severity, contribution_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            perf.agent_name,
                            insights.debate_id,
                            perf.proposals_made,
                            perf.critiques_given,
                            perf.critiques_received,
                            1 if perf.proposal_accepted else 0,
                            1 if perf.vote_aligned_with_consensus else 0,
                            perf.average_critique_severity,
                            perf.contribution_score,
                        )
                        for perf in insights.agent_performances
                    ],
                )

            # Update pattern clusters in batch
            if insights.pattern_insights:
                cursor.executemany(
                    """
                    INSERT INTO pattern_clusters (category, pattern_text, occurrence_count,
                        avg_severity, debate_ids, first_seen, last_seen)
                    VALUES (?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(category, pattern_text) DO UPDATE SET
                        occurrence_count = occurrence_count + 1,
                        avg_severity = (avg_severity * occurrence_count + ?) / (occurrence_count + 1),
                        debate_ids = json_insert(debate_ids, '$[#]', ?),
                        last_seen = ?
                    """,
                    [
                        (
                            insight.metadata.get("category", "general"),
                            insight.title,
                            insight.metadata.get("avg_severity", 0.5),
                            json.dumps([insights.debate_id]),
                            insight.created_at,
                            insight.created_at,
                            insight.metadata.get("avg_severity", 0.5),
                            insights.debate_id,
                            insight.created_at,
                        )
                        for insight in insights.pattern_insights
                    ],
                )

            conn.commit()

        # Sync high-confidence insights to Knowledge Mound
        if self._km_adapter:
            for insight in all_insights:
                if insight.confidence >= self._km_min_confidence:
                    try:
                        self._km_adapter.store_insight(insight)
                        logger.debug("Insight synced to Knowledge Mound: %s", insight.id)
                    except (RuntimeError, ValueError, TypeError) as e:
                        logger.warning("Failed to sync insight to KM: %s", e)

        return stored_count

    async def store_debate_insights(self, insights: DebateInsights) -> int:
        """
        Store all insights from a debate.

        Returns:
            Number of insights stored
        """
        return await asyncio.to_thread(self._sync_store_debate_insights, insights)

    def _sync_get_insight(self, insight_id: str) -> tuple | None:
        """Sync helper: Retrieve insight row by ID."""
        with self.connection() as conn:
            cursor = conn.cursor()
            # column name interpolation, parameterized
            cursor.execute(f"SELECT {INSIGHT_COLUMNS} FROM insights WHERE id = ?", (insight_id,))
            return cursor.fetchone()

    async def get_insight(self, insight_id: str) -> Insight | None:
        """Retrieve a specific insight by ID."""
        row = await asyncio.to_thread(self._sync_get_insight, insight_id)
        if not row:
            return None
        return self._row_to_insight(row)

    def _sync_search(
        self,
        query: str,
        insight_type: InsightType | None,
        agent: str | None,
        limit: int,
    ) -> list[tuple]:
        """Sync helper: Search insights."""
        with self.connection() as conn:
            cursor = conn.cursor()

            # column name interpolation, parameterized
            sql = f"SELECT {INSIGHT_COLUMNS} FROM insights WHERE 1=1"
            params: list = []

            if query:
                escaped_query = _escape_like_pattern(query)
                sql += " AND (title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')"
                params.extend([f"%{escaped_query}%", f"%{escaped_query}%"])

            if insight_type:
                sql += " AND type = ?"
                params.append(insight_type.value)

            if agent:
                escaped_agent = _escape_like_pattern(agent)
                sql += " AND agents_involved LIKE ? ESCAPE '\\'"
                params.append(f'%"{escaped_agent}"%')

            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            return cursor.fetchall()

    async def search(
        self,
        query: str = "",
        insight_type: InsightType | None = None,
        agent: str | None = None,
        limit: int = 20,
    ) -> list[Insight]:
        """
        Search insights by query, type, or agent.

        Args:
            query: Text to search in title/description
            insight_type: Filter by insight type
            agent: Filter by agent involvement
            limit: Maximum results

        Returns:
            List of matching insights
        """
        rows = await asyncio.to_thread(self._sync_search, query, insight_type, agent, limit)
        return [self._row_to_insight(row) for row in rows]

    def _sync_get_common_patterns(
        self, min_occurrences: int, category: str | None, limit: int
    ) -> list[tuple]:
        """Sync helper: Get common patterns."""
        with self.connection() as conn:
            cursor = conn.cursor()

            sql = """
                SELECT category, pattern_text, occurrence_count, avg_severity, last_seen
                FROM pattern_clusters
                WHERE occurrence_count >= ?
            """
            params: list = [min_occurrences]

            if category:
                sql += " AND category = ?"
                params.append(category)

            sql += " ORDER BY occurrence_count DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            return cursor.fetchall()

    async def get_common_patterns(
        self,
        min_occurrences: int = 2,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Get commonly occurring patterns across debates.

        Returns:
            List of pattern dictionaries with occurrence counts
        """
        rows = await asyncio.to_thread(
            self._sync_get_common_patterns, min_occurrences, category, limit
        )
        return [
            {
                "category": row[0],
                "pattern": row[1],
                "occurrences": row[2],
                "avg_severity": row[3],
                "last_seen": row[4],
            }
            for row in rows
        ]

    def _sync_get_agent_stats(self, agent_name: str) -> tuple | None:
        """Sync helper: Get agent stats."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COUNT(*) as debate_count,
                    SUM(proposals_made) as total_proposals,
                    SUM(proposal_accepted) as proposals_accepted,
                    SUM(critiques_given) as total_critiques,
                    AVG(contribution_score) as avg_contribution,
                    AVG(avg_critique_severity) as avg_severity_received
                FROM agent_performance_history
                WHERE agent_name = ?
                """,
                (agent_name,),
            )
            return cursor.fetchone()

    async def get_agent_stats(self, agent_name: str) -> dict:
        """
        Get aggregate statistics for an agent.

        Returns:
            Dictionary with performance metrics
        """
        row = await asyncio.to_thread(self._sync_get_agent_stats, agent_name)

        if not row or row[0] == 0:
            return {"agent": agent_name, "debate_count": 0}

        return {
            "agent": agent_name,
            "debate_count": row[0],
            "total_proposals": row[1] or 0,
            "proposals_accepted": row[2] or 0,
            "acceptance_rate": (row[2] or 0) / max(1, row[1] or 1),
            "total_critiques": row[3] or 0,
            "avg_contribution": row[4] or 0.5,
            "avg_severity_received": row[5] or 0.0,
        }

    def _sync_get_all_agent_rankings(self) -> list[tuple]:
        """Sync helper: Get agent rankings."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    agent_name,
                    COUNT(*) as debate_count,
                    SUM(proposal_accepted) as proposals_accepted,
                    AVG(contribution_score) as avg_contribution
                FROM agent_performance_history
                GROUP BY agent_name
                HAVING debate_count >= 1
                ORDER BY avg_contribution DESC
                """)
            return cursor.fetchall()

    async def get_all_agent_rankings(self) -> list[dict]:
        """
        Get ranked list of all agents by performance.

        Returns:
            List of agent stats ordered by contribution score
        """
        rows = await asyncio.to_thread(self._sync_get_all_agent_rankings)
        return [
            {
                "agent": row[0],
                "debate_count": row[1],
                "proposals_accepted": row[2] or 0,
                "avg_contribution": row[3] or 0.5,
            }
            for row in rows
        ]

    def _sync_get_recent_insights(self, limit: int) -> list[tuple]:
        """Sync helper: Get recent insights."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                # column constant
                f"SELECT {INSIGHT_COLUMNS} FROM insights ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return cursor.fetchall()

    async def get_recent_insights(self, limit: int = 20) -> list[Insight]:
        """Get most recent insights across all debates."""
        rows = await asyncio.to_thread(self._sync_get_recent_insights, limit)
        return [self._row_to_insight(row) for row in rows]

    def _sync_get_stats(self) -> dict:
        """Sync helper: Get overall stats."""
        with self.connection() as conn:
            cursor = conn.cursor()

            stats = {}

            cursor.execute("SELECT COUNT(*) FROM insights")
            row = cursor.fetchone()
            stats["total_insights"] = row[0] if row else 0

            cursor.execute("SELECT COUNT(*) FROM debate_summaries")
            row = cursor.fetchone()
            stats["total_debates"] = row[0] if row else 0

            cursor.execute("SELECT COUNT(*) FROM debate_summaries WHERE consensus_reached = 1")
            row = cursor.fetchone()
            stats["consensus_debates"] = row[0] if row else 0

            cursor.execute("SELECT type, COUNT(*) FROM insights GROUP BY type")
            stats["insights_by_type"] = dict(cursor.fetchall())

            cursor.execute("SELECT COUNT(DISTINCT agent_name) FROM agent_performance_history")
            row = cursor.fetchone()
            stats["unique_agents"] = row[0] if row else 0

            cursor.execute("SELECT AVG(total_insights) FROM debate_summaries")
            row = cursor.fetchone()
            avg = row[0] if row else None
            stats["avg_insights_per_debate"] = avg if avg else 0

        return stats

    async def get_stats(self) -> dict:
        """Get overall statistics about stored insights."""
        return await asyncio.to_thread(self._sync_get_stats)

    def _row_to_insight(self, row) -> Insight:
        """Convert a database row to an Insight object."""
        try:
            insight_type = InsightType(row[1])
        except ValueError:
            logger.warning("Invalid insight type '%s', defaulting to PATTERN", row[1])
            insight_type = InsightType.PATTERN
        return Insight(
            id=row[0],
            type=insight_type,
            title=row[2],
            description=row[3] or "",
            confidence=row[4] or 0.5,
            debate_id=row[5],
            agents_involved=safe_json_loads(row[6], []),
            evidence=safe_json_loads(row[7], []),
            created_at=row[8] or datetime.now().isoformat(),
            metadata=safe_json_loads(row[9], {}),
        )

    # =========================================================================
    # Audience Wisdom Injection (fallback when agents timeout)
    # =========================================================================

    def _ensure_wisdom_table(self) -> None:
        """Ensure the wisdom_submissions table exists."""
        with self.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wisdom_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    loop_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    submitter_id TEXT DEFAULT 'anonymous',
                    context_tags TEXT,
                    used INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_wisdom_loop_id
                ON wisdom_submissions(loop_id, used)
            """)
            conn.commit()

    def add_wisdom_submission(self, loop_id: str, wisdom_data: dict) -> int:
        """
        Add audience wisdom with proper loop association.

        Args:
            loop_id: The debate/loop ID this wisdom is for
            wisdom_data: Dict with 'text', optional 'submitter_id', 'context_tags'

        Returns:
            The ID of the inserted wisdom submission
        """
        self._ensure_wisdom_table()

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO wisdom_submissions (loop_id, text, submitter_id, context_tags)
                VALUES (?, ?, ?, ?)
                """,
                (
                    loop_id,
                    wisdom_data.get("text", "")[:280],  # Character limit
                    wisdom_data.get("submitter_id", "anonymous"),
                    json.dumps(wisdom_data.get("context_tags", [])),
                ),
            )
            wisdom_id = cursor.lastrowid
            conn.commit()

            # Log to flight recorder for debugging
            self._log_wisdom_event(
                {
                    "type": "wisdom_submitted",
                    "loop_id": loop_id,
                    "wisdom_id": wisdom_id,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            logger.info("[wisdom] Added submission %s for loop %s", wisdom_id, loop_id)
            return wisdom_id

    def get_relevant_wisdom(self, loop_id: str, limit: int = 3) -> list[dict]:
        """
        Retrieve unused wisdom for current loop.

        Args:
            loop_id: The debate/loop ID to get wisdom for
            limit: Maximum number of wisdom entries to return

        Returns:
            List of wisdom dicts with 'id', 'text', 'submitter_id', 'context_tags'
        """
        self._ensure_wisdom_table()

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, text, submitter_id, context_tags, created_at
                FROM wisdom_submissions
                WHERE loop_id = ? AND used = 0
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (loop_id, limit),
            )

            return [
                {
                    "id": row[0],
                    "text": row[1],
                    "submitter_id": row[2],
                    "context_tags": safe_json_loads(row[3], []),
                    "created_at": row[4],
                }
                for row in cursor.fetchall()
            ]

    def mark_wisdom_used(self, wisdom_id: int) -> None:
        """Mark a wisdom submission as used."""
        self._ensure_wisdom_table()

        with self.connection() as conn:
            conn.execute("UPDATE wisdom_submissions SET used = 1 WHERE id = ?", (wisdom_id,))
            conn.commit()

        self._log_wisdom_event(
            {
                "type": "wisdom_used",
                "wisdom_id": wisdom_id,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def _log_wisdom_event(self, event_data: dict) -> None:
        """Flight recorder: log wisdom events for replay/debugging."""
        try:
            event_log = self.db_path.parent / "wisdom_events.jsonl"
            with open(event_log, "a") as f:
                f.write(json.dumps(event_data) + "\n")
        except OSError as e:
            # Never crash main loop due to logging, but note the failure
            logger.warning("Failed to log wisdom event: %s", e)

    # =========================================================================
    # Insight Application Cycle (B2)
    # =========================================================================

    def _sync_get_relevant_insights(
        self,
        domain: str | None,
        min_confidence: float,
        limit: int,
    ) -> list[tuple]:
        """Sync helper: Get high-confidence insights for a domain."""
        with self.connection() as conn:
            cursor = conn.cursor()

            sql = f"""
                SELECT {INSIGHT_COLUMNS} FROM insights
                WHERE confidence >= ?
            """  # column name interpolation, parameterized
            params: list = [min_confidence]

            if domain:
                # Search for domain in metadata or title/description
                escaped_domain = _escape_like_pattern(domain)
                sql += """ AND (
                    metadata LIKE ? ESCAPE '\\'
                    OR title LIKE ? ESCAPE '\\'
                    OR description LIKE ? ESCAPE '\\'
                )"""
                params.extend(
                    [
                        f'%"{escaped_domain}"%',
                        f"%{escaped_domain}%",
                        f"%{escaped_domain}%",
                    ]
                )

            sql += " ORDER BY confidence DESC, created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            return cursor.fetchall()

    async def get_relevant_insights(
        self,
        domain: str | None = None,
        min_confidence: float = 0.7,
        limit: int = 5,
    ) -> list[Insight]:
        """
        Get high-confidence insights relevant to a domain for injection into debates.

        This method retrieves insights that can be applied as "learned practices"
        in future debates, closing the insight application cycle.

        Args:
            domain: Optional domain to filter by (e.g., "security", "design")
            min_confidence: Minimum confidence threshold (default 0.7)
            limit: Maximum number of insights to return

        Returns:
            List of high-confidence Insight objects
        """
        rows = await asyncio.to_thread(
            self._sync_get_relevant_insights, domain, min_confidence, limit
        )
        return [self._row_to_insight(row) for row in rows]

    def _sync_record_insight_usage(
        self,
        insight_id: str,
        debate_id: str,
        was_successful: bool,
    ) -> None:
        """Sync helper: Record that an insight was applied to a debate."""
        with self.connection() as conn:
            cursor = conn.cursor()

            # Ensure usage tracking table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS insight_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    insight_id TEXT NOT NULL,
                    debate_id TEXT NOT NULL,
                    was_successful INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(insight_id, debate_id)
                )
            """)

            # Record the usage
            cursor.execute(
                """
                INSERT OR REPLACE INTO insight_usage
                (insight_id, debate_id, was_successful, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (insight_id, debate_id, 1 if was_successful else 0, datetime.now().isoformat()),
            )

            # Update insight confidence based on usage success
            # Increase confidence if successful, decrease if not
            adjustment = 0.05 if was_successful else -0.03
            cursor.execute(
                """
                UPDATE insights
                SET confidence = MIN(0.99, MAX(0.1, confidence + ?))
                WHERE id = ?
                """,
                (adjustment, insight_id),
            )

            conn.commit()

    async def record_insight_usage(
        self,
        insight_id: str,
        debate_id: str,
        was_successful: bool = True,
    ) -> None:
        """
        Record that an insight was applied to a debate.

        This tracks insight usage and adjusts confidence based on success,
        completing the learning loop.

        Args:
            insight_id: ID of the insight that was applied
            debate_id: ID of the debate where it was applied
            was_successful: Whether the debate outcome correlated with success
        """
        await asyncio.to_thread(
            self._sync_record_insight_usage, insight_id, debate_id, was_successful
        )
        logger.debug(
            "[insight] Recorded usage: insight=%s debate=%s success=%s",
            insight_id,
            debate_id,
            was_successful,
        )

    def _sync_get_insight_usage_stats(self, insight_id: str) -> dict:
        """Sync helper: Get usage statistics for an insight."""
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_uses,
                    SUM(was_successful) as successful_uses
                FROM insight_usage
                WHERE insight_id = ?
                """,
                (insight_id,),
            )
            row = cursor.fetchone()

            return {
                "insight_id": insight_id,
                "total_uses": row[0] if row else 0,
                "successful_uses": row[1] if row else 0,
                "success_rate": (row[1] / row[0]) if row and row[0] > 0 else 0.0,
            }

    async def get_insight_usage_stats(self, insight_id: str) -> dict:
        """Get usage statistics for a specific insight."""
        return await asyncio.to_thread(self._sync_get_insight_usage_stats, insight_id)
