"""
ClaudeMemAdapter - Bridges claude-mem MCP memory to the Knowledge Mound.

This adapter enables integration between claude-mem's observation store
and the Knowledge Mound:

- Forward flow: Pull observations from claude-mem into KM
- Reverse flow: Context injection from claude-mem into debates
- Search: Query observations by topic/project

claude-mem is a local MCP service that stores observations from
Claude Code sessions. This adapter is read-mostly - it pulls
observations into KM but does NOT write back to claude-mem.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aragora.knowledge.mound.adapters._base import (
    ADAPTER_CIRCUIT_CONFIGS,
    AdapterCircuitBreakerConfig,
    KnowledgeMoundAdapter,
)
from aragora.knowledge.mound.adapters._semantic_mixin import SemanticSearchMixin
from aragora.knowledge.mound.adapters._types import SyncResult
from aragora.runtime.connector_factory import ConnectorFactoryNotRegisteredError, create_connector

if TYPE_CHECKING:
    from aragora.connectors.memory.claude_mem import ClaudeMemConnector

logger = logging.getLogger(__name__)

# Add circuit breaker config for claude_mem (local service, moderate thresholds)
ADAPTER_CIRCUIT_CONFIGS["claude_mem"] = AdapterCircuitBreakerConfig(
    failure_threshold=5,
    timeout_seconds=30.0,
)


@dataclass
class ClaudeMemContextResult:
    """Result of context injection from claude-mem."""

    observations_injected: int = 0
    context_content: list[str] = field(default_factory=list)
    total_tokens_estimate: int = 0
    search_time_ms: int = 0
    source: str = "claude_mem"


class ClaudeMemAdapter(SemanticSearchMixin, KnowledgeMoundAdapter):
    """
    Adapter that bridges claude-mem observations to the Knowledge Mound.

    Read-mostly adapter: pulls observations from claude-mem into KM
    for unified search and context injection. Does not write back
    to claude-mem (that's handled by the MCP service).

    Usage:
        from aragora.connectors.memory.claude_mem import ClaudeMemConnector, ClaudeMemConfig
        from aragora.knowledge.mound.adapters.claude_mem_adapter import ClaudeMemAdapter

        connector = ClaudeMemConnector(ClaudeMemConfig.from_env())
        adapter = ClaudeMemAdapter(connector=connector)

        # Search observations
        results = await adapter.search_observations("deployment checklist")

        # Inject context for debate
        ctx = await adapter.inject_context("rate limiting best practices")
    """

    adapter_name = "claude_mem"

    def __init__(
        self,
        connector: ClaudeMemConnector | None = None,
        project: str | None = None,
        enable_dual_write: bool = False,
        event_callback: Any | None = None,
        enable_resilience: bool = True,
    ):
        super().__init__(
            enable_dual_write=enable_dual_write,
            event_callback=event_callback,
            enable_resilience=enable_resilience,
        )
        self._connector = connector
        self._project = project
        self._synced_ids: set[str] = set()  # Track already-synced observation IDs

    def _get_connector(self) -> ClaudeMemConnector | None:
        """Lazy-init connector if not provided."""
        if self._connector is None:
            try:
                self._connector = create_connector("claude_mem")
                if self._project is None:
                    self._project = self._connector.config.project
            except (ImportError, OSError, ValueError, ConnectorFactoryNotRegisteredError) as e:
                logger.debug("claude-mem connector unavailable: %s", e)
                return None
        return self._connector

    async def search_observations(
        self,
        query: str,
        limit: int = 10,
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search claude-mem observations.

        Args:
            query: Search query string
            limit: Max results
            project: Optional project filter

        Returns:
            List of evidence dicts with id, content, metadata
        """
        connector = self._get_connector()
        if not connector:
            return []

        start = time.time()
        try:
            results = await connector.search(
                query=query,
                limit=limit,
                project=project or self._project,
            )
            latency = time.time() - start
            self._record_metric("search", True, latency)

            return [
                {
                    "id": ev.id,
                    "content": ev.content,
                    "title": ev.title,
                    "source": "claude_mem",
                    "created_at": ev.created_at,
                    "metadata": ev.metadata,
                }
                for ev in results
            ]
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            latency = time.time() - start
            self._record_metric("search", False, latency)
            logger.warning("claude-mem search failed: %s", e)
            return []

    async def inject_context(
        self,
        topic: str | None = None,
        limit: int = 10,
        project: str | None = None,
    ) -> ClaudeMemContextResult:
        """Inject context from claude-mem for debate initialization.

        Args:
            topic: Topic to search for relevant observations
            limit: Maximum observations to inject
            project: Optional project filter

        Returns:
            ClaudeMemContextResult with injected content
        """
        if not topic:
            return ClaudeMemContextResult()

        start_ms = int(time.time() * 1000)
        observations = await self.search_observations(
            query=topic,
            limit=limit,
            project=project,
        )

        context_content = []
        total_tokens = 0

        for obs in observations:
            content = obs.get("content", "")
            if content:
                context_content.append(content)
                total_tokens += len(content) // 4  # Rough token estimate

        search_time_ms = int(time.time() * 1000) - start_ms

        result = ClaudeMemContextResult(
            observations_injected=len(context_content),
            context_content=context_content,
            total_tokens_estimate=total_tokens,
            search_time_ms=search_time_ms,
        )

        self._emit_event(
            "claude_mem_context_injected",
            {
                "topic": topic,
                "observations_injected": result.observations_injected,
                "tokens_estimate": result.total_tokens_estimate,
            },
        )

        return result

    def evidence_to_knowledge_item(self, evidence: dict[str, Any]) -> dict[str, Any]:
        """Convert a claude-mem evidence dict to a KnowledgeItem-compatible dict.

        Args:
            evidence: Evidence dict from search_observations

        Returns:
            Dict compatible with KnowledgeMound ingestion
        """
        content = evidence.get("content", "")
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        return {
            "id": f"cm_{evidence.get('id', 'unknown')}",
            "content": content,
            "content_hash": content_hash,
            "source_type": "claude_mem",
            "source_id": evidence.get("id", ""),
            "confidence": 0.6,  # Default moderate confidence for external observations
            "metadata": {
                "source": "claude_mem",
                "title": evidence.get("title", ""),
                "project": evidence.get("metadata", {}).get("project"),
                "files_read": evidence.get("metadata", {}).get("files_read"),
                "files_modified": evidence.get("metadata", {}).get("files_modified"),
                "original_created_at": evidence.get("created_at"),
            },
        }

    async def sync_to_km(
        self,
        mound: Any = None,
        workspace_id: str | None = None,
        query: str = "",
        limit: int = 50,
    ) -> SyncResult:
        """Pull observations from claude-mem into Knowledge Mound.

        Args:
            mound: KnowledgeMound instance (optional, for direct ingestion)
            workspace_id: Target workspace
            query: Search query to filter observations
            limit: Max observations to sync

        Returns:
            SyncResult with counts
        """
        start = time.time()
        observations = await self.search_observations(query=query, limit=limit)

        synced = 0
        skipped = 0
        errors: list[str] = []

        for obs in observations:
            obs_id = obs.get("id", "")
            if obs_id in self._synced_ids:
                skipped += 1
                continue

            try:
                km_item = self.evidence_to_knowledge_item(obs)

                if mound and hasattr(mound, "store_knowledge"):
                    await mound.store_knowledge(
                        content=km_item["content"],
                        source=km_item["source_type"],
                        source_id=km_item["source_id"],
                        confidence=km_item["confidence"],
                        metadata=km_item["metadata"],
                    )

                self._synced_ids.add(obs_id)
                synced += 1
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                errors.append(f"{obs_id}: {e}")

        latency = time.time() - start
        self._record_metric("sync", len(errors) == 0, latency)

        self._emit_event(
            "claude_mem_sync_complete",
            {
                "synced": synced,
                "skipped": skipped,
                "errors": len(errors),
            },
        )

        return SyncResult(
            records_synced=synced,
            records_skipped=skipped,
            records_failed=len(errors),
            errors=errors,
            duration_ms=int(latency * 1000),
        )

    def health_check(self) -> dict[str, Any]:
        """Check adapter health including claude-mem connectivity."""
        base = super().health_check()
        base["connector_available"] = self._get_connector() is not None
        base["synced_observation_count"] = len(self._synced_ids)
        base["project"] = self._project
        return base


__all__ = ["ClaudeMemAdapter", "ClaudeMemContextResult"]
