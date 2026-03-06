"""Knowledge Mound Feedback Bridge for the Nomic Loop.

After a successful self-improvement cycle, this bridge extracts
learned patterns and persists them in the Knowledge Mound so that
future cycles can query past experience.

Usage:
    from aragora.nomic.km_feedback_bridge import KMFeedbackBridge
    from aragora.nomic.cycle_telemetry import CycleRecord

    bridge = KMFeedbackBridge()
    bridge.persist_cycle_learnings(record)

    learnings = bridge.retrieve_relevant_learnings("improve test coverage")
    for item in learnings:
        print(item["content"])
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LearningItem:
    """A single learning extracted from a cycle."""

    content: str
    tags: list[str] = field(default_factory=list)
    source: str = "nomic_cycle"
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "tags": self.tags,
            "source": self.source,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

_ERROR_PATTERNS: list[tuple[str, list[str]]] = [
    ("test_failure", ["assert", "test fail", "pytest", "unittest", "test_failure"]),
    (
        "syntax_error",
        ["syntaxerror", "syntax error", "invalid syntax", "unexpected token", "unexpected eof"],
    ),
    ("import_error", ["importerror", "import error", "modulenotfounderror", "no module named"]),
    ("timeout", ["timeout", "timed out", "deadline exceeded", "asyncio.timeout"]),
    ("budget_exceeded", ["budget", "cost limit", "rate limit", "quota", "429"]),
    ("merge_conflict", ["merge conflict", "conflict marker", "<<<<<<", ">>>>>>", "cannot merge"]),
    ("gauntlet_fail", ["gauntlet", "receipt verification", "gauntlet fail", "receipt invalid"]),
]


def classify_error(error_str: str) -> str:
    """Classify an error string into a known category.

    Returns one of: ``"test_failure"``, ``"syntax_error"``, ``"import_error"``,
    ``"timeout"``, ``"budget_exceeded"``, ``"merge_conflict"``,
    ``"gauntlet_fail"``, ``"unknown"``.
    """
    if not error_str:
        return "unknown"
    lower = error_str.lower()
    for category, keywords in _ERROR_PATTERNS:
        if any(kw in lower for kw in keywords):
            return category
    return "unknown"


class KMFeedbackBridge:
    """Bridge between the Nomic Loop and the Knowledge Mound.

    Responsibilities:
    1. **persist_cycle_learnings**: After a cycle, extract what worked,
       what failed, and which agents performed best, then store as
       KnowledgeItems with structured tags.
    2. **retrieve_relevant_learnings**: Before a cycle, query KM for
       past learnings relevant to the current goal.
    """

    def __init__(self, km: Any | None = None):
        """Initialize the bridge.

        Args:
            km: Optional Knowledge Mound instance. If None, will attempt
                to acquire one via ``get_knowledge_mound()`` at call time.
        """
        self._km = km
        self._in_memory_store: list[LearningItem] = []

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------

    def persist_cycle_learnings(self, cycle_record: Any) -> list[LearningItem]:
        """Extract learnings from a cycle record and persist to KM.

        Args:
            cycle_record: A CycleRecord (from cycle_telemetry) or any
                          object with matching attributes.

        Returns:
            List of LearningItem objects that were persisted.
        """
        items = self._extract_learnings(cycle_record)
        if not items:
            return []

        km = self._get_km()
        persisted: list[LearningItem] = []

        for item in items:
            # Always store in memory first (guaranteed to succeed)
            self._in_memory_store.append(item)
            persisted.append(item)
            # Then attempt KM ingestion (best-effort)
            if km is not None:
                try:
                    self._ingest_to_km(km, item)
                except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as e:
                    logger.debug("km_feedback_persist_failed: %s", e)

        logger.info(
            "km_feedback_persisted count=%d cycle=%s goal=%s",
            len(persisted),
            getattr(cycle_record, "cycle_id", "unknown"),
            getattr(cycle_record, "goal", "")[:60],
        )
        return persisted

    def _extract_learnings(self, record: Any) -> list[LearningItem]:
        """Extract structured learnings from a cycle record."""
        items: list[LearningItem] = []
        cycle_id = getattr(record, "cycle_id", "unknown")
        goal = getattr(record, "goal", "")
        success = getattr(record, "success", False)
        agents = getattr(record, "agents_used", [])
        quality_delta = getattr(record, "quality_delta", 0.0)
        cost_usd = getattr(record, "cost_usd", 0.0)
        timestamp = getattr(record, "timestamp", time.time())

        base_tags = [
            "nomic_learned:true",
            f"cycle_id:{cycle_id}",
            f"goal:{goal[:80]}",
        ]

        # Learning 1: Outcome summary
        outcome = "succeeded" if success else "failed"
        items.append(
            LearningItem(
                content=(
                    f"Nomic cycle {cycle_id} {outcome} on goal: {goal}. "
                    f"Quality delta: {quality_delta:.4f}, cost: ${cost_usd:.4f}, "
                    f"agents: {', '.join(agents) if agents else 'none'}."
                ),
                tags=base_tags + [f"outcome:{outcome}"],
                source="nomic_cycle_summary",
                timestamp=timestamp,
            )
        )

        # Learning 2: Agent performance (if we have agent data)
        if agents:
            if success:
                items.append(
                    LearningItem(
                        content=(
                            f"Agents {', '.join(agents)} succeeded on goal type: {goal[:60]}. "
                            f"Consider reusing this team for similar goals."
                        ),
                        tags=base_tags + ["agent_success"] + [f"agent:{a}" for a in agents[:5]],
                        source="nomic_agent_performance",
                        timestamp=timestamp,
                    )
                )
            else:
                items.append(
                    LearningItem(
                        content=(
                            f"Agents {', '.join(agents)} failed on goal type: {goal[:60]}. "
                            f"Consider alternative agents or different decomposition."
                        ),
                        tags=base_tags + ["agent_failure"] + [f"agent:{a}" for a in agents[:5]],
                        source="nomic_agent_performance",
                        timestamp=timestamp,
                    )
                )

        # Learning 3: Cost efficiency
        if success and cost_usd > 0 and quality_delta > 0:
            efficiency = quality_delta / cost_usd
            items.append(
                LearningItem(
                    content=(
                        f"Cost efficiency for goal '{goal[:40]}': "
                        f"{efficiency:.2f} quality-per-dollar "
                        f"(delta={quality_delta:.4f}, cost=${cost_usd:.4f})."
                    ),
                    tags=base_tags + ["cost_efficiency"],
                    source="nomic_cost_analysis",
                    timestamp=timestamp,
                )
            )

        return items

    # ------------------------------------------------------------------
    # Retrieve
    # ------------------------------------------------------------------

    def retrieve_relevant_learnings(
        self,
        goal_text: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Query KM for past learnings relevant to the given goal.

        Falls back to in-memory keyword search if KM is unavailable.

        Args:
            goal_text: The current goal to find relevant learnings for.
            limit: Maximum number of results.

        Returns:
            List of dicts with 'content', 'tags', 'source', 'timestamp'.
        """
        results: list[dict[str, Any]] = []

        # Try KM first
        km = self._get_km()
        if km is not None:
            try:
                km_results = self._search_km(km, goal_text, limit)
                results.extend(km_results)
            except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as e:
                logger.debug("km_feedback_retrieve_km_failed: %s", e)

        # Supplement with in-memory store
        if len(results) < limit:
            in_memory = self._search_in_memory(goal_text, limit - len(results))
            results.extend(in_memory)

        logger.info(
            "km_feedback_retrieved count=%d goal=%s",
            len(results),
            goal_text[:60],
        )
        return results[:limit]

    # ------------------------------------------------------------------
    # Internal: KM operations
    # ------------------------------------------------------------------

    def _get_km(self) -> Any:
        """Acquire a Knowledge Mound instance."""
        if self._km is not None:
            return self._km

        try:
            from aragora.knowledge.mound import get_knowledge_mound

            return get_knowledge_mound()
        except ImportError:
            return None
        except (RuntimeError, OSError, ValueError) as e:
            logger.debug("km_feedback_km_unavailable: %s", e)
            return None

    def _ingest_to_km(self, km: Any, item: LearningItem) -> None:
        """Ingest a single learning item into the KM."""
        try:
            from aragora.knowledge.mound.core import KnowledgeItem

            ki = KnowledgeItem(  # type: ignore[call-arg]
                content=item.content,
                source=item.source,  # type: ignore[arg-type]
                tags=item.tags,
            )

            # Synchronous ingestion (preferred for reliability)
            if hasattr(km, "ingest_sync"):
                km.ingest_sync(ki)
            elif hasattr(km, "ingest"):
                # Try fire-and-forget async
                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(km.ingest(ki))
                except RuntimeError:
                    # No event loop - skip
                    pass
        except ImportError:
            logger.debug("KnowledgeItem not available for ingestion")

    def _search_km(
        self,
        km: Any,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Search KM for learnings matching the query."""
        results: list[dict[str, Any]] = []

        # Try semantic search
        if hasattr(km, "search"):
            items = km.search(
                query=f"nomic_learned {query}",
                limit=limit,
                tags=["nomic_learned:true"],
            )
            if items:
                for item in items:
                    content = getattr(item, "content", str(item))
                    tags = getattr(item, "tags", [])
                    source = getattr(item, "source", "km")
                    timestamp = getattr(item, "timestamp", 0.0)
                    results.append(
                        {
                            "content": content,
                            "tags": tags,
                            "source": source,
                            "timestamp": timestamp,
                        }
                    )

        return results

    # ------------------------------------------------------------------
    # Pipeline outcomes
    # ------------------------------------------------------------------

    def record_pipeline_outcome(
        self,
        *,
        goal: str,
        success: bool,
        completed: int = 0,
        failed: int = 0,
        duration_seconds: float = 0.0,
        orchestration_id: str = "",
    ) -> None:
        """Record a completed pipeline outcome for cross-cycle learning.

        Args:
            goal: The goal that was executed.
            success: Whether the pipeline succeeded.
            completed: Number of completed subtasks.
            failed: Number of failed subtasks.
            duration_seconds: Wall-clock duration of the pipeline.
            orchestration_id: Identifier for the orchestration run.
        """
        outcome = "succeeded" if success else "failed"
        item = LearningItem(
            content=(
                f"Pipeline {outcome} on goal: {goal[:120]}. "
                f"Completed={completed}, failed={failed}, "
                f"duration={duration_seconds:.1f}s, "
                f"orchestration={orchestration_id}."
            ),
            tags=[
                "nomic_learned:true",
                f"pipeline_outcome:{outcome}",
                f"orchestration_id:{orchestration_id}",
            ],
            source="nomic_pipeline_outcome",
            timestamp=time.time(),
        )

        self._in_memory_store.append(item)

        km = self._get_km()
        if km is not None:
            try:
                self._ingest_to_km(km, item)
            except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as e:
                logger.debug("km_feedback_pipeline_outcome_failed: %s", e)

        logger.info(
            "km_feedback_pipeline_outcome goal=%s success=%s",
            goal[:60],
            success,
        )

    # ------------------------------------------------------------------
    # Structured outcomes (cross-cycle learning)
    # ------------------------------------------------------------------

    def persist_structured_outcome(
        self,
        *,
        cycle_id: str,
        goal: str,
        goal_type: str = "",
        track: str = "",
        agent: str = "",
        success: bool = False,
        files_changed: int = 0,
        quality_delta: float = 0.0,
        cost_usd: float = 0.0,
        error_pattern: str = "",
        duration_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Persist a structured outcome dict with typed tags for KM storage.

        This method provides a richer schema than ``record_pipeline_outcome``
        and is designed for cross-cycle pattern queries.

        Returns:
            The structured outcome dict that was stored.
        """
        classified_error = classify_error(error_pattern) if error_pattern else ""

        outcome: dict[str, Any] = {
            "cycle_id": cycle_id,
            "goal": goal,
            "goal_type": goal_type,
            "track": track,
            "agent": agent,
            "success": success,
            "files_changed": files_changed,
            "quality_delta": quality_delta,
            "cost_usd": cost_usd,
            "error_pattern": error_pattern,
            "error_class": classified_error,
            "duration_seconds": duration_seconds,
            "timestamp": time.time(),
        }

        tags = [
            "nomic_learned:true",
            "structured_outcome:true",
            f"cycle_id:{cycle_id}",
            f"success:{'true' if success else 'false'}",
        ]
        if goal_type:
            tags.append(f"goal_type:{goal_type}")
        if track:
            tags.append(f"track:{track}")
        if agent:
            tags.append(f"agent:{agent}")
        if classified_error:
            tags.append(f"error_class:{classified_error}")

        import json

        item = LearningItem(
            content=json.dumps(outcome, default=str),
            tags=tags,
            source="nomic_structured_outcome",
        )

        self._in_memory_store.append(item)

        km = self._get_km()
        if km is not None:
            try:
                self._ingest_to_km(km, item)
            except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as e:
                logger.debug("km_feedback_structured_outcome_persist_failed: %s", e)

        logger.info(
            "km_feedback_structured_outcome cycle=%s track=%s success=%s",
            cycle_id,
            track,
            success,
        )
        return outcome

    def retrieve_success_patterns(
        self,
        goal_type: str | None = None,
        track: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Query stored structured outcomes that were successful.

        Optionally filter by ``goal_type`` and/or ``track``.

        Returns:
            List of structured outcome dicts (most recent first).
        """
        import json

        results: list[dict[str, Any]] = []

        for item in reversed(self._in_memory_store):
            if item.source != "nomic_structured_outcome":
                continue
            if "success:true" not in item.tags:
                continue
            if goal_type and f"goal_type:{goal_type}" not in item.tags:
                continue
            if track and f"track:{track}" not in item.tags:
                continue
            try:
                parsed = json.loads(item.content)
                results.append(parsed)
            except (json.JSONDecodeError, TypeError):
                continue
            if len(results) >= limit:
                break

        return results

    def get_track_agent_effectiveness(self, track: str) -> dict[str, float]:
        """Compute per-agent success rate for a given track.

        Returns:
            Dict mapping agent name to success rate (0.0 -- 1.0).
            Agents without structured outcomes are omitted.
        """
        import json

        agent_attempts: dict[str, int] = {}
        agent_successes: dict[str, int] = {}

        for item in self._in_memory_store:
            if item.source != "nomic_structured_outcome":
                continue
            if f"track:{track}" not in item.tags:
                continue
            try:
                parsed = json.loads(item.content)
            except (json.JSONDecodeError, TypeError):
                continue
            agent = parsed.get("agent", "")
            if not agent:
                continue
            agent_attempts[agent] = agent_attempts.get(agent, 0) + 1
            if parsed.get("success"):
                agent_successes[agent] = agent_successes.get(agent, 0) + 1

        return {
            agent: agent_successes.get(agent, 0) / count
            for agent, count in agent_attempts.items()
            if count > 0
        }

    def get_error_pattern_frequency(self, limit: int = 10) -> list[tuple[str, int]]:
        """Return the most common error classes across structured outcomes.

        Returns:
            List of ``(error_class, count)`` tuples sorted descending by count.
        """
        import json

        counts: dict[str, int] = {}

        for item in self._in_memory_store:
            if item.source != "nomic_structured_outcome":
                continue
            try:
                parsed = json.loads(item.content)
            except (json.JSONDecodeError, TypeError):
                continue
            error_class = parsed.get("error_class", "")
            if error_class:
                counts[error_class] = counts.get(error_class, 0) + 1

        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_counts[:limit]

    def _search_in_memory(
        self,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Keyword-based search over in-memory store."""
        query_words = set(query.lower().split())
        scored: list[tuple[float, LearningItem]] = []

        for item in self._in_memory_store:
            content_words = set(item.content.lower().split())
            tag_words = set(
                word for tag in item.tags for word in tag.lower().replace(":", " ").split()
            )
            all_words = content_words | tag_words
            overlap = len(query_words & all_words)
            if overlap > 0:
                score = overlap / max(len(query_words), 1)
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item.to_dict() for _, item in scored[:limit]]


__all__ = [
    "KMFeedbackBridge",
    "LearningItem",
    "classify_error",
]
