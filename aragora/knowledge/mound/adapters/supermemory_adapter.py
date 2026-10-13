"""
SupermemoryAdapter - Bridges Supermemory to the Knowledge Mound.

This adapter enables bidirectional integration between Supermemory's
external persistence service and the Knowledge Mound:

- Forward flow: Debate outcomes synced to Supermemory
- Reverse flow: Context injection from Supermemory into debates
- Search: Semantic query across external memory

The adapter provides:
- Context injection for debate initialization
- Outcome persistence for cross-session learning
- Semantic search across historical memories
- Privacy filtering before external sync
"""

from __future__ import annotations

import importlib.util
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.memory.supermemory import SupermemoryClient, SupermemoryConfig
    from aragora.debate import DebateResult

from aragora.knowledge.mound.adapters._base import (
    KnowledgeMoundAdapter,
    ADAPTER_CIRCUIT_CONFIGS,
    AdapterCircuitBreakerConfig,
)
from aragora.knowledge.mound.adapters._semantic_mixin import SemanticSearchMixin
from aragora.knowledge.mound.adapters._types import SyncResult

logger = logging.getLogger(__name__)

# Add circuit breaker config for supermemory (external service, lenient thresholds)
ADAPTER_CIRCUIT_CONFIGS["supermemory"] = AdapterCircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    timeout_seconds=60.0,  # Cooldown time before half-open
    half_open_max_calls=3,
)


@dataclass
class ContextInjectionResult:
    """Result of context injection from Supermemory."""

    memories_injected: int = 0
    context_content: list[str] = field(default_factory=list)
    total_tokens_estimate: int = 0
    search_time_ms: int = 0
    source: str = "supermemory"


@dataclass
class SyncOutcomeResult:
    """Result of syncing debate outcome to Supermemory."""

    success: bool = False
    memory_id: str | None = None
    error: str | None = None
    synced_at: datetime | None = None


@dataclass
class SupermemorySearchResult:
    """Search result from Supermemory."""

    content: str
    similarity: float
    memory_id: str | None = None
    container_tag: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SupermemoryAdapter(SemanticSearchMixin, KnowledgeMoundAdapter):
    """
    Adapter that bridges Supermemory to the Knowledge Mound.

    Provides methods for:
    - inject_context: Load relevant context from Supermemory on debate start
    - sync_debate_outcome: Persist debate conclusions to Supermemory
    - search_memories: Semantic search across external memory
    - get_cross_session_insights: Retrieve patterns from past sessions

    Usage:
        from aragora.memory.supermemory import SupermemoryConfig, SupermemoryClient
        from aragora.knowledge.mound.adapters import SupermemoryAdapter

        config = SupermemoryConfig.from_env()
        client = SupermemoryClient(config)
        adapter = SupermemoryAdapter(client, config)

        # Inject context on debate start
        context = await adapter.inject_context(debate_topic="rate limiting")

        # Sync outcome after debate
        result = await adapter.sync_debate_outcome(debate_result)
    """

    adapter_name = "supermemory"
    source_type = "supermemory"

    def __init__(
        self,
        client: SupermemoryClient | None = None,
        config: SupermemoryConfig | None = None,
        min_importance_threshold: float = 0.7,
        max_context_items: int = 10,
        enable_privacy_filter: bool = True,
        **kwargs: Any,
    ):
        """Initialize the Supermemory adapter.

        Args:
            client: Supermemory client instance (optional, created from config if not provided)
            config: Supermemory configuration (optional, loaded from env if not provided)
            min_importance_threshold: Minimum importance to sync externally
            max_context_items: Maximum items to inject as context
            enable_privacy_filter: Whether to filter sensitive content
            **kwargs: Additional args passed to KnowledgeMoundAdapter
        """
        super().__init__(**kwargs)
        self._client = client
        self._config = config
        self._min_importance = min_importance_threshold
        self._max_context_items = max_context_items
        self._enable_privacy_filter = enable_privacy_filter
        self._privacy_filter: Any = None

    def _ensure_client(self) -> SupermemoryClient | None:
        """Lazily initialize the client if not provided."""
        if self._client is not None:
            return self._client

        # Avoid initializing a client when the SDK isn't available.
        # This keeps explicit client=None behavior consistent in tests and
        # prevents circuit breaker trips on missing optional deps.
        try:
            if importlib.util.find_spec("supermemory") is None:
                logger.debug("supermemory package not installed; client unavailable")
                return None
        except (ImportError, ValueError, AttributeError):
            logger.debug("Unable to probe supermemory package; client unavailable")
            return None

        try:
            from aragora.memory.supermemory import SupermemoryClient, get_client

            # Try to get from singleton or create new
            if self._config is not None:
                self._client = SupermemoryClient(self._config)
            else:
                self._client = get_client()

            return self._client
        except ImportError:
            logger.warning("supermemory package not available")
            return None
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to initialize Supermemory client: %s", e)
            return None

    def _ensure_privacy_filter(self) -> Any:
        """Lazily initialize the privacy filter."""
        if self._privacy_filter is not None:
            return self._privacy_filter

        if not self._enable_privacy_filter:
            return None

        try:
            from aragora.memory.supermemory import PrivacyFilter

            self._privacy_filter = PrivacyFilter()
            return self._privacy_filter
        except ImportError:
            return None

    def sync_to_km(self) -> SyncResult:
        """No-op forward sync for external memory adapter.

        Supermemory is an external persistence layer, not a KM source. This
        method exists to satisfy the BidirectionalCoordinator interface
        when the adapter is auto-registered via AdapterFactory.
        """
        start_time = time.time()
        result = SyncResult(records_synced=0, records_skipped=0, records_failed=0)
        result.duration_ms = (time.time() - start_time) * 1000
        return result

    async def inject_context(
        self,
        debate_topic: str | None = None,
        debate_id: str | None = None,
        container_tag: str | None = None,
        limit: int | None = None,
    ) -> ContextInjectionResult:
        """Load relevant context from Supermemory for debate initialization.

        Args:
            debate_topic: Topic to search for relevant memories
            debate_id: Optional debate ID for tracking
            container_tag: Optional container filter
            limit: Max items to retrieve

        Returns:
            ContextInjectionResult with injected memories
        """
        client = self._ensure_client()
        if client is None:
            logger.debug("Supermemory client not available for context injection")
            return ContextInjectionResult()

        start_time = time.time()
        limit = limit or self._max_context_items

        try:
            # Search for relevant memories
            query = debate_topic or "*"
            if self._enable_resilience:
                async with self._resilient_call("inject_context"):
                    response = await client.search(
                        query=query,
                        limit=limit,
                        container_tag=container_tag,
                    )
            else:
                response = await client.search(
                    query=query,
                    limit=limit,
                    container_tag=container_tag,
                )

            # Extract content for injection
            context_content = [r.content for r in response.results]

            # Estimate token count (rough: 1 token per 4 chars)
            total_chars = sum(len(c) for c in context_content)
            token_estimate = total_chars // 4

            search_time_ms = int((time.time() - start_time) * 1000)

            self._emit_event(
                "context_injected",
                {
                    "debate_id": debate_id,
                    "topic": debate_topic,
                    "items_injected": len(context_content),
                    "search_time_ms": search_time_ms,
                },
            )

            return ContextInjectionResult(
                memories_injected=len(context_content),
                context_content=context_content,
                total_tokens_estimate=token_estimate,
                search_time_ms=search_time_ms,
            )

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to inject context from Supermemory: %s", e)
            return ContextInjectionResult()

    async def sync_debate_outcome(
        self,
        debate_result: DebateResult,
        container_tag: str | None = None,
    ) -> SyncOutcomeResult:
        """Persist debate outcome to Supermemory.

        Args:
            debate_result: The debate result to sync
            container_tag: Optional container tag override

        Returns:
            SyncOutcomeResult with sync status
        """
        client = self._ensure_client()
        if client is None:
            return SyncOutcomeResult(success=False, error="Client not available")

        # Check importance threshold
        confidence = getattr(debate_result, "confidence", 0.5)
        if confidence < self._min_importance:
            logger.debug(
                "Skipping sync for debate with confidence %s (threshold: %s)",
                confidence,
                self._min_importance,
            )
            return SyncOutcomeResult(
                success=True,
                error=f"Below importance threshold ({confidence} < {self._min_importance})",
            )

        try:
            # Build content from debate result
            content_parts = []
            if hasattr(debate_result, "conclusion") and getattr(debate_result, "conclusion"):
                content_parts.append(f"Conclusion: {debate_result.conclusion}")
            elif hasattr(debate_result, "final_answer") and getattr(debate_result, "final_answer"):
                content_parts.append(f"Final answer: {debate_result.final_answer}")
            if hasattr(debate_result, "consensus_type"):
                content_parts.append(f"Consensus: {debate_result.consensus_type}")
            if hasattr(debate_result, "key_claims") and debate_result.key_claims:
                claims = ", ".join(debate_result.key_claims[:5])
                content_parts.append(f"Key claims: {claims}")

            content = "\n".join(content_parts) if content_parts else str(debate_result)

            # Apply privacy filter
            privacy_filter = self._ensure_privacy_filter()
            if privacy_filter:
                content = privacy_filter.filter(content)

            # Build metadata
            round_count = getattr(debate_result, "round_count", None)
            if round_count is None:
                round_count = getattr(debate_result, "rounds_used", None)
            if round_count is None:
                round_count = getattr(debate_result, "rounds_completed", None)

            metadata = {
                "debate_id": getattr(debate_result, "debate_id", None),
                "confidence": confidence,
                "consensus_type": getattr(debate_result, "consensus_type", None),
                "round_count": round_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "aragora",
            }

            # Get container tag
            tag = container_tag
            if tag is None and self._config:
                tag = self._config.get_container_tag("debate_outcomes")
            tag = tag or "aragora_debates"

            # Sync to Supermemory
            if self._enable_resilience:
                async with self._resilient_call("sync_outcome"):
                    result = await client.add_memory(
                        content=content,
                        container_tag=tag,
                        metadata=metadata,
                    )
            else:
                result = await client.add_memory(
                    content=content,
                    container_tag=tag,
                    metadata=metadata,
                )

            if result.success:
                self._emit_event(
                    "outcome_synced",
                    {
                        "debate_id": metadata.get("debate_id"),
                        "memory_id": result.memory_id,
                        "confidence": confidence,
                    },
                )
                return SyncOutcomeResult(
                    success=True,
                    memory_id=result.memory_id,
                    synced_at=datetime.now(timezone.utc),
                )
            else:
                return SyncOutcomeResult(success=False, error=result.error)

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to sync debate outcome: %s", e)
            return SyncOutcomeResult(success=False, error="Debate outcome sync failed")

    async def search_memories(
        self,
        query: str,
        limit: int = 10,
        container_tag: str | None = None,
        min_similarity: float = 0.5,
    ) -> list[SupermemorySearchResult]:
        """Search Supermemory for relevant memories.

        Args:
            query: Search query
            limit: Maximum results
            container_tag: Optional container filter
            min_similarity: Minimum similarity threshold

        Returns:
            List of SupermemorySearchResult
        """
        client = self._ensure_client()
        if client is None:
            return []

        try:
            if self._enable_resilience:
                async with self._resilient_call("search_memories"):
                    response = await client.search(
                        query=query,
                        limit=limit,
                        container_tag=container_tag,
                    )
            else:
                response = await client.search(
                    query=query,
                    limit=limit,
                    container_tag=container_tag,
                )

            # Filter by similarity and convert to results
            results = []
            for r in response.results:
                if r.similarity >= min_similarity:
                    results.append(
                        SupermemorySearchResult(
                            content=r.content,
                            similarity=r.similarity,
                            memory_id=r.memory_id,
                            container_tag=r.container_tag,
                            metadata=r.metadata,
                        )
                    )

            return results

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Search failed: %s", e)
            return []

    async def get_cross_session_insights(
        self,
        topic: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get insights from past sessions relevant to a topic.

        Args:
            topic: Optional topic to search for
            limit: Maximum insights to return

        Returns:
            List of insight dictionaries
        """
        results = await self.search_memories(
            query=topic or "debate insights patterns",
            limit=limit,
            container_tag=self._config.get_container_tag("patterns") if self._config else None,
        )

        return [
            {
                "content": r.content,
                "similarity": r.similarity,
                "source": "supermemory",
                "metadata": r.metadata,
            }
            for r in results
        ]

    async def health_check(self) -> dict[str, Any]:  # type: ignore[override]
        """Check adapter and Supermemory health.

        Returns:
            Health status dictionary
        """
        client = self._ensure_client()
        if client is None:
            return {
                "healthy": False,
                "error": "Client not available",
                "adapter": self.adapter_name,
            }

        try:
            health = await client.health_check()
            return {
                "healthy": health.get("healthy", False),
                "latency_ms": health.get("latency_ms", 0),
                "adapter": self.adapter_name,
                "external": health,
            }
        except (RuntimeError, ValueError, TypeError, AttributeError):  # noqa: BLE001 - adapter isolation
            return {
                "healthy": False,
                "error": "Health check failed",
                "adapter": self.adapter_name,
            }

    def get_stats(self) -> dict[str, Any]:
        """Get adapter statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "adapter": self.adapter_name,
            "client_initialized": self._client is not None,
            "privacy_filter_enabled": self._enable_privacy_filter,
            "min_importance_threshold": self._min_importance,
            "max_context_items": self._max_context_items,
            "reverse_flow": self.get_reverse_flow_stats(),
        }
