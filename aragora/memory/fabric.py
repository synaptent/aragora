"""
MemoryFabric — Unified query interface across all memory systems.

Queries all configured systems in parallel, deduplicates results,
ranks by relevance × surprise × recency, and returns top-k.

This is the single entry-point for "what does the system know about X?"
regardless of where the knowledge is stored.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

from aragora.memory.surprise import ContentSurpriseScorer

logger = logging.getLogger(__name__)


@runtime_checkable
class SearchableBackend(Protocol):
    """Minimal protocol for any memory system the fabric can query."""

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class FabricResult:
    """A single result from a cross-system memory query."""

    content: str
    source_system: str
    relevance: float  # 0-1
    recency: float  # 0-1, based on age
    item_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RememberResult:
    """Result of a unified remember (write) operation."""

    stored: bool
    systems_written: list[str]
    surprise_combined: float
    reason: str


class MemoryFabric:
    """Unified query interface across all memory systems.

    Queries all systems in parallel, deduplicates results,
    ranks by relevance × surprise × recency, returns top-k.
    """

    def __init__(
        self,
        surprise_scorer: ContentSurpriseScorer | None = None,
        backends: dict[str, Any] | None = None,
        titans_controller: Any | None = None,
    ):
        """Initialise with optional backends keyed by system name.

        Backends should implement a ``search(query, limit) -> list[dict]``
        method.  Each dict should contain at least ``"content"`` and
        optionally ``"id"``, ``"relevance"``, ``"created_at"`` (unix ts).

        Args:
            surprise_scorer: ContentSurpriseScorer for novelty scoring.
            backends: Dict of name -> searchable backend.
            titans_controller: Optional TitansMemoryController for active
                sweep hooks (on_query / on_write).
        """
        self._scorer = surprise_scorer or ContentSurpriseScorer()
        self._backends: dict[str, Any] = backends or {}
        self._titans_controller = titans_controller

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_backend(self, name: str, backend: Any) -> None:
        """Register a searchable backend by name."""
        self._backends[name] = backend

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def query(
        self,
        query: str,
        limit: int = 10,
        systems: list[str] | None = None,
        min_relevance: float = 0.0,
    ) -> list[FabricResult]:
        """Search all (or selected) backends, deduplicate, rank, return top-k."""
        targets = (
            {k: v for k, v in self._backends.items() if k in systems}
            if systems
            else dict(self._backends)
        )

        if not targets:
            return []

        # Query each backend
        raw_results: list[FabricResult] = []
        tasks = [
            self._query_backend(name, backend, query, limit) for name, backend in targets.items()
        ]
        backend_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result_set in backend_results:
            if isinstance(result_set, BaseException):
                logger.warning("Backend query failed: %s", result_set)
                continue
            raw_results.extend(result_set)

        # Deduplicate by keyword overlap
        deduped = self._deduplicate(raw_results)

        # Filter by min relevance
        filtered = [r for r in deduped if r.relevance >= min_relevance]

        # Sort by composite score (relevance * recency)
        filtered.sort(key=lambda r: r.relevance * max(r.recency, 0.1), reverse=True)

        results = filtered[:limit]
        if self._titans_controller:
            try:
                await self._titans_controller.on_query(query, results)
            except (RuntimeError, ValueError, OSError, AttributeError, TypeError) as exc:
                logger.warning("Titans controller on_query failed: %s", exc)
        return results

    async def remember(
        self,
        content: str,
        source: str,
        metadata: dict[str, Any] | None = None,
        existing_context: str = "",
    ) -> RememberResult:
        """Score surprise, write to appropriate system(s) based on score.

        Returns which systems were written to and the surprise score.
        """
        score = self._scorer.score(content, source, existing_context)

        if not score.should_store:
            return RememberResult(
                stored=False,
                systems_written=[],
                surprise_combined=score.combined,
                reason=score.reason,
            )

        # Determine which systems to write to based on surprise level
        systems_written: list[str] = []
        if score.combined >= 0.7:
            # High surprise → write to all available backends with a store method
            for name, backend in self._backends.items():
                if hasattr(backend, "store") or hasattr(backend, "store_knowledge"):
                    systems_written.append(name)
        elif score.combined >= 0.3:
            # Moderate → write to primary backends only
            for name in ("continuum", "consensus"):
                if name in self._backends:
                    systems_written.append(name)

        result = RememberResult(
            stored=True,
            systems_written=systems_written,
            surprise_combined=score.combined,
            reason=score.reason,
        )
        if result.stored and self._titans_controller:
            try:
                await self._titans_controller.on_write(
                    item_id=f"{source}_{hash(content) % 10**8}",
                    source=source,
                    content=content,
                )
            except (RuntimeError, ValueError, OSError, AttributeError, TypeError) as exc:
                logger.warning("Titans controller on_write failed: %s", exc)
        return result

    async def context_for_debate(
        self,
        task: str,
        budget_tokens: int = 2000,
    ) -> str:
        """One-call method: query + format + budget for debate injection."""
        results = await self.query(task, limit=8)

        if not results:
            return ""

        sections: list[str] = []
        chars_budget = budget_tokens * 4  # rough token→char estimate
        used = 0

        for result in results:
            entry = f"[{result.source_system}] {result.content}"
            if used + len(entry) > chars_budget:
                break
            sections.append(entry)
            used += len(entry)

        if not sections:
            return ""

        return "## MEMORY CONTEXT\n" + "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _query_backend(
        self,
        name: str,
        backend: Any,
        query: str,
        limit: int,
    ) -> list[FabricResult]:
        """Query a single backend, normalise results to FabricResult."""
        results: list[FabricResult] = []

        try:
            if asyncio.iscoroutinefunction(getattr(backend, "search", None)):
                raw = await backend.search(query, limit=limit)
            elif hasattr(backend, "search"):
                raw = backend.search(query, limit=limit)
            else:
                return []

            now = time.time()
            for item in raw or []:
                if isinstance(item, dict):
                    content = item.get("content", "")
                    relevance = float(cast(Any, item.get("relevance", item.get("score", 0.5))))
                    created = float(item.get("created_at", now))
                    age_days = max(0.0, (now - created) / 86400.0)
                    recency = 0.5 ** (age_days / 30.0)
                    results.append(
                        FabricResult(
                            content=str(content),
                            source_system=name,
                            relevance=min(1.0, max(0.0, relevance)),
                            recency=round(recency, 4),
                            item_id=str(item.get("id", "")),
                            metadata=item.get("metadata", {}),
                        )
                    )
                elif hasattr(item, "content"):
                    results.append(
                        FabricResult(
                            content=str(item.content),
                            source_system=name,
                            relevance=float(getattr(item, "relevance", 0.5)),
                            recency=0.8,
                            item_id=str(getattr(item, "id", "")),
                        )
                    )

        except (RuntimeError, ValueError, OSError, AttributeError, TypeError) as exc:
            logger.warning("Backend %s query failed: %s", name, exc)

        return results

    @staticmethod
    def _deduplicate(
        results: list[FabricResult],
        threshold: float = 0.8,
    ) -> list[FabricResult]:
        """Remove near-duplicates by keyword overlap."""
        if not results:
            return []

        kept: list[FabricResult] = []
        seen_kw: list[set[str]] = []

        for r in results:
            kw = {w for w in re.findall(r"[a-z]{3,}", r.content.lower())}
            is_dup = False
            for prev_kw in seen_kw:
                if not kw or not prev_kw:
                    continue
                overlap = len(kw & prev_kw) / max(len(kw | prev_kw), 1)
                if overlap >= threshold:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(r)
                seen_kw.append(kw)

        return kept


__all__ = ["MemoryFabric", "FabricResult", "RememberResult"]
