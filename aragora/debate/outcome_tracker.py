"""
Outcome tracking for consensus decisions.

Tracks implementation outcomes to provide feedback on debate quality:
- Did the consensus decision actually work when implemented?
- What is the calibration curve (confidence vs success rate)?
- What are common failure patterns?

This enables:
1. Self-calibration: Adjust Trickster sensitivity based on outcome history
2. Calibration curves: Measure if high-confidence decisions actually succeed
3. Pattern learning: Identify what debate qualities predict success
"""

from __future__ import annotations

__all__ = [
    "ConsensusOutcome",
    "CalibrationBucket",
    "OutcomeTracker",
    "AsyncOutcomeTracker",
    "DEFAULT_OUTCOMES_DB",
]

import asyncio
import functools
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from aragora.config import DB_TIMEOUT_SECONDS
from aragora.persistence.db_config import get_nomic_dir

T = TypeVar("T")

logger = logging.getLogger(__name__)

# Default database path (respects ARAGORA_DATA_DIR)
DEFAULT_OUTCOMES_DB = get_nomic_dir() / "outcomes.db"


@dataclass
class ConsensusOutcome:
    """Record of a consensus decision and its implementation outcome."""

    debate_id: str
    consensus_text: str
    consensus_confidence: float  # 0.0-1.0
    implementation_attempted: bool
    implementation_succeeded: bool
    tests_passed: int = 0
    tests_failed: int = 0
    rollback_triggered: bool = False
    time_to_failure: float | None = None  # Seconds until first error
    failure_reason: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Additional context
    agents_participating: list[str] = field(default_factory=list)
    rounds_completed: int = 0
    trickster_interventions: int = 0
    evidence_coverage: float = 0.0  # Average evidence quality

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        d = asdict(self)
        d["agents_participating"] = json.dumps(d["agents_participating"])
        return d

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> ConsensusOutcome:
        """Create from database row."""
        d = dict(row)
        d["agents_participating"] = json.loads(d.get("agents_participating", "[]"))
        # Filter out database-only fields (e.g., 'id') that aren't in the dataclass
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class CalibrationBucket:
    """Statistics for a confidence bucket."""

    confidence_min: float
    confidence_max: float
    total_count: int
    success_count: int

    @property
    def success_rate(self) -> float:
        """Actual success rate in this bucket."""
        return self.success_count / self.total_count if self.total_count > 0 else 0.0

    @property
    def expected_rate(self) -> float:
        """Expected success rate (midpoint of bucket)."""
        return (self.confidence_min + self.confidence_max) / 2

    @property
    def calibration_error(self) -> float:
        """How miscalibrated this bucket is (positive = overconfident)."""
        return self.expected_rate - self.success_rate


class OutcomeTracker:
    """Tracks consensus decision outcomes for calibration and learning.

    Uses SQLiteStore internally for standardized schema management.

    Usage:
        tracker = OutcomeTracker()

        # After a nomic cycle
        outcome = ConsensusOutcome(
            debate_id="nomic-cycle-5",
            consensus_text="Add caching layer...",
            consensus_confidence=0.85,
            implementation_attempted=True,
            implementation_succeeded=True,
            tests_passed=142,
            tests_failed=0,
        )
        tracker.record_outcome(outcome)

        # Get calibration data
        curve = tracker.get_calibration_curve()
        for bucket in curve:
            print(f"Confidence {bucket.confidence_min}-{bucket.confidence_max}: "
                  f"{bucket.success_rate:.0%} actual vs {bucket.expected_rate:.0%} expected")

        # Adjust Trickster sensitivity
        if tracker.is_overconfident(threshold=0.7):
            trickster.config.hollow_detection_threshold *= 0.9
    """

    SCHEMA_NAME = "outcome_tracker"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debate_id TEXT UNIQUE NOT NULL,
            consensus_text TEXT,
            consensus_confidence REAL,
            implementation_attempted INTEGER,
            implementation_succeeded INTEGER,
            tests_passed INTEGER DEFAULT 0,
            tests_failed INTEGER DEFAULT 0,
            rollback_triggered INTEGER DEFAULT 0,
            time_to_failure REAL,
            failure_reason TEXT,
            timestamp TEXT,
            agents_participating TEXT,
            rounds_completed INTEGER DEFAULT 0,
            trickster_interventions INTEGER DEFAULT 0,
            evidence_coverage REAL DEFAULT 0.0
        );

        CREATE INDEX IF NOT EXISTS idx_outcomes_confidence
        ON outcomes(consensus_confidence);
    """

    def __init__(self, db_path: Path = DEFAULT_OUTCOMES_DB):
        from aragora.storage.base_store import SQLiteStore

        # Create SQLiteStore-based database wrapper
        class _OutcomeDB(SQLiteStore):
            SCHEMA_NAME = OutcomeTracker.SCHEMA_NAME
            SCHEMA_VERSION = OutcomeTracker.SCHEMA_VERSION
            INITIAL_SCHEMA = OutcomeTracker.INITIAL_SCHEMA

        self.db_path = Path(db_path)
        self._db = _OutcomeDB(str(db_path), timeout=DB_TIMEOUT_SECONDS)

    def record_outcome(self, outcome: ConsensusOutcome) -> None:
        """Record an outcome to the database."""
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO outcomes (
                    debate_id, consensus_text, consensus_confidence,
                    implementation_attempted, implementation_succeeded,
                    tests_passed, tests_failed, rollback_triggered,
                    time_to_failure, failure_reason, timestamp,
                    agents_participating, rounds_completed,
                    trickster_interventions, evidence_coverage
                ) VALUES (
                    :debate_id, :consensus_text, :consensus_confidence,
                    :implementation_attempted, :implementation_succeeded,
                    :tests_passed, :tests_failed, :rollback_triggered,
                    :time_to_failure, :failure_reason, :timestamp,
                    :agents_participating, :rounds_completed,
                    :trickster_interventions, :evidence_coverage
                )
            """,
                outcome.to_dict(),
            )
            conn.commit()

        logger.info(
            "Recorded outcome for %s: success=%s, confidence=%.2f",
            outcome.debate_id,
            outcome.implementation_succeeded,
            outcome.consensus_confidence,
        )

    def get_outcome(self, debate_id: str) -> ConsensusOutcome | None:
        """Get outcome by debate ID."""
        with self._db.connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM outcomes WHERE debate_id = ?", (debate_id,)
            ).fetchone()

            if row:
                return ConsensusOutcome.from_row(row)
            return None

    def get_recent_outcomes(self, limit: int = 50) -> list[ConsensusOutcome]:
        """Get recent outcomes ordered by timestamp."""
        with self._db.connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM outcomes ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()

            return [ConsensusOutcome.from_row(row) for row in rows]

    def get_success_rate_by_confidence(
        self,
        bucket_size: float = 0.1,
    ) -> dict[str, float]:
        """Get success rate bucketed by confidence level.

        Returns:
            Dict mapping confidence range (e.g., "0.7-0.8") to success rate
        """
        with self._db.connection() as conn:
            rows = conn.execute("""
                SELECT
                    CAST(consensus_confidence * 10 AS INTEGER) * 0.1 as bucket_start,
                    COUNT(*) as total,
                    SUM(CASE WHEN implementation_succeeded = 1 THEN 1 ELSE 0 END) as successes
                FROM outcomes
                WHERE implementation_attempted = 1
                GROUP BY bucket_start
                ORDER BY bucket_start
            """).fetchall()

            result = {}
            for row in rows:
                bucket_start = row[0]
                bucket_end = bucket_start + bucket_size
                total = row[1]
                successes = row[2]
                rate = successes / total if total > 0 else 0.0
                key = f"{bucket_start:.1f}-{bucket_end:.1f}"
                result[key] = rate

            return result

    def get_calibration_curve(
        self,
        num_buckets: int = 10,
    ) -> list[CalibrationBucket]:
        """Get calibration curve data.

        Returns list of CalibrationBucket objects showing actual vs expected
        success rates for each confidence level.
        """
        bucket_size = 1.0 / num_buckets
        buckets = []

        with self._db.connection() as conn:
            for i in range(num_buckets):
                conf_min = i * bucket_size
                conf_max = (i + 1) * bucket_size

                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN implementation_succeeded = 1 THEN 1 ELSE 0 END) as successes
                    FROM outcomes
                    WHERE implementation_attempted = 1
                      AND consensus_confidence >= ?
                      AND consensus_confidence < ?
                """,
                    (conf_min, conf_max),
                ).fetchone()

                total = row[0] or 0
                successes = row[1] or 0

                buckets.append(
                    CalibrationBucket(
                        confidence_min=conf_min,
                        confidence_max=conf_max,
                        total_count=total,
                        success_count=successes,
                    )
                )

        return buckets

    def get_failure_patterns(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get common failure reasons with frequency.

        Returns list of dicts with 'reason' and 'count' keys.
        """
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT failure_reason, COUNT(*) as count
                FROM outcomes
                WHERE implementation_succeeded = 0
                  AND failure_reason IS NOT NULL
                  AND failure_reason != ''
                GROUP BY failure_reason
                ORDER BY count DESC
                LIMIT ?
            """,
                (limit,),
            ).fetchall()

            return [{"reason": row[0], "count": row[1]} for row in rows]

    def get_overall_stats(self) -> dict[str, Any]:
        """Get overall outcome statistics."""
        with self._db.connection() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN implementation_attempted = 1 THEN 1 ELSE 0 END) as attempted,
                    SUM(CASE WHEN implementation_succeeded = 1 THEN 1 ELSE 0 END) as succeeded,
                    SUM(CASE WHEN rollback_triggered = 1 THEN 1 ELSE 0 END) as rollbacks,
                    AVG(consensus_confidence) as avg_confidence,
                    SUM(tests_passed) as total_tests_passed,
                    SUM(tests_failed) as total_tests_failed
                FROM outcomes
            """).fetchone()

            total = row[0] or 0
            attempted = row[1] or 0
            succeeded = row[2] or 0

            return {
                "total_outcomes": total,
                "attempted": attempted,
                "succeeded": succeeded,
                "success_rate": succeeded / attempted if attempted > 0 else 0.0,
                "rollbacks": row[3] or 0,
                "avg_confidence": row[4] or 0.0,
                "total_tests_passed": row[5] or 0,
                "total_tests_failed": row[6] or 0,
            }

    def is_overconfident(self, threshold: float = 0.7) -> bool:
        """Check if the system is overconfident.

        Returns True if high-confidence (>threshold) debates have
        lower success rate than their confidence suggests.
        """
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT
                    AVG(consensus_confidence) as avg_confidence,
                    AVG(CASE WHEN implementation_succeeded = 1 THEN 1.0 ELSE 0.0 END) as success_rate,
                    COUNT(*) as count
                FROM outcomes
                WHERE implementation_attempted = 1
                  AND consensus_confidence >= ?
            """,
                (threshold,),
            ).fetchone()

            count = row[2] or 0
            if count < 5:  # Need enough samples
                return False

            avg_confidence = row[0] or 0
            success_rate = row[1] or 0

            # Overconfident if expected success (confidence) exceeds actual success
            return avg_confidence > success_rate + 0.1  # 10% margin

    def get_calibration_adjustment(self) -> float:
        """Get recommended adjustment for Trickster sensitivity.

        Returns a multiplier:
        - < 1.0: System is overconfident, increase Trickster sensitivity
        - > 1.0: System is underconfident, can decrease sensitivity
        - 1.0: Well-calibrated
        """
        curve = self.get_calibration_curve()

        # Focus on high-confidence buckets (0.7+)
        high_conf_buckets = [b for b in curve if b.confidence_min >= 0.7 and b.total_count >= 3]

        if not high_conf_buckets:
            return 1.0  # Not enough data

        # Calculate average calibration error
        total_error = sum(b.calibration_error * b.total_count for b in high_conf_buckets)
        total_count = sum(b.total_count for b in high_conf_buckets)

        if total_count == 0:
            return 1.0

        avg_error = total_error / total_count

        # Convert error to adjustment multiplier
        # Positive error = overconfident = lower multiplier = increase sensitivity
        # Error of 0.2 (20% overconfident) -> multiplier of 0.8
        adjustment = 1.0 - avg_error

        # Clamp to reasonable range
        return max(0.5, min(1.5, adjustment))

    def close(self) -> None:
        """Close the underlying database resources."""
        self._db.close()


class AsyncOutcomeTracker:
    """Async wrapper for OutcomeTracker that avoids blocking the event loop.

    All database operations are executed in a thread pool via run_in_executor
    to prevent blocking the async event loop when called from async contexts.

    Usage:
        tracker = AsyncOutcomeTracker()

        # After a nomic cycle
        outcome = ConsensusOutcome(
            debate_id="nomic-cycle-5",
            consensus_text="Add caching layer...",
            consensus_confidence=0.85,
            implementation_attempted=True,
            implementation_succeeded=True,
            tests_passed=142,
            tests_failed=0,
        )
        await tracker.record_outcome(outcome)

        # Get calibration data
        curve = await tracker.get_calibration_curve()
        for bucket in curve:
            print(f"Confidence {bucket.confidence_min}-{bucket.confidence_max}: "
                  f"{bucket.success_rate:.0%} actual vs {bucket.expected_rate:.0%} expected")

        # Adjust Trickster sensitivity
        if await tracker.is_overconfident(threshold=0.7):
            trickster.config.hollow_detection_threshold *= 0.9
    """

    def __init__(self, db_path: Path = DEFAULT_OUTCOMES_DB):
        """Initialize the async outcome tracker.

        Args:
            db_path: Path to the SQLite database file
        """
        self._sync_tracker = OutcomeTracker(db_path)
        self._executor = None  # Uses default ThreadPoolExecutor

    async def _run_in_executor(self, func: functools.partial[T]) -> T:
        """Run a blocking function in a thread pool executor.

        Args:
            func: Partial function to execute

        Returns:
            Result from the function
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, func)

    async def record_outcome(self, outcome: ConsensusOutcome) -> None:
        """Record an outcome to the database (async).

        Args:
            outcome: ConsensusOutcome to record
        """
        await self._run_in_executor(functools.partial(self._sync_tracker.record_outcome, outcome))

    async def get_outcome(self, debate_id: str) -> ConsensusOutcome | None:
        """Get outcome by debate ID (async).

        Args:
            debate_id: ID of the debate to retrieve

        Returns:
            ConsensusOutcome if found, None otherwise
        """
        return await self._run_in_executor(
            functools.partial(self._sync_tracker.get_outcome, debate_id)
        )

    async def get_recent_outcomes(self, limit: int = 50) -> list[ConsensusOutcome]:
        """Get recent outcomes ordered by timestamp (async).

        Args:
            limit: Maximum number of outcomes to return

        Returns:
            List of ConsensusOutcome objects
        """
        return await self._run_in_executor(
            functools.partial(self._sync_tracker.get_recent_outcomes, limit)
        )

    async def get_success_rate_by_confidence(
        self,
        bucket_size: float = 0.1,
    ) -> dict[str, float]:
        """Get success rate bucketed by confidence level (async).

        Args:
            bucket_size: Size of each confidence bucket

        Returns:
            Dict mapping confidence range (e.g., "0.7-0.8") to success rate
        """
        return await self._run_in_executor(
            functools.partial(self._sync_tracker.get_success_rate_by_confidence, bucket_size)
        )

    async def get_calibration_curve(
        self,
        num_buckets: int = 10,
    ) -> list[CalibrationBucket]:
        """Get calibration curve data (async).

        Args:
            num_buckets: Number of buckets to divide the confidence range into

        Returns:
            List of CalibrationBucket objects showing actual vs expected
            success rates for each confidence level.
        """
        return await self._run_in_executor(
            functools.partial(self._sync_tracker.get_calibration_curve, num_buckets)
        )

    async def get_failure_patterns(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get common failure reasons with frequency (async).

        Args:
            limit: Maximum number of patterns to return

        Returns:
            List of dicts with 'reason' and 'count' keys.
        """
        return await self._run_in_executor(
            functools.partial(self._sync_tracker.get_failure_patterns, limit)
        )

    async def get_overall_stats(self) -> dict[str, Any]:
        """Get overall outcome statistics (async).

        Returns:
            Dict with statistics including total_outcomes, attempted, succeeded,
            success_rate, rollbacks, avg_confidence, total_tests_passed,
            total_tests_failed.
        """
        return await self._run_in_executor(functools.partial(self._sync_tracker.get_overall_stats))

    async def is_overconfident(self, threshold: float = 0.7) -> bool:
        """Check if the system is overconfident (async).

        Returns True if high-confidence (>threshold) debates have
        lower success rate than their confidence suggests.

        Args:
            threshold: Confidence threshold to consider

        Returns:
            True if the system is overconfident
        """
        return await self._run_in_executor(
            functools.partial(self._sync_tracker.is_overconfident, threshold)
        )

    async def get_calibration_adjustment(self) -> float:
        """Get recommended adjustment for Trickster sensitivity (async).

        Returns a multiplier:
        - < 1.0: System is overconfident, increase Trickster sensitivity
        - > 1.0: System is underconfident, can decrease sensitivity
        - 1.0: Well-calibrated

        Returns:
            Adjustment multiplier clamped to [0.5, 1.5]
        """
        return await self._run_in_executor(
            functools.partial(self._sync_tracker.get_calibration_adjustment)
        )

    @property
    def db_path(self) -> Path:
        """Get the database path."""
        return self._sync_tracker.db_path
