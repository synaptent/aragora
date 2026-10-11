"""
Knowledge management for debates.

Extracted from Arena to improve code organization and testability.
Handles Knowledge Mound operations including:
- KnowledgeMoundOperations initialization
- KnowledgeBridgeHub access
- RevalidationScheduler management
- Bidirectional coordinator and adapter factory
- Culture hints retrieval and application
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    import asyncio

    from aragora.core import DebateResult, Environment
    from aragora.debate.knowledge_mound_ops import KnowledgeMoundOperations
    from aragora.knowledge.mound import KnowledgeMound

logger = logging.getLogger(__name__)


class ArenaKnowledgeManager:
    """Manages Knowledge Mound operations for Arena debates.

    Consolidates KM initialization, context retrieval, outcome ingestion,
    and culture-based protocol hints into a single manager class.

    Example:
        km_manager = ArenaKnowledgeManager(
            knowledge_mound=mound,
            enable_retrieval=True,
            enable_ingestion=True,
            notify_callback=arena._notify_spectator,
        )
        km_manager.initialize(arena)

        # During debate
        await km_manager.init_context(debate_id, domain, env, agents, protocol)
        context = await km_manager.fetch_context(task)

        # After debate
        await km_manager.ingest_outcome(result, env)
    """

    def __init__(
        self,
        knowledge_mound: KnowledgeMound | None = None,
        enable_retrieval: bool = False,
        enable_ingestion: bool = False,
        # Supermemory integration (external memory)
        enable_supermemory: bool = False,
        supermemory_adapter: Any | None = None,
        supermemory_inject_on_start: bool = True,
        supermemory_max_context_items: int = 10,
        supermemory_context_container_tag: str | None = None,
        supermemory_sync_on_conclusion: bool = True,
        supermemory_min_confidence_for_sync: float = 0.7,
        supermemory_outcome_container_tag: str | None = None,
        supermemory_enable_privacy_filter: bool = True,
        supermemory_enable_resilience: bool = True,
        supermemory_enable_km_adapter: bool = False,
        enable_auto_revalidation: bool = False,
        revalidation_staleness_threshold: float = 0.7,
        revalidation_check_interval_seconds: int = 3600,
        notify_callback: Callable[[str, dict[str, Any]], None] | None = None,
        # Pulse trending topics integration
        pulse_store: Any | None = None,
        enable_pulse_context: bool = False,
    ):
        """Initialize the knowledge manager.

        Args:
            knowledge_mound: KnowledgeMound instance for storage/retrieval
            enable_retrieval: Whether to fetch knowledge context for debates
            enable_ingestion: Whether to store debate outcomes in KM
            enable_auto_revalidation: Whether to auto-revalidate stale knowledge
            revalidation_staleness_threshold: Staleness threshold for revalidation
            revalidation_check_interval_seconds: Interval between revalidation checks
            notify_callback: Callback for KM event notifications
        """
        self.knowledge_mound = knowledge_mound
        self.enable_retrieval = enable_retrieval
        self.enable_ingestion = enable_ingestion
        # Supermemory config
        self.enable_supermemory = enable_supermemory
        self.supermemory_adapter = supermemory_adapter
        self.supermemory_inject_on_start = supermemory_inject_on_start
        self.supermemory_max_context_items = supermemory_max_context_items
        self.supermemory_context_container_tag = supermemory_context_container_tag
        self.supermemory_sync_on_conclusion = supermemory_sync_on_conclusion
        self.supermemory_min_confidence_for_sync = supermemory_min_confidence_for_sync
        self.supermemory_outcome_container_tag = supermemory_outcome_container_tag
        self.supermemory_enable_privacy_filter = supermemory_enable_privacy_filter
        self.supermemory_enable_resilience = supermemory_enable_resilience
        self.supermemory_enable_km_adapter = supermemory_enable_km_adapter
        self.enable_auto_revalidation = enable_auto_revalidation
        self.revalidation_staleness_threshold = revalidation_staleness_threshold
        self.revalidation_check_interval_seconds = revalidation_check_interval_seconds
        self._notify_callback = notify_callback

        # Pulse trending topics integration
        self.pulse_store = pulse_store
        self.enable_pulse_context = enable_pulse_context

        # Components initialized during initialize()
        self._knowledge_ops: KnowledgeMoundOperations | None = None
        self._km_metrics: Any | None = None
        self.knowledge_bridge_hub: Any | None = None
        self.revalidation_scheduler: Any | None = None
        self._km_coordinator: Any | None = None
        self._km_adapters: dict[str, Any] = {}
        self._supermemory_synced_debate_ids: set[str] = set()

        # Culture hint storage
        self._culture_consensus_hint: str | None = None
        self._culture_extra_critiques: int = 0
        self._culture_early_consensus: float | None = None
        self._culture_domain_patterns: dict[str, Any] = {}

    def initialize(
        self,
        continuum_memory: Any | None = None,
        consensus_memory: Any | None = None,
        elo_system: Any | None = None,
        cost_tracker: Any | None = None,
        insight_store: Any | None = None,
        flip_detector: Any | None = None,
        evidence_store: Any | None = None,
        pulse_manager: Any | None = None,
        memory: Any | None = None,
    ) -> None:
        """Initialize KM infrastructure components.

        Creates:
        - KnowledgeMoundOperations for query/store
        - KMMetrics for observability
        - KnowledgeBridgeHub for unified bridge access
        - RevalidationScheduler if auto-revalidation enabled
        - BidirectionalCoordinator and adapters for subsystem sync

        Args:
            continuum_memory: ContinuumMemory instance
            consensus_memory: ConsensusMemory instance
            elo_system: EloSystem for agent rankings
            cost_tracker: CostTracker for budget tracking
            insight_store: InsightStore for pattern insights
            flip_detector: FlipDetector for position tracking
            evidence_store: EvidenceStore for evidence storage
            pulse_manager: PulseManager for trending topics
            memory: Legacy memory instance
        """
        from aragora.debate.knowledge_mound_ops import KnowledgeMoundOperations

        # Initialize KM metrics for observability
        self._km_metrics = None
        if self.knowledge_mound:
            try:
                from aragora.knowledge.mound.metrics import KMMetrics

                self._km_metrics = KMMetrics()
                logger.debug("[knowledge_mound] KMMetrics initialized for observability")
            except ImportError:
                logger.debug("[knowledge_mound] KMMetrics not available")

        # Create KnowledgeMoundOperations
        self._knowledge_ops = KnowledgeMoundOperations(
            knowledge_mound=self.knowledge_mound,
            enable_retrieval=self.enable_retrieval,
            enable_ingestion=self.enable_ingestion,
            notify_callback=self._notify_callback,
            metrics=self._km_metrics,
        )

        # Initialize KnowledgeBridgeHub for unified bridge access
        self.knowledge_bridge_hub = None
        if self.knowledge_mound:
            from aragora.knowledge.bridges import KnowledgeBridgeHub

            self.knowledge_bridge_hub = KnowledgeBridgeHub(self.knowledge_mound)

        # Initialize RevalidationScheduler for automatic knowledge revalidation
        self.revalidation_scheduler = None
        if self.enable_auto_revalidation and self.knowledge_mound:
            try:
                from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

                self.revalidation_scheduler = RevalidationScheduler(
                    knowledge_mound=self.knowledge_mound,
                    staleness_threshold=self.revalidation_staleness_threshold,
                    check_interval_seconds=self.revalidation_check_interval_seconds,
                )
                logger.info(
                    "[knowledge_mound] RevalidationScheduler initialized "
                    "(staleness_threshold=%.2f)",
                    self.revalidation_staleness_threshold,
                )
            except ImportError as e:
                logger.debug("[knowledge_mound] RevalidationScheduler unavailable: %s", e)

        # Initialize KM adapter factory and coordinator for bidirectional sync
        self._km_coordinator = None
        self._km_adapters = {}
        if self.knowledge_mound:
            try:
                from aragora.knowledge.mound.adapters import AdapterFactory
                from aragora.knowledge.mound.bidirectional_coordinator import (
                    BidirectionalCoordinator,
                )

                # Create coordinator
                self._km_coordinator = BidirectionalCoordinator()

                # Create adapters from available subsystems
                factory = AdapterFactory(
                    event_callback=self._notify_callback,
                )

                self._km_adapters = factory.create_from_subsystems(
                    continuum_memory=continuum_memory,
                    consensus_memory=consensus_memory,
                    elo_system=elo_system,
                    cost_tracker=cost_tracker,
                    insight_store=insight_store,
                    flip_detector=flip_detector,
                    evidence_store=evidence_store,
                    pulse_manager=pulse_manager,
                    memory=memory,
                )

                # Register adapters with coordinator
                if self._km_adapters:
                    enable_overrides = (
                        {"supermemory"} if self.supermemory_enable_km_adapter else None
                    )
                    registered = factory.register_with_coordinator(
                        self._km_coordinator,
                        self._km_adapters,
                        enable_overrides=enable_overrides,
                    )
                    logger.info(
                        "[knowledge_mound] AdapterFactory created %d adapters, "
                        "registered %d with coordinator",
                        len(self._km_adapters),
                        registered,
                    )
            except ImportError as e:
                logger.debug("[knowledge_mound] AdapterFactory unavailable: %s", e)
            except (RuntimeError, TypeError, ValueError, AttributeError) as e:
                logger.warning("[knowledge_mound] Failed to initialize adapters: %s", e)

        # Initialize Supermemory adapter (external memory persistence)
        self._init_supermemory_adapter()

    def _init_supermemory_adapter(self) -> None:
        """Initialize Supermemory adapter if enabled and available."""
        if not self.enable_supermemory:
            return

        if self.supermemory_adapter is None:
            try:
                from aragora.connectors.supermemory import (
                    SupermemoryConfig,
                )
                from aragora.knowledge.mound.adapters import SupermemoryAdapter

                config = SupermemoryConfig.from_env()
                if config is None:
                    logger.info("[supermemory] SUPERMEMORY_API_KEY not set; disabling integration")
                    self.enable_supermemory = False
                    return

                self.supermemory_adapter = SupermemoryAdapter(
                    config=config,
                    min_importance_threshold=self.supermemory_min_confidence_for_sync,
                    max_context_items=self.supermemory_max_context_items,
                    enable_privacy_filter=self.supermemory_enable_privacy_filter,
                    enable_resilience=self.supermemory_enable_resilience,
                    event_callback=self._notify_callback,
                )
                logger.info("[supermemory] Adapter initialized")
            except ImportError as e:
                logger.debug("[supermemory] Integration unavailable: %s", e)
                self.enable_supermemory = False
            except (RuntimeError, TypeError, ValueError, OSError, ConnectionError) as e:
                logger.warning("[supermemory] Failed to initialize adapter: %s", e)
                self.enable_supermemory = False
        else:
            # If adapter is provided externally, wire event callback if supported.
            if self._notify_callback and hasattr(self.supermemory_adapter, "set_event_callback"):
                try:
                    self.supermemory_adapter.set_event_callback(self._notify_callback)
                except (AttributeError, TypeError, RuntimeError) as e:
                    logger.debug("[supermemory] Failed to set event callback: %s", e)

    async def init_context(
        self,
        debate_id: str,
        domain: str,
        env: Environment,
        agents: list,
        protocol: Any,
    ) -> "asyncio.Task[Any] | None":
        """Initialize Knowledge Mound context for the debate.

        Emits DEBATE_START event to trigger cross-subsystem handlers:
        - mound_to_belief: Initialize belief priors from historical cruxes
        - mound_to_team_selection: Query domain experts for team assembly
        - mound_to_trickster: Load flip history for consistency checking
        - culture_to_debate: Load learned culture patterns

        Args:
            debate_id: Unique debate identifier
            domain: Detected debate domain for targeted retrieval
            env: Environment with task info
            agents: List of agents participating
            protocol: Debate protocol settings

        Returns:
            The in-flight KM culture-profile retrieval task scheduled by the
            ``culture_to_debate`` reaction, if one was scheduled. Callers
            should await it (with a bound) before calling ``get_culture_hints``
            - the retrieval runs as a fire-and-forget task, so reading hints
            immediately after this returns can otherwise race it. ``None``
            if no retrieval was scheduled (offline mode, no Knowledge Mound,
            or dispatch failed).
        """
        from aragora.utils.env import is_offline_mode

        if is_offline_mode():
            return None

        try:
            from aragora.debate.event_subscribers import (
                bootstrap_debate_event_subscribers,
            )
            from aragora.events.types import StreamEvent, StreamEventType
            from aragora.knowledge.event_subscribers import get_knowledge_event_subscriber

            manager = bootstrap_debate_event_subscribers()

            # Emit DEBATE_START to trigger KM→subsystem flows
            event = StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={
                    "debate_id": debate_id,
                    "domain": domain,
                    "question": env.task,
                    "agent_count": len(agents),
                    "protocol": {
                        "rounds": protocol.rounds,
                        "consensus": protocol.consensus,
                    },
                },
            )
            manager.dispatch(event)
            logger.debug("[arena] KM context initialized for debate %s", debate_id)
            return get_knowledge_event_subscriber().get_pending_culture_task(debate_id)

        except ImportError:
            logger.debug("[arena] KM context initialization skipped (events not available)")
            return None
        except (RuntimeError, TypeError, ValueError, AttributeError) as e:
            logger.warning("[arena] Failed to initialize KM context: %s", e)
            return None

    def get_culture_hints(self, debate_id: str) -> dict[str, Any]:
        """Retrieve culture hints from the knowledge event subscriber.

        Args:
            debate_id: Debate identifier

        Returns:
            Dict of protocol hints derived from organizational culture
        """
        from aragora.utils.env import is_offline_mode

        if is_offline_mode():
            return {}

        try:
            from aragora.debate.event_subscribers import (
                bootstrap_debate_event_subscribers,
            )
            from aragora.knowledge.event_subscribers import get_knowledge_event_subscriber

            bootstrap_debate_event_subscribers()
            hints = get_knowledge_event_subscriber().get_debate_culture_hints(debate_id)
            if hints:
                logger.debug(
                    "[arena] Retrieved %s culture hints for debate %s", len(hints), debate_id
                )
            return hints

        except ImportError:
            return {}
        except (RuntimeError, TypeError, ValueError, AttributeError) as e:
            logger.debug("[arena] Failed to get culture hints: %s", e)
            return {}

    def apply_culture_hints(self, hints: dict[str, Any]) -> None:
        """Apply culture-derived hints to protocol and debate configuration.

        Args:
            hints: Protocol hints from organizational culture patterns
        """
        if not hints:
            return

        try:
            # Apply recommended consensus method if available
            if "recommended_consensus" in hints:
                recommended = hints["recommended_consensus"]
                if recommended in ("unanimous", "majority", "consensus"):
                    logger.info("[arena] Culture recommends %s consensus", recommended)
                    self._culture_consensus_hint = recommended

            # Apply extra critique rounds for conservative cultures
            if hints.get("extra_critique_rounds", 0) > 0:
                extra = hints["extra_critique_rounds"]
                logger.info("[arena] Culture suggests %s extra critique rounds", extra)
                self._culture_extra_critiques = extra

            # Apply early consensus threshold for aggressive cultures
            if "early_consensus_threshold" in hints:
                threshold = hints["early_consensus_threshold"]
                logger.info("[arena] Culture suggests early consensus at %.0f%%", threshold * 100)
                self._culture_early_consensus = threshold

            # Store domain-specific patterns
            if "domain_patterns" in hints:
                patterns = hints["domain_patterns"]
                logger.debug("[arena] Loaded %s domain-specific culture patterns", len(patterns))
                self._culture_domain_patterns = patterns

        except (KeyError, TypeError, AttributeError) as e:
            logger.debug("[arena] Failed to apply culture hints (data error): %s", e)
        except (RuntimeError, ValueError) as e:
            logger.warning("[arena] Unexpected error applying culture hints: %s", e)

    async def fetch_context(
        self,
        task: str,
        limit: int = 10,
        auth_context: Any | None = None,
    ) -> str | None:
        """Fetch relevant knowledge from Knowledge Mound for debate context.

        Args:
            task: The debate task/question
            limit: Maximum number of knowledge items to retrieve

        Returns:
            Formatted knowledge context string or None
        """
        if self._knowledge_ops is None:
            return None
        if auth_context is None:
            return await self._knowledge_ops.fetch_knowledge_context(task, limit)
        return await self._knowledge_ops.fetch_knowledge_context(
            task, limit, auth_context=auth_context
        )

    def fetch_pulse_topics(self, task: str, limit: int = 5) -> list[dict[str, Any]]:
        """Fetch relevant trending topics from the Pulse store.

        Queries the Pulse store for recent topics that may be relevant
        to the current debate task.

        Args:
            task: The debate task/question
            limit: Maximum number of topics to return

        Returns:
            List of dicts with topic, platform, volume, category, hours_ago
        """
        if not self.enable_pulse_context or not self.pulse_store:
            return []

        try:
            recent = self.pulse_store.get_recent_topics(hours=24)
            if not recent:
                return []

            # Extract keywords from task for relevance matching
            task_words = {w.lower() for w in task.split() if len(w) >= 3}

            scored: list[tuple[Any, int]] = []
            for record in recent:
                topic_text = getattr(record, "topic_text", "")
                topic_words = {w.lower() for w in topic_text.split() if len(w) >= 3}
                overlap = len(task_words & topic_words)
                scored.append((record, overlap))

            # Sort by relevance (overlap), then volume
            scored.sort(key=lambda x: (x[1], getattr(x[0], "volume", 0)), reverse=True)

            results = []
            for record, _score in scored[:limit]:
                results.append(
                    {
                        "topic": getattr(record, "topic_text", ""),
                        "platform": getattr(record, "platform", "unknown"),
                        "volume": getattr(record, "volume", 0),
                        "category": getattr(record, "category", ""),
                        "hours_ago": getattr(record, "hours_ago", 0.0),
                    }
                )

            return results
        except (AttributeError, TypeError) as e:
            logger.debug("Pulse context fetch error: %s", e)
            return []

    async def ingest_outcome(self, result: DebateResult, env: Environment) -> None:
        """Store debate outcome in Knowledge Mound for future retrieval.

        Args:
            result: The debate result to store
            env: Environment with task context
        """
        if self._knowledge_ops is not None:
            await self._knowledge_ops.ingest_debate_outcome(result, env=env)

        # Optional: sync outcome to Supermemory (external persistence)
        if not self.enable_supermemory or not self.supermemory_adapter:
            return
        if not self.supermemory_sync_on_conclusion:
            return

        debate_id = getattr(result, "debate_id", None)
        if debate_id and debate_id in self._supermemory_synced_debate_ids:
            return

        try:
            sync_result = await self.supermemory_adapter.sync_debate_outcome(
                result,
                container_tag=self.supermemory_outcome_container_tag,
            )
            if sync_result.success:
                if debate_id:
                    self._supermemory_synced_debate_ids.add(debate_id)
            else:
                logger.debug(
                    "[supermemory] Outcome sync failed: %s",
                    sync_result.error,
                )
        except (RuntimeError, ConnectionError, OSError, TypeError, AttributeError) as e:
            logger.debug("[supermemory] Outcome sync error: %s", e)

    @property
    def culture_consensus_hint(self) -> str | None:
        """Get culture-recommended consensus method."""
        return self._culture_consensus_hint

    @property
    def culture_extra_critiques(self) -> int:
        """Get culture-recommended extra critique rounds."""
        return self._culture_extra_critiques

    @property
    def culture_early_consensus(self) -> float | None:
        """Get culture-recommended early consensus threshold."""
        return self._culture_early_consensus

    @property
    def culture_domain_patterns(self) -> dict[str, Any]:
        """Get culture domain patterns."""
        return self._culture_domain_patterns
