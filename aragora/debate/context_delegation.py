"""
Context delegation methods for Arena.

Extracted from Arena to reduce orchestrator size. Contains methods
for gathering, caching, and managing debate context including:
- Historical context from past debates
- Continuum memory context
- Evidence research context
- Trending/pulse context
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.debate.context_gatherer import ContextGatherer
    from aragora.debate.memory_manager import MemoryManager
    from aragora.debate.state_cache import DebateStateCache
    from aragora.reasoning.evidence_grounding import EvidenceGrounder

logger = logging.getLogger(__name__)


class ContextDelegator:
    """Handles context gathering and caching delegations for Arena.

    Centralizes context-related operations that were spread across Arena:
    - Historical debate context
    - Continuum memory context
    - Evidence/research context
    - Trending topics context

    Usage:
        delegator = ContextDelegator(
            context_gatherer=gatherer,
            memory_manager=manager,
            cache=cache,
            evidence_grounder=grounder,
        )
        context = delegator.get_continuum_context(domain, task)
    """

    def __init__(
        self,
        context_gatherer: ContextGatherer | None = None,
        memory_manager: MemoryManager | None = None,
        cache: DebateStateCache | None = None,
        evidence_grounder: EvidenceGrounder | None = None,
        continuum_memory: Any = None,
        env: Any = None,
        auth_context: Any | None = None,
        extract_domain_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.context_gatherer = context_gatherer
        self.memory_manager = memory_manager
        self._cache = cache
        self.evidence_grounder = evidence_grounder
        self.continuum_memory = continuum_memory
        self.env = env
        self._auth_context = auth_context
        self._extract_domain = extract_domain_fn or (lambda: "general")

    def _require_gatherer(self) -> ContextGatherer:
        if self.context_gatherer is None:
            raise RuntimeError("ContextDelegator has no context_gatherer configured")
        return self.context_gatherer

    def _resolve_tenant_id(self) -> str | None:
        if not self._auth_context:
            return None
        enforce = os.environ.get("ARAGORA_MEMORY_TENANT_ENFORCE", "1") == "1"
        if not enforce:
            return None
        workspace_id = getattr(self._auth_context, "workspace_id", None)
        org_id = getattr(self._auth_context, "org_id", None)
        return workspace_id or org_id

    def get_continuum_context(self) -> str:
        """Retrieve relevant memories from ContinuumMemory for debate context."""
        if self._cache and self._cache.has_continuum_context():
            return self._cache.continuum_context

        if not self.continuum_memory:
            return ""

        domain = self._extract_domain()
        task = self.env.task if self.env else ""
        tenant_id = self._resolve_tenant_id()
        context_envelope: dict[str, Any] = {}
        try:
            from aragora.memory.access import build_access_envelope

            context_envelope = build_access_envelope(
                self._auth_context,
                source="debate.context.continuum",
            )
        except (ImportError, AttributeError):
            context_envelope = {}
        gatherer = self._require_gatherer()
        context, retrieved_ids, retrieved_tiers = gatherer.get_continuum_context(
            continuum_memory=self.continuum_memory,
            domain=domain,
            task=task,
            tenant_id=tenant_id,
            auth_context=self._auth_context,
        )

        # Track retrieved IDs and tiers for outcome updates
        if self._cache:
            self._cache.track_continuum_retrieval(
                context,
                retrieved_ids,
                retrieved_tiers,
                context_envelope=context_envelope,
            )
        return context

    async def perform_research(self, task: str) -> str:
        """Perform multi-source research for the debate topic."""
        gatherer = self._require_gatherer()
        result = await gatherer.gather_all(task)
        # Update cache and evidence grounder
        if self._cache:
            self._cache.evidence_pack = gatherer.evidence_pack
        if self.evidence_grounder:
            self.evidence_grounder.set_evidence_pack(gatherer.evidence_pack)
        return result

    async def gather_aragora_context(self, task: str) -> str | None:
        """Gather Aragora-specific documentation context if relevant."""
        return await self._require_gatherer().gather_aragora_context(task)

    async def gather_evidence_context(self, task: str) -> str | None:
        """Gather evidence from web, GitHub, and local docs connectors."""
        gatherer = self._require_gatherer()
        result = await gatherer.gather_evidence_context(task)
        # Update cache and evidence grounder
        if self._cache:
            self._cache.evidence_pack = gatherer.evidence_pack
        if self.evidence_grounder:
            self.evidence_grounder.set_evidence_pack(gatherer.evidence_pack)
        return result

    async def gather_trending_context(self) -> str | None:
        """Gather pulse/trending context from social platforms."""
        return await self._require_gatherer().gather_trending_context()

    async def refresh_evidence_for_round(
        self,
        combined_text: str,
        evidence_collector: Any,
        task: str,
        evidence_store_callback: Any,
        prompt_builder: Any = None,
    ) -> int:
        """Refresh evidence based on claims made during a debate round.

        Args:
            combined_text: Combined text from proposals and critiques
            evidence_collector: EvidenceCollector instance
            task: The debate task
            evidence_store_callback: Callback to store evidence in memory
            prompt_builder: Optional PromptBuilder to update

        Returns:
            Number of new evidence snippets added
        """
        count, updated_pack = await self._require_gatherer().refresh_evidence_for_round(
            combined_text=combined_text,
            evidence_collector=evidence_collector,
            task=task,
            evidence_store_callback=evidence_store_callback,
        )

        if updated_pack:
            if self._cache:
                self._cache.evidence_pack = updated_pack
            if self.evidence_grounder:
                self.evidence_grounder.set_evidence_pack(updated_pack)
            if prompt_builder:
                prompt_builder.set_evidence_pack(updated_pack)

        return count

    async def fetch_historical_context(self, task: str, limit: int = 3) -> str:
        """Fetch similar past debates for historical context."""
        if not self.memory_manager:
            return ""
        return await self.memory_manager.fetch_historical_context(task, limit)

    def format_patterns_for_prompt(self, patterns: list[dict]) -> str:
        """Format learned patterns as prompt context for agents."""
        if not self.memory_manager:
            return ""
        return self.memory_manager._format_patterns_for_prompt(patterns)

    def get_successful_patterns(self, limit: int = 5) -> str:
        """Retrieve successful patterns from CritiqueStore memory."""
        if not self.memory_manager:
            return ""
        return self.memory_manager.get_successful_patterns(limit)


__all__ = ["ContextDelegator"]
