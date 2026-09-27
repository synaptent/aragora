"""Workspace-to-Pipeline bridge for execution history deduplication.

Queries workspace beads for recently completed work that matches a given
goal or topic, allowing the Idea-to-Execution pipeline to skip stages
that have already been accomplished.

The bridge uses keyword matching against bead titles and descriptions to
find related past work, then produces a ``WorkspaceContext`` summarising
what was already done, what goals can be skipped, and how long ago each
piece of work was completed.

Usage:
    bridge = WorkspacePipelineBridge()
    ctx = await bridge.query_context("Implement rate limiter")
    if "implement rate limiter" in ctx.completed_goals:
        print("Already done!")
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, cast

logger = logging.getLogger(__name__)

# Beads older than this many days are considered stale and excluded.
DEFAULT_STALENESS_DAYS = 30

# Minimum keyword overlap ratio to consider a bead "related".
_MIN_KEYWORD_OVERLAP = 0.3

# Common stop-words filtered out of keyword extraction.
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "is",
        "it",
        "as",
        "be",
        "was",
        "are",
        "from",
        "this",
        "that",
        "not",
        "we",
        "should",
        "can",
        "will",
        "do",
        "has",
        "have",
        "been",
    }
)


def _extract_keywords(text: str) -> set[str]:
    """Extract normalised keywords from *text*, filtering stop-words."""
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def _keyword_overlap(query_kw: set[str], target_kw: set[str]) -> float:
    """Return the fraction of *query_kw* present in *target_kw*."""
    if not query_kw:
        return 0.0
    return len(query_kw & target_kw) / len(query_kw)


@dataclass
class BeadSummary:
    """Lightweight summary of a workspace bead for pipeline context."""

    bead_id: str
    title: str
    description: str
    status: str  # "done", "failed", "running", etc.
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    days_ago: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "bead_id": self.bead_id,
            "title": self.title,
            "status": self.status,
            "days_ago": round(self.days_ago, 1),
        }
        if self.description:
            d["description"] = self.description
        if self.result:
            d["result_summary"] = str(self.result)[:200]
        return d


@dataclass
class WorkspaceContext:
    """Context assembled from workspace execution history.

    Provided to the pipeline so it can skip, annotate, or prioritise
    goals based on what has already been attempted.
    """

    related_beads: list[BeadSummary] = field(default_factory=list)
    completed_goals: set[str] = field(default_factory=set)
    suggested_skip_stages: list[str] = field(default_factory=list)
    execution_history: list[str] = field(default_factory=list)

    @property
    def has_context(self) -> bool:
        return bool(self.related_beads)

    def to_dict(self) -> dict[str, Any]:
        return {
            "related_beads": [b.to_dict() for b in self.related_beads],
            "completed_goals": sorted(self.completed_goals),
            "suggested_skip_stages": self.suggested_skip_stages,
            "execution_history": self.execution_history,
            "has_context": self.has_context,
        }


class WorkspacePipelineBridge:
    """Queries workspace beads for execution history relevant to a goal.

    The bridge lazily imports workspace modules so it does not pull in
    heavy dependencies at module load time.  If the workspace store is
    not initialised or unavailable, all queries return empty context.

    Args:
        bead_manager: Explicit ``BeadManager`` instance (auto-created if
            ``None``).
        staleness_days: Beads completed more than this many days ago are
            excluded from results.
        min_keyword_overlap: Minimum fraction of query keywords that must
            appear in a bead for it to be considered related.
    """

    def __init__(
        self,
        bead_manager: Any | None = None,
        staleness_days: int = DEFAULT_STALENESS_DAYS,
        min_keyword_overlap: float = _MIN_KEYWORD_OVERLAP,
    ) -> None:
        self._bead_manager = bead_manager
        self._staleness_days = staleness_days
        self._min_overlap = min_keyword_overlap
        self._initialised = False

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    async def _ensure_bead_manager(self) -> bool:
        """Lazily create a BeadManager if one was not injected.

        Returns ``True`` if a manager is available, ``False`` otherwise.
        """
        if self._bead_manager is not None:
            self._initialised = True
            return True

        if self._initialised:
            # Already tried and failed.
            return self._bead_manager is not None

        self._initialised = True
        try:
            from aragora.workspace.bead import BeadManager  # noqa: F811

            self._bead_manager = BeadManager()
            return True
        except (ImportError, RuntimeError, ValueError, TypeError, OSError, AttributeError) as exc:
            logger.debug("Workspace BeadManager unavailable; bridge disabled: %s", exc)
            return False

    @property
    def available(self) -> bool:
        """Whether a bead manager has been configured."""
        return self._bead_manager is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def query_context(
        self,
        goal: str,
        *,
        staleness_days: int | None = None,
    ) -> WorkspaceContext:
        """Query workspace for beads related to *goal*.

        Args:
            goal: The goal or topic to search for.
            staleness_days: Override the default staleness window.

        Returns:
            A ``WorkspaceContext`` summarising related past work.
        """
        ctx = WorkspaceContext()

        if not await self._ensure_bead_manager():
            return ctx
        bead_manager = cast(Any, self._bead_manager)

        max_age = staleness_days if staleness_days is not None else self._staleness_days
        cutoff = time.time() - (max_age * 86400)
        query_kw = _extract_keywords(goal)

        if not query_kw:
            return ctx

        try:
            all_beads = await bead_manager.list_beads()
        except (RuntimeError, ValueError, TypeError, OSError, AttributeError, KeyError) as exc:
            logger.debug("Failed to list beads from workspace store: %s", exc)
            return ctx

        seen_titles: set[str] = set()

        for bead in all_beads:
            # Freshness filter: exclude beads created before cutoff that
            # are not yet completed, or completed before cutoff.
            bead_time = getattr(bead, "completed_at", None) or getattr(bead, "created_at", None)
            if bead_time is not None and bead_time < cutoff:
                continue

            title = getattr(bead, "title", "") or ""
            description = getattr(bead, "description", "") or ""
            combined_text = f"{title} {description}"
            bead_kw = _extract_keywords(combined_text)

            overlap = _keyword_overlap(query_kw, bead_kw)
            if overlap < self._min_overlap:
                continue

            status_raw = getattr(bead, "status", None)
            status_str = (
                cast(Any, status_raw).value if hasattr(status_raw, "value") else str(status_raw)
            )

            completed_at = getattr(bead, "completed_at", None)
            now = time.time()
            days_ago = (now - completed_at) / 86400 if completed_at else 0.0

            # Deduplicate by normalised title
            norm_title = title.strip().lower()
            if norm_title in seen_titles:
                continue
            seen_titles.add(norm_title)

            summary = BeadSummary(
                bead_id=getattr(bead, "bead_id", getattr(bead, "id", "")),
                title=title,
                description=description[:300],
                status=status_str,
                completed_at=completed_at,
                result=getattr(bead, "result", None),
                days_ago=days_ago,
            )
            ctx.related_beads.append(summary)

            # Track completed goals
            if status_str in ("done", "completed"):
                ctx.completed_goals.add(norm_title)
                ctx.execution_history.append(
                    f"Last attempt at '{title}' was {days_ago:.1f} days ago, result: success"
                )
            elif status_str == "failed":
                ctx.execution_history.append(
                    f"Last attempt at '{title}' was {days_ago:.1f} days ago, result: failed"
                )

        # Suggest skipping ideation if enough goals are already done
        if ctx.completed_goals:
            ctx.suggested_skip_stages.append("ideation")

        return ctx

    async def mark_completed_goals(
        self,
        goal_graph: Any,
        workspace_ctx: WorkspaceContext,
    ) -> int:
        """Annotate goals in *goal_graph* that were already completed.

        Adds ``workspace_status: "already_done"`` to the goal's metadata
        for each goal whose normalised title appears in
        ``workspace_ctx.completed_goals``.

        Returns the number of goals marked.
        """
        marked = 0
        if not workspace_ctx.completed_goals:
            return marked

        for goal in getattr(goal_graph, "goals", []):
            norm = getattr(goal, "title", "").strip().lower()
            if norm in workspace_ctx.completed_goals:
                meta = getattr(goal, "metadata", None)
                if meta is None:
                    meta = {}
                    goal.metadata = meta
                meta["workspace_status"] = "already_done"
                # Find the matching bead for richer annotation
                for bead_summary in workspace_ctx.related_beads:
                    if bead_summary.title.strip().lower() == norm:
                        meta["workspace_bead_id"] = bead_summary.bead_id
                        meta["workspace_days_ago"] = bead_summary.days_ago
                        break
                marked += 1

        return marked
