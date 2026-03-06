"""User Feedback -> Self-Improvement Bridge.

Converts user feedback (NPS, bug reports, feature requests, debate quality
ratings) into actionable self-improvement goals that the Nomic Loop can
execute.  Closes the loop:

    User submits feedback -> FeedbackAnalyzer categorizes ->
    ImprovementQueue receives goal -> MetaPlanner picks up next cycle

Follows the same pattern as ``aragora.gauntlet.improvement_bridge``:
stateless conversion functions plus a thin orchestration class.

Processing state is tracked in SQLite to avoid reprocessing feedback items.

Usage:
    from aragora.nomic.feedback_analyzer import FeedbackAnalyzer

    analyzer = FeedbackAnalyzer()
    results = analyzer.process_new_feedback()
    print(f"Queued {results.goals_created} improvement goals")
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

# Feedback type -> improvement category
_FEEDBACK_TYPE_CATEGORY: dict[str, str] = {
    "bug_report": "reliability",
    "feature_request": "features",
    "debate_quality": "accuracy",
    "nps": "ux",
    "general": "ux",
}

# Category -> Nomic Loop track
_CATEGORY_TRACK: dict[str, str] = {
    "ux": "sme",
    "performance": "core",
    "accuracy": "core",
    "reliability": "core",
    "features": "developer",
}

# Category -> default priority (1 = highest, 5 = lowest)
_CATEGORY_PRIORITY: dict[str, int] = {
    "reliability": 1,
    "accuracy": 2,
    "performance": 3,
    "features": 4,
    "ux": 5,
}

# Keywords that override the default category inference
_KEYWORD_CATEGORY: dict[str, str] = {
    "slow": "performance",
    "timeout": "performance",
    "latency": "performance",
    "fast": "performance",
    "speed": "performance",
    "crash": "reliability",
    "error": "reliability",
    "broken": "reliability",
    "fail": "reliability",
    "bug": "reliability",
    "wrong": "accuracy",
    "incorrect": "accuracy",
    "inaccurate": "accuracy",
    "hallucin": "accuracy",
    "feature": "features",
    "wish": "features",
    "would be nice": "features",
    "add": "features",
    "confusing": "ux",
    "difficult": "ux",
    "hard to": "ux",
    "unclear": "ux",
    "ui": "ux",
    "ux": "ux",
}

# NPS score thresholds
_NPS_DETRACTOR_MAX = 6  # 0-6 are detractors
_NPS_PASSIVE_MAX = 8  # 7-8 are passives
_NPS_INVESTIGATION_THRESHOLD = 5  # Score <= this triggers investigation goal

# Similarity threshold for deduplication
_DEDUP_SIMILARITY_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AnalysisResult:
    """Result of processing a batch of user feedback."""

    feedback_processed: int = 0
    goals_created: int = 0
    duplicates_skipped: int = 0
    already_processed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class FeedbackItem:
    """A user feedback entry retrieved from the store."""

    id: str
    user_id: str | None
    feedback_type: str
    score: int | None
    comment: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


# ---------------------------------------------------------------------------
# Processing state store (SQLite)
# ---------------------------------------------------------------------------


def _resolve_analyzer_db_path(db_path: Path | None = None) -> str:
    """Resolve the database path for the feedback analyzer state."""
    if db_path is not None:
        return str(db_path)

    try:
        from aragora.config import resolve_db_path

        return resolve_db_path("feedback_analyzer.db")
    except ImportError:
        pass

    import os

    data_dir = os.environ.get("ARAGORA_DATA_DIR", str(Path.home() / ".aragora"))
    return os.path.join(data_dir, "feedback_analyzer.db")


class _ProcessingStateStore:
    """Tracks which feedback items have been processed."""

    _CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS processed_feedback (
    feedback_id  TEXT PRIMARY KEY,
    processed_at REAL NOT NULL,
    goal_id      TEXT,
    skipped      INTEGER NOT NULL DEFAULT 0,
    reason       TEXT
)
"""

    def __init__(self, db_path: Path | None = None):
        self._db_path = _resolve_analyzer_db_path(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_table(self) -> None:
        conn = self._connect()
        try:
            conn.execute(self._CREATE_TABLE)
            conn.commit()
        finally:
            conn.close()

    def is_processed(self, feedback_id: str) -> bool:
        """Check if a feedback item has already been processed."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT 1 FROM processed_feedback WHERE feedback_id = ?",
                (feedback_id,),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def mark_processed(
        self,
        feedback_id: str,
        *,
        goal_id: str | None = None,
        skipped: bool = False,
        reason: str | None = None,
    ) -> None:
        """Mark a feedback item as processed."""
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO processed_feedback "
                "(feedback_id, processed_at, goal_id, skipped, reason) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    feedback_id,
                    time.time(),
                    goal_id,
                    1 if skipped else 0,
                    reason,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_processed_ids(self) -> set[str]:
        """Return all processed feedback IDs."""
        conn = self._connect()
        try:
            cursor = conn.execute("SELECT feedback_id FROM processed_feedback")
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Core analyzer
# ---------------------------------------------------------------------------


class FeedbackAnalyzer:
    """Analyzes user feedback and converts high-signal items into improvement goals.

    Reads from the FeedbackStore (user-facing feedback database), categorizes
    each item, deduplicates against existing goals, and pushes new
    ``ImprovementGoal`` objects into the ``ImprovementQueue`` for the
    MetaPlanner to consume.

    Args:
        feedback_db_path: Path to the feedback SQLite database.
            If None, uses the default ``resolve_db_path("feedback.db")``.
        state_db_path: Path to the processing state database.
            If None, uses the default ``resolve_db_path("feedback_analyzer.db")``.
        queue_db_path: Path to the improvement queue database.
            If None, uses the ImprovementQueue default.
        dedup_threshold: Similarity threshold for deduplication (0.0-1.0).
    """

    def __init__(
        self,
        *,
        feedback_db_path: str | Path | None = None,
        state_db_path: Path | None = None,
        queue_db_path: Path | None = None,
        dedup_threshold: float = _DEDUP_SIMILARITY_THRESHOLD,
    ):
        self._feedback_db_path = str(feedback_db_path) if feedback_db_path else None
        self._state = _ProcessingStateStore(db_path=state_db_path)
        self._queue_db_path = queue_db_path
        self._dedup_threshold = dedup_threshold
        self._similarity_backend = None

    def _get_feedback_db_path(self) -> str:
        """Resolve the feedback database path lazily."""
        if self._feedback_db_path:
            return self._feedback_db_path
        try:
            from aragora.config import resolve_db_path

            return resolve_db_path("feedback.db")
        except ImportError:
            import os

            data_dir = os.environ.get("ARAGORA_DATA_DIR", str(Path.home() / ".aragora"))
            return os.path.join(data_dir, "feedback.db")

    def _get_improvement_queue(self) -> Any:
        """Lazy-import and create the ImprovementQueue."""
        from aragora.nomic.feedback_orchestrator import ImprovementQueue

        return ImprovementQueue(db_path=self._queue_db_path)

    def process_new_feedback(self, limit: int = 50) -> AnalysisResult:
        """Process unprocessed feedback and queue improvement goals.

        Args:
            limit: Maximum number of feedback items to process per call.

        Returns:
            AnalysisResult with counts and any errors.
        """
        result = AnalysisResult()

        try:
            items = self._fetch_unprocessed(limit=limit)
        except (sqlite3.Error, OSError) as exc:
            logger.warning("feedback_analyzer_fetch_failed: %s", exc)
            result.errors.append(f"fetch_failed: {type(exc).__name__}")
            return result

        if not items:
            return result

        # Get existing goal descriptions for deduplication
        existing_goals = self._get_existing_goal_descriptions()

        queue = self._get_improvement_queue()

        for item in items:
            try:
                self._process_one(item, queue, existing_goals, result)
            except (sqlite3.Error, OSError, ValueError, TypeError, KeyError) as exc:
                logger.warning("feedback_analyzer_item_failed id=%s: %s", item.id, exc)
                result.errors.append(f"item_{item.id}: {type(exc).__name__}")

        logger.info(
            "feedback_analyzer_complete processed=%d goals=%d dupes=%d skipped=%d",
            result.feedback_processed,
            result.goals_created,
            result.duplicates_skipped,
            result.already_processed,
        )

        return result

    def _process_one(
        self,
        item: FeedbackItem,
        queue: Any,
        existing_goals: list[str],
        result: AnalysisResult,
    ) -> None:
        """Process a single feedback item."""
        result.feedback_processed += 1

        # Skip empty/invalid feedback
        if not item.comment and item.score is None:
            self._state.mark_processed(item.id, skipped=True, reason="empty_feedback")
            return

        # Categorize
        category = self._categorize(item)
        goal_description = self._build_goal_description(item, category)

        if not goal_description:
            self._state.mark_processed(item.id, skipped=True, reason="no_description")
            return

        # Deduplicate against existing goals
        if self._is_duplicate(goal_description, existing_goals):
            self._state.mark_processed(item.id, skipped=True, reason="duplicate")
            result.duplicates_skipped += 1
            return

        # Build and push the improvement goal
        from aragora.nomic.feedback_orchestrator import ImprovementGoal

        priority_float = self._priority_to_float(_CATEGORY_PRIORITY.get(category, 5))
        goal_id = self._make_goal_id(item)

        goal = ImprovementGoal(
            goal=goal_description,
            source="user_feedback",
            priority=priority_float,
            context={
                "feedback_id": item.id,
                "feedback_type": item.feedback_type,
                "category": category,
                "track": _CATEGORY_TRACK.get(category, "core"),
                "user_id": item.user_id,
                "score": item.score,
            },
        )

        queue.push(goal)
        existing_goals.append(goal_description)

        self._state.mark_processed(item.id, goal_id=goal_id)
        result.goals_created += 1

    def _fetch_unprocessed(self, limit: int = 50) -> list[FeedbackItem]:
        """Fetch feedback items that haven't been processed yet."""
        processed_ids = self._state.get_processed_ids()

        db_path = self._get_feedback_db_path()
        if not Path(db_path).exists():
            return []

        conn = sqlite3.connect(db_path, timeout=10)
        try:
            cursor = conn.execute(
                "SELECT id, user_id, feedback_type, score, comment, metadata, created_at "
                "FROM feedback ORDER BY created_at DESC LIMIT ?",
                (limit + len(processed_ids),),  # Fetch extra to account for processed
            )
            items = []
            for row in cursor.fetchall():
                fid = row[0]
                if fid in processed_ids:
                    continue
                metadata = {}
                if row[5]:
                    try:
                        metadata = json.loads(row[5])
                    except (json.JSONDecodeError, TypeError):
                        pass
                items.append(
                    FeedbackItem(
                        id=fid,
                        user_id=row[1],
                        feedback_type=row[2],
                        score=row[3],
                        comment=row[4],
                        metadata=metadata,
                        created_at=row[6] or "",
                    )
                )
                if len(items) >= limit:
                    break
            return items
        finally:
            conn.close()

    def _get_existing_goal_descriptions(self) -> list[str]:
        """Get descriptions of existing unconsumed goals for deduplication."""
        try:
            queue = self._get_improvement_queue()
            goals = queue.peek(limit=100)
            return [g.goal for g in goals]
        except (sqlite3.Error, OSError, ImportError) as exc:
            logger.debug("Could not peek existing goals: %s", exc)
            return []

    @staticmethod
    def _categorize(item: FeedbackItem) -> str:
        """Categorize a feedback item into an improvement category.

        Uses the feedback type as a baseline, then scans keywords in the
        comment to refine the category.
        """
        # Baseline from feedback type
        category = _FEEDBACK_TYPE_CATEGORY.get(item.feedback_type, "ux")

        # NPS detractors: check comment keywords for more specific category
        if item.feedback_type == "nps" and item.score is not None:
            if item.score <= _NPS_DETRACTOR_MAX:
                category = "ux"  # Default for detractors

        # Keyword scan on comment for refinement
        if item.comment:
            comment_lower = item.comment.lower()
            for keyword, kw_category in _KEYWORD_CATEGORY.items():
                if keyword in comment_lower:
                    category = kw_category
                    break

        return category

    @staticmethod
    def _build_goal_description(item: FeedbackItem, category: str) -> str:
        """Build a human-readable improvement goal description."""
        if item.feedback_type == "bug_report":
            prefix = "Fix user-reported bug"
            detail = item.comment or "No details provided"
            return f"{prefix}: {detail[:200]}"

        if item.feedback_type == "feature_request":
            prefix = "Implement user-requested feature"
            detail = item.comment or "No details provided"
            return f"{prefix}: {detail[:200]}"

        if item.feedback_type == "debate_quality":
            if item.score is not None and item.score < 5:
                prefix = "Improve debate quality"
            else:
                prefix = "Review debate quality feedback"
            detail = item.comment or f"score={item.score}"
            return f"{prefix}: {detail[:200]}"

        if item.feedback_type == "nps":
            if item.score is not None and item.score <= _NPS_INVESTIGATION_THRESHOLD:
                prefix = f"Investigate low NPS score ({item.score}/10)"
                detail = item.comment or "No reason provided"
                return f"{prefix}: {detail[:200]}"
            elif item.comment:
                # Promoter or passive with comment: still useful feedback
                prefix = "Address NPS feedback"
                return f"{prefix} ({category}): {item.comment[:200]}"
            else:
                # High NPS without comment: no actionable goal
                return ""

        # General feedback
        if item.comment:
            prefix = f"Address user feedback ({category})"
            return f"{prefix}: {item.comment[:200]}"

        return ""

    def _is_duplicate(self, description: str, existing: list[str]) -> bool:
        """Check if a goal description is too similar to an existing one."""
        if self._similarity_backend is None:
            from aragora.debate.similarity.factory import get_backend

            self._similarity_backend = get_backend(preferred="auto")
        for existing_desc in existing:
            ratio = self._similarity_backend.compute_similarity(
                description.lower(), existing_desc.lower()
            )
            if ratio >= self._dedup_threshold:
                return True
        return False

    @staticmethod
    def _priority_to_float(priority_int: int) -> float:
        """Convert integer priority (1=highest) to float (1.0=highest).

        Uses the same mapping as FeedbackGoal.to_improvement_goal().
        """
        return max(0.0, min(1.0, 1.0 - (priority_int - 1) * 0.2))

    @staticmethod
    def _make_goal_id(item: FeedbackItem) -> str:
        """Generate a stable goal ID from a feedback item."""
        raw = f"user_feedback:{item.id}"
        return f"uf-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def process_new_feedback(**kwargs: Any) -> AnalysisResult:
    """Convenience function: create an analyzer and process new feedback.

    Accepts the same keyword arguments as ``FeedbackAnalyzer.__init__``.
    """
    analyzer = FeedbackAnalyzer(**kwargs)
    return analyzer.process_new_feedback()


__all__ = [
    "AnalysisResult",
    "FeedbackAnalyzer",
    "FeedbackItem",
    "process_new_feedback",
]
