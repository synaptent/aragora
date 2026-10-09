"""
A/B testing framework for prompt evolution.

Enables scientific comparison of evolved prompts vs baseline prompts
through controlled debate experiments.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from aragora.config import DB_TIMEOUT_SECONDS, resolve_db_path
from aragora.storage.base_store import SQLiteStore

logger = logging.getLogger(__name__)

AB_TEST_LOG_SCHEMA_VERSION = "1.0"
DEFAULT_AB_TEST_DIMENSIONS = (
    "relevance",
    "accuracy",
    "completeness",
    "clarity",
    "reasoning",
    "evidence",
    "safety",
)
AB_TEST_LOG_METADATA_KEYS = (
    "experiment",
    "hypothesis",
    "rubric",
    "tags",
    "notes",
    "owner",
)

# Explicit column list for SELECT queries - must match ABTest.from_row() order
AB_TEST_COLUMNS = """id, agent, baseline_prompt_version, evolved_prompt_version,
    baseline_wins, evolved_wins, baseline_debates, evolved_debates,
    started_at, concluded_at, status, metadata"""


class ABTestStatus(Enum):
    """Status of an A/B test."""

    ACTIVE = "active"
    CONCLUDED = "concluded"
    CANCELLED = "cancelled"


@dataclass
class ABTestRubric:
    """Rubric metadata for evaluating A/B test outcomes."""

    name: str
    version: str = "1.0"
    dimensions: list[str] = field(default_factory=lambda: list(DEFAULT_AB_TEST_DIMENSIONS))
    weights: dict[str, float] = field(default_factory=dict)
    scale: str = "1-5"
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.dimensions:
            self.dimensions = list(DEFAULT_AB_TEST_DIMENSIONS)
        self.weights = _normalize_weights(self.dimensions, self.weights)

    def to_dict(self) -> dict[str, Any]:
        """Serialize rubric to a dict for storage/logging."""
        return {
            "name": self.name,
            "version": self.version,
            "dimensions": list(self.dimensions),
            "weights": dict(self.weights),
            "scale": self.scale,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ABTestRubric:
        """Parse rubric from a dictionary."""
        return cls(
            name=str(data.get("name", "default")),
            version=str(data.get("version", "1.0")),
            dimensions=list(data.get("dimensions") or list(DEFAULT_AB_TEST_DIMENSIONS)),
            weights=dict(data.get("weights") or {}),
            scale=str(data.get("scale", "1-5")),
            notes=data.get("notes"),
        )


def _normalize_weights(
    dimensions: list[str],
    weights: dict[str, Any] | None,
) -> dict[str, float]:
    if not weights:
        return {dim: 1.0 / max(len(dimensions), 1) for dim in dimensions}

    normalized: dict[str, float] = {}
    for dim in dimensions:
        try:
            normalized[dim] = float(weights.get(dim, 0.0))
        except (TypeError, ValueError):
            normalized[dim] = 0.0
    total = sum(normalized.values())
    if total <= 0:
        return {dim: 1.0 / max(len(dimensions), 1) for dim in dimensions}
    return {dim: value / total for dim, value in normalized.items()}


def _extract_log_metadata(metadata: dict | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {key: metadata[key] for key in AB_TEST_LOG_METADATA_KEYS if key in metadata}


def _build_ab_test_log_event(
    event: str,
    test: ABTest,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": AB_TEST_LOG_SCHEMA_VERSION,
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test_id": test.id,
        "agent": test.agent,
        "baseline_prompt_version": test.baseline_prompt_version,
        "evolved_prompt_version": test.evolved_prompt_version,
        "status": test.status.value,
        "baseline_wins": test.baseline_wins,
        "evolved_wins": test.evolved_wins,
        "baseline_debates": test.baseline_debates,
        "evolved_debates": test.evolved_debates,
    }
    metadata = _extract_log_metadata(test.metadata)
    if metadata:
        payload["metadata"] = metadata
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


@dataclass
class ABTest:
    """
    An A/B test comparing baseline and evolved prompts.

    Tracks wins and losses for each variant to determine
    if the evolved prompt is actually an improvement.
    """

    id: str
    agent: str
    baseline_prompt_version: int
    evolved_prompt_version: int
    baseline_wins: int = 0
    evolved_wins: int = 0
    baseline_debates: int = 0
    evolved_debates: int = 0
    started_at: str = ""
    concluded_at: str | None = None
    status: ABTestStatus = ABTestStatus.ACTIVE
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()

    @property
    def evolved_win_rate(self) -> float:
        """Calculate win rate for evolved prompt."""
        total = self.baseline_wins + self.evolved_wins
        return self.evolved_wins / total if total > 0 else 0.5

    @property
    def baseline_win_rate(self) -> float:
        """Calculate win rate for baseline prompt."""
        total = self.baseline_wins + self.evolved_wins
        return self.baseline_wins / total if total > 0 else 0.5

    @property
    def total_debates(self) -> int:
        """Total debates in the test."""
        return self.baseline_debates + self.evolved_debates

    @property
    def sample_size(self) -> int:
        """Number of decided debates (with a winner)."""
        return self.baseline_wins + self.evolved_wins

    @property
    def is_significant(self) -> bool:
        """
        Check if results are statistically significant.

        Uses a simple threshold: at least 20 samples and
        > 60% win rate difference.
        """
        if self.sample_size < 20:
            return False

        diff = abs(self.evolved_win_rate - 0.5)
        return diff > 0.1  # 10% improvement threshold

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "agent": self.agent,
            "baseline_prompt_version": self.baseline_prompt_version,
            "evolved_prompt_version": self.evolved_prompt_version,
            "baseline_wins": self.baseline_wins,
            "evolved_wins": self.evolved_wins,
            "baseline_debates": self.baseline_debates,
            "evolved_debates": self.evolved_debates,
            "evolved_win_rate": self.evolved_win_rate,
            "baseline_win_rate": self.baseline_win_rate,
            "total_debates": self.total_debates,
            "sample_size": self.sample_size,
            "is_significant": self.is_significant,
            "started_at": self.started_at,
            "concluded_at": self.concluded_at,
            "status": self.status.value,
            "metadata": self.metadata,
        }

    @property
    def rubric(self) -> ABTestRubric | None:
        """Return rubric metadata if present."""
        if isinstance(self.metadata, dict) and "rubric" in self.metadata:
            rubric_data = self.metadata.get("rubric")
            if isinstance(rubric_data, dict):
                return ABTestRubric.from_dict(rubric_data)
        return None

    @classmethod
    def from_row(cls, row: tuple) -> ABTest:
        """Create from database row."""
        return cls(
            id=row[0],
            agent=row[1],
            baseline_prompt_version=row[2],
            evolved_prompt_version=row[3],
            baseline_wins=row[4],
            evolved_wins=row[5],
            baseline_debates=row[6],
            evolved_debates=row[7],
            started_at=row[8],
            concluded_at=row[9],
            status=ABTestStatus(row[10]) if row[10] else ABTestStatus.ACTIVE,
            metadata=json.loads(row[11]) if row[11] else {},
        )


@dataclass
class ABTestResult:
    """Result of concluding an A/B test."""

    test_id: str
    winner: str  # "baseline", "evolved", or "tie"
    confidence: float
    recommendation: str
    stats: dict = field(default_factory=dict)


class ABTestManager(SQLiteStore):
    """
    Manages A/B tests for prompt evolution.

    Provides:
    - Test creation and lifecycle management
    - Result recording and aggregation
    - Statistical analysis for decision making

    Inherits from SQLiteStore for standardized schema management.
    """

    SCHEMA_NAME = "ab_testing"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS ab_tests (
            id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            baseline_prompt_version INTEGER NOT NULL,
            evolved_prompt_version INTEGER NOT NULL,
            baseline_wins INTEGER DEFAULT 0,
            evolved_wins INTEGER DEFAULT 0,
            baseline_debates INTEGER DEFAULT 0,
            evolved_debates INTEGER DEFAULT 0,
            started_at TEXT,
            concluded_at TEXT,
            status TEXT DEFAULT 'active',
            metadata TEXT,
            UNIQUE(agent, status)
        );

        CREATE TABLE IF NOT EXISTS ab_test_debates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id TEXT NOT NULL,
            debate_id TEXT NOT NULL,
            variant TEXT NOT NULL,
            won INTEGER NOT NULL,
            recorded_at TEXT,
            FOREIGN KEY (test_id) REFERENCES ab_tests(id),
            UNIQUE(test_id, debate_id)
        );
    """

    def __init__(self, db_path: str = "ab_tests.db"):
        """
        Initialize the A/B test manager.

        Args:
            db_path: Path to SQLite database file
        """
        super().__init__(resolve_db_path(db_path), timeout=DB_TIMEOUT_SECONDS)

    def start_test(
        self,
        agent: str,
        baseline_version: int,
        evolved_version: int,
        metadata: dict | None = None,
        rubric: ABTestRubric | dict[str, Any] | None = None,
    ) -> ABTest:
        """
        Start a new A/B test for an agent.

        Args:
            agent: Agent name
            baseline_version: Version number of baseline prompt
            evolved_version: Version number of evolved prompt
            metadata: Optional additional metadata

        Returns:
            The created ABTest

        Raises:
            ValueError: If agent already has an active test
        """
        # Check for existing active test
        existing = self.get_active_test(agent)
        if existing:
            raise ValueError(f"Agent {agent} already has an active test: {existing.id}")

        metadata_dict = dict(metadata or {})
        if rubric is not None:
            rubric_obj = (
                rubric if isinstance(rubric, ABTestRubric) else ABTestRubric.from_dict(rubric)
            )
            metadata_dict["rubric"] = rubric_obj.to_dict()

        test = ABTest(
            id=str(uuid.uuid4()),
            agent=agent,
            baseline_prompt_version=baseline_version,
            evolved_prompt_version=evolved_version,
            metadata=metadata_dict,
        )

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ab_tests
                (id, agent, baseline_prompt_version, evolved_prompt_version,
                 started_at, status, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    test.id,
                    test.agent,
                    test.baseline_prompt_version,
                    test.evolved_prompt_version,
                    test.started_at,
                    test.status.value,
                    json.dumps(test.metadata),
                ),
            )

        logger.info(
            "Started A/B test %s for %s: v%s vs v%s",
            test.id,
            agent,
            baseline_version,
            evolved_version,
        )
        self._log_event(
            "ab_test_started", test, rubric=test.rubric.to_dict() if test.rubric else None
        )

        return test

    def get_test(self, test_id: str) -> ABTest | None:
        """Get a specific A/B test by ID."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT {AB_TEST_COLUMNS} FROM ab_tests WHERE id = ?",  # nosec B608  # noqa: S608
                (test_id,),
            )
            row = cursor.fetchone()

            if row:
                return ABTest.from_row(row)
            return None

    def get_active_test(self, agent: str) -> ABTest | None:
        """Get the active A/B test for an agent, if any."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT {AB_TEST_COLUMNS} FROM ab_tests WHERE agent = ? AND status = 'active'",  # nosec B608  # noqa: S608
                (agent,),
            )
            row = cursor.fetchone()

            if row:
                return ABTest.from_row(row)
            return None

    def get_agent_tests(self, agent: str, limit: int = 10) -> list[ABTest]:
        """Get all tests for an agent."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT {AB_TEST_COLUMNS} FROM ab_tests
                WHERE agent = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,  # nosec B608 - AB_TEST_COLUMNS is a constant  # noqa: S608
                (agent, limit),
            )

            return [ABTest.from_row(row) for row in cursor.fetchall()]

    def record_result(
        self,
        agent: str,
        debate_id: str,
        variant: str,
        won: bool,
        metrics: dict[str, Any] | None = None,
        rubric: ABTestRubric | dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> ABTest | None:
        """
        Record a debate result for the active test.

        Args:
            agent: Agent name
            debate_id: ID of the debate
            variant: Which variant was used ("baseline" or "evolved")
            won: Whether the agent won the debate

        Returns:
            Updated ABTest or None if no active test
        """
        test = self.get_active_test(agent)
        if not test:
            logger.debug("No active A/B test for %s", agent)
            return None

        if variant not in ("baseline", "evolved"):
            raise ValueError(f"Invalid variant: {variant}")

        with self.connection() as conn:
            cursor = conn.cursor()

            # Record the debate
            try:
                cursor.execute(
                    """
                    INSERT INTO ab_test_debates
                    (test_id, debate_id, variant, won, recorded_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        test.id,
                        debate_id,
                        variant,
                        1 if won else 0,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            except sqlite3.IntegrityError:
                logger.warning("Debate %s already recorded for test %s", debate_id, test.id)
                return test

            # Update test counters
            if variant == "baseline":
                cursor.execute(
                    """
                    UPDATE ab_tests
                    SET baseline_debates = baseline_debates + 1,
                        baseline_wins = baseline_wins + ?
                    WHERE id = ?
                    """,
                    (1 if won else 0, test.id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE ab_tests
                    SET evolved_debates = evolved_debates + 1,
                        evolved_wins = evolved_wins + ?
                    WHERE id = ?
                    """,
                    (1 if won else 0, test.id),
                )

        logger.info("Recorded %s %s for test %s", variant, "win" if won else "loss", test.id)

        rubric_obj = (
            rubric
            if isinstance(rubric, ABTestRubric)
            else (ABTestRubric.from_dict(rubric) if isinstance(rubric, dict) else test.rubric)
        )
        self._log_event(
            "ab_test_result_recorded",
            test,
            debate_id=debate_id,
            variant=variant,
            won=bool(won),
            metrics=metrics,
            rubric=rubric_obj.to_dict() if rubric_obj else None,
            notes=notes,
        )

        return self.get_test(test.id)

    def conclude_test(
        self,
        test_id: str,
        force: bool = False,
    ) -> ABTestResult:
        """
        Conclude an A/B test and determine the winner.

        Args:
            test_id: ID of the test to conclude
            force: Force conclusion even if not statistically significant

        Returns:
            ABTestResult with winner and recommendation
        """
        test = self.get_test(test_id)
        if not test:
            raise ValueError(f"Test not found: {test_id}")

        if test.status != ABTestStatus.ACTIVE:
            raise ValueError(f"Test already concluded: {test_id}")

        # Determine winner
        if test.sample_size == 0:
            winner = "tie"
            confidence = 0.0
            recommendation = "No data collected. Cannot determine winner."
        elif test.evolved_win_rate > 0.55:
            winner = "evolved"
            confidence = min(1.0, (test.evolved_win_rate - 0.5) * 5)
            recommendation = (
                f"Evolved prompt (v{test.evolved_prompt_version}) wins with "
                f"{test.evolved_win_rate:.1%} win rate. Recommend adoption."
            )
        elif test.baseline_win_rate > 0.55:
            winner = "baseline"
            confidence = min(1.0, (test.baseline_win_rate - 0.5) * 5)
            recommendation = (
                f"Baseline prompt (v{test.baseline_prompt_version}) performs better. "
                f"Recommend keeping current version."
            )
        else:
            winner = "tie"
            confidence = 0.3
            recommendation = (
                "No significant difference detected. "
                "Consider running longer test or trying different evolution."
            )

        # Add significance warning if needed
        if not test.is_significant and not force:
            recommendation += (
                " Note: Results may not be statistically significant "
                f"(n={test.sample_size}). Consider collecting more data."
            )

        # Update test status
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE ab_tests
                SET status = 'concluded',
                    concluded_at = ?
                WHERE id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), test_id),
            )

        result = ABTestResult(
            test_id=test_id,
            winner=winner,
            confidence=confidence,
            recommendation=recommendation,
            stats={
                "evolved_win_rate": test.evolved_win_rate,
                "baseline_win_rate": test.baseline_win_rate,
                "sample_size": test.sample_size,
                "total_debates": test.total_debates,
                "is_significant": test.is_significant,
            },
        )

        logger.info(
            "Concluded A/B test %s: winner=%s, confidence=%.2f", test_id, winner, confidence
        )
        self._log_event(
            "ab_test_concluded",
            test,
            winner=winner,
            confidence=confidence,
            stats=result.stats,
        )

        return result

    def cancel_test(self, test_id: str) -> bool:
        """Cancel an active test without concluding."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE ab_tests
                SET status = 'cancelled',
                    concluded_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (datetime.now(timezone.utc).isoformat(), test_id),
            )
            cancelled = cursor.rowcount > 0
        if cancelled:
            test = self.get_test(test_id)
            if test:
                self._log_event("ab_test_cancelled", test)
        return cancelled

    def get_variant_for_debate(self, agent: str) -> str | None:
        """
        Get which variant to use for the next debate.

        Alternates between baseline and evolved to ensure
        balanced sampling.

        Returns:
            "baseline" or "evolved", or None if no active test
        """
        test = self.get_active_test(agent)
        if not test:
            return None

        # Use the variant with fewer debates
        if test.baseline_debates <= test.evolved_debates:
            return "baseline"
        return "evolved"

    def _log_event(self, event: str, test: ABTest, **extra: Any) -> None:
        payload = _build_ab_test_log_event(event, test, **extra)
        logger.info(event, extra={"ab_test_event": payload})
