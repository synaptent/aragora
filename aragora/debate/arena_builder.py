"""
Builder pattern for Arena construction with explicit dependency DAG.

Provides a fluent interface for configuring and constructing Arena instances
with many optional components. This simplifies Arena creation and makes the
configuration more readable.

Initialization DAG
------------------
The Arena initialization follows this dependency graph:

    ┌─────────────────────────────────────────────┐
    │            CORE (Required)                  │
    │  environment, agents, protocol              │
    └─────────────────┬───────────────────────────┘
                      │
    ┌─────────────────┼───────────────────────────┐
    │                 ▼                           │
    │  ┌──────────────────────────────────────┐  │
    │  │          Extensions                   │  │
    │  │  billing, broadcast, training         │  │
    │  └──────────────────────────────────────┘  │
    │                 │                           │
    │  ┌──────────────▼──────────────────────┐   │
    │  │          Trackers                    │   │
    │  │  elo, calibration, position, etc.   │   │
    │  └──────────────────────────────────────┘  │
    │                 │                           │
    │  ┌──────────────▼──────────────────────┐   │
    │  │       User Participation             │   │
    │  │  event_emitter → audience_manager   │   │
    │  └──────────────────────────────────────┘  │
    │                 │                           │
    │  ┌──────────────▼──────────────────────┐   │
    │  │       Roles and Stances             │   │
    │  │  role_rotator, stance assignment    │   │
    │  └──────────────────────────────────────┘  │
    │                 │                           │
    │  ┌──────────────▼──────────────────────┐   │
    │  │       Convergence Detection          │   │
    │  │  semantic similarity backend         │   │
    │  └──────────────────────────────────────┘  │
    │                 │                           │
    │  ┌──────────────▼──────────────────────┐   │
    │  │       Phase Initialization           │   │
    │  │  proposal, critique, consensus, etc. │   │
    │  └──────────────────────────────────────┘  │
    │                                            │
    └────────────────────────────────────────────┘

Example:
    arena = (
        ArenaBuilder(environment, agents)
        .with_protocol(protocol)
        .with_memory(critique_store)
        .with_elo_system(elo)
        .with_spectator(spectator_stream)
        .build()
    )
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from aragora.core import Agent, Environment
from aragora.debate.protocol import CircuitBreaker, DebateProtocol
from aragora.spectate.stream import SpectatorStream


class InitPhase(Enum):
    """Initialization phases in dependency order.

    Used for tracking which phases have been configured and
    validating prerequisites before building.
    """

    CORE = auto()
    EXTENSIONS = auto()
    TRACKERS = auto()
    USER_PARTICIPATION = auto()
    ROLES = auto()
    CONVERGENCE = auto()
    PHASES = auto()

    @classmethod
    def dependencies(cls) -> dict[InitPhase, list[InitPhase]]:
        """Return the dependency graph for each phase."""
        return {
            cls.CORE: [],
            cls.EXTENSIONS: [cls.CORE],
            cls.TRACKERS: [cls.CORE],
            cls.USER_PARTICIPATION: [cls.CORE],
            cls.ROLES: [cls.CORE, cls.TRACKERS],
            cls.CONVERGENCE: [cls.CORE],
            cls.PHASES: [cls.CORE, cls.TRACKERS, cls.ROLES, cls.CONVERGENCE],
        }


if TYPE_CHECKING:
    from aragora.agents.calibration import CalibrationTracker
    from aragora.agents.grounded import MomentDetector
    from aragora.agents.personas import PersonaManager
    from aragora.agents.positions import PositionLedger
    from aragora.agents.truth_grounding import PositionTracker
    from aragora.connectors.evidence import EvidenceCollector
    from aragora.debate.orchestrator import Arena
    from aragora.insights.store import InsightStore
    from aragora.memory.continuum import ContinuumMemory
    from aragora.debate.embeddings import DebateEmbeddingsDatabase
    from aragora.memory.store import CritiqueStore
    from aragora.pulse.ingestor import TrendingTopic
    from aragora.ranking.dissent import DissentRetriever
    from aragora.ranking.elo import EloSystem
    from aragora.ranking.relationship import RelationshipTracker
    from aragora.reasoning.flip import FlipDetector
    from aragora.replay.recorder import ReplayRecorder
    from aragora.templates import DebateTemplate

logger = logging.getLogger(__name__)


class ArenaBuilder:
    """Fluent builder for Arena construction.

    Simplifies the creation of Arena instances by providing a clear,
    chainable interface for setting optional components.

    Required parameters are provided in the constructor.
    Optional parameters are set via fluent methods.

    Usage:
        # Minimal setup
        arena = ArenaBuilder(env, agents).build()

        # Full configuration
        arena = (
            ArenaBuilder(env, agents)
            .with_protocol(DebateProtocol(rounds=5))
            .with_memory(critique_store)
            .with_elo_system(elo)
            .with_spectator(spectator)
            .with_recorder(recorder)
            .build()
        )
    """

    def __init__(
        self,
        environment: Environment,
        agents: list[Agent],
    ):
        """Initialize builder with required parameters.

        Args:
            environment: The debate environment (task, constraints, etc.)
            agents: List of agents participating in the debate
        """
        self._environment = environment
        self._agents = agents

        # Protocol configuration
        self._protocol: DebateProtocol | None = None
        self._template: DebateTemplate | None = None

        # Memory and persistence
        self._memory: CritiqueStore | None = None
        self._debate_embeddings: DebateEmbeddingsDatabase | None = None
        self._insight_store: InsightStore | None = None
        self._continuum_memory: ContinuumMemory | None = None

        # Event handling
        self._event_hooks: dict = {}
        self._event_emitter = None
        self._spectator: SpectatorStream | None = None
        self._recorder: ReplayRecorder | None = None

        # Agent tracking and ranking
        self._agent_weights: dict[str, float] = {}
        self._elo_system: EloSystem | None = None
        self._persona_manager: PersonaManager | None = None
        self._calibration_tracker: CalibrationTracker | None = None
        self._relationship_tracker: RelationshipTracker | None = None

        # Position and truth grounding
        self._position_tracker: PositionTracker | None = None
        self._position_ledger: PositionLedger | None = None
        self._flip_detector: FlipDetector | None = None
        self._moment_detector: MomentDetector | None = None

        # Historical context
        self._dissent_retriever: DissentRetriever | None = None
        self._evidence_collector: EvidenceCollector | None = None
        self._document_store: Any | None = None
        self._document_org_id: str | None = None
        self._receipt_org_id: str | None = None
        self._receipt_created_by: str | None = None
        self._evidence_store: Any | None = None
        self._trending_topic: TrendingTopic | None = None
        self._consensus_memory: Any = None
        self._tier_analytics_tracker: Any = None
        self._knowledge_mound: Any | None = None
        self._enable_knowledge_retrieval: bool | None = None
        self._enable_knowledge_ingestion: bool | None = None
        self._enable_cross_debate_memory: bool | None = None
        self._enable_supermemory: bool | None = None
        self._supermemory_context_container_tag: str | None = None
        self._supermemory_max_context_items: int | None = None
        self._enable_belief_guidance: bool | None = None
        self._enable_cartographer: bool | None = None
        self._enable_introspection: bool | None = None
        self._enable_auto_execution: bool | None = None

        # Loop configuration
        self._loop_id: str = ""
        self._strict_loop_scoping: bool = False
        self._circuit_breaker: CircuitBreaker | None = None
        self._initial_messages: list = []

        # Airlock configuration
        self._use_airlock: bool = False
        self._airlock_config: Any = None

        # Performance monitoring
        self._performance_monitor: Any = None
        self._enable_performance_monitor: bool = True
        self._enable_telemetry: bool = False

        # Evolution
        self._population_manager: Any = None
        self._auto_evolve: bool = False
        self._breeding_threshold: float = 0.8
        self._prompt_evolver: Any = None
        self._enable_prompt_evolution: bool = False

        # Pulse / trending
        self._pulse_manager: Any = None
        self._auto_fetch_trending: bool = False

        # Checkpointing
        self._checkpoint_manager: Any = None
        self._enable_checkpointing: bool = True  # Enabled by default for debate resume support
        self._breakpoint_manager: Any = None

        # Agent selection
        self._agent_selector: Any = None
        self._use_performance_selection: bool = False
        self._enable_position_ledger: bool = False

        # Provider routing hints (from ProviderRouter)
        self._provider_hints: dict[str, float] | None = None

        # Extensions: Billing
        self._org_id: str = ""
        self._user_id: str = ""
        self._usage_tracker: Any = None

        # Extensions: Broadcast
        self._broadcast_pipeline: Any = None
        self._auto_broadcast: bool = False
        self._broadcast_min_confidence: float = 0.8

        # Extensions: Training export
        self._training_exporter: Any = None
        self._auto_export_training: bool = False
        self._training_export_min_confidence: float = 0.75

        # Extensions: RLM training hook (reads from settings)
        self._enable_rlm_training: bool = True  # Default fallback
        try:
            from aragora.config.settings import get_settings

            self._enable_rlm_training = get_settings().integration.rlm_training_enabled
        except (ImportError, AttributeError, KeyError) as e:
            logger.debug("Could not load RLM training setting, using default: %s", e)

        # Multilingual support
        self._multilingual_manager: Any = None
        self._default_language: str = "en"

        # Mode-based phase prompts
        self._mode_sequence: list[str] | None = None

        # New orchestration features (Phase 4 integration)
        self._hook_manager: Any = None  # HookManager for extended lifecycle hooks
        self._delegation_strategy: Any = None  # DelegationStrategy for task routing
        self._cancellation_token: Any = None  # CancellationToken for cooperative abort
        self._enable_stream_chaining: bool = False  # Enable agent-to-agent streaming
        self._byzantine_config: Any = None  # ByzantineConsensusConfig for fault tolerance
        self._session_id: str = ""  # Session ID for session lifecycle tracking

    # =========================================================================
    # Protocol Configuration
    # =========================================================================

    def with_protocol(self, protocol: DebateProtocol) -> ArenaBuilder:
        """Set the debate protocol.

        Args:
            protocol: DebateProtocol instance with rounds, consensus settings, etc.
        """
        self._protocol = protocol
        return self

    def with_rounds(self, rounds: int) -> ArenaBuilder:
        """Set the number of debate rounds (creates protocol if needed).

        Args:
            rounds: Number of critique/revision rounds
        """
        if self._protocol is None:
            self._protocol = DebateProtocol(rounds=rounds)
        else:
            self._protocol.rounds = rounds
        return self

    def with_template(
        self,
        template: DebateTemplate,
        overrides: dict | None = None,
    ) -> ArenaBuilder:
        """Configure arena from a DebateTemplate.

        Converts the template to a DebateProtocol with appropriate settings:
        - Role rotation using template roles
        - Rounds from template phases
        - Consensus threshold from template
        - Topology based on template type

        Args:
            template: DebateTemplate to apply
            overrides: Optional dict of protocol fields to override

        Returns:
            Self for method chaining
        """
        from aragora.templates import template_to_protocol

        self._protocol = template_to_protocol(template, overrides)
        self._template = template
        return self

    # =========================================================================
    # Mode-Based Phase Prompts
    # =========================================================================

    def with_mode_sequence(self, modes: list[str]) -> ArenaBuilder:
        """Set mode sequence for phase-aware agent prompts.

        Maps operational modes to debate phases. The sequence defines which
        mode system prompt is injected for each phase:
        - modes[0] -> propose phase (default: architect)
        - modes[1] -> critique phase (default: reviewer)
        - modes[2] -> revise phase (default: coder)

        Args:
            modes: List of mode names (e.g., ["architect", "reviewer", "coder"])

        Returns:
            Self for method chaining
        """
        self._mode_sequence = modes
        return self

    # =========================================================================
    # Memory and Persistence
    # =========================================================================

    def with_memory(self, memory: CritiqueStore) -> ArenaBuilder:
        """Set the critique store for memory persistence.

        Args:
            memory: CritiqueStore instance for storing debate outcomes
        """
        self._memory = memory
        return self

    def with_debate_embeddings(self, embeddings: DebateEmbeddingsDatabase) -> ArenaBuilder:
        """Set the debate embeddings database for historical context.

        Args:
            embeddings: DebateEmbeddingsDatabase for semantic search
        """
        self._debate_embeddings = embeddings
        return self

    def with_insight_store(self, store: InsightStore) -> ArenaBuilder:
        """Set the insight store for extracting learnings.

        Args:
            store: InsightStore for debate insights
        """
        self._insight_store = store
        return self

    def with_continuum_memory(self, memory: ContinuumMemory) -> ArenaBuilder:
        """Set continuum memory for cross-debate learning.

        Args:
            memory: ContinuumMemory instance
        """
        self._continuum_memory = memory
        return self

    def with_memory_options(
        self,
        *,
        enable_knowledge_retrieval: bool | None = None,
        enable_knowledge_ingestion: bool | None = None,
        enable_cross_debate_memory: bool | None = None,
        enable_supermemory: bool | None = None,
        supermemory_context_container_tag: str | None = None,
        supermemory_max_context_items: int | None = None,
        enable_belief_guidance: bool | None = None,
    ) -> ArenaBuilder:
        """Set optional memory and knowledge flags."""
        if enable_knowledge_retrieval is not None:
            self._enable_knowledge_retrieval = enable_knowledge_retrieval
        if enable_knowledge_ingestion is not None:
            self._enable_knowledge_ingestion = enable_knowledge_ingestion
        if enable_cross_debate_memory is not None:
            self._enable_cross_debate_memory = enable_cross_debate_memory
        if enable_supermemory is not None:
            self._enable_supermemory = enable_supermemory
        if supermemory_context_container_tag is not None:
            self._supermemory_context_container_tag = supermemory_context_container_tag
        if supermemory_max_context_items is not None:
            self._supermemory_max_context_items = supermemory_max_context_items
        if enable_belief_guidance is not None:
            self._enable_belief_guidance = enable_belief_guidance
        return self

    def with_knowledge_mound(self, knowledge_mound: Any) -> ArenaBuilder:
        """Set the Knowledge Mound instance for debate context enrichment.

        When provided, the Arena will use this KM for retrieving relevant
        organizational knowledge during debates and ingesting outcomes afterward.

        Args:
            knowledge_mound: A KnowledgeMound instance (or compatible object)
        """
        self._knowledge_mound = knowledge_mound
        return self

    def with_feature_flags(
        self,
        *,
        enable_cartographer: bool | None = None,
        enable_introspection: bool | None = None,
        enable_auto_execution: bool | None = None,
    ) -> ArenaBuilder:
        """Set optional feature flags for debate behavior."""
        if enable_cartographer is not None:
            self._enable_cartographer = enable_cartographer
        if enable_introspection is not None:
            self._enable_introspection = enable_introspection
        if enable_auto_execution is not None:
            self._enable_auto_execution = enable_auto_execution
        return self

    # =========================================================================
    # Event Handling
    # =========================================================================

    def with_event_hooks(self, hooks: dict) -> ArenaBuilder:
        """Set event hooks for streaming events.

        Args:
            hooks: Dict mapping event names to handler functions
        """
        self._event_hooks = hooks
        return self

    def with_event_emitter(self, emitter) -> ArenaBuilder:
        """Set event emitter for subscribing to user events.

        Args:
            emitter: Event emitter instance
        """
        self._event_emitter = emitter
        return self

    def with_spectator(self, spectator: SpectatorStream) -> ArenaBuilder:
        """Set spectator stream for real-time events.

        Args:
            spectator: SpectatorStream instance
        """
        self._spectator = spectator
        return self

    def with_recorder(self, recorder: ReplayRecorder) -> ArenaBuilder:
        """Set replay recorder for debate recording.

        Args:
            recorder: ReplayRecorder instance
        """
        self._recorder = recorder
        return self

    def with_rlm_training(self, enabled: bool = True) -> ArenaBuilder:
        """Enable or disable RLM training data collection.

        When enabled, debate outcomes are automatically collected as
        training trajectories for the RLM system.

        Args:
            enabled: Whether to enable RLM training (default: True)
        """
        self._enable_rlm_training = enabled
        return self

    # =========================================================================
    # Agent Tracking and Ranking
    # =========================================================================

    def with_agent_weights(self, weights: dict[str, float]) -> ArenaBuilder:
        """Set reliability weights from capability probing.

        Args:
            weights: Dict mapping agent names to reliability weights
        """
        self._agent_weights = weights
        return self

    def with_elo_system(self, elo: EloSystem) -> ArenaBuilder:
        """Set ELO system for relationship tracking.

        Args:
            elo: EloSystem instance
        """
        self._elo_system = elo
        return self

    def with_persona_manager(self, manager: PersonaManager) -> ArenaBuilder:
        """Set persona manager for agent specialization.

        Args:
            manager: PersonaManager instance
        """
        self._persona_manager = manager
        return self

    def with_calibration_tracker(self, tracker: CalibrationTracker) -> ArenaBuilder:
        """Set calibration tracker for prediction accuracy.

        Args:
            tracker: CalibrationTracker instance
        """
        self._calibration_tracker = tracker
        return self

    def with_relationship_tracker(self, tracker: RelationshipTracker) -> ArenaBuilder:
        """Set relationship tracker for agent relationships.

        Args:
            tracker: RelationshipTracker instance
        """
        self._relationship_tracker = tracker
        return self

    # =========================================================================
    # Position and Truth Grounding
    # =========================================================================

    def with_position_tracker(self, tracker: PositionTracker) -> ArenaBuilder:
        """Set position tracker for truth-grounded personas.

        Args:
            tracker: PositionTracker instance
        """
        self._position_tracker = tracker
        return self

    def with_position_ledger(self, ledger: PositionLedger) -> ArenaBuilder:
        """Set position ledger for grounded personas.

        Args:
            ledger: PositionLedger instance
        """
        self._position_ledger = ledger
        return self

    def with_flip_detector(self, detector: FlipDetector) -> ArenaBuilder:
        """Set flip detector for position reversal detection.

        Args:
            detector: FlipDetector instance
        """
        self._flip_detector = detector
        return self

    def with_moment_detector(self, detector: MomentDetector) -> ArenaBuilder:
        """Set moment detector for significant moments.

        Args:
            detector: MomentDetector instance
        """
        self._moment_detector = detector
        return self

    # =========================================================================
    # Historical Context
    # =========================================================================

    def with_dissent_retriever(self, retriever: DissentRetriever) -> ArenaBuilder:
        """Set dissent retriever for historical minority views.

        Args:
            retriever: DissentRetriever instance
        """
        self._dissent_retriever = retriever
        return self

    def with_evidence_collector(self, collector: EvidenceCollector) -> ArenaBuilder:
        """Set evidence collector for auto-collecting evidence.

        Args:
            collector: EvidenceCollector instance
        """
        self._evidence_collector = collector
        return self

    def with_document_store(self, store: Any, org_id: str | None = None) -> ArenaBuilder:
        """Set DocumentStore for uploaded document context.

        Only documents owned by ``org_id`` are used; without it the debate
        gets no document context.
        """
        self._document_store = store
        self._document_org_id = org_id
        return self

    def with_receipt_owner(self, org_id: str | None, created_by: str | None) -> ArenaBuilder:
        """Set the org and creator stamped on the feedback phase's auto-receipt."""
        self._receipt_org_id = org_id
        self._receipt_created_by = created_by
        return self

    def with_evidence_store(self, store: Any) -> ArenaBuilder:
        """Set EvidenceStore for evidence snippet context."""
        self._evidence_store = store
        return self

    def with_trending_topic(self, topic: TrendingTopic) -> ArenaBuilder:
        """Set trending topic to seed debate context.

        Args:
            topic: TrendingTopic instance
        """
        self._trending_topic = topic
        return self

    # =========================================================================
    # Loop Configuration
    # =========================================================================

    def with_loop_id(self, loop_id: str) -> ArenaBuilder:
        """Set loop ID for multi-loop scoping.

        Args:
            loop_id: Unique identifier for this loop
        """
        self._loop_id = loop_id
        return self

    def with_strict_loop_scoping(self, strict: bool = True) -> ArenaBuilder:
        """Enable strict loop scoping (drop events without loop_id).

        Args:
            strict: Whether to enforce strict scoping
        """
        self._strict_loop_scoping = strict
        return self

    def with_circuit_breaker(self, breaker: CircuitBreaker) -> ArenaBuilder:
        """Set circuit breaker for agent failure handling.

        Args:
            breaker: CircuitBreaker instance
        """
        self._circuit_breaker = breaker
        return self

    def with_initial_messages(self, messages: list) -> ArenaBuilder:
        """Set initial conversation history (for fork debates).

        Args:
            messages: List of initial messages
        """
        self._initial_messages = messages
        return self

    # =========================================================================
    # Airlock Resilience
    # =========================================================================

    def with_airlock(
        self,
        enabled: bool = True,
        config: Any = None,
    ) -> ArenaBuilder:
        """Enable airlock resilience layer for agents.

        Airlock wraps agents with timeout protection and fallback handling.

        Args:
            enabled: Whether to enable airlock protection
            config: Optional AirlockConfig for customization
        """
        self._use_airlock = enabled
        if config is not None:
            self._airlock_config = config
        return self

    # =========================================================================
    # Performance Monitoring
    # =========================================================================

    def with_telemetry(
        self,
        performance_monitor: Any = None,
        enable_performance_monitor: bool = False,
        enable_telemetry: bool = False,
    ) -> ArenaBuilder:
        """Configure performance monitoring and telemetry.

        Args:
            performance_monitor: AgentPerformanceMonitor instance
            enable_performance_monitor: Auto-create monitor if True
            enable_telemetry: Enable Prometheus/Blackbox emission
        """
        if performance_monitor is not None:
            self._performance_monitor = performance_monitor
        self._enable_performance_monitor = enable_performance_monitor
        self._enable_telemetry = enable_telemetry
        return self

    # =========================================================================
    # Evolution and Self-Improvement
    # =========================================================================

    def with_evolution(
        self,
        population_manager: Any = None,
        auto_evolve: bool = False,
        breeding_threshold: float = 0.8,
        prompt_evolver: Any = None,
        enable_prompt_evolution: bool = False,
    ) -> ArenaBuilder:
        """Configure evolution and self-improvement.

        Args:
            population_manager: PopulationManager for genome evolution
            auto_evolve: Trigger evolution after high-quality debates
            breeding_threshold: Min confidence to trigger evolution
            prompt_evolver: PromptEvolver for pattern extraction
            enable_prompt_evolution: Auto-create PromptEvolver if True
        """
        if population_manager is not None:
            self._population_manager = population_manager
        self._auto_evolve = auto_evolve
        self._breeding_threshold = breeding_threshold
        if prompt_evolver is not None:
            self._prompt_evolver = prompt_evolver
        self._enable_prompt_evolution = enable_prompt_evolution
        return self

    # =========================================================================
    # Checkpointing and Breakpoints
    # =========================================================================

    def with_checkpointing(
        self,
        checkpoint_manager: Any = None,
        enable_checkpointing: bool = False,
        breakpoint_manager: Any = None,
    ) -> ArenaBuilder:
        """Configure debate checkpointing and breakpoints.

        Args:
            checkpoint_manager: CheckpointManager for pause/resume
            enable_checkpointing: Auto-create CheckpointManager if True
            breakpoint_manager: BreakpointManager for human-in-the-loop
        """
        if checkpoint_manager is not None:
            self._checkpoint_manager = checkpoint_manager
        self._enable_checkpointing = enable_checkpointing
        if breakpoint_manager is not None:
            self._breakpoint_manager = breakpoint_manager
        return self

    # =========================================================================
    # Agent Selection
    # =========================================================================

    def with_agent_selection(
        self,
        agent_selector: Any = None,
        use_performance_selection: bool = False,
    ) -> ArenaBuilder:
        """Configure agent selection strategy.

        Args:
            agent_selector: AgentSelector for performance-based selection
            use_performance_selection: Enable ELO/calibration-based selection
        """
        if agent_selector is not None:
            self._agent_selector = agent_selector
        self._use_performance_selection = use_performance_selection
        return self

    def with_enable_position_ledger(self, enabled: bool = True) -> ArenaBuilder:
        """Enable auto-creation of PositionLedger.

        Args:
            enabled: Auto-create PositionLedger if not provided
        """
        self._enable_position_ledger = enabled
        return self

    def with_provider_hints(self, hints: dict[str, float]) -> ArenaBuilder:
        """Set provider routing hints from ProviderRouter.

        Args:
            hints: Mapping of provider/model name to quality score (0-1).
                Passed through to ArenaConfig and used by TeamSelector
                during agent selection to bias toward higher-quality providers.
        """
        self._provider_hints = hints
        return self

    # =========================================================================
    # Pulse / Trending
    # =========================================================================

    def with_pulse(
        self,
        pulse_manager: Any = None,
        auto_fetch_trending: bool = False,
    ) -> ArenaBuilder:
        """Configure Pulse for trending topics.

        Args:
            pulse_manager: PulseManager for auto-fetching trending topics
            auto_fetch_trending: Auto-fetch if no topic provided
        """
        if pulse_manager is not None:
            self._pulse_manager = pulse_manager
        self._auto_fetch_trending = auto_fetch_trending
        return self

    # =========================================================================
    # Extensions: Billing
    # =========================================================================

    def with_billing(
        self,
        org_id: str = "",
        user_id: str = "",
        usage_tracker: Any = None,
    ) -> ArenaBuilder:
        """Configure billing and usage tracking.

        Args:
            org_id: Organization ID for multi-tenancy
            user_id: User ID for usage attribution
            usage_tracker: UsageTracker for recording token usage
        """
        self._org_id = org_id
        self._user_id = user_id
        if usage_tracker is not None:
            self._usage_tracker = usage_tracker
        return self

    # =========================================================================
    # Extensions: Broadcast
    # =========================================================================

    def with_broadcast(
        self,
        pipeline: Any = None,
        auto_broadcast: bool = False,
        min_confidence: float = 0.8,
    ) -> ArenaBuilder:
        """Configure broadcast auto-trigger.

        Args:
            pipeline: BroadcastPipeline for audio/video generation
            auto_broadcast: Auto-trigger after high-quality debates
            min_confidence: Minimum confidence to trigger broadcast
        """
        if pipeline is not None:
            self._broadcast_pipeline = pipeline
        self._auto_broadcast = auto_broadcast
        self._broadcast_min_confidence = min_confidence
        return self

    # =========================================================================
    # Extensions: Training Export
    # =========================================================================

    def with_training_export(
        self,
        exporter: Any = None,
        auto_export: bool = False,
        min_confidence: float = 0.75,
    ) -> ArenaBuilder:
        """Configure training data export (Tinker integration).

        Args:
            exporter: DebateTrainingExporter for auto-export
            auto_export: Auto-export training data after debates
            min_confidence: Min confidence to export as SFT
        """
        if exporter is not None:
            self._training_exporter = exporter
        self._auto_export_training = auto_export
        self._training_export_min_confidence = min_confidence
        return self

    # =========================================================================
    # Historical Memory
    # =========================================================================

    def with_consensus_memory(self, memory: Any) -> ArenaBuilder:
        """Set consensus memory for historical outcomes.

        Args:
            memory: ConsensusMemory instance
        """
        self._consensus_memory = memory
        return self

    def with_tier_analytics_tracker(self, tracker: Any) -> ArenaBuilder:
        """Set tier analytics tracker for memory ROI.

        Args:
            tracker: TierAnalyticsTracker instance
        """
        self._tier_analytics_tracker = tracker
        return self

    # =========================================================================
    # Multilingual Support
    # =========================================================================

    def with_multilingual(
        self,
        manager: Any = None,
        default_language: str = "en",
        auto_translate: bool = True,
    ) -> ArenaBuilder:
        """Configure multilingual debate support.

        Enables automatic translation between different participant languages,
        language detection, and multilingual conclusion generation.

        Args:
            manager: MultilingualDebateManager instance (created if None)
            default_language: ISO 639-1 language code (default: "en")
            auto_translate: Enable automatic message translation

        Returns:
            Self for method chaining

        Example:
            arena = (
                ArenaBuilder(env, agents)
                .with_multilingual(default_language="es")
                .build()
            )
        """
        if manager is None:
            from aragora.debate.translation import (
                Language,
                MultilingualDebateConfig,
                MultilingualDebateManager,
            )

            lang = Language.from_code(default_language) or Language.ENGLISH
            config = MultilingualDebateConfig(
                default_language=lang,
                auto_translate=auto_translate,
            )
            manager = MultilingualDebateManager(config=config)

        self._multilingual_manager = manager
        self._default_language = default_language
        return self

    # =========================================================================
    # New Orchestration Features (Phase 4 Integration)
    # =========================================================================

    def with_hook_manager(self, hook_manager: Any) -> ArenaBuilder:
        """Set the HookManager for extended lifecycle hooks.

        The HookManager provides PRE_DEBATE, POST_ROUND, ON_FINDING, etc.
        hooks for automation and WebSocket event bridging.

        Args:
            hook_manager: HookManager instance

        Returns:
            Self for method chaining
        """
        self._hook_manager = hook_manager
        return self

    def with_delegation(self, strategy: Any) -> ArenaBuilder:
        """Set the delegation strategy for task routing.

        Delegation strategies (ContentBased, LoadBalanced, Hybrid) route
        tasks to appropriate agents based on keywords, workload, or expertise.

        Args:
            strategy: DelegationStrategy instance

        Returns:
            Self for method chaining
        """
        self._delegation_strategy = strategy
        return self

    def with_cancellation(self, token: Any) -> ArenaBuilder:
        """Set the cancellation token for cooperative abort.

        CancellationToken enables user-initiated cancellation of long-running
        debates without leaving orphan processes.

        Args:
            token: CancellationToken instance

        Returns:
            Self for method chaining
        """
        self._cancellation_token = token
        return self

    def with_stream_chaining(self, enabled: bool = True) -> ArenaBuilder:
        """Enable agent-to-agent stream chaining.

        Stream chaining allows agents to receive streaming output from
        other agents without file I/O intermediary, reducing latency.

        Args:
            enabled: Whether to enable stream chaining

        Returns:
            Self for method chaining
        """
        self._enable_stream_chaining = enabled
        return self

    def with_byzantine_consensus(self, config: Any) -> ArenaBuilder:
        """Set Byzantine consensus configuration.

        Byzantine consensus (PBFT-style) tolerates faulty or adversarial
        agents where n >= 3f + 1. Use for critical decisions.

        Args:
            config: ByzantineConsensusConfig instance

        Returns:
            Self for method chaining
        """
        self._byzantine_config = config
        return self

    def with_session(self, session_id: str) -> ArenaBuilder:
        """Set session ID for session lifecycle tracking.

        Session ID enables pause/resume and session management endpoints.

        Args:
            session_id: Unique session identifier

        Returns:
            Self for method chaining
        """
        self._session_id = session_id
        return self

    # =========================================================================
    # Composite Configuration
    # =========================================================================

    def with_full_tracking(
        self,
        elo_system: EloSystem,
        persona_manager: PersonaManager | None = None,
        calibration_tracker: CalibrationTracker | None = None,
        relationship_tracker: RelationshipTracker | None = None,
    ) -> ArenaBuilder:
        """Configure all tracking components at once.

        Args:
            elo_system: EloSystem instance (required)
            persona_manager: Optional PersonaManager
            calibration_tracker: Optional CalibrationTracker
            relationship_tracker: Optional RelationshipTracker
        """
        self._elo_system = elo_system
        if persona_manager:
            self._persona_manager = persona_manager
        if calibration_tracker:
            self._calibration_tracker = calibration_tracker
        if relationship_tracker:
            self._relationship_tracker = relationship_tracker
        return self

    def with_full_memory(
        self,
        memory: CritiqueStore,
        debate_embeddings: DebateEmbeddingsDatabase | None = None,
        continuum_memory: ContinuumMemory | None = None,
        insight_store: InsightStore | None = None,
    ) -> ArenaBuilder:
        """Configure all memory components at once.

        Args:
            memory: CritiqueStore instance (required)
            debate_embeddings: Optional DebateEmbeddingsDatabase
            continuum_memory: Optional ContinuumMemory
            insight_store: Optional InsightStore
        """
        self._memory = memory
        if debate_embeddings:
            self._debate_embeddings = debate_embeddings
        if continuum_memory:
            self._continuum_memory = continuum_memory
        if insight_store:
            self._insight_store = insight_store
        return self

    # =========================================================================
    # Build
    # =========================================================================

    def build(self) -> Arena:
        """Build and return the configured Arena instance.

        Returns:
            Configured Arena instance
        """
        # Import here to avoid circular dependency
        from aragora.debate.orchestrator import Arena

        # Inject RLM training hook if enabled
        event_hooks = dict(self._event_hooks)  # Copy to avoid mutating original
        if self._enable_rlm_training:
            try:
                from aragora.rlm.debate_integration import create_training_hook

                training_hook = create_training_hook()
                existing_hook = event_hooks.get("on_debate_complete")
                if existing_hook:
                    # Chain hooks together
                    def chained_hook(
                        result, ctx=None, _existing=existing_hook, _training=training_hook
                    ):
                        _existing(result, ctx)
                        _training(result, ctx)

                    event_hooks["on_debate_complete"] = chained_hook
                else:
                    event_hooks["on_debate_complete"] = training_hook
                logger.debug("RLM training hook enabled via ArenaBuilder")
            except ImportError:
                logger.debug("RLM training hook unavailable - debate_integration not found")

        from aragora.debate.protocol import resolve_default_protocol

        arena_kwargs: dict[str, Any] = {
            "environment": self._environment,
            "agents": self._agents,
            "protocol": resolve_default_protocol(self._protocol),
            "memory": self._memory,
            "event_hooks": event_hooks,
            "hook_manager": self._hook_manager,
            "event_emitter": self._event_emitter,
            "spectator": self._spectator,
            "debate_embeddings": self._debate_embeddings,
            "insight_store": self._insight_store,
            "recorder": self._recorder,
            "agent_weights": self._agent_weights,
            "position_tracker": self._position_tracker,
            "position_ledger": self._position_ledger,
            "enable_position_ledger": self._enable_position_ledger,
            "elo_system": self._elo_system,
            "persona_manager": self._persona_manager,
            "dissent_retriever": self._dissent_retriever,
            "consensus_memory": self._consensus_memory,
            "flip_detector": self._flip_detector,
            "calibration_tracker": self._calibration_tracker,
            "continuum_memory": self._continuum_memory,
            "relationship_tracker": self._relationship_tracker,
            "moment_detector": self._moment_detector,
            "tier_analytics_tracker": self._tier_analytics_tracker,
            "document_store": self._document_store,
            "document_org_id": self._document_org_id,
            "receipt_org_id": self._receipt_org_id,
            "receipt_created_by": self._receipt_created_by,
            "evidence_store": self._evidence_store,
            "loop_id": self._loop_id,
            "strict_loop_scoping": self._strict_loop_scoping,
            "circuit_breaker": self._circuit_breaker,
            "initial_messages": self._initial_messages,
            "trending_topic": self._trending_topic,
            "pulse_manager": self._pulse_manager,
            "auto_fetch_trending": self._auto_fetch_trending,
            "population_manager": self._population_manager,
            "auto_evolve": self._auto_evolve,
            "breeding_threshold": self._breeding_threshold,
            "evidence_collector": self._evidence_collector,
            "breakpoint_manager": self._breakpoint_manager,
            "checkpoint_manager": self._checkpoint_manager,
            "enable_checkpointing": self._enable_checkpointing,
            "performance_monitor": self._performance_monitor,
            "enable_performance_monitor": self._enable_performance_monitor,
            "enable_telemetry": self._enable_telemetry,
            "use_airlock": self._use_airlock,
            "airlock_config": self._airlock_config,
            "agent_selector": self._agent_selector,
            "use_performance_selection": self._use_performance_selection,
            "prompt_evolver": self._prompt_evolver,
            "enable_prompt_evolution": self._enable_prompt_evolution,
            "org_id": self._org_id,
            "user_id": self._user_id,
            "usage_tracker": self._usage_tracker,
            "broadcast_pipeline": self._broadcast_pipeline,
            "auto_broadcast": self._auto_broadcast,
            "broadcast_min_confidence": self._broadcast_min_confidence,
            "training_exporter": self._training_exporter,
            "auto_export_training": self._auto_export_training,
            "training_export_min_confidence": self._training_export_min_confidence,
            "mode_sequence": self._mode_sequence,
        }

        if self._knowledge_mound is not None:
            arena_kwargs["knowledge_mound"] = self._knowledge_mound
        if self._enable_knowledge_retrieval is not None:
            arena_kwargs["enable_knowledge_retrieval"] = self._enable_knowledge_retrieval
        if self._enable_knowledge_ingestion is not None:
            arena_kwargs["enable_knowledge_ingestion"] = self._enable_knowledge_ingestion
        if self._enable_cross_debate_memory is not None:
            arena_kwargs["enable_cross_debate_memory"] = self._enable_cross_debate_memory
        if self._enable_supermemory is not None:
            arena_kwargs["enable_supermemory"] = self._enable_supermemory
        if self._supermemory_context_container_tag is not None:
            arena_kwargs["supermemory_context_container_tag"] = (
                self._supermemory_context_container_tag
            )
        if self._supermemory_max_context_items is not None:
            arena_kwargs["supermemory_max_context_items"] = self._supermemory_max_context_items
        if self._enable_belief_guidance is not None:
            arena_kwargs["enable_belief_guidance"] = self._enable_belief_guidance
        if self._enable_cartographer is not None:
            arena_kwargs["enable_cartographer"] = self._enable_cartographer
        if self._enable_introspection is not None:
            arena_kwargs["enable_introspection"] = self._enable_introspection
        if self._enable_auto_execution is not None:
            arena_kwargs["enable_auto_execution"] = self._enable_auto_execution

        arena = Arena(**arena_kwargs)

        # Set provider routing hints on the arena (used by team selection)
        if self._provider_hints is not None:
            arena._provider_hints = self._provider_hints  # type: ignore[attr-defined]

        return arena


# Convenience function for minimal Arena creation
def create_arena(
    environment: Environment,
    agents: list[Agent],
    protocol: DebateProtocol | None = None,
    memory: CritiqueStore | None = None,
    elo_system: EloSystem | None = None,
) -> Arena:
    """Create an Arena with commonly used options.

    For more complex configurations, use ArenaBuilder directly.

    Args:
        environment: The debate environment
        agents: List of participating agents
        protocol: Optional debate protocol
        memory: Optional critique store
        elo_system: Optional ELO system

    Returns:
        Configured Arena instance
    """
    builder = ArenaBuilder(environment, agents)

    if protocol:
        builder.with_protocol(protocol)
    if memory:
        builder.with_memory(memory)
    if elo_system:
        builder.with_elo_system(elo_system)

    return builder.build()
