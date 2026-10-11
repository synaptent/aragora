"""Primary and legacy configuration groups for Arena initialization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from aragora.config import DEFAULT_ROUNDS
from aragora.resilience import CircuitBreaker

if TYPE_CHECKING:
    from aragora.protocols.debate import DebateProtocol
from aragora.spectate.stream import SpectatorStream
from aragora.protocols import (
    BroadcastPipelineProtocol,
    CalibrationTrackerProtocol,
    ConsensusMemoryProtocol,
    ContinuumMemoryProtocol,
    DebateEmbeddingsProtocol,
    DissentRetrieverProtocol,
    EloSystemProtocol,
    EventEmitterProtocol,
    EvidenceCollectorProtocol,
    FlipDetectorProtocol,
    InsightStoreProtocol,
    MomentDetectorProtocol,
    PersonaManagerProtocol,
    PopulationManagerProtocol,
    PositionLedgerProtocol,
    PositionTrackerProtocol,
    PromptEvolverProtocol,
    PulseManagerProtocol,
    RelationshipTrackerProtocol,
)


@dataclass
class DebateConfig:
    """Configuration for debate protocol settings.

    Groups parameters related to debate rounds, consensus detection,
    and protocol-level behavior.

    Example::

        debate_config = DebateConfig(
            rounds=5,
            consensus_threshold=0.6,
            enable_adaptive_rounds=True,
        )
        arena = Arena(env, agents, debate_config=debate_config)
    """

    # Protocol settings (passed to DebateProtocol or override defaults)
    rounds: int = DEFAULT_ROUNDS  # Number of debate rounds
    consensus_threshold: float = 0.6  # Threshold for consensus detection (matches DEBATE_DEFAULTS)
    convergence_detection: bool = True  # Enable semantic convergence detection
    convergence_threshold: float = 0.85  # Similarity threshold for convergence
    divergence_threshold: float = 0.3  # Threshold for divergence detection
    timeout_seconds: int = 0  # Overall debate timeout (0 = no timeout)
    judge_selection: Literal[
        "random", "voted", "last", "elo_ranked", "calibrated", "crux_aware"
    ] = "elo_ranked"  # Judge selection mode

    # Adaptive debate settings
    enable_adaptive_rounds: bool = False  # Use memory-based strategy for rounds
    debate_strategy: Any | None = None  # Pre-configured DebateStrategy instance

    # Early termination settings
    enable_judge_termination: bool = False  # Allow judge to terminate early
    enable_early_stopping: bool = False  # Allow agents to request early stop

    # Hierarchy settings (Gastown pattern)
    enable_agent_hierarchy: bool = True  # Assign orchestrator/monitor/worker roles
    hierarchy_config: Any | None = None  # Optional HierarchyConfig

    def apply_to_protocol(self, protocol: DebateProtocol) -> DebateProtocol:
        """Apply config values to a DebateProtocol instance."""
        protocol.rounds = self.rounds
        protocol.consensus_threshold = self.consensus_threshold
        protocol.convergence_detection = self.convergence_detection
        protocol.convergence_threshold = self.convergence_threshold
        protocol.divergence_threshold = self.divergence_threshold
        protocol.timeout_seconds = self.timeout_seconds
        protocol.judge_selection = self.judge_selection
        return protocol


@dataclass
class AgentConfig:
    """Configuration for agent management and selection.

    Groups parameters related to agent pool management, performance-based
    selection, and resilience settings.

    Example::

        agent_config = AgentConfig(
            use_performance_selection=True,
            use_airlock=True,
            agent_weights={"claude": 1.2, "gpt4": 1.0},
        )
        arena = Arena(env, agents, agent_config=agent_config)
    """

    # Agent weights and selection
    agent_weights: dict[str, float] | None = None  # Reliability weights
    agent_selector: Any | None = None  # AgentSelector for performance-based selection
    use_performance_selection: bool = True  # Enable ELO/calibration-based selection

    # Resilience settings
    circuit_breaker: CircuitBreaker | None = None  # Circuit breaker for failure handling
    use_airlock: bool = False  # Wrap agents with AirlockProxy for timeout protection
    airlock_config: Any | None = None  # AirlockConfig customization

    # Tracking subsystems
    position_tracker: PositionTrackerProtocol | None = None
    position_ledger: PositionLedgerProtocol | None = None
    enable_position_ledger: bool = False  # Auto-create PositionLedger
    elo_system: EloSystemProtocol | None = None
    calibration_tracker: CalibrationTrackerProtocol | None = None
    relationship_tracker: RelationshipTrackerProtocol | None = None

    # Personas
    persona_manager: PersonaManagerProtocol | None = None
    vertical: str | None = None  # Industry vertical
    vertical_persona_manager: Any | None = None
    auto_detect_vertical: bool = True

    # Agent Fabric (high-scale orchestration)
    fabric: Any | None = None  # AgentFabric instance
    fabric_config: Any | None = None  # FabricDebateConfig


@dataclass
class StreamingConfig:
    """Configuration for WebSocket streaming and event handling.

    Groups parameters related to real-time event emission, spectator
    streams, and event hooks.

    Example::

        streaming_config = StreamingConfig(
            spectator=spectator_stream,
            event_emitter=emitter,
            loop_id="debate-123",
        )
        arena = Arena(env, agents, streaming_config=streaming_config)
    """

    # Event hooks and emitters
    event_hooks: dict[str, Any] | None = None  # Hooks for streaming events
    hook_manager: Any | None = None  # HookManager for extended lifecycle
    event_emitter: EventEmitterProtocol | None = None  # User event subscription

    # Spectator streaming
    spectator: SpectatorStream | None = None  # Real-time event stream

    # Recording
    recorder: Any | None = None  # ReplayRecorder for debate recording

    # Loop scoping
    loop_id: str = ""  # Loop ID for multi-loop scoping
    strict_loop_scoping: bool = False  # Drop events without loop_id

    # Skills integration
    skill_registry: Any | None = None  # SkillRegistry for extensible capabilities
    enable_skills: bool = False  # Enable skills during evidence collection

    # Propulsion (push-based work assignment)
    propulsion_engine: Any | None = None  # PropulsionEngine
    enable_propulsion: bool = False  # Enable propulsion events


@dataclass
class ObservabilityConfig:
    """Configuration for telemetry, monitoring, and health systems.

    Groups parameters related to performance monitoring, Prometheus metrics,
    and billing integration.

    Example::

        observability_config = ObservabilityConfig(
            enable_telemetry=True,
            enable_performance_monitor=True,
            org_id="org-123",
        )
        arena = Arena(env, agents, observability_config=observability_config)
    """

    # Performance monitoring
    performance_monitor: Any | None = None  # AgentPerformanceMonitor
    enable_performance_monitor: bool = True  # Auto-create monitor
    enable_telemetry: bool = False  # Enable Prometheus metrics

    # Prompt evolution
    prompt_evolver: PromptEvolverProtocol | None = None  # Pattern extraction
    enable_prompt_evolution: bool = False  # Auto-create evolver

    # Breakpoints (human-in-the-loop)
    breakpoint_manager: Any | None = None  # BreakpointManager

    # Trending topics / Pulse integration
    trending_topic: Any | None = None  # TrendingTopic to seed context
    pulse_manager: PulseManagerProtocol | None = None  # Auto-fetch trending
    auto_fetch_trending: bool = False  # Auto-fetch if none provided

    # Evolution / breeding
    population_manager: PopulationManagerProtocol | None = None  # Genome evolution
    auto_evolve: bool = False  # Trigger evolution after quality debates
    breeding_threshold: float = 0.8  # Min confidence for evolution

    # Evidence collection
    evidence_collector: EvidenceCollectorProtocol | None = None

    # Billing / usage tracking
    org_id: str = ""  # Organization ID for multi-tenancy
    user_id: str = ""  # User ID for attribution
    usage_tracker: Any | None = None  # UsageTracker

    # Broadcast pipeline
    broadcast_pipeline: BroadcastPipelineProtocol | None = None
    auto_broadcast: bool = False  # Auto-trigger broadcast
    broadcast_min_confidence: float = 0.8  # Min confidence for broadcast

    # Training export
    training_exporter: Any | None = None  # DebateTrainingExporter
    auto_export_training: bool = False  # Auto-export training data
    training_export_min_confidence: float = 0.75  # Min confidence to export

    # ML Integration (stable - enabled by default)
    enable_ml_delegation: bool = True  # ML-based agent selection
    ml_delegation_strategy: Any | None = None  # MLDelegationStrategy
    ml_delegation_weight: float = 0.3  # Weight for ML vs ELO
    enable_quality_gates: bool = True  # Filter low-quality responses
    quality_gate_threshold: float = 0.6  # Min quality score
    enable_consensus_estimation: bool = True  # Early termination estimation
    consensus_early_termination_threshold: float = 0.85  # Probability threshold

    # Post-debate workflow
    post_debate_workflow: Any | None = None  # Workflow DAG
    enable_post_debate_workflow: bool = False  # Auto-trigger workflow
    post_debate_workflow_threshold: float = 0.7  # Min confidence for workflow

    # Fork/continuation
    initial_messages: list[Any] | None = None  # Initial conversation history


# Primary config classes tuple for iteration
PRIMARY_CONFIG_CLASSES = (
    DebateConfig,
    AgentConfig,
    StreamingConfig,
    ObservabilityConfig,
)


# ===========================================================================
# Decomposed Config Groups (Legacy)
# ===========================================================================
# These provide focused configuration for specific Arena subsystems.
# They can be passed individually to Arena or composed into an ArenaConfig.
# Note: Some overlap with primary configs above - both are supported.


@dataclass
class MemoryConfig:
    """Memory subsystem configuration.

    Groups parameters related to critique storage, continuum memory,
    consensus memory, and knowledge mound integration.

    Example::

        memory_config = MemoryConfig(
            enable_knowledge_retrieval=True,
            enable_cross_debate_memory=True,
            auto_create_knowledge_mound=True,
        )
        arena = Arena(env, agents, memory_config=memory_config)
    """

    # Core memory stores
    memory: Any | None = None  # CritiqueStore instance
    continuum_memory: ContinuumMemoryProtocol | None = None  # Cross-debate learning
    consensus_memory: ConsensusMemoryProtocol | None = None  # Historical outcomes
    debate_embeddings: DebateEmbeddingsProtocol | None = None  # Historical context
    insight_store: InsightStoreProtocol | None = None  # Debate learnings
    dissent_retriever: DissentRetrieverProtocol | None = None  # Historical minority views
    flip_detector: FlipDetectorProtocol | None = None  # Position reversal detection
    moment_detector: MomentDetectorProtocol | None = None  # Significant moments
    tier_analytics_tracker: Any | None = None  # Memory ROI tracking

    # Cross-debate memory
    cross_debate_memory: Any | None = None  # Institutional knowledge
    enable_cross_debate_memory: bool = True  # Inject institutional knowledge

    # Knowledge Mound integration
    knowledge_mound: Any | None = None  # KnowledgeMound instance
    auto_create_knowledge_mound: bool = True  # Auto-create if not provided
    enable_knowledge_retrieval: bool = True  # Query mound before debates
    enable_knowledge_ingestion: bool = True  # Store consensus outcomes
    enable_knowledge_extraction: bool = False  # Extract structured claims
    extraction_min_confidence: float = 0.3  # Min confidence for extraction
    enable_belief_guidance: bool = True  # Inject historical cruxes
    enable_outcome_context: bool = True  # Inject past outcome data into debates

    # Revalidation settings
    enable_auto_revalidation: bool = False  # Auto-trigger for stale knowledge
    revalidation_staleness_threshold: float = 0.8  # Staleness threshold
    revalidation_check_interval_seconds: int = 3600  # Check interval
    revalidation_scheduler: Any | None = None  # RevalidationScheduler instance

    # RLM cognitive load limiter
    use_rlm_limiter: bool = True  # Use RLM for context compression
    rlm_limiter: Any | None = None  # Pre-configured limiter
    rlm_compression_threshold: int = 3000  # Chars to trigger compression
    rlm_max_recent_messages: int = 5  # Recent messages at full detail
    rlm_summary_level: str = "SUMMARY"  # Abstraction level
    rlm_compression_round_threshold: int = 3  # Auto-compression after N rounds

    # Supermemory (external cross-session memory)
    enable_supermemory: bool = False  # Master switch (opt-in)
    supermemory_adapter: Any | None = None  # Pre-configured adapter
    supermemory_inject_on_start: bool = True  # Inject context at debate start
    supermemory_max_context_items: int = 10  # Max items to inject
    supermemory_context_container_tag: str | None = None  # Container tag for context
    supermemory_sync_on_conclusion: bool = True  # Persist outcomes after debate
    supermemory_min_confidence_for_sync: float = 0.7  # Min confidence for sync
    supermemory_outcome_container_tag: str | None = None  # Container tag for outcomes
    supermemory_enable_privacy_filter: bool = True  # Filter PII before sync
    supermemory_enable_resilience: bool = True  # Retry on transient failures
    supermemory_enable_km_adapter: bool = False  # Auto-enable KM adapter

    # Codebase grounding (code-aware debates)
    codebase_path: str | None = None  # Path to repository for code-grounded debates
    enable_codebase_grounding: bool = False  # Inject codebase structure into debate context
    codebase_persist_to_km: bool = False  # Persist codebase structures to Knowledge Mound

    # Checkpointing
    checkpoint_manager: Any | None = None  # CheckpointManager for resume
    enable_checkpointing: bool = True  # Auto-create CheckpointManager


@dataclass
class SupermemoryConfig:
    """Supermemory (external cross-session memory) configuration.

    Groups all supermemory_* parameters into a single config object.

    Example::

        supermemory_config = SupermemoryConfig(
            enable_supermemory=True,
            supermemory_max_context_items=20,
        )
        arena = Arena(env, agents, supermemory_config=supermemory_config)
    """

    enable_supermemory: bool = False
    supermemory_adapter: Any | None = None
    supermemory_inject_on_start: bool = True
    supermemory_max_context_items: int = 10
    supermemory_context_container_tag: str | None = None
    supermemory_sync_on_conclusion: bool = True
    supermemory_min_confidence_for_sync: float = 0.7
    supermemory_outcome_container_tag: str | None = None
    supermemory_enable_privacy_filter: bool = True
    supermemory_enable_resilience: bool = True
    supermemory_enable_km_adapter: bool = False


@dataclass
class KnowledgeConfig:
    """Knowledge Mound configuration."""

    knowledge_mound: Any | None = None
    auto_create_knowledge_mound: bool = True
    enable_knowledge_retrieval: bool = True
    enable_knowledge_ingestion: bool = True
    enable_knowledge_extraction: bool = False
    extraction_min_confidence: float = 0.3
    enable_auto_revalidation: bool = False
    revalidation_staleness_threshold: float = 0.7
    revalidation_check_interval_seconds: int = 3600
    revalidation_scheduler: Any | None = None
    enable_belief_guidance: bool = True
    enable_outcome_context: bool = True


@dataclass
class MLConfig:
    """Machine learning integration configuration."""

    enable_ml_delegation: bool = True
    ml_delegation_strategy: Any | None = None
    ml_delegation_weight: float = 0.3
    enable_quality_gates: bool = True
    quality_gate_threshold: float = 0.6
    enable_consensus_estimation: bool = True
    consensus_early_termination_threshold: float = 0.85


@dataclass
class RLMConfig:
    """RLM cognitive load limiter configuration."""

    use_rlm_limiter: bool = True
    rlm_limiter: Any | None = None
    rlm_compression_threshold: int = 3000
    rlm_max_recent_messages: int = 5
    rlm_summary_level: str = "SUMMARY"
    rlm_compression_round_threshold: int = 3


@dataclass
class TelemetryConfig:
    """Telemetry and performance monitoring configuration."""

    performance_monitor: Any | None = None
    enable_performance_monitor: bool = True
    enable_telemetry: bool = False


@dataclass
class PersonaConfig:
    """Persona and vertical configuration."""

    persona_manager: PersonaManagerProtocol | None = None
    vertical: str | None = None
    auto_detect_vertical: bool = True
    vertical_persona_manager: Any | None = None


@dataclass
class ResilienceConfig:
    """Resilience and fault tolerance configuration."""

    circuit_breaker: CircuitBreaker | None = None
    use_airlock: bool = False
    airlock_config: Any | None = None


@dataclass
class EvolutionConfig:
    """Evolution and prompt optimization configuration."""

    population_manager: PopulationManagerProtocol | None = None
    auto_evolve: bool = False
    breeding_threshold: float = 0.8
    prompt_evolver: PromptEvolverProtocol | None = None
    enable_prompt_evolution: bool = False


@dataclass
class BillingConfig:
    """Billing and usage tracking configuration."""

    org_id: str = ""
    user_id: str = ""
    usage_tracker: Any | None = None


@dataclass
class BroadcastConfig:
    """Broadcast and training export configuration."""

    broadcast_pipeline: BroadcastPipelineProtocol | None = None
    auto_broadcast: bool = False
    broadcast_min_confidence: float = 0.8
    broadcast_platforms: list[str] | None = None
    training_exporter: Any | None = None
    auto_export_training: bool = False
    training_export_min_confidence: float = 0.75


@dataclass
class TranslationConfig:
    """Multi-language translation configuration."""

    translation_service: Any | None = None  # Pre-configured TranslationService
    multilingual_manager: Any | None = None  # Pre-configured MultilingualDebateManager
    enable_translation: bool = False  # Enable multi-language debate support
    default_language: str = "en"  # Default language code (ISO 639-1)
    target_languages: list[str] | None = None  # Languages to translate conclusions to
    auto_detect_language: bool = True  # Auto-detect source language of messages
    translate_conclusions: bool = True  # Translate final conclusions to target languages
    translation_cache_ttl_seconds: int = 3600  # Translation cache TTL (1 hour default)
    translation_cache_max_entries: int = 10000  # Max entries in translation cache


# Legacy config classes tuple (preserved for compatibility)
LEGACY_CONFIG_CLASSES = (
    KnowledgeConfig,
    SupermemoryConfig,
    MLConfig,
    RLMConfig,
    TelemetryConfig,
    PersonaConfig,
    ResilienceConfig,
    EvolutionConfig,
    BillingConfig,
    BroadcastConfig,
    TranslationConfig,
)

# All config classes (primary + legacy + MemoryConfig which is in both)
ALL_CONFIG_CLASSES = PRIMARY_CONFIG_CLASSES + (MemoryConfig,) + LEGACY_CONFIG_CLASSES

__all__ = [
    # Primary config classes
    "DebateConfig",
    "AgentConfig",
    "StreamingConfig",
    "ObservabilityConfig",
    "PRIMARY_CONFIG_CLASSES",
    # Legacy config classes
    "MemoryConfig",
    "SupermemoryConfig",
    "KnowledgeConfig",
    "MLConfig",
    "RLMConfig",
    "TelemetryConfig",
    "PersonaConfig",
    "ResilienceConfig",
    "EvolutionConfig",
    "BillingConfig",
    "BroadcastConfig",
    "TranslationConfig",
    "LEGACY_CONFIG_CLASSES",
    "ALL_CONFIG_CLASSES",
]
