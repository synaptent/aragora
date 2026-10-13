"""Task pattern matching for agent selection.

Classifies tasks into pattern categories and provides agent affinity scores
based on historical performance in those categories.

Integrates with CritiqueStore to leverage existing pattern tracking data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.memory.store import CritiqueStore

logger = logging.getLogger(__name__)


@dataclass
class PatternAffinity:
    """Agent's affinity for a task pattern."""

    agent_name: str
    pattern: str
    success_rate: float
    sample_size: int
    confidence: float  # Higher with more samples


# Task patterns for classification
# Maps pattern names to keyword lists
TASK_PATTERNS: dict[str, list[str]] = {
    "refactor": [
        "refactor",
        "restructure",
        "reorganize",
        "cleanup",
        "clean up",
        "extract",
        "modular",
        "decouple",
    ],
    "bugfix": [
        "fix",
        "bug",
        "error",
        "crash",
        "broken",
        "regression",
        "issue",
        "problem",
        "fault",
        "defect",
    ],
    "feature": [
        "add",
        "implement",
        "create",
        "build",
        "new",
        "feature",
        "introduce",
        "develop",
    ],
    "optimize": [
        "optimize",
        "performance",
        "speed",
        "fast",
        "efficient",
        "memory",
        "latency",
        "throughput",
    ],
    "security": [
        "security",
        "vulnerab",
        "auth",
        "encrypt",
        "sanitize",
        "injection",
        "xss",
        "csrf",
        "permission",
    ],
    "test": [
        "test",
        "coverage",
        "unit",
        "integration",
        "mock",
        "fixture",
        "assert",
        "spec",
    ],
    "docs": [
        "document",
        "readme",
        "comment",
        "docstring",
        "explain",
        "clarify",
        "guide",
    ],
    "architecture": [
        "design",
        "architect",
        "pattern",
        "structure",
        "layer",
        "component",
        "interface",
    ],
}

# Maps task patterns to CritiqueStore issue categories for lookup
PATTERN_TO_ISSUE_TYPE: dict[str, str] = {
    "refactor": "architecture",
    "bugfix": "correctness",
    "feature": "completeness",
    "optimize": "performance",
    "security": "security",
    "test": "testing",
    "docs": "clarity",
    "architecture": "architecture",
}


class TaskPatternMatcher:
    """Match task patterns to historically successful agents.

    Uses keyword matching to classify tasks and CritiqueStore data
    to find agents with strong track records in those areas.

    Example:
        matcher = TaskPatternMatcher()
        pattern = matcher.classify_task("Fix the authentication bug")
        # Returns: "bugfix"

        affinities = matcher.get_agent_affinities("bugfix", critique_store)
        # Returns: {"claude": 0.85, "gpt": 0.72, ...}
    """

    def __init__(
        self,
        patterns: dict[str, list[str]] | None = None,
        min_samples_for_confidence: int = 5,
    ):
        """Initialize the pattern matcher.

        Args:
            patterns: Custom pattern definitions (uses defaults if None)
            min_samples_for_confidence: Minimum samples for high confidence
        """
        self.patterns = patterns or TASK_PATTERNS
        self.min_samples = min_samples_for_confidence
        self._pattern_cache: dict[str, str] = {}

    def classify_task(self, task_description: str) -> str:
        """Classify a task into a pattern category.

        Uses keyword matching to identify the dominant task type.
        Returns "general" if no strong pattern match is found.

        Args:
            task_description: The task or topic to classify

        Returns:
            Pattern name (e.g., "bugfix", "refactor", "feature")
        """
        if not task_description:
            return "general"

        # Check cache
        cache_key = task_description[:200].lower()
        if cache_key in self._pattern_cache:
            return self._pattern_cache[cache_key]

        task_lower = task_description.lower()
        scores: dict[str, int] = {}

        for pattern, keywords in self.patterns.items():
            score = 0
            for keyword in keywords:
                # Count occurrences (word boundary matching for accuracy)
                matches = len(re.findall(rf"\b{re.escape(keyword)}", task_lower))
                score += matches
            scores[pattern] = score

        max_score = max(scores.values()) if scores else 0
        if max_score == 0:
            result = "general"
        else:
            result = max(scores, key=lambda k: scores[k])

        # Cache result
        self._pattern_cache[cache_key] = result
        logger.debug(
            "pattern_classification task_snippet=%r pattern=%s", task_description[:50], result
        )

        return result

    def get_agent_affinities(
        self,
        pattern: str,
        critique_store: CritiqueStore | None = None,
    ) -> dict[str, float]:
        """Get agent success rates for a task pattern.

        Queries CritiqueStore to find agents who have given valuable
        critiques in the issue category corresponding to this pattern.

        Args:
            pattern: Task pattern (e.g., "bugfix", "security")
            critique_store: CritiqueStore instance for data lookup

        Returns:
            Dict mapping agent names to success rates (0.0-1.0)
        """
        if critique_store is None:
            return {}

        # Map task pattern to issue type
        issue_type = PATTERN_TO_ISSUE_TYPE.get(pattern, "general")

        try:
            affinities = self._query_agent_pattern_stats(critique_store, issue_type)
            if affinities:
                logger.debug(
                    "agent_affinities pattern=%s issue_type=%s agents=%s",
                    pattern,
                    issue_type,
                    list(affinities.keys()),
                )
            return affinities
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("Failed to get agent affinities for %s: %s", pattern, e)
            return {}

    def _query_agent_pattern_stats(
        self,
        critique_store: CritiqueStore,
        issue_type: str,
    ) -> dict[str, float]:
        """Query CritiqueStore for agent performance in an issue type.

        Joins critiques with patterns to find which agents gave critiques
        that led to improvements in the specified issue category.

        Args:
            critique_store: CritiqueStore instance
            issue_type: Issue category to query

        Returns:
            Dict mapping agent names to improvement rates
        """
        with critique_store.connection() as conn:
            cursor = conn.cursor()

            # Query agents who gave critiques containing issues of this type
            # that led to improvements
            cursor.execute(
                """
                SELECT c.agent,
                       SUM(CASE WHEN c.led_to_improvement = 1 THEN 1 ELSE 0 END) as successes,
                       COUNT(*) as total
                FROM critiques c
                WHERE c.issues LIKE ?
                  AND c.agent IS NOT NULL
                GROUP BY c.agent
                HAVING total >= 2
                ORDER BY successes DESC
                LIMIT 20
                """,
                (f"%{issue_type}%",),
            )

            results: dict[str, float] = {}
            for row in cursor.fetchall():
                agent_name = row[0]
                successes = row[1]
                total = row[2]
                if total > 0:
                    results[agent_name] = successes / total

            # If no pattern-specific data, fall back to general agent reputation
            if not results:
                cursor.execute("""
                    SELECT agent_name,
                           CAST(critiques_valuable AS REAL) / NULLIF(critiques_given, 0) as rate
                    FROM agent_reputation
                    WHERE critiques_given > 0
                    ORDER BY rate DESC
                    LIMIT 10
                    """)
                for row in cursor.fetchall():
                    if row[1] is not None:
                        results[row[0]] = row[1]

            return results

    def get_pattern_affinities(
        self,
        pattern: str,
        critique_store: CritiqueStore | None = None,
    ) -> list[PatternAffinity]:
        """Get detailed affinity data for a pattern.

        Similar to get_agent_affinities but returns full PatternAffinity objects
        with confidence scores.

        Args:
            pattern: Task pattern name
            critique_store: CritiqueStore instance

        Returns:
            List of PatternAffinity objects sorted by confidence-weighted score
        """
        if critique_store is None:
            return []

        issue_type = PATTERN_TO_ISSUE_TYPE.get(pattern, "general")

        try:
            with critique_store.connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT c.agent,
                           SUM(CASE WHEN c.led_to_improvement = 1 THEN 1 ELSE 0 END) as successes,
                           COUNT(*) as total
                    FROM critiques c
                    WHERE c.issues LIKE ?
                      AND c.agent IS NOT NULL
                    GROUP BY c.agent
                    HAVING total >= 1
                    ORDER BY successes DESC
                    """,
                    (f"%{issue_type}%",),
                )

                affinities: list[PatternAffinity] = []
                for row in cursor.fetchall():
                    agent_name = row[0]
                    successes = row[1]
                    total = row[2]

                    success_rate = successes / total if total > 0 else 0.0
                    # Confidence increases with sample size, capped at 1.0
                    confidence = min(1.0, total / self.min_samples)

                    affinities.append(
                        PatternAffinity(
                            agent_name=agent_name,
                            pattern=pattern,
                            success_rate=success_rate,
                            sample_size=total,
                            confidence=confidence,
                        )
                    )

                # Sort by confidence-weighted success rate
                affinities.sort(
                    key=lambda a: a.success_rate * a.confidence,
                    reverse=True,
                )
                return affinities

        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("Failed to get pattern affinities for %s: %s", pattern, e)
            return []


# Module-level singleton for convenience
_pattern_matcher: TaskPatternMatcher | None = None


def get_pattern_matcher() -> TaskPatternMatcher:
    """Get or create the singleton TaskPatternMatcher instance."""
    global _pattern_matcher
    if _pattern_matcher is None:
        _pattern_matcher = TaskPatternMatcher()
    return _pattern_matcher


def classify_task(task_description: str) -> str:
    """Convenience function to classify a task."""
    return get_pattern_matcher().classify_task(task_description)
