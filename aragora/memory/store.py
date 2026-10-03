"""
SQLite-based critique pattern store for self-improvement.

Stores successful critique patterns so future debates can learn from past successes.
"""

from __future__ import annotations

__all__ = [
    "Pattern",
    "AgentReputation",
    "CritiqueStore",
    "CRITIQUE_STORE_SCHEMA_VERSION",
]

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from aragora.config import (
    CACHE_TTL_AGENT_REPUTATION,
    CACHE_TTL_ALL_REPUTATIONS,
    CACHE_TTL_CRITIQUE_PATTERNS,
    CACHE_TTL_CRITIQUE_STATS,
    resolve_db_path,
)
from aragora.core import Critique, DebateResult
from aragora.storage.base_store import SQLiteStore
from aragora.storage.schema import safe_add_column
from aragora.utils.cache import invalidate_cache, ttl_cache
from aragora.utils.json_helpers import safe_json_loads

# Schema version for CritiqueStore migrations
CRITIQUE_STORE_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    """Current UTC time as a naive ISO-8601 string.

    Rows stamped here are aged with UTC ``julianday('now')`` comparisons
    (decay ranking, prune_stale_patterns), so stamps must be UTC. Kept naive
    (no ``+00:00`` suffix) to match the format of legacy local-time rows and
    SQLite's own ``CURRENT_TIMESTAMP`` defaults.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


CRITIQUE_INITIAL_SCHEMA = """
    -- Debates table
    CREATE TABLE IF NOT EXISTS debates (
        id TEXT PRIMARY KEY,
        task TEXT NOT NULL,
        final_answer TEXT,
        consensus_reached INTEGER,
        confidence REAL,
        rounds_used INTEGER,
        duration_seconds REAL,
        grounded_verdict TEXT,  -- JSON: evidence, citations, grounding score
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    -- Critiques table (includes Titans/MIRAS prediction tracking)
    CREATE TABLE IF NOT EXISTS critiques (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        debate_id TEXT,
        agent TEXT NOT NULL,
        target_agent TEXT,
        issues TEXT,  -- JSON array
        suggestions TEXT,  -- JSON array
        severity REAL,
        reasoning TEXT,
        led_to_improvement INTEGER DEFAULT 0,
        expected_usefulness REAL DEFAULT 0.5,
        actual_usefulness REAL,
        prediction_error REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (debate_id) REFERENCES debates(id)
    );

    -- Patterns table (includes Titans/MIRAS surprise scoring)
    CREATE TABLE IF NOT EXISTS patterns (
        id TEXT PRIMARY KEY,
        issue_type TEXT NOT NULL,
        issue_text TEXT NOT NULL,
        suggestion_text TEXT,
        success_count INTEGER DEFAULT 0,
        failure_count INTEGER DEFAULT 0,
        avg_severity REAL DEFAULT 0.5,
        surprise_score REAL DEFAULT 0.0,
        base_rate REAL DEFAULT 0.5,
        avg_prediction_error REAL DEFAULT 0.0,
        prediction_count INTEGER DEFAULT 0,
        example_task TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    -- Pattern embeddings for semantic search (optional, for future)
    CREATE TABLE IF NOT EXISTS pattern_embeddings (
        pattern_id TEXT PRIMARY KEY,
        embedding BLOB,
        FOREIGN KEY (pattern_id) REFERENCES patterns(id)
    );

    -- Agent reputation tracking (includes Titans/MIRAS calibration)
    CREATE TABLE IF NOT EXISTS agent_reputation (
        agent_name TEXT PRIMARY KEY,
        proposals_made INTEGER DEFAULT 0,
        proposals_accepted INTEGER DEFAULT 0,
        critiques_given INTEGER DEFAULT 0,
        critiques_valuable INTEGER DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        total_predictions INTEGER DEFAULT 0,
        total_prediction_error REAL DEFAULT 0.0,
        calibration_score REAL DEFAULT 0.5
    );

    -- Patterns archive table for adaptive forgetting
    CREATE TABLE IF NOT EXISTS patterns_archive (
        id TEXT,
        issue_type TEXT,
        issue_text TEXT,
        suggestion_text TEXT,
        success_count INTEGER,
        failure_count INTEGER,
        avg_severity REAL,
        surprise_score REAL,
        example_task TEXT,
        created_at TEXT,
        updated_at TEXT,
        archived_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_critiques_debate ON critiques(debate_id);
    CREATE INDEX IF NOT EXISTS idx_patterns_type ON patterns(issue_type);
    CREATE INDEX IF NOT EXISTS idx_patterns_success ON patterns(success_count DESC);
    -- Composite index for filtered retrieval by type with success ranking
    CREATE INDEX IF NOT EXISTS idx_patterns_type_success ON patterns(issue_type, success_count DESC);
    -- Composite index for time-decayed ranking queries
    CREATE INDEX IF NOT EXISTS idx_patterns_success_updated ON patterns(success_count DESC, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_reputation_score ON agent_reputation(proposals_accepted DESC);
    CREATE INDEX IF NOT EXISTS idx_reputation_agent ON agent_reputation(agent_name);
"""

_TASK_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "how",
    "in",
    "is",
    "of",
    "on",
    "or",
    "should",
    "the",
    "to",
    "what",
    "when",
    "which",
    "with",
}


@dataclass
class Pattern:
    """A reusable critique pattern."""

    id: str
    issue_type: str  # categorized issue type
    issue_text: str
    suggestion_text: str
    success_count: int
    failure_count: int
    avg_severity: float
    example_task: str
    created_at: str
    updated_at: str

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.5


@dataclass
class AgentReputation:
    """Per-agent reputation tracking for weighted voting."""

    agent_name: str
    proposals_made: int = 0
    proposals_accepted: int = 0
    critiques_given: int = 0
    critiques_valuable: int = 0
    updated_at: str = ""
    # Titans/MIRAS calibration fields
    total_predictions: int = 0
    total_prediction_error: float = 0.0
    calibration_score: float = 0.5

    @property
    def score(self) -> float:
        """0-1 reputation score based on track record."""
        if self.proposals_made == 0:
            return 0.5  # Neutral for new agents
        acceptance = self.proposals_accepted / self.proposals_made
        critique_quality = (
            self.critiques_valuable / self.critiques_given if self.critiques_given > 0 else 0.5
        )
        # Weight: 60% proposal acceptance, 40% critique quality
        return 0.6 * acceptance + 0.4 * critique_quality

    @property
    def reputation_score(self) -> float:
        """Alias for score property (for API compatibility)."""
        return self.score

    @property
    def proposal_acceptance_rate(self) -> float:
        """Rate of proposals accepted (0-1)."""
        if self.proposals_made == 0:
            return 0.0
        return self.proposals_accepted / self.proposals_made

    @property
    def critique_value(self) -> float:
        """Rate of valuable critiques (0-1)."""
        if self.critiques_given == 0:
            return 0.0
        return self.critiques_valuable / self.critiques_given

    @property
    def debates_participated(self) -> int:
        """Estimated debates participated (based on proposals made)."""
        return self.proposals_made

    @property
    def vote_weight(self) -> float:
        """
        Vote weight multiplier (0.4-1.6 range).

        Includes Titans/MIRAS calibration bonus: agents with accurate
        predictions (low error) get a bonus, inaccurate ones get a penalty.
        """
        base_weight = 0.5 + self.score  # 0.5-1.5 range
        # Calibration bonus: (calibration - 0.5) * 0.2 gives -0.1 to +0.1
        calibration_bonus = (self.calibration_score - 0.5) * 0.2
        return max(0.4, min(1.6, base_weight + calibration_bonus))


class CritiqueStore(SQLiteStore):
    """
    SQLite-based storage for critique patterns.

    Enables self-improvement by:
    1. Storing successful critique -> fix patterns
    2. Retrieving similar patterns for new critiques
    3. Tracking which patterns lead to consensus
    """

    SCHEMA_NAME = "critique_store"
    SCHEMA_VERSION = CRITIQUE_STORE_SCHEMA_VERSION
    INITIAL_SCHEMA = CRITIQUE_INITIAL_SCHEMA

    def __init__(self, db_path: str = "agora_memory.db") -> None:
        super().__init__(resolve_db_path(db_path))

    def _post_init(self) -> None:
        """Backfill columns for legacy critique store databases."""
        with self.connection() as conn:
            # safe_add_column is idempotent (no-op if column already exists)
            for pattern_col_name, pattern_col_type, pattern_default in [
                ("surprise_score", "REAL", "0.0"),
                ("base_rate", "REAL", "0.5"),
                ("avg_prediction_error", "REAL", "0.0"),
                ("prediction_count", "INTEGER", "0"),
            ]:
                safe_add_column(
                    conn, "patterns", pattern_col_name, pattern_col_type, pattern_default
                )

            critique_columns: list[tuple[str, str, str | None]] = [
                ("expected_usefulness", "REAL", "0.5"),
                ("actual_usefulness", "REAL", None),
                ("prediction_error", "REAL", None),
            ]
            for critique_col_name, critique_col_type, critique_default in critique_columns:
                safe_add_column(
                    conn,
                    "critiques",
                    critique_col_name,
                    critique_col_type,
                    critique_default,
                )

            for reputation_col_name, reputation_col_type, reputation_default in [
                ("total_predictions", "INTEGER", "0"),
                ("total_prediction_error", "REAL", "0.0"),
                ("calibration_score", "REAL", "0.5"),
            ]:
                safe_add_column(
                    conn,
                    "agent_reputation",
                    reputation_col_name,
                    reputation_col_type,
                    reputation_default,
                )

            conn.commit()

    @staticmethod
    def _tokenize_task(text: str) -> set[str]:
        """Tokenize task text for lightweight similarity matching."""
        return {
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if len(token) > 2 and token not in _TASK_STOPWORDS
        }

    @classmethod
    def _score_task_similarity(cls, task: str, candidate_task: str) -> float:
        """Score how similar two debate tasks are."""
        normalized_task = task.strip().lower()
        normalized_candidate = candidate_task.strip().lower()

        if not normalized_task or not normalized_candidate:
            return 0.0
        if normalized_task == normalized_candidate:
            return 1.0

        task_words = cls._tokenize_task(task)
        candidate_words = cls._tokenize_task(candidate_task)
        if not task_words or not candidate_words:
            return 0.0

        overlap = len(task_words & candidate_words)
        if overlap == 0:
            return 0.0

        similarity = overlap / len(task_words | candidate_words)
        if normalized_task in normalized_candidate or normalized_candidate in normalized_task:
            similarity = max(similarity, 0.75)

        return similarity

    def store_debate(self, result: DebateResult) -> None:
        """Store a complete debate result."""
        with self.connection() as conn:
            cursor = conn.cursor()

            # Serialize grounded_verdict if present
            grounded_verdict_json = None
            if result.grounded_verdict:
                try:
                    grounded_verdict_json = json.dumps(result.grounded_verdict.to_dict())
                except (AttributeError, TypeError) as e:
                    # Fallback for objects without to_dict - continue without verdict
                    logger.debug("Could not serialize grounded_verdict: %s", e)

            # Store debate
            cursor.execute(
                """
                INSERT OR REPLACE INTO debates
                (id, task, final_answer, consensus_reached, confidence, rounds_used, duration_seconds, grounded_verdict)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    result.id,
                    result.task,
                    result.final_answer,
                    1 if result.consensus_reached else 0,
                    result.confidence,
                    result.rounds_used,
                    result.duration_seconds,
                    grounded_verdict_json,
                ),
            )

            # Store critiques (batch insert for O(1) instead of O(N))
            if result.critiques:
                cursor.executemany(
                    """
                    INSERT INTO critiques
                    (debate_id, agent, target_agent, issues, suggestions, severity, reasoning)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            result.id,
                            critique.agent,
                            critique.target_agent,
                            json.dumps(critique.issues),
                            json.dumps(critique.suggestions),
                            critique.severity,
                            critique.reasoning,
                        )
                        for critique in result.critiques
                    ],
                )

            conn.commit()

        # Invalidate related caches so API returns fresh data
        invalidate_cache("memory")
        invalidate_cache("debates")

    async def get_relevant_context(
        self,
        task: str,
        max_tokens: int = 2000,
        limit: int = 3,
    ) -> str:
        """Return conclusions from similar past debates for prompt injection."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT task, final_answer, confidence, created_at
                FROM debates
                WHERE consensus_reached = 1
                  AND final_answer IS NOT NULL
                  AND TRIM(COALESCE(final_answer, '')) != ''
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
            rows = cursor.fetchall()

        scored_matches: list[tuple[float, str, str, float | None, str]] = []
        for row in rows:
            candidate_task = row[0] or ""
            similarity = self._score_task_similarity(task, candidate_task)
            if similarity < 0.2:
                continue

            scored_matches.append(
                (
                    similarity,
                    candidate_task,
                    row[1] or "",
                    row[2],
                    row[3] or "",
                )
            )

        if not scored_matches:
            return ""

        scored_matches.sort(key=lambda item: (item[0], item[4]), reverse=True)
        char_budget = max(200, max_tokens * 4)
        lines: list[str] = []
        chars_used = 0

        for similarity, candidate_task, final_answer, confidence, created_at in scored_matches[
            :limit
        ]:
            compact_task = re.sub(r"\s+", " ", candidate_task).strip()
            compact_answer = re.sub(r"\s+", " ", final_answer).strip()
            compact_task = compact_task[:120] + "..." if len(compact_task) > 120 else compact_task
            compact_answer = (
                compact_answer[:280] + "..." if len(compact_answer) > 280 else compact_answer
            )

            confidence_text = (
                f", confidence {confidence:.0%}" if isinstance(confidence, int | float) else ""
            )
            created_label = created_at[:10] if created_at else "unknown date"
            line = (
                f'- {created_label}: Similar debate on "{compact_task}" concluded '
                f'"{compact_answer}" (similarity {similarity:.0%}{confidence_text}).'
            )

            if chars_used + len(line) > char_budget and lines:
                break

            lines.append(line)
            chars_used += len(line)

        return "\n".join(lines)

    def store(self, critique: Critique, debate_id: str | None = None) -> int:
        """Store a critique record and return the row id."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO critiques
                (debate_id, agent, target_agent, issues, suggestions, severity, reasoning)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    debate_id,
                    critique.agent,
                    critique.target_agent,
                    json.dumps(critique.issues),
                    json.dumps(critique.suggestions),
                    critique.severity,
                    critique.reasoning,
                ),
            )
            conn.commit()
            row_id = cursor.lastrowid

        invalidate_cache("memory")
        return int(row_id) if row_id is not None else 0

    def delete_debate(self, debate_id: str, cascade_critiques: bool = True) -> bool:
        """Delete a debate record and optionally its critiques.

        Used for rollback operations when a transaction fails.

        Args:
            debate_id: ID of the debate to delete
            cascade_critiques: If True, also delete associated critique records

        Returns:
            True if the record was deleted, False if not found
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            # Check if record exists
            cursor.execute("SELECT 1 FROM debates WHERE id = ?", (debate_id,))
            if not cursor.fetchone():
                return False

            # Delete associated critiques first if cascading
            if cascade_critiques:
                cursor.execute("DELETE FROM critiques WHERE debate_id = ?", (debate_id,))
                deleted_critiques = cursor.rowcount
                if deleted_critiques > 0:
                    logger.debug(
                        "[critique_store] Deleted %d critique records for debate %s",
                        deleted_critiques,
                        debate_id,
                    )

            # Delete the debate record
            cursor.execute("DELETE FROM debates WHERE id = ?", (debate_id,))
            conn.commit()

            # Invalidate caches
            invalidate_cache("memory")
            invalidate_cache("debates")

            logger.debug("[critique_store] Deleted debate record: %s", debate_id)
            return True

    def delete_pattern(self, pattern_id: str) -> bool:
        """Delete a pattern record.

        Args:
            pattern_id: ID of the pattern to delete

        Returns:
            True if deleted, False if not found
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            # Also delete associated embedding if exists
            cursor.execute("DELETE FROM pattern_embeddings WHERE pattern_id = ?", (pattern_id,))

            # Delete the pattern
            cursor.execute("DELETE FROM patterns WHERE id = ?", (pattern_id,))
            conn.commit()

            if cursor.rowcount > 0:
                invalidate_cache("memory")
                logger.debug("[critique_store] Deleted pattern: %s", pattern_id)
                return True
            return False

    def get_recent(self, limit: int = 20) -> list[Critique]:
        """Return the most recent critiques."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT agent, target_agent, issues, suggestions, severity, reasoning
                FROM critiques
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        critiques: list[Critique] = []
        for row in rows:
            critiques.append(
                Critique(
                    agent=row[0],
                    target_agent=row[1],
                    target_content="",
                    issues=safe_json_loads(row[2], []),
                    suggestions=safe_json_loads(row[3], []),
                    severity=row[4] if row[4] is not None else 0.0,
                    reasoning=row[5] or "",
                )
            )
        return critiques

    def get_critiques_batch(self, debate_ids: list[str]) -> dict[str, list[Critique]]:
        """
        Batch-fetch critiques for multiple debates in a single query.

        This method avoids N+1 queries by fetching all critiques for multiple
        debates at once, rather than querying each debate separately.

        Args:
            debate_ids: List of debate IDs to fetch critiques for

        Returns:
            Dict mapping debate_id -> list of Critique objects.
            Includes empty lists for debate_ids with no critiques.
        """
        if not debate_ids:
            return {}

        # Initialize result with empty lists for all requested IDs
        result: dict[str, list[Critique]] = {debate_id: [] for debate_id in debate_ids}

        with self.connection() as conn:
            cursor = conn.cursor()

            # Use parameterized IN clause to fetch all critiques in one query
            placeholders = ",".join("?" * len(debate_ids))
            cursor.execute(
                f"""
                SELECT debate_id, agent, target_agent, issues, suggestions, severity, reasoning
                FROM critiques
                WHERE debate_id IN ({placeholders})
                ORDER BY created_at ASC
                """,  # noqa: S608 -- parameterized query
                debate_ids,
            )

            # Group critiques by debate_id
            for row in cursor.fetchall():
                debate_id = row[0]
                if debate_id in result:
                    result[debate_id].append(
                        Critique(
                            agent=row[1],
                            target_agent=row[2],
                            target_content="",
                            issues=safe_json_loads(row[3], []),
                            suggestions=safe_json_loads(row[4], []),
                            severity=row[5] if row[5] is not None else 0.0,
                            reasoning=row[6] or "",
                        )
                    )

        return result

    def get_debates_with_critiques_batch(
        self,
        debate_ids: list[str],
    ) -> list[dict]:
        """
        Batch-fetch debates with their critiques using a JOIN.

        This method fetches multiple debates along with their critiques in a
        single query using LEFT JOIN, avoiding N+1 queries.

        Args:
            debate_ids: List of debate IDs to fetch

        Returns:
            List of debate dicts, each with a 'critiques' field containing
            the list of associated critiques.
        """
        if not debate_ids:
            return []

        with self.connection() as conn:
            cursor = conn.cursor()

            # Use LEFT JOIN to fetch debates and critiques together
            placeholders = ",".join("?" * len(debate_ids))
            cursor.execute(
                f"""
                SELECT d.id, d.task, d.final_answer, d.consensus_reached, d.confidence,
                       d.rounds_used, d.duration_seconds, d.grounded_verdict, d.created_at,
                       c.agent, c.target_agent, c.issues, c.suggestions, c.severity, c.reasoning
                FROM debates d
                LEFT JOIN critiques c ON d.id = c.debate_id
                WHERE d.id IN ({placeholders})
                ORDER BY d.id, c.created_at ASC
                """,  # noqa: S608 -- parameterized query
                debate_ids,
            )

            # Group results by debate
            debates_map: dict[str, dict] = {}
            for row in cursor.fetchall():
                debate_id = row[0]

                if debate_id not in debates_map:
                    debates_map[debate_id] = {
                        "id": debate_id,
                        "task": row[1],
                        "final_answer": row[2],
                        "consensus_reached": bool(row[3]),
                        "confidence": row[4],
                        "rounds_used": row[5],
                        "duration_seconds": row[6],
                        "grounded_verdict": safe_json_loads(row[7], None),
                        "created_at": row[8],
                        "critiques": [],
                    }

                # Add critique if present (LEFT JOIN may return NULL for debates without critiques)
                if row[9] is not None:  # agent column indicates critique exists
                    debates_map[debate_id]["critiques"].append(
                        Critique(
                            agent=row[9],
                            target_agent=row[10],
                            target_content="",
                            issues=safe_json_loads(row[11], []),
                            suggestions=safe_json_loads(row[12], []),
                            severity=row[13] if row[13] is not None else 0.0,
                            reasoning=row[14] or "",
                        )
                    )

            return list(debates_map.values())

    def get_relevant(self, issue_type: str | None = None, limit: int = 10) -> list[Pattern]:
        """Backward-compatible wrapper for retrieve_patterns()."""
        return self.retrieve_patterns(issue_type=issue_type, min_success=1, limit=limit)

    def store_pattern(self, critique: Critique, successful_fix: str) -> None:
        """Store a successful critique pattern."""
        with self.connection() as conn:
            cursor = conn.cursor()

            for issue in critique.issues:
                # Create pattern ID from issue hash
                pattern_id = hashlib.sha256(issue.lower().encode()).hexdigest()[:12]

                # Categorize issue type (simple heuristic)
                issue_type = self._categorize_issue(issue)

                # Get matching suggestion
                suggestion = critique.suggestions[0] if critique.suggestions else ""

                # Atomic upsert to avoid race condition in concurrent writes
                # Uses INSERT ... ON CONFLICT to eliminate check-then-act race window
                now = _utc_now_iso()
                cursor.execute(
                    """
                    INSERT INTO patterns
                        (id, issue_type, issue_text, suggestion_text, success_count,
                         avg_severity, example_task, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        success_count = success_count + 1,
                        avg_severity = (avg_severity * success_count + ?) / (success_count + 1),
                        updated_at = ?
                    """,
                    (
                        pattern_id,
                        issue_type,
                        issue,
                        suggestion,
                        critique.severity,  # initial avg_severity for INSERT
                        successful_fix[:500],
                        now,  # created_at (only set on INSERT)
                        now,  # updated_at
                        critique.severity,  # new severity for UPDATE averaging
                        now,  # updated_at for UPDATE
                    ),
                )

                # Update surprise score (Titans/MIRAS: track unexpected successes)
                self._update_surprise_score(cursor, pattern_id, is_success=True)

            conn.commit()

        # Invalidate related caches so API returns fresh data
        invalidate_cache("memory")

    def _categorize_issue(self, issue: str) -> str:
        """Simple issue categorization."""
        issue_lower = issue.lower()

        categories = {
            "performance": ["slow", "performance", "efficient", "optimize", "speed", "latency"],
            "security": ["security", "vulnerab", "injection", "auth", "permission", "xss", "csrf"],
            "correctness": ["bug", "error", "incorrect", "wrong", "fail", "break", "crash"],
            "clarity": ["unclear", "confusing", "readab", "document", "comment", "naming"],
            "architecture": ["design", "structure", "pattern", "modular", "coupling", "cohesion"],
            "completeness": ["missing", "incomplete", "todo", "edge case", "handle"],
            "testing": ["test", "coverage", "assert", "mock", "unit", "integration"],
        }

        for category, keywords in categories.items():
            if any(kw in issue_lower for kw in keywords):
                return category

        return "general"

    def fail_pattern(self, issue_text: str, issue_type: str = "general") -> None:
        """
        Record a pattern failure (critique didn't help reach consensus).

        This is the counterpart to store_pattern - called when a critique
        with matching issue text did NOT lead to improvement.
        Implements Titans/MIRAS failure tracking for balanced learning.
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            # Create pattern ID from issue hash (same as store_pattern)
            pattern_id = hashlib.sha256(issue_text.lower().encode()).hexdigest()[:12]

            # Increment failure count if pattern exists
            cursor.execute(
                """
                UPDATE patterns
                SET failure_count = failure_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (_utc_now_iso(), pattern_id),
            )

            # Update surprise score based on unexpected failure
            if cursor.rowcount > 0:
                self._update_surprise_score(cursor, pattern_id, is_success=False)

            conn.commit()

    def update_prediction_outcome(
        self,
        critique_id: int,
        actual_usefulness: float,
        agent_name: str | None = None,
    ) -> float:
        """
        Update critique with actual outcome, return prediction error.

        Implements Titans/MIRAS prediction error tracking - compares
        the agent's expected usefulness with the actual outcome.

        Args:
            critique_id: Database ID of the critique
            actual_usefulness: How useful the critique actually was (0.0-1.0)
            agent_name: Optional agent name to update calibration score

        Returns:
            Prediction error (|expected - actual|)
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            # Get expected usefulness
            cursor.execute(
                "SELECT expected_usefulness, agent FROM critiques WHERE id = ?",
                (critique_id,),
            )
            row = cursor.fetchone()
            if not row:
                return 0.0

            expected = row[0] if row[0] is not None else 0.5
            agent = agent_name or row[1]

            # Calculate prediction error
            prediction_error = abs(expected - actual_usefulness)

            # Update critique with outcome
            cursor.execute(
                """
                UPDATE critiques
                SET actual_usefulness = ?,
                    prediction_error = ?
                WHERE id = ?
                """,
                (actual_usefulness, prediction_error, critique_id),
            )

            # Update agent's calibration score if agent provided
            if agent:
                self._update_agent_calibration(cursor, agent, prediction_error)

            conn.commit()
            return prediction_error

    def _update_agent_calibration(
        self,
        cursor,
        agent_name: str,
        prediction_error: float,
    ) -> None:
        """
        Update agent's calibration score based on prediction accuracy.

        Agents with lower average prediction error get better calibration scores.
        """
        # Ensure agent exists
        cursor.execute(
            "INSERT OR IGNORE INTO agent_reputation (agent_name) VALUES (?)",
            (agent_name,),
        )

        # Update prediction tracking and calibration
        cursor.execute(
            """
            UPDATE agent_reputation
            SET total_predictions = total_predictions + 1,
                total_prediction_error = total_prediction_error + ?,
                calibration_score = 1.0 - (
                    (total_prediction_error + ?) / (total_predictions + 1)
                ),
                updated_at = ?
            WHERE agent_name = ?
            """,
            (prediction_error, prediction_error, _utc_now_iso(), agent_name),
        )

    def _calculate_surprise(self, cursor, issue_type: str, is_success: bool) -> float:
        """
        Calculate surprise score based on deviation from base rate.

        Implements Titans/MIRAS "surprise-based memorization" - patterns
        that deviate from expected outcomes get higher surprise scores.

        Args:
            cursor: Database cursor
            issue_type: Category of the issue
            is_success: Whether this was a success (True) or failure (False)

        Returns:
            Surprise score between 0.0 and 1.0
        """
        # Get base success rate for this issue type
        cursor.execute(
            """
            SELECT AVG(
                CAST(success_count AS REAL) /
                NULLIF(success_count + failure_count, 0)
            )
            FROM patterns
            WHERE issue_type = ? AND (success_count + failure_count) > 0
            """,
            (issue_type,),
        )
        result = cursor.fetchone()
        base_rate = result[0] if result and result[0] is not None else 0.5

        # Actual outcome: 1.0 for success, 0.0 for failure
        actual = 1.0 if is_success else 0.0

        # Surprise = |actual - expected|, normalized to 0-1
        surprise = abs(actual - base_rate)
        return min(1.0, surprise * 2)  # Scale up for visibility

    def _update_surprise_score(self, cursor, pattern_id: str, is_success: bool) -> None:
        """Update surprise score for a pattern after success/failure."""
        # Get pattern's issue_type
        cursor.execute("SELECT issue_type FROM patterns WHERE id = ?", (pattern_id,))
        result = cursor.fetchone()
        if not result:
            return

        issue_type = result[0]
        surprise = self._calculate_surprise(cursor, issue_type, is_success)

        # Update with exponential moving average (alpha = 0.3)
        cursor.execute(
            """
            UPDATE patterns
            SET surprise_score = surprise_score * 0.7 + ? * 0.3,
                base_rate = (
                    SELECT AVG(
                        CAST(success_count AS REAL) /
                        NULLIF(success_count + failure_count, 0)
                    )
                    FROM patterns WHERE issue_type = ?
                )
            WHERE id = ?
            """,
            (surprise, issue_type, pattern_id),
        )

    @ttl_cache(
        ttl_seconds=CACHE_TTL_CRITIQUE_PATTERNS, key_prefix="critique_patterns", skip_first=False
    )
    def retrieve_patterns(
        self,
        issue_type: str | None = None,
        min_success: int = 2,
        limit: int = 10,
        decay_halflife_days: int = 30,
    ) -> list[Pattern]:
        """
        Retrieve successful patterns with Titans/MIRAS-inspired ranking.

        Ranking formula:
            score = (success_count * (1 + surprise_score)) /
                    (1 + age_days / decay_halflife_days)

        This prioritizes:
        - Higher success counts
        - More surprising patterns (unexpected successes)
        - Recent patterns (time-decay)
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            # Build query with Titans/MIRAS-inspired ranking
            base_sql = """
                SELECT id, issue_type, issue_text, suggestion_text, success_count,
                       failure_count, avg_severity, example_task, created_at, updated_at,
                       (success_count * (1 + COALESCE(surprise_score, 0))) /
                       (1 + (julianday('now') - julianday(updated_at)) / ?) as decay_score
                FROM patterns
                WHERE success_count >= ?
            """
            params: list[float | int | str] = [decay_halflife_days, min_success]

            if issue_type:
                base_sql += " AND issue_type = ?"
                params.append(issue_type)

            base_sql += " ORDER BY decay_score DESC LIMIT ?"
            params.append(limit)

            cursor.execute(base_sql, params)

            patterns = [
                Pattern(
                    id=row[0],
                    issue_type=row[1],
                    issue_text=row[2],
                    suggestion_text=row[3],
                    success_count=row[4],
                    failure_count=row[5],
                    avg_severity=row[6],
                    example_task=row[7],
                    created_at=row[8],
                    updated_at=row[9],
                )
                for row in cursor.fetchall()
            ]

            return patterns

    def retrieve_patterns_with_embeddings(
        self,
        issue_type: str | None = None,
        min_success: int = 2,
        limit: int = 10,
        decay_halflife_days: int = 30,
    ) -> list[tuple[Pattern, bytes | None]]:
        """
        Retrieve successful patterns with their embeddings using a JOIN.

        This method avoids N+1 queries by fetching patterns and embeddings
        in a single query using LEFT JOIN, rather than querying embeddings
        separately for each pattern.

        Args:
            issue_type: Filter by issue category (e.g., 'performance', 'security')
            min_success: Minimum success count threshold
            limit: Maximum patterns to return
            decay_halflife_days: Half-life for time-decay ranking

        Returns:
            List of (Pattern, embedding_bytes) tuples. embedding_bytes is None
            if no embedding exists for that pattern.
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            # Use LEFT JOIN to fetch patterns with embeddings in one query
            # This avoids the N+1 pattern of:
            #   1. SELECT * FROM patterns WHERE ...
            #   2. for each pattern: SELECT * FROM pattern_embeddings WHERE pattern_id = ?
            base_sql = """
                SELECT p.id, p.issue_type, p.issue_text, p.suggestion_text, p.success_count,
                       p.failure_count, p.avg_severity, p.example_task, p.created_at, p.updated_at,
                       e.embedding,
                       (p.success_count * (1 + COALESCE(p.surprise_score, 0))) /
                       (1 + (julianday('now') - julianday(p.updated_at)) / ?) as decay_score
                FROM patterns p
                LEFT JOIN pattern_embeddings e ON p.id = e.pattern_id
                WHERE p.success_count >= ?
            """
            params: list[float | int | str] = [decay_halflife_days, min_success]

            if issue_type:
                base_sql += " AND p.issue_type = ?"
                params.append(issue_type)

            base_sql += " ORDER BY decay_score DESC LIMIT ?"
            params.append(limit)

            cursor.execute(base_sql, params)

            results: list[tuple[Pattern, bytes | None]] = []
            for row in cursor.fetchall():
                pattern = Pattern(
                    id=row[0],
                    issue_type=row[1],
                    issue_text=row[2],
                    suggestion_text=row[3],
                    success_count=row[4],
                    failure_count=row[5],
                    avg_severity=row[6],
                    example_task=row[7],
                    created_at=row[8],
                    updated_at=row[9],
                )
                embedding = row[10]  # May be None if no embedding exists
                results.append((pattern, embedding))

            return results

    def get_patterns_batch(
        self,
        pattern_ids: list[str],
    ) -> dict[str, tuple[Pattern, bytes | None]]:
        """
        Batch-fetch patterns with embeddings by IDs.

        This method fetches multiple patterns in a single query using an IN clause
        with LEFT JOIN, avoiding N+1 queries when you need to look up many patterns.

        Args:
            pattern_ids: List of pattern IDs to fetch

        Returns:
            Dict mapping pattern_id -> (Pattern, embedding_bytes) tuple.
            Only includes patterns that exist.
        """
        if not pattern_ids:
            return {}

        with self.connection() as conn:
            cursor = conn.cursor()

            # Use parameterized IN clause with LEFT JOIN
            placeholders = ",".join("?" * len(pattern_ids))
            cursor.execute(
                f"""
                SELECT p.id, p.issue_type, p.issue_text, p.suggestion_text, p.success_count,
                       p.failure_count, p.avg_severity, p.example_task, p.created_at, p.updated_at,
                       e.embedding
                FROM patterns p
                LEFT JOIN pattern_embeddings e ON p.id = e.pattern_id
                WHERE p.id IN ({placeholders})
                """,  # noqa: S608 -- parameterized query
                pattern_ids,
            )

            results: dict[str, tuple[Pattern, bytes | None]] = {}
            for row in cursor.fetchall():
                pattern = Pattern(
                    id=row[0],
                    issue_type=row[1],
                    issue_text=row[2],
                    suggestion_text=row[3],
                    success_count=row[4],
                    failure_count=row[5],
                    avg_severity=row[6],
                    example_task=row[7],
                    created_at=row[8],
                    updated_at=row[9],
                )
                embedding = row[10]
                results[pattern.id] = (pattern, embedding)

            return results

    @ttl_cache(ttl_seconds=CACHE_TTL_CRITIQUE_STATS, key_prefix="critique_stats", skip_first=False)
    def get_stats(self) -> dict:
        """Get statistics about stored patterns and debates.

        Uses consolidated queries to reduce database round-trips from 6 to 2.
        """
        # Ensure tables exist
        self._init_db()

        with self.connection() as conn:
            cursor = conn.cursor()

            # Consolidated query: All counts and averages in one query using subqueries
            cursor.execute("""
                SELECT
                    (SELECT COUNT(*) FROM debates) as total_debates,
                    (SELECT COUNT(*) FROM debates WHERE consensus_reached = 1) as consensus_debates,
                    (SELECT COUNT(*) FROM critiques) as total_critiques,
                    (SELECT COUNT(*) FROM patterns) as total_patterns,
                    (SELECT AVG(confidence) FROM debates WHERE consensus_reached = 1) as avg_confidence
            """)
            row = cursor.fetchone()

            stats = {
                "total_debates": row[0] if row[0] else 0,
                "consensus_debates": row[1] if row[1] else 0,
                "total_critiques": row[2] if row[2] else 0,
                "total_patterns": row[3] if row[3] else 0,
                "avg_consensus_confidence": row[4] if row[4] else 0.0,
            }

            # Second query: patterns by type (GROUP BY can't easily combine)
            cursor.execute("SELECT issue_type, COUNT(*) FROM patterns GROUP BY issue_type")
            stats["patterns_by_type"] = dict(cursor.fetchall())

            return stats

    def export_for_training(self, limit: int = 1000, offset: int = 0) -> list[dict]:
        """Export successful patterns for potential fine-tuning.

        Args:
            limit: Maximum number of records to return (default 1000)
            offset: Number of records to skip (for pagination)

        Returns:
            List of training data dictionaries
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT d.task, c.issues, c.suggestions, d.final_answer, d.consensus_reached
                FROM critiques c
                JOIN debates d ON c.debate_id = d.id
                WHERE d.consensus_reached = 1
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )

            training_data = []
            for row in cursor.fetchall():
                training_data.append(
                    {
                        "task": row[0],
                        "issues": safe_json_loads(row[1], []),
                        "suggestions": safe_json_loads(row[2], []),
                        "successful_answer": row[3],
                    }
                )

            return training_data

    # =========================================================================
    # Agent Reputation Tracking
    # =========================================================================

    @ttl_cache(
        ttl_seconds=CACHE_TTL_AGENT_REPUTATION, key_prefix="agent_reputation", skip_first=False
    )
    def get_reputation(self, agent_name: str) -> AgentReputation | None:
        """Get reputation for an agent."""
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT agent_name, proposals_made, proposals_accepted,
                       critiques_given, critiques_valuable, updated_at,
                       COALESCE(total_predictions, 0),
                       COALESCE(total_prediction_error, 0.0),
                       COALESCE(calibration_score, 0.5)
                FROM agent_reputation
                WHERE agent_name = ?
            """,
                (agent_name,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return AgentReputation(
                agent_name=row[0],
                proposals_made=row[1],
                proposals_accepted=row[2],
                critiques_given=row[3],
                critiques_valuable=row[4],
                updated_at=row[5],
                total_predictions=row[6],
                total_prediction_error=row[7],
                calibration_score=row[8],
            )

    def get_vote_weight(self, agent_name: str) -> float:
        """Get vote weight for an agent (0.5-1.5 range based on reputation)."""
        rep = self.get_reputation(agent_name)
        if not rep:
            return 1.0  # Neutral weight for unknown agents
        return rep.vote_weight

    def get_vote_weights_batch(self, agent_names: list[str]) -> dict[str, float]:
        """Get vote weights for multiple agents in a single query.

        This is more efficient than calling get_vote_weight() for each agent
        when processing votes, as it fetches all reputations in one query.

        Args:
            agent_names: List of agent names to fetch weights for

        Returns:
            Dict mapping agent names to their vote weights (0.4-1.6 range)
        """
        if not agent_names:
            return {}

        with self.connection() as conn:
            cursor = conn.cursor()

            # Build placeholders for IN clause
            placeholders = ",".join("?" * len(agent_names))

            cursor.execute(
                f"""
                SELECT agent_name, proposals_made, proposals_accepted,
                       critiques_given, critiques_valuable,
                       COALESCE(calibration_score, 0.5)
                FROM agent_reputation
                WHERE agent_name IN ({placeholders})
                """,  # noqa: S608 -- parameterized query
                agent_names,
            )

            weights: dict[str, float] = {}
            for row in cursor.fetchall():
                agent_name = row[0]
                proposals_made = row[1]
                proposals_accepted = row[2]
                critiques_given = row[3]
                critiques_valuable = row[4]
                calibration_score = row[5]

                # Calculate reputation score (same logic as AgentReputation.score)
                if proposals_made == 0:
                    score = 0.5
                else:
                    acceptance = proposals_accepted / proposals_made
                    critique_quality = (
                        critiques_valuable / critiques_given if critiques_given > 0 else 0.5
                    )
                    score = 0.6 * acceptance + 0.4 * critique_quality

                # Calculate vote weight (same logic as AgentReputation.vote_weight)
                base_weight = 0.5 + score  # 0.5-1.5 range
                calibration_bonus = (calibration_score - 0.5) * 0.2
                weights[agent_name] = max(0.4, min(1.6, base_weight + calibration_bonus))

            # Fill in missing agents with default weight
            for name in agent_names:
                if name not in weights:
                    weights[name] = 1.0

            return weights

    # Whitelist of allowed column increments - prevents SQL injection.
    # Only these hardcoded SQL fragments can be used in UPDATE statements.
    _REPUTATION_INCREMENTS: dict[str, str] = {
        "proposal_made": "proposals_made = proposals_made + 1",
        "proposal_accepted": "proposals_accepted = proposals_accepted + 1",
        "critique_given": "critiques_given = critiques_given + 1",
        "critique_valuable": "critiques_valuable = critiques_valuable + 1",
    }

    def update_reputation(
        self,
        agent_name: str,
        proposal_made: bool = False,
        proposal_accepted: bool = False,
        critique_given: bool = False,
        critique_valuable: bool = False,
    ) -> None:
        """Update reputation metrics for an agent.

        Uses a whitelist of allowed column updates to prevent SQL injection.
        Only boolean flags corresponding to _REPUTATION_INCREMENTS keys are processed.
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            # Ensure agent exists
            cursor.execute(
                """
                INSERT OR IGNORE INTO agent_reputation (agent_name)
                VALUES (?)
            """,
                (agent_name,),
            )

            # Build updates from whitelist only - no dynamic column names
            updates: list[str] = []
            if proposal_made:
                updates.append(self._REPUTATION_INCREMENTS["proposal_made"])
            if proposal_accepted:
                updates.append(self._REPUTATION_INCREMENTS["proposal_accepted"])
            if critique_given:
                updates.append(self._REPUTATION_INCREMENTS["critique_given"])
            if critique_valuable:
                updates.append(self._REPUTATION_INCREMENTS["critique_valuable"])

            if updates:
                updates.append("updated_at = ?")
                # Column names from whitelist, values parameterized
                sql = f"""
                    UPDATE agent_reputation
                    SET {", ".join(updates)}
                    WHERE agent_name = ?
                """  # noqa: S608 -- dynamic clause from internal state
                cursor.execute(sql, [_utc_now_iso(), agent_name])

                # Log reputation changes at debug level
                change_types = []
                if proposal_made:
                    change_types.append("proposal_made")
                if proposal_accepted:
                    change_types.append("proposal_accepted")
                if critique_given:
                    change_types.append("critique_given")
                if critique_valuable:
                    change_types.append("critique_valuable")
                logger.debug("[reputation] Updated %s: %s", agent_name, ", ".join(change_types))

            conn.commit()

    @ttl_cache(
        ttl_seconds=CACHE_TTL_ALL_REPUTATIONS, key_prefix="all_reputations", skip_first=False
    )
    def get_all_reputations(self, limit: int = 500) -> list[AgentReputation]:
        """Get agent reputations, ordered by score.

        Args:
            limit: Maximum number of agents to return (default 500)

        Returns:
            List of AgentReputation objects
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT agent_name, proposals_made, proposals_accepted,
                       critiques_given, critiques_valuable, updated_at,
                       COALESCE(total_predictions, 0),
                       COALESCE(total_prediction_error, 0.0),
                       COALESCE(calibration_score, 0.5)
                FROM agent_reputation
                ORDER BY proposals_accepted DESC
                LIMIT ?
                """,
                (limit,),
            )

            reputations = [
                AgentReputation(
                    agent_name=row[0],
                    proposals_made=row[1],
                    proposals_accepted=row[2],
                    critiques_given=row[3],
                    critiques_valuable=row[4],
                    updated_at=row[5],
                    total_predictions=row[6],
                    total_prediction_error=row[7],
                    calibration_score=row[8],
                )
                for row in cursor.fetchall()
            ]

            return reputations

    # =========================================================================
    # Adaptive Forgetting (Titans/MIRAS)
    # =========================================================================

    def prune_stale_patterns(
        self,
        max_age_days: int = 90,
        min_success_rate: float = 0.3,
        archive: bool = True,
    ) -> int:
        """
        Remove or archive patterns that are stale or unsuccessful.

        Implements Titans/MIRAS "adaptive forgetting" - discards obsolete
        information to prevent memory bloat and outdated patterns from
        interfering with learning.

        Args:
            max_age_days: Patterns older than this without updates get pruned
            min_success_rate: Patterns below this success rate get pruned
            archive: If True, move to archive table instead of deleting

        Returns:
            Number of patterns pruned
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            # Evaluate the age cutoff once so the archive SELECT and the
            # DELETE match the exact same rows; separate julianday('now')
            # calls could straddle the threshold and delete an unarchived row.
            cursor.execute("SELECT julianday('now') - ?", (max_age_days,))
            cutoff_julian = cursor.fetchone()[0]

            if archive:
                # Move stale/unsuccessful patterns to archive table
                cursor.execute(
                    """
                    INSERT INTO patterns_archive
                        (id, issue_type, issue_text, suggestion_text, success_count,
                         failure_count, avg_severity, surprise_score, example_task,
                         created_at, updated_at)
                    SELECT id, issue_type, issue_text, suggestion_text, success_count,
                           failure_count, avg_severity, surprise_score, example_task,
                           created_at, updated_at
                    FROM patterns
                    WHERE julianday(updated_at) <= ?
                      AND (
                        CAST(success_count AS REAL) /
                        NULLIF(success_count + failure_count, 0)
                      ) < ?
                    """,
                    (cutoff_julian, min_success_rate),
                )

            # Delete stale/unsuccessful patterns
            cursor.execute(
                """
                DELETE FROM patterns
                WHERE julianday(updated_at) <= ?
                  AND (
                    CAST(success_count AS REAL) /
                    NULLIF(success_count + failure_count, 0)
                  ) < ?
                """,
                (cutoff_julian, min_success_rate),
            )

            pruned = cursor.rowcount
            conn.commit()

        invalidate_cache("memory")
        invalidate_cache("archive_stats")
        return pruned

    def get_archive_stats(self) -> dict:
        """Get statistics about archived patterns."""
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM patterns_archive")
            row = cursor.fetchone()
            total = row[0] if row else 0

            cursor.execute("""
                SELECT issue_type, COUNT(*)
                FROM patterns_archive
                GROUP BY issue_type
                """)
            by_type = dict(cursor.fetchall())

            return {"total_archived": total, "archived_by_type": by_type}
