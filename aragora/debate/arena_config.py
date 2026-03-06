"""
Arena configuration dataclass.

Extracted from orchestrator.py for modularity.
Provides type-safe configuration for Arena initialization.

The configuration is organized into logical sub-config groups using the
strategy/builder pattern. Each group is a standalone dataclass that can
be used independently or composed into the main ArenaConfig.

Backward compatibility is preserved: all fields can still be accessed
directly on ArenaConfig (e.g., ``config.enable_consensus``) and all
fields can still be passed as flat kwargs to ``ArenaConfig()``.

Sub-config groups
-----------------
- **HookConfig**: Event hooks, YAML hooks, hook handlers
- **TrackingConfig**: Position, ELO, persona, flip detection, relationships
- **KnowledgeMoundConfig**: Knowledge retrieval, ingestion, extraction, revalidation
- **MemoryCoordinationConfig**: Cross-system atomic writes, rollback policy
- **PerformanceFeedbackConfig**: Selection feedback loop, performance-ELO integration
- **AuditTrailConfig**: Decision receipts, evidence provenance, bead tracking
- **MLIntegrationConfig**: ML delegation, quality gates, consensus estimation
- **RLMCognitiveConfig**: RLM cognitive load limiter settings
- **CheckpointMemoryConfig**: Checkpoint manager, memory state in checkpoints
- **CrossPollinationConfig**: Phase 9 cross-pollination bridges
- **KMBidirectionalConfig**: Phase 10 bidirectional Knowledge Mound sync
- **TranslationConfig**: Multi-language translation support

Builder usage
-------------
::

    config = (
        ArenaConfig.builder()
        .with_knowledge(enable_knowledge_retrieval=True)
        .with_audit_trail(enable_receipt_generation=True)
        .with_ml(enable_ml_delegation=True, ml_delegation_weight=0.5)
        .build()
    )
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING, Any

from aragora.debate.protocol import CircuitBreaker

if TYPE_CHECKING:
    pass
from aragora.spectate.stream import SpectatorStream
from aragora.type_protocols import (
    BroadcastPipelineProtocol,
    DebateEmbeddingsProtocol,
    EventEmitterProtocol,
    EvidenceCollectorProtocol,
    InsightStoreProtocol,
    PopulationManagerProtocol,
    PromptEvolverProtocol,
    PulseManagerProtocol,
)


# =============================================================================
# Sub-Config Dataclasses (imported from arena_sub_configs.py)
# =============================================================================

from .arena_sub_configs import (
    AuditTrailConfig,
    AutoExecutionConfig,
    BudgetSubConfig,
    CheckpointMemoryConfig,
    CrossPollinationConfig,
    HookConfig,
    KMBidirectionalConfig,
    KnowledgeMoundConfig,
    MemoryCoordinationConfig,
    MLIntegrationConfig,
    PerformanceFeedbackConfig,
    PowerSamplingConfig,
    RLMCognitiveConfig,
    SupermemorySubConfig,
    TrackingConfig,
    TranslationSubConfig,
)


# =============================================================================
# Sub-config field name -> sub-config attribute name mapping
# Built once at module load for O(1) lookups.
# =============================================================================

_SUB_CONFIG_GROUPS: dict[str, tuple[str, type]] = {}
"""Maps field_name -> (sub_config_attr_on_ArenaConfig, sub_config_class)."""

_SUB_CONFIG_ATTRS: list[tuple[str, type]] = [
    ("hook_config", HookConfig),
    ("tracking_config", TrackingConfig),
    ("knowledge_config", KnowledgeMoundConfig),
    ("memory_coordination_config", MemoryCoordinationConfig),
    ("performance_feedback_config", PerformanceFeedbackConfig),
    ("audit_trail_config", AuditTrailConfig),
    ("ml_integration_config", MLIntegrationConfig),
    ("rlm_cognitive_config", RLMCognitiveConfig),
    ("checkpoint_memory_config", CheckpointMemoryConfig),
    ("cross_pollination_config", CrossPollinationConfig),
    ("km_bidirectional_config", KMBidirectionalConfig),
    ("translation_sub_config", TranslationSubConfig),
    ("supermemory_sub_config", SupermemorySubConfig),
    ("budget_sub_config", BudgetSubConfig),
    ("power_sampling_config", PowerSamplingConfig),
    ("auto_execution_config", AutoExecutionConfig),
]

for _attr_name, _cls in _SUB_CONFIG_ATTRS:
    for _f in dataclass_fields(_cls):
        _SUB_CONFIG_GROUPS[_f.name] = (_attr_name, _cls)


# =============================================================================
# ArenaConfig Builder
# =============================================================================


class ArenaConfigBuilder:
    """Fluent builder for ArenaConfig.

    Allows constructing an ArenaConfig step-by-step using logical groupings::

        config = (
            ArenaConfig.builder()
            .with_hooks(enable_yaml_hooks=True)
            .with_tracking(enable_position_ledger=True)
            .with_knowledge(enable_knowledge_retrieval=True)
            .with_audit_trail(enable_receipt_generation=True)
            .with_ml(enable_ml_delegation=True)
            .build()
        )
    """

    def __init__(self) -> None:
        self._kwargs: dict[str, Any] = {}

    def _merge(self, kwargs: dict[str, Any]) -> ArenaConfigBuilder:
        self._kwargs.update(kwargs)
        return self

    # -- Top-level fields --

    def with_identity(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set identification fields (loop_id, strict_loop_scoping)."""
        return self._merge(kwargs)

    def with_core(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set core subsystem fields (memory, event_emitter, spectator, etc.)."""
        return self._merge(kwargs)

    # -- Sub-config groups --

    def with_hooks(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set hook configuration fields."""
        return self._merge(kwargs)

    def with_tracking(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set tracking subsystem fields."""
        return self._merge(kwargs)

    def with_knowledge(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set Knowledge Mound integration fields."""
        return self._merge(kwargs)

    def with_memory_coordination(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set memory coordination fields."""
        return self._merge(kwargs)

    def with_performance_feedback(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set performance feedback loop fields."""
        return self._merge(kwargs)

    def with_audit_trail(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set audit trail fields (receipts, provenance, beads)."""
        return self._merge(kwargs)

    def with_ml(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set ML integration fields."""
        return self._merge(kwargs)

    def with_rlm(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set RLM cognitive load limiter fields."""
        return self._merge(kwargs)

    def with_checkpoint(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set checkpoint and memory state fields."""
        return self._merge(kwargs)

    def with_cross_pollination(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set Phase 9 cross-pollination bridge fields."""
        return self._merge(kwargs)

    def with_km_bidirectional(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set Phase 10 bidirectional KM fields."""
        return self._merge(kwargs)

    def with_translation(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set multi-language translation fields."""
        return self._merge(kwargs)

    def with_supermemory(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set Supermemory external memory integration fields."""
        return self._merge(kwargs)

    def with_budget(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set per-debate budget configuration fields."""
        return self._merge(kwargs)

    def with_power_sampling(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set power sampling configuration for inference-time reasoning."""
        return self._merge(kwargs)

    def with_post_debate(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set post-debate coordinator pipeline configuration."""
        return self._merge(kwargs)

    def with_auto_execution(self, **kwargs: Any) -> ArenaConfigBuilder:
        """Set auto-execution configuration for decision pipeline."""
        return self._merge(kwargs)

    def build(self) -> ArenaConfig:
        """Build the ArenaConfig from accumulated settings."""
        return ArenaConfig(**self._kwargs)


# =============================================================================
# ArenaConfig (main configuration class)
# =============================================================================


class ArenaConfig:
    """Configuration for Arena debate orchestration.

    Groups optional dependencies and settings that can be passed to Arena.
    This allows for cleaner initialization and easier testing.

    All fields from the sub-config dataclasses are accessible directly
    on this class for backward compatibility::

        config = ArenaConfig(enable_receipt_generation=True)
        assert config.enable_receipt_generation is True  # works

    Sub-config objects are also accessible for grouped usage::

        config.audit_trail_config.enable_receipt_generation  # also works

    Initialization Flow
    -------------------
    Arena initialization follows a layered architecture pattern:

    1. **Core Configuration** (_init_core):
       - Sets up environment, agents, protocol, spectator
       - Initializes circuit breaker for fault tolerance
       - Configures loop scoping for multi-debate sessions

    2. **Tracking Subsystems** (_init_trackers):
       - Position and belief tracking (PositionTracker, PositionLedger)
       - ELO rating system for agent ranking
       - Persona manager for agent specialization
       - Flip detector for position reversals
       - Relationship tracker for agent interactions
       - Moment detector for significant events

    3. **User Participation** (_init_user_participation):
       - Sets up event queue for user votes/suggestions
       - Subscribes to event emitter for real-time participation

    4. **Roles and Stances** (_init_roles_and_stances):
       - Initializes cognitive role rotation (Heavy3-inspired)
       - Sets up initial agent stances

    5. **Convergence Detection** (_init_convergence):
       - Configures semantic similarity backend
       - Sets up convergence thresholds

    6. **Phase Classes** (_init_phases):
       - ContextInitializer, ProposalPhase, DebateRoundsPhase
       - ConsensusPhase, AnalyticsPhase, FeedbackPhase, VotingPhase

    Dependency Injection
    --------------------
    Most subsystems are optional and can be injected for testing:

    - Memory systems: critique_store, continuum_memory, debate_embeddings
    - Tracking: elo_system, position_ledger, relationship_tracker
    - Events: event_emitter, spectator
    - Recording: recorder, evidence_collector

    Example
    -------
    Basic usage with minimal configuration::

        config = ArenaConfig(loop_id="debate-123")
        arena = Arena.from_config(env, agents, protocol, config)

    Full production setup with all subsystems::

        config = ArenaConfig(
            loop_id="debate-123",
            strict_loop_scoping=True,
            memory=critique_store,
            continuum_memory=continuum,
            elo_system=elo,
            event_emitter=emitter,
            spectator=stream,
        )
        arena = Arena.from_config(env, agents, protocol, config)

    Builder pattern::

        config = (
            ArenaConfig.builder()
            .with_identity(loop_id="debate-123")
            .with_knowledge(enable_knowledge_retrieval=True)
            .with_audit_trail(enable_receipt_generation=True)
            .build()
        )
    """

    # Keep __slots__ off so property delegation works with __dict__.
    # We use __init__ directly to support both flat kwargs and sub-configs.

    def __init__(
        self,
        # Identification
        loop_id: str = "",
        strict_loop_scoping: bool = False,
        # Core subsystems (typically injected)
        memory: Any | None = None,
        event_emitter: EventEmitterProtocol | None = None,
        spectator: SpectatorStream | None = None,
        debate_embeddings: DebateEmbeddingsProtocol | None = None,
        insight_store: InsightStoreProtocol | None = None,
        recorder: Any | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        evidence_collector: EvidenceCollectorProtocol | None = None,
        # Skills system integration
        skill_registry: Any | None = None,
        enable_skills: bool = False,
        # Propulsion engine (Gastown pattern)
        propulsion_engine: Any | None = None,
        enable_propulsion: bool = False,
        # Agent configuration
        agent_weights: dict[str, float] | None = None,
        # Vertical personas
        vertical: str | None = None,
        vertical_persona_manager: Any | None = None,
        auto_detect_vertical: bool = True,
        # Performance telemetry
        performance_monitor: Any | None = None,
        enable_performance_monitor: bool = True,
        enable_telemetry: bool = False,
        # Agent selection
        agent_selector: Any | None = None,
        use_performance_selection: bool = True,
        # Airlock resilience
        use_airlock: bool = False,
        airlock_config: Any | None = None,
        # Prompt evolution
        prompt_evolver: PromptEvolverProtocol | None = None,
        enable_prompt_evolution: bool = False,
        # Billing/usage
        org_id: str = "",
        user_id: str = "",
        usage_tracker: Any | None = None,
        # Broadcast
        broadcast_pipeline: BroadcastPipelineProtocol | None = None,
        auto_broadcast: bool = False,
        broadcast_min_confidence: float = 0.8,
        broadcast_platforms: list[str] | None = None,
        # Training data export
        training_exporter: Any | None = None,
        auto_export_training: bool = False,
        training_export_min_confidence: float = 0.75,
        training_export_path: str = "",
        # Genesis evolution
        population_manager: PopulationManagerProtocol | None = None,
        auto_evolve: bool = False,
        breeding_threshold: float = 0.8,
        # Fork/continuation
        initial_messages: list[Any] | None = None,
        trending_topic: Any | None = None,
        pulse_manager: PulseManagerProtocol | None = None,
        auto_fetch_trending: bool = False,
        # Human-in-the-loop breakpoints
        breakpoint_manager: Any | None = None,
        # Post-debate workflow automation
        post_debate_workflow: Any | None = None,
        enable_post_debate_workflow: bool = False,
        post_debate_workflow_threshold: float = 0.7,
        # Result routing: route debate results back to originating chat channel
        # When enabled, completed debates route results to the platform that started them
        # (Telegram, Slack, Discord, Teams, WhatsApp, email, webhook)
        enable_result_routing: bool = False,
        # N+1 Query Detection
        enable_n1_detection: bool = False,
        n1_detection_mode: str = "warn",
        n1_detection_threshold: int = 5,
        # Autotuner (budget-aware debate optimization)
        autotune_config: Any | None = None,
        # Stability Detection (adaptive stopping)
        enable_stability_detection: bool = False,
        stability_threshold: float = 0.85,
        stability_min_rounds: int = 1,
        stability_agreement_threshold: float = 0.7,
        stability_conflict_confidence: float = 0.4,
        # Debate Forking (branch divergent debates)
        enable_debate_forking: bool = False,
        fork_disagreement_threshold: float = 0.7,
        fork_max_branches: int = 3,
        # Unified Voting Engine
        enable_unified_voting: bool = False,
        voting_weight_reputation: float = 0.4,
        voting_weight_calibration: float = 0.3,
        voting_weight_consistency: float = 0.3,
        # Privacy anonymization (HIPAA Safe Harbor)
        enable_privacy_anonymization: bool = False,
        anonymization_method: str = "redact",
        # Sandbox verification of code proposals
        enable_sandbox_verification: bool = False,
        # Data classification (tag results with sensitivity metadata)
        enable_data_classification: bool = False,
        # Protocol-level flags (stored for preset passthrough to Arena/Protocol)
        enable_adaptive_consensus: bool = False,
        enable_synthesis: bool = False,
        enable_knowledge_injection: bool = False,
        enable_meta_learning: bool = False,
        # Agent provider diversity: prefer heterogeneous model consensus
        min_provider_diversity: int = 1,  # Minimum number of distinct providers
        prefer_diverse_providers: bool = False,  # Prefer agents from different providers
        # ---- Sub-config objects (optional, for grouped construction) ----
        hook_config: HookConfig | None = None,
        tracking_config: TrackingConfig | None = None,
        knowledge_config: KnowledgeMoundConfig | None = None,
        memory_coordination_config: MemoryCoordinationConfig | None = None,
        performance_feedback_config: PerformanceFeedbackConfig | None = None,
        audit_trail_config: AuditTrailConfig | None = None,
        ml_integration_config: MLIntegrationConfig | None = None,
        rlm_cognitive_config: RLMCognitiveConfig | None = None,
        checkpoint_memory_config: CheckpointMemoryConfig | None = None,
        cross_pollination_config: CrossPollinationConfig | None = None,
        km_bidirectional_config: KMBidirectionalConfig | None = None,
        translation_sub_config: TranslationSubConfig | None = None,
        supermemory_sub_config: SupermemorySubConfig | None = None,
        budget_sub_config: BudgetSubConfig | None = None,
        power_sampling_config: PowerSamplingConfig | None = None,
        auto_execution_config: AutoExecutionConfig | None = None,
        # ---- Flat kwargs that belong to sub-configs (backward compat) ----
        **kwargs: Any,
    ) -> None:
        # -- Top-level fields (not in any sub-config) --
        self.loop_id = loop_id
        self.strict_loop_scoping = strict_loop_scoping
        self.memory = memory
        self.event_emitter = event_emitter
        self.spectator = spectator
        self.debate_embeddings = debate_embeddings
        self.insight_store = insight_store
        self.recorder = recorder
        self.circuit_breaker = circuit_breaker
        self.evidence_collector = evidence_collector
        self.skill_registry = skill_registry
        self.enable_skills = enable_skills
        self.propulsion_engine = propulsion_engine
        self.enable_propulsion = enable_propulsion
        self.agent_weights = agent_weights
        self.vertical = vertical
        self.vertical_persona_manager = vertical_persona_manager
        self.auto_detect_vertical = auto_detect_vertical
        self.performance_monitor = performance_monitor
        self.enable_performance_monitor = enable_performance_monitor
        self.enable_telemetry = enable_telemetry
        self.agent_selector = agent_selector
        self.use_performance_selection = use_performance_selection
        self.use_airlock = use_airlock
        self.airlock_config = airlock_config
        self.prompt_evolver = prompt_evolver
        self.enable_prompt_evolution = enable_prompt_evolution
        self.org_id = org_id
        self.user_id = user_id
        self.usage_tracker = usage_tracker
        self.broadcast_pipeline = broadcast_pipeline
        self.auto_broadcast = auto_broadcast
        self.broadcast_min_confidence = broadcast_min_confidence
        self.broadcast_platforms = broadcast_platforms
        self.training_exporter = training_exporter
        self.auto_export_training = auto_export_training
        self.training_export_min_confidence = training_export_min_confidence
        self.training_export_path = training_export_path
        self.population_manager = population_manager
        self.auto_evolve = auto_evolve
        self.breeding_threshold = breeding_threshold
        self.initial_messages = initial_messages
        self.trending_topic = trending_topic
        self.pulse_manager = pulse_manager
        self.auto_fetch_trending = auto_fetch_trending
        self.breakpoint_manager = breakpoint_manager
        self.post_debate_workflow = post_debate_workflow
        self.enable_post_debate_workflow = enable_post_debate_workflow
        self.post_debate_workflow_threshold = post_debate_workflow_threshold
        self.enable_result_routing = enable_result_routing
        self.enable_n1_detection = enable_n1_detection
        self.n1_detection_mode = n1_detection_mode
        self.n1_detection_threshold = n1_detection_threshold
        self.autotune_config = autotune_config
        self.enable_stability_detection = enable_stability_detection
        self.stability_threshold = stability_threshold
        self.stability_min_rounds = stability_min_rounds
        self.stability_agreement_threshold = stability_agreement_threshold
        self.stability_conflict_confidence = stability_conflict_confidence

        # Debate Forking
        self.enable_debate_forking = enable_debate_forking
        self.fork_disagreement_threshold = fork_disagreement_threshold
        self.fork_max_branches = fork_max_branches

        # Unified Voting Engine
        self.enable_unified_voting = enable_unified_voting
        self.voting_weight_reputation = voting_weight_reputation
        self.voting_weight_calibration = voting_weight_calibration
        self.voting_weight_consistency = voting_weight_consistency

        # Privacy anonymization
        self.enable_privacy_anonymization = enable_privacy_anonymization
        self.anonymization_method = anonymization_method

        # Sandbox verification of code proposals
        self.enable_sandbox_verification = enable_sandbox_verification

        # Data classification (tag results with sensitivity metadata)
        self.enable_data_classification = enable_data_classification

        # Protocol-level flags (preset passthrough)
        self.enable_adaptive_consensus = enable_adaptive_consensus
        self.enable_synthesis = enable_synthesis
        self.enable_knowledge_injection = enable_knowledge_injection
        self.enable_meta_learning = enable_meta_learning

        # Agent provider diversity
        self.min_provider_diversity = min_provider_diversity
        self.prefer_diverse_providers = prefer_diverse_providers

        # Post-debate coordinator pipeline (default-on, opt-out via disable_post_debate_pipeline)
        self.post_debate_config = kwargs.pop("post_debate_config", None)
        self.disable_post_debate_pipeline = kwargs.pop("disable_post_debate_pipeline", False)

        # Explainability
        self.auto_explain = kwargs.pop("auto_explain", False)
        self.enable_live_explainability = kwargs.pop("enable_live_explainability", False)

        # Agent introspection (self-awareness in prompts)
        self.enable_introspection = kwargs.pop("enable_introspection", True)

        # Argument cartography (debate graph visualization)
        self.enable_cartographer = kwargs.pop("enable_cartographer", True)

        # Decision pipeline (auto-create GitHub issues from plans)
        self.auto_execute_plan = kwargs.pop("auto_execute_plan", False)

        # -- Build sub-configs from flat kwargs + explicit sub-config objects --
        # For each sub-config group, collect any flat kwargs that belong to it,
        # then merge with an explicit sub-config object if provided.
        self.hook_config = self._build_sub_config(HookConfig, hook_config, kwargs)
        self.tracking_config = self._build_sub_config(TrackingConfig, tracking_config, kwargs)
        self.knowledge_config = self._build_sub_config(
            KnowledgeMoundConfig, knowledge_config, kwargs
        )
        self.memory_coordination_config = self._build_sub_config(
            MemoryCoordinationConfig, memory_coordination_config, kwargs
        )
        self.performance_feedback_config = self._build_sub_config(
            PerformanceFeedbackConfig, performance_feedback_config, kwargs
        )
        self.audit_trail_config = self._build_sub_config(
            AuditTrailConfig, audit_trail_config, kwargs
        )
        self.ml_integration_config = self._build_sub_config(
            MLIntegrationConfig, ml_integration_config, kwargs
        )
        self.rlm_cognitive_config = self._build_sub_config(
            RLMCognitiveConfig, rlm_cognitive_config, kwargs
        )
        self.checkpoint_memory_config = self._build_sub_config(
            CheckpointMemoryConfig, checkpoint_memory_config, kwargs
        )
        self.cross_pollination_config = self._build_sub_config(
            CrossPollinationConfig, cross_pollination_config, kwargs
        )
        self.km_bidirectional_config = self._build_sub_config(
            KMBidirectionalConfig, km_bidirectional_config, kwargs
        )
        self.translation_sub_config = self._build_sub_config(
            TranslationSubConfig, translation_sub_config, kwargs
        )
        self.supermemory_sub_config = self._build_sub_config(
            SupermemorySubConfig, supermemory_sub_config, kwargs
        )
        self.budget_sub_config = self._build_sub_config(BudgetSubConfig, budget_sub_config, kwargs)
        self.power_sampling_config = self._build_sub_config(
            PowerSamplingConfig, power_sampling_config, kwargs
        )
        self.auto_execution_config = self._build_sub_config(
            AutoExecutionConfig, auto_execution_config, kwargs
        )

        # Any remaining kwargs are unknown fields
        if kwargs:
            unknown = ", ".join(sorted(kwargs.keys()))
            raise TypeError(f"ArenaConfig received unknown keyword arguments: {unknown}")

        # Post-init defaults
        if self.broadcast_platforms is None:
            self.broadcast_platforms = ["rss"]

    @staticmethod
    def _build_sub_config(
        cls: type,
        explicit: Any | None,
        kwargs: dict[str, Any],
    ) -> Any:
        """Build a sub-config from flat kwargs, optionally overlaying on an explicit instance.

        If an explicit sub-config object is provided, flat kwargs override its values.
        If no explicit object is provided, a new one is created from defaults + kwargs.
        """
        field_names = {f.name for f in dataclass_fields(cls)}
        overrides = {}
        for name in list(kwargs):
            if name in field_names:
                overrides[name] = kwargs.pop(name)

        if explicit is not None:
            # Start from the explicit object's values, then apply overrides
            init_kwargs = {}
            for f in dataclass_fields(cls):
                if f.name in overrides:
                    init_kwargs[f.name] = overrides[f.name]
                else:
                    init_kwargs[f.name] = getattr(explicit, f.name)
            return cls(**init_kwargs)
        else:
            # Create from defaults + overrides
            return cls(**overrides)

    # =========================================================================
    # Backward-compatible attribute access via __getattr__
    # =========================================================================

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to sub-configs for backward compatibility.

        This allows ``config.enable_receipt_generation`` to transparently
        access ``config.audit_trail_config.enable_receipt_generation``.
        """
        # Look up which sub-config owns this field
        mapping = _SUB_CONFIG_GROUPS.get(name)
        if mapping is not None:
            attr_name, _ = mapping
            sub = object.__getattribute__(self, attr_name)
            return getattr(sub, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        """Delegate attribute setting to sub-configs for backward compatibility.

        This allows ``config.enable_receipt_generation = True`` to transparently
        set ``config.audit_trail_config.enable_receipt_generation = True``.
        """
        # During __init__, allow setting all attributes directly
        # After __init__, delegate sub-config fields
        mapping = _SUB_CONFIG_GROUPS.get(name)
        if mapping is not None:
            attr_name, _ = mapping
            # Check if the sub-config attribute exists yet (it may not during __init__)
            try:
                sub = object.__getattribute__(self, attr_name)
                setattr(sub, name, value)
                return
            except AttributeError:
                # Sub-config not yet initialized, fall through to direct set
                pass
        object.__setattr__(self, name, value)

    # =========================================================================
    # Equality and repr (dataclass-like behavior)
    # =========================================================================

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ArenaConfig):
            return NotImplemented
        return self.__dict__ == other.__dict__

    def __repr__(self) -> str:
        parts = []
        for key, value in self.__dict__.items():
            # Skip sub-configs that are at default values to keep repr manageable
            if key.endswith("_config") and key != "airlock_config":
                mapping = {a: c for a, c in _SUB_CONFIG_ATTRS}
                cls = mapping.get(key)
                if cls is not None:
                    default = cls()
                    if value == default:
                        continue
            parts.append(f"{key}={value!r}")
        return f"ArenaConfig({', '.join(parts)})"

    # =========================================================================
    # Builder factory
    # =========================================================================

    @classmethod
    def builder(cls) -> ArenaConfigBuilder:
        """Create a new ArenaConfigBuilder for fluent construction."""
        return ArenaConfigBuilder()

    @classmethod
    def from_preset(
        cls,
        name: str,
        overrides: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ArenaConfig:
        """Create an ArenaConfig from a named preset.

        Presets provide sensible defaults for common use cases (sme, enterprise,
        minimal, audit). Overrides and kwargs take precedence over preset values.

        Args:
            name: Preset name (sme, enterprise, minimal, audit).
            overrides: Optional dict of overrides.
            **kwargs: Additional overrides as keyword arguments.

        Returns:
            Configured ArenaConfig instance.
        """
        from aragora.debate.presets import apply_preset

        merged = apply_preset(name, overrides=overrides, **kwargs)
        return cls(**merged)

    # =========================================================================
    # to_arena_kwargs (preserved from original)
    # =========================================================================

    def to_arena_kwargs(self) -> dict[str, Any]:
        """Convert config to kwargs dict for Arena.__init__.

        Returns:
            Dictionary of keyword arguments for Arena initialization.

        Note:
            Only includes parameters that Arena.__init__ currently accepts.
            broadcast_platforms and training_export_path are stored in config
            but not yet supported by Arena.
        """
        return {
            "memory": self.memory,
            "event_hooks": self.event_hooks,
            "hook_manager": self.hook_manager,
            "event_emitter": self.event_emitter,
            "spectator": self.spectator,
            "debate_embeddings": self.debate_embeddings,
            "insight_store": self.insight_store,
            "recorder": self.recorder,
            "agent_weights": self.agent_weights,
            "position_tracker": self.position_tracker,
            "position_ledger": self.position_ledger,
            "enable_position_ledger": self.enable_position_ledger,
            "elo_system": self.elo_system,
            "persona_manager": self.persona_manager,
            "dissent_retriever": self.dissent_retriever,
            "consensus_memory": self.consensus_memory,
            "flip_detector": self.flip_detector,
            "calibration_tracker": self.calibration_tracker,
            "continuum_memory": self.continuum_memory,
            "relationship_tracker": self.relationship_tracker,
            "moment_detector": self.moment_detector,
            "tier_analytics_tracker": self.tier_analytics_tracker,
            "knowledge_mound": self.knowledge_mound,
            "enable_knowledge_retrieval": self.enable_knowledge_retrieval,
            "enable_knowledge_ingestion": self.enable_knowledge_ingestion,
            "enable_knowledge_extraction": self.enable_knowledge_extraction,
            "extraction_min_confidence": self.extraction_min_confidence,
            # Supermemory (external memory integration)
            "enable_supermemory": self.enable_supermemory,
            "supermemory_enable_km_adapter": self.supermemory_enable_km_adapter,
            "supermemory_adapter": self.supermemory_adapter,
            "supermemory_inject_on_start": self.supermemory_inject_on_start,
            "supermemory_max_context_items": self.supermemory_max_context_items,
            "supermemory_context_container_tag": self.supermemory_context_container_tag,
            "supermemory_sync_on_conclusion": self.supermemory_sync_on_conclusion,
            "supermemory_min_confidence_for_sync": self.supermemory_min_confidence_for_sync,
            "supermemory_outcome_container_tag": self.supermemory_outcome_container_tag,
            "supermemory_enable_privacy_filter": self.supermemory_enable_privacy_filter,
            "supermemory_enable_resilience": self.supermemory_enable_resilience,
            # Auto-revalidation
            "enable_auto_revalidation": self.enable_auto_revalidation,
            "enable_belief_guidance": self.enable_belief_guidance,
            "enable_outcome_context": getattr(self, "enable_outcome_context", True),
            # Cross-debate institutional memory
            "cross_debate_memory": self.cross_debate_memory,
            "enable_cross_debate_memory": self.enable_cross_debate_memory,
            # Post-debate workflow automation
            "post_debate_workflow": self.post_debate_workflow,
            "enable_post_debate_workflow": self.enable_post_debate_workflow,
            "post_debate_workflow_threshold": self.post_debate_workflow_threshold,
            "enable_result_routing": self.enable_result_routing,
            # Post-debate coordinator pipeline
            "post_debate_config": self.post_debate_config,
            "disable_post_debate_pipeline": self.disable_post_debate_pipeline,
            "loop_id": self.loop_id,
            "strict_loop_scoping": self.strict_loop_scoping,
            "circuit_breaker": self.circuit_breaker,
            "initial_messages": self.initial_messages,
            "trending_topic": self.trending_topic,
            "pulse_manager": self.pulse_manager,
            "auto_fetch_trending": self.auto_fetch_trending,
            "population_manager": self.population_manager,
            "auto_evolve": self.auto_evolve,
            "breeding_threshold": self.breeding_threshold,
            "evidence_collector": self.evidence_collector,
            "skill_registry": self.skill_registry,
            "enable_skills": self.enable_skills,
            "propulsion_engine": self.propulsion_engine,
            "enable_propulsion": self.enable_propulsion,
            "breakpoint_manager": self.breakpoint_manager,
            "performance_monitor": self.performance_monitor,
            "enable_performance_monitor": self.enable_performance_monitor,
            "enable_telemetry": self.enable_telemetry,
            "use_airlock": self.use_airlock,
            "airlock_config": self.airlock_config,
            "agent_selector": self.agent_selector,
            "use_performance_selection": self.use_performance_selection,
            "prompt_evolver": self.prompt_evolver,
            "enable_prompt_evolution": self.enable_prompt_evolution,
            "checkpoint_manager": self.checkpoint_manager,
            "enable_checkpointing": self.enable_checkpointing,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "usage_tracker": self.usage_tracker,
            "broadcast_pipeline": self.broadcast_pipeline,
            "auto_broadcast": self.auto_broadcast,
            "broadcast_min_confidence": self.broadcast_min_confidence,
            "training_exporter": self.training_exporter,
            "auto_export_training": self.auto_export_training,
            "training_export_min_confidence": self.training_export_min_confidence,
            # ML Integration
            "enable_ml_delegation": self.enable_ml_delegation,
            "ml_delegation_strategy": self.ml_delegation_strategy,
            "ml_delegation_weight": self.ml_delegation_weight,
            "enable_quality_gates": self.enable_quality_gates,
            "quality_gate_threshold": self.quality_gate_threshold,
            "enable_consensus_estimation": self.enable_consensus_estimation,
            "consensus_early_termination_threshold": self.consensus_early_termination_threshold,
            # Note: stability detection fields stored in ArenaConfig but not yet
            # wired to Arena.__init__. Access via arena.config.enable_stability_detection etc.
            # "enable_stability_detection": self.enable_stability_detection,
            # "stability_threshold": self.stability_threshold,
            # "stability_min_rounds": self.stability_min_rounds,
            # "stability_agreement_threshold": self.stability_agreement_threshold,
            # "stability_conflict_confidence": self.stability_conflict_confidence,
            # RLM Cognitive Limiter
            "use_rlm_limiter": self.use_rlm_limiter,
            "rlm_limiter": self.rlm_limiter,
            "rlm_compression_threshold": self.rlm_compression_threshold,
            "rlm_max_recent_messages": self.rlm_max_recent_messages,
            "rlm_summary_level": self.rlm_summary_level,
            "rlm_compression_round_threshold": self.rlm_compression_round_threshold,
            # Note: The following are stored in ArenaConfig but not yet in Arena.__init__:
            # - Memory Coordination: enable_coordinated_writes, memory_coordinator,
            #   coordinator_parallel_writes, coordinator_rollback_on_failure,
            #   coordinator_min_confidence_for_mound
            # - Selection Feedback Loop: enable_performance_feedback, selection_feedback_loop,
            #   feedback_loop_weight, feedback_loop_decay, feedback_loop_min_debates
            # - Hook System: enable_hook_handlers, hook_handler_registry
            # - Broadcast: broadcast_platforms, training_export_path
            # - Phase 9 Cross-Pollination Bridges (auto-initialized by SubsystemCoordinator):
            #   * Performance Router: enable_performance_router, performance_router_bridge,
            #     performance_router_latency_weight, performance_router_quality_weight,
            #     performance_router_consistency_weight
            #   * Outcome Complexity: enable_outcome_complexity, outcome_complexity_bridge,
            #     outcome_complexity_high_success_boost, outcome_complexity_low_success_penalty,
            #     outcome_complexity_min_outcomes
            #   * Analytics Selection: enable_analytics_selection, analytics_selection_bridge,
            #     analytics_selection_diversity_weight, analytics_selection_synergy_weight
            #   * Novelty Selection: enable_novelty_selection, novelty_selection_bridge,
            #     novelty_selection_low_penalty, novelty_selection_high_bonus,
            #     novelty_selection_min_proposals, novelty_selection_low_threshold
            #   * Relationship Bias: enable_relationship_bias, relationship_bias_bridge,
            #     relationship_bias_alliance_threshold, relationship_bias_agreement_threshold,
            #     relationship_bias_vote_penalty, relationship_bias_min_debates
            #   * RLM Selection: enable_rlm_selection, rlm_selection_bridge,
            #     rlm_selection_min_operations, rlm_selection_compression_weight,
            #     rlm_selection_query_weight, rlm_selection_max_boost
            #   * Calibration Cost: enable_calibration_cost, calibration_cost_bridge,
            #     calibration_cost_min_predictions, calibration_cost_ece_threshold,
            #     calibration_cost_overconfident_multiplier, calibration_cost_weight
        }


# ===========================================================================
# Primary and Legacy Config Groups (imported from arena_primary_configs.py)
# ===========================================================================

from .arena_primary_configs import (
    ALL_CONFIG_CLASSES,
    AgentConfig,
    BillingConfig,
    BroadcastConfig,
    DebateConfig,
    EvolutionConfig,
    KnowledgeConfig,
    LEGACY_CONFIG_CLASSES,
    MLConfig,
    MemoryConfig,
    ObservabilityConfig,
    PRIMARY_CONFIG_CLASSES,
    PersonaConfig,
    RLMConfig,
    ResilienceConfig,
    StreamingConfig,
    TelemetryConfig,
    TranslationConfig,
)


# Sub-config classes (new pattern) for direct import
SUB_CONFIG_CLASSES = (
    HookConfig,
    TrackingConfig,
    KnowledgeMoundConfig,
    MemoryCoordinationConfig,
    PerformanceFeedbackConfig,
    AuditTrailConfig,
    MLIntegrationConfig,
    RLMCognitiveConfig,
    CheckpointMemoryConfig,
    CrossPollinationConfig,
    KMBidirectionalConfig,
    TranslationSubConfig,
    SupermemorySubConfig,
    BudgetSubConfig,
)


__all__ = [
    "ArenaConfig",
    "ArenaConfigBuilder",
    # Sub-config classes (new strategy/builder pattern)
    "HookConfig",
    "TrackingConfig",
    "KnowledgeMoundConfig",
    "MemoryCoordinationConfig",
    "PerformanceFeedbackConfig",
    "AuditTrailConfig",
    "MLIntegrationConfig",
    "RLMCognitiveConfig",
    "CheckpointMemoryConfig",
    "CrossPollinationConfig",
    "KMBidirectionalConfig",
    "TranslationSubConfig",
    "SupermemorySubConfig",
    "BudgetSubConfig",
    "SUB_CONFIG_CLASSES",
    # Primary config classes (for Arena constructor refactoring)
    "DebateConfig",
    "AgentConfig",
    "MemoryConfig",
    "StreamingConfig",
    "ObservabilityConfig",
    # Legacy config classes
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
    # Config class collections
    "PRIMARY_CONFIG_CLASSES",
    "LEGACY_CONFIG_CLASSES",
    "ALL_CONFIG_CLASSES",
]
