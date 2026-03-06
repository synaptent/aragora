"""
Multi-agent debate orchestrator.

Implements the propose -> critique -> revise loop with configurable
debate protocols and consensus mechanisms.
"""

from __future__ import annotations
import asyncio
from collections import deque
from types import TracebackType
from typing import TYPE_CHECKING, Any
import warnings  # noqa: F401 - used for deprecation warnings in __init__

from aragora.core import Agent, Critique, DebateResult, Environment, Message, Vote
from aragora.debate.arena_config import (
    AgentConfig,
    DebateConfig,
    MemoryConfig,
    ObservabilityConfig,
    StreamingConfig,
)
from aragora.debate.arena_primary_configs import (
    EvolutionConfig,
    KnowledgeConfig,
    MLConfig,
    SupermemoryConfig,
)
from aragora.debate.arena_initializer import ArenaInitializer
from aragora.debate.arena_phases import create_phase_executor, init_phases
from aragora.debate.batch_loaders import debate_loader_context
from aragora.debate.context import DebateContext
from aragora.debate.hierarchy import HierarchyConfig
from aragora.debate.protocol import CircuitBreaker, DebateProtocol
from aragora.logging_config import get_logger as get_structured_logger
from aragora.observability.n1_detector import n1_detection_scope
from aragora.observability.tracing import add_span_attributes, get_tracer
from aragora.debate.performance_monitor import get_debate_monitor
from aragora.server.metrics import ACTIVE_DEBATES
from aragora.spectate.stream import SpectatorStream

# Extracted sibling modules
from aragora.debate.orchestrator_agents import (
    assign_hierarchy_roles as _agents_assign_hierarchy_roles,
)
from aragora.debate.orchestrator_checkpoints import (
    cleanup_checkpoints as _cp_cleanup_checkpoints,
    list_checkpoints as _cp_list_checkpoints,
    restore_from_checkpoint as _cp_restore_from_checkpoint,
    save_checkpoint as _cp_save_checkpoint,
)
from aragora.debate.orchestrator_config import merge_config_objects
from aragora.debate.orchestrator_delegates import ArenaDelegatesMixin
from aragora.debate.orchestrator_factory import (
    create as _factory_create,
    from_config as _factory_from_config,
    from_configs as _factory_from_configs,
)
from aragora.debate.orchestrator_init import (
    _KNOWLEDGE_MOUND_UNSET as _INIT_KNOWLEDGE_MOUND_UNSET,
    apply_core_components as _init_apply_core_components,
    apply_tracker_components as _init_apply_tracker_components,
    cleanup_convergence as _conv_cleanup_convergence,
    init_convergence as _conv_init_convergence,
    init_context_delegator as _context_init_context_delegator,
    init_event_bus as _participation_init_event_bus,
    init_prompt_context_builder as _context_init_prompt_context_builder,
    init_roles_and_stances as _roles_init_roles_and_stances,
    init_skills_and_propulsion as _init_skills_and_propulsion,
    init_termination_checker as _termination_init_termination_checker,
    init_user_participation as _participation_init_user_participation,
    reinit_convergence_for_debate as _conv_reinit_convergence_for_debate,
    resolve_knowledge_mound as _init_resolve_knowledge_mound,
    run_init_subsystems as _init_run_init_subsystems,
    store_post_tracker_config as _init_store_post_tracker_config,
)
from aragora.debate.orchestrator_setup import (
    init_caches as _lifecycle_init_caches,
    init_checkpoint_ops as _lifecycle_init_checkpoint_ops,
    init_event_emitter as _lifecycle_init_event_emitter,
    init_lifecycle_manager as _lifecycle_init_lifecycle_manager,
)
from aragora.debate.orchestrator_memory import (
    init_checkpoint_bridge as _mem_init_checkpoint_bridge,
    init_cross_subscriber_bridge as _mem_init_cross_subscriber_bridge,
)
from aragora.debate.orchestrator_runner import (
    cleanup_debate_resources as _runner_cleanup_debate_resources,
    execute_debate_phases as _runner_execute_debate_phases,
    handle_debate_completion as _runner_handle_debate_completion,
    initialize_debate_context as _runner_initialize_debate_context,
    record_debate_metrics as _runner_record_debate_metrics,
    setup_debate_infrastructure as _runner_setup_debate_infrastructure,
)
from aragora.debate.orchestrator_setup import (
    init_agent_hierarchy as _setup_init_agent_hierarchy,
    init_debate_strategy as _setup_init_debate_strategy,
    init_fabric_integration as _setup_init_fabric_integration,
    init_cost_tracking as _setup_init_cost_tracking,
    init_grounded_operations as _setup_init_grounded_operations,
    init_health_registry as _setup_init_health_registry,
    init_knowledge_ops as _setup_init_knowledge_ops,
    init_selection_feedback as _setup_init_selection_feedback,
    init_post_debate_workflow as _setup_init_post_debate_workflow,
    init_rlm_limiter as _setup_init_rlm_limiter,
    setup_agent_channels as _setup_agent_channels,
    teardown_agent_channels as _setup_teardown_agent_channels,
)
from aragora.debate.orchestrator_state import (
    extract_debate_domain as _state_extract_debate_domain,
    filter_responses_by_quality as _state_filter_responses_by_quality,
    get_continuum_context as _state_get_continuum_context,
    require_agents as _state_require_agents,
    select_debate_team as _state_select_debate_team,
    select_judge as _state_select_judge,
    should_terminate_early as _state_should_terminate_early,
    sync_prompt_builder_state as _state_sync_prompt_builder_state,
)

# Re-export for backward compatibility (tests import from orchestrator)
from aragora.debate.orchestrator_setup import (  # noqa: F401
    compute_domain_from_task as _compute_domain_from_task,
)

# Structured logger for all debate events (JSON-formatted in production)
logger = get_structured_logger(__name__)

# Sentinel for distinguishing "not provided" from explicit None
_KNOWLEDGE_MOUND_UNSET = _INIT_KNOWLEDGE_MOUND_UNSET

# TYPE_CHECKING imports for type hints without runtime import overhead
if TYPE_CHECKING:
    from aragora.debate.checkpoint_manager import CheckpointManager
    from aragora.debate.checkpoint_ops import CheckpointOperations
    from aragora.debate.context_gatherer import ContextGatherer
    from aragora.debate.event_emission import EventEmitter as _EventEmitter
    from aragora.debate.lifecycle_manager import LifecycleManager
    from aragora.debate.memory_manager import MemoryManager
    from aragora.debate.state_cache import DebateStateCache
    from aragora.debate.phases import (
        AnalyticsPhase,
        ConsensusPhase,
        ContextInitializer,
        DebateRoundsPhase,
        FeedbackPhase,
        ProposalPhase,
        VotingPhase,
    )
    from aragora.debate.prompt_builder import PromptBuilder
    from aragora.debate.revalidation_scheduler import RevalidationScheduler
    from aragora.debate.strategy import DebateStrategy
    from aragora.memory.consensus import ConsensusMemory
    from aragora.memory.continuum import ContinuumMemory
    from aragora.ml.delegation import MLDelegationStrategy
    from aragora.ranking.elo import EloSystem
    from aragora.reasoning.citations import CitationExtractor
    from aragora.reasoning.evidence_grounding import EvidenceGrounder
    from aragora.rlm.cognitive_limiter import RLMCognitiveLoadLimiter
    from aragora.types.protocols import EventEmitterProtocol
    from aragora.workflow.engine import Workflow


class Arena(ArenaDelegatesMixin):
    """
    Orchestrates multi-agent debates.

    The Arena manages the flow of a debate:
    1. Proposers generate initial proposals
    2. Critics critique each proposal
    3. Proposers revise based on critique
    4. Repeat for configured rounds
    5. Consensus mechanism selects final answer

    Configuration Patterns
    ----------------------
    Arena supports two configuration patterns:

    1. **Config Objects (Recommended)**::

        arena = Arena(
            environment=env,
            agents=agents,
            debate_config=DebateConfig(rounds=5, consensus_threshold=0.8),
            agent_config=AgentConfig(use_airlock=True),
        )

    2. **Individual Parameters (Legacy)**::

        arena = Arena(environment=env, agents=agents, protocol=protocol)

    Factory Methods: ``Arena.from_configs()`` (preferred), ``Arena.from_config()``
    """

    # Phase class attributes (initialized by init_phases)
    voting_phase: VotingPhase
    citation_extractor: CitationExtractor | None
    evidence_grounder: EvidenceGrounder
    prompt_builder: PromptBuilder
    memory_manager: MemoryManager
    context_gatherer: ContextGatherer
    context_initializer: ContextInitializer
    proposal_phase: ProposalPhase
    debate_rounds_phase: DebateRoundsPhase
    consensus_phase: ConsensusPhase
    analytics_phase: AnalyticsPhase
    feedback_phase: FeedbackPhase

    # Lifecycle/cache attributes (initialized by orchestrator_lifecycle helpers)
    _cache: DebateStateCache
    _lifecycle: LifecycleManager
    _event_emitter: _EventEmitter
    _checkpoint_ops: CheckpointOperations

    # Convergence attributes (initialized by orchestrator_convergence.init_convergence)
    convergence_detector: Any | None
    _convergence_debate_id: str | None
    _previous_round_responses: dict[str, str]

    # Role attributes (initialized by orchestrator_roles.init_roles_and_stances)
    roles_manager: Any
    role_rotator: Any
    role_matcher: Any
    current_role_assignments: Any

    # Core component attributes (initialized by orchestrator_init.apply_core_components)
    env: Any
    agents: list[Any]
    protocol: Any
    memory: Any
    hooks: dict[str, Any]
    hook_manager: Any
    event_emitter: Any
    spectator: Any
    debate_embeddings: Any
    insight_store: Any
    recorder: Any
    agent_weights: dict[str, float]
    loop_id: str
    strict_loop_scoping: bool
    circuit_breaker: Any
    agent_pool: Any
    immune_system: Any
    chaos_director: Any
    performance_monitor: Any
    prompt_evolver: Any
    autonomic: Any
    initial_messages: list[Any]
    trending_topic: Any
    pulse_manager: Any
    auto_fetch_trending: bool
    population_manager: Any
    auto_evolve: bool
    breeding_threshold: float
    evidence_collector: Any
    breakpoint_manager: Any
    agent_selector: Any
    use_performance_selection: bool
    checkpoint_manager: Any
    org_id: str
    user_id: str
    _budget_coordinator: Any
    extensions: Any
    cartographer: Any
    event_bridge: Any
    _event_bus: Any
    enable_ml_delegation: bool
    ml_delegation_weight: float
    enable_quality_gates: bool
    quality_gate_threshold: float
    enable_consensus_estimation: bool
    consensus_early_termination_threshold: float
    _ml_delegation_strategy: Any
    _ml_quality_gate: Any
    _ml_consensus_estimator: Any

    # Tracker component attributes (initialized by orchestrator_init.apply_tracker_components)
    position_tracker: Any
    position_ledger: Any
    elo_system: Any
    persona_manager: Any
    dissent_retriever: Any
    consensus_memory: Any
    flip_detector: Any
    calibration_tracker: Any
    continuum_memory: Any
    relationship_tracker: Any
    moment_detector: Any
    tier_analytics_tracker: Any
    knowledge_mound: Any
    enable_knowledge_retrieval: bool
    enable_knowledge_ingestion: bool
    enable_knowledge_extraction: bool
    extraction_min_confidence: float
    enable_belief_guidance: bool
    _trackers: Any
    vertical: Any
    vertical_persona_manager: Any

    # Post-tracker config attributes (initialized by orchestrator_init.store_post_tracker_config)
    enable_auto_revalidation: bool
    revalidation_staleness_threshold: float
    revalidation_check_interval_seconds: int
    revalidation_scheduler: Any
    document_store: Any
    evidence_store: Any
    enable_supermemory: bool
    supermemory_adapter: Any
    supermemory_inject_on_start: bool
    supermemory_max_context_items: int
    supermemory_context_container_tag: str | None
    supermemory_sync_on_conclusion: bool
    supermemory_min_confidence_for_sync: float
    supermemory_outcome_container_tag: str | None
    supermemory_enable_privacy_filter: bool
    supermemory_enable_resilience: bool
    supermemory_enable_km_adapter: bool
    cross_debate_memory: Any
    enable_cross_debate_memory: bool

    # Skills and propulsion (initialized by orchestrator_init.init_skills_and_propulsion)
    skill_registry: Any
    enable_skills: bool
    propulsion_engine: Any
    enable_propulsion: bool

    # Setup attributes (initialized by orchestrator_setup helpers)
    _fabric: Any
    _fabric_config: Any
    enable_adaptive_rounds: bool
    debate_strategy: Any
    enable_post_debate_workflow: bool
    post_debate_workflow: Any
    post_debate_workflow_threshold: float
    post_debate_config: Any
    enable_agent_hierarchy: bool
    _hierarchy: Any
    _knowledge_ops: Any
    _km_coordinator: Any
    _km_adapters: Any
    knowledge_bridge_hub: Any
    rlm_compression_threshold: int
    rlm_max_recent_messages: int
    rlm_summary_level: str
    rlm_compression_round_threshold: int
    enable_auto_execution: bool
    auto_execution_mode: str
    auto_approval_mode: str
    auto_max_risk: str
    enable_unified_memory: bool
    enable_retention_gate: bool
    memory_gateway: Any
    enable_live_explainability: bool
    live_explainability_stream: Any
    enable_introspection: bool
    active_introspection_tracker: Any
    enable_sandbox_verification: bool
    enable_data_classification: bool

    # Selection feedback / cost / health (initialized by orchestrator_setup helpers)
    _selection_feedback_loop: Any
    _cost_tracker: Any
    _health_registry: Any

    def __init__(
        self,
        environment: Environment,
        agents: list[Agent],
        protocol: DebateProtocol | None = None,
        # Config Objects (Preferred)
        debate_config: DebateConfig | None = None,
        agent_config: AgentConfig | None = None,
        memory_config: MemoryConfig | None = None,
        streaming_config: StreamingConfig | None = None,
        observability_config: ObservabilityConfig | None = None,
        # Focused Config Objects (override individual params in their group)
        knowledge_config: KnowledgeConfig | None = None,
        supermemory_config: SupermemoryConfig | None = None,
        evolution_config: EvolutionConfig | None = None,
        ml_config: MLConfig | None = None,
        # Individual Parameters (Legacy)
        memory: Any = None,
        event_hooks: dict[str, Any] | None = None,
        hook_manager: Any = None,
        event_emitter: EventEmitterProtocol | None = None,
        spectator: SpectatorStream | None = None,
        debate_embeddings: Any = None,
        insight_store: Any = None,
        recorder: Any = None,
        agent_weights: dict[str, float] | None = None,
        position_tracker: Any = None,
        position_ledger: Any = None,
        enable_position_ledger: bool = False,
        elo_system: EloSystem | None = None,
        persona_manager: Any = None,
        vertical: str | None = None,
        vertical_persona_manager: Any = None,
        auto_detect_vertical: bool = True,
        dissent_retriever: Any = None,
        consensus_memory: ConsensusMemory | None = None,
        flip_detector: Any = None,
        calibration_tracker: Any = None,
        continuum_memory: ContinuumMemory | None = None,
        relationship_tracker: Any = None,
        moment_detector: Any = None,
        tier_analytics_tracker: Any = None,
        knowledge_mound: Any = _KNOWLEDGE_MOUND_UNSET,
        auto_create_knowledge_mound: bool = True,
        enable_knowledge_retrieval: bool = True,
        enable_knowledge_ingestion: bool = True,
        enable_knowledge_extraction: bool = False,
        extraction_min_confidence: float = 0.3,
        enable_supermemory: bool = False,
        supermemory_adapter: Any = None,
        supermemory_inject_on_start: bool = True,
        supermemory_max_context_items: int = 10,
        supermemory_context_container_tag: str | None = None,
        supermemory_sync_on_conclusion: bool = True,
        supermemory_min_confidence_for_sync: float = 0.7,
        supermemory_outcome_container_tag: str | None = None,
        supermemory_enable_privacy_filter: bool = True,
        supermemory_enable_resilience: bool = True,
        supermemory_enable_km_adapter: bool = False,
        enable_belief_guidance: bool = True,
        enable_outcome_context: bool = True,
        enable_auto_revalidation: bool = False,
        revalidation_staleness_threshold: float = 0.8,
        revalidation_check_interval_seconds: int = 3600,
        revalidation_scheduler: RevalidationScheduler | None = None,
        loop_id: str = "",
        strict_loop_scoping: bool = False,
        circuit_breaker: CircuitBreaker | None = None,
        initial_messages: list[Message] | None = None,
        trending_topic: Any = None,
        pulse_manager: Any = None,
        auto_fetch_trending: bool = False,
        population_manager: Any = None,
        auto_evolve: bool = False,
        breeding_threshold: float = 0.8,
        evidence_collector: Any = None,
        document_store: Any | None = None,
        evidence_store: Any | None = None,
        skill_registry: Any = None,
        enable_skills: bool = False,
        propulsion_engine: Any = None,
        enable_propulsion: bool = False,
        breakpoint_manager: Any = None,
        checkpoint_manager: CheckpointManager | None = None,
        enable_checkpointing: bool = True,
        codebase_path: str | None = None,
        enable_codebase_grounding: bool = False,
        codebase_persist_to_km: bool = False,
        performance_monitor: Any = None,
        enable_performance_monitor: bool = True,
        enable_telemetry: bool = False,
        use_airlock: bool = False,
        airlock_config: Any = None,
        agent_selector: Any = None,
        use_performance_selection: bool = False,
        enable_agent_hierarchy: bool = True,
        hierarchy_config: HierarchyConfig | None = None,
        prompt_evolver: Any = None,
        enable_prompt_evolution: bool = False,
        org_id: str = "",
        user_id: str = "",
        usage_tracker: Any = None,
        broadcast_pipeline: Any = None,
        auto_broadcast: bool = False,
        broadcast_min_confidence: float = 0.8,
        training_exporter: Any = None,
        auto_export_training: bool = False,
        training_export_min_confidence: float = 0.75,
        enable_ml_delegation: bool = True,
        ml_delegation_strategy: MLDelegationStrategy | None = None,
        ml_delegation_weight: float = 0.3,
        enable_quality_gates: bool = True,
        quality_gate_threshold: float = 0.6,
        enable_consensus_estimation: bool = True,
        consensus_early_termination_threshold: float = 0.85,
        use_rlm_limiter: bool = True,
        rlm_limiter: RLMCognitiveLoadLimiter | None = None,
        rlm_compression_threshold: int = 3000,
        rlm_max_recent_messages: int = 5,
        rlm_summary_level: str = "SUMMARY",
        rlm_compression_round_threshold: int = 3,
        enable_adaptive_rounds: bool = False,
        debate_strategy: DebateStrategy | None = None,
        cross_debate_memory: Any = None,
        enable_cross_debate_memory: bool = True,
        post_debate_workflow: Workflow | None = None,
        enable_post_debate_workflow: bool = False,
        post_debate_workflow_threshold: float = 0.7,
        post_debate_config: Any | None = None,
        disable_post_debate_pipeline: bool = False,
        # Result routing to originating chat channels
        enable_result_routing: bool = False,
        fabric: Any = None,
        fabric_config: Any = None,
        mode_sequence: list[str] | None = None,
        enable_auto_execution: bool = False,
        auto_execution_mode: str = "workflow",
        auto_approval_mode: str = "risk_based",
        auto_max_risk: str = "low",
        # Meta-Learning
        meta_learner: Any = None,
        enable_meta_learning: bool = False,
        # Unified Memory Gateway
        enable_unified_memory: bool = False,
        enable_retention_gate: bool = False,
        # Live explainability stream (real-time factor decomposition)
        enable_live_explainability: bool = False,
        # Sandbox verification of code proposals
        enable_sandbox_verification: bool = False,
    ) -> None:
        """Initialize the Arena with environment, agents, and optional subsystems."""
        self.mode_sequence = mode_sequence
        knowledge_mound_param_provided = knowledge_mound is not _KNOWLEDGE_MOUND_UNSET
        knowledge_mound_param_none = knowledge_mound is None

        # Merge config objects (take precedence over individual params)
        cfg = merge_config_objects(
            debate_config=debate_config,
            agent_config=agent_config,
            memory_config=memory_config,
            streaming_config=streaming_config,
            observability_config=observability_config,
            knowledge_config=knowledge_config,
            supermemory_config=supermemory_config,
            evolution_config=evolution_config,
            ml_config=ml_config,
            protocol=protocol,
            enable_adaptive_rounds=enable_adaptive_rounds,
            debate_strategy=debate_strategy,
            enable_agent_hierarchy=enable_agent_hierarchy,
            hierarchy_config=hierarchy_config,
            agent_weights=agent_weights,
            agent_selector=agent_selector,
            use_performance_selection=use_performance_selection,
            circuit_breaker=circuit_breaker,
            use_airlock=use_airlock,
            airlock_config=airlock_config,
            position_tracker=position_tracker,
            position_ledger=position_ledger,
            enable_position_ledger=enable_position_ledger,
            elo_system=elo_system,
            calibration_tracker=calibration_tracker,
            relationship_tracker=relationship_tracker,
            persona_manager=persona_manager,
            vertical=vertical,
            vertical_persona_manager=vertical_persona_manager,
            auto_detect_vertical=auto_detect_vertical,
            fabric=fabric,
            fabric_config=fabric_config,
            memory=memory,
            continuum_memory=continuum_memory,
            consensus_memory=consensus_memory,
            debate_embeddings=debate_embeddings,
            insight_store=insight_store,
            dissent_retriever=dissent_retriever,
            flip_detector=flip_detector,
            moment_detector=moment_detector,
            tier_analytics_tracker=tier_analytics_tracker,
            cross_debate_memory=cross_debate_memory,
            enable_cross_debate_memory=enable_cross_debate_memory,
            knowledge_mound=knowledge_mound,
            auto_create_knowledge_mound=auto_create_knowledge_mound,
            enable_knowledge_retrieval=enable_knowledge_retrieval,
            enable_knowledge_ingestion=enable_knowledge_ingestion,
            enable_knowledge_extraction=enable_knowledge_extraction,
            extraction_min_confidence=extraction_min_confidence,
            enable_supermemory=enable_supermemory,
            supermemory_adapter=supermemory_adapter,
            supermemory_inject_on_start=supermemory_inject_on_start,
            supermemory_max_context_items=supermemory_max_context_items,
            supermemory_context_container_tag=supermemory_context_container_tag,
            supermemory_sync_on_conclusion=supermemory_sync_on_conclusion,
            supermemory_min_confidence_for_sync=supermemory_min_confidence_for_sync,
            supermemory_outcome_container_tag=supermemory_outcome_container_tag,
            supermemory_enable_privacy_filter=supermemory_enable_privacy_filter,
            supermemory_enable_resilience=supermemory_enable_resilience,
            supermemory_enable_km_adapter=supermemory_enable_km_adapter,
            enable_belief_guidance=enable_belief_guidance,
            enable_outcome_context=enable_outcome_context,
            enable_auto_revalidation=enable_auto_revalidation,
            revalidation_staleness_threshold=revalidation_staleness_threshold,
            revalidation_check_interval_seconds=revalidation_check_interval_seconds,
            revalidation_scheduler=revalidation_scheduler,
            use_rlm_limiter=use_rlm_limiter,
            rlm_limiter=rlm_limiter,
            rlm_compression_threshold=rlm_compression_threshold,
            rlm_max_recent_messages=rlm_max_recent_messages,
            rlm_summary_level=rlm_summary_level,
            rlm_compression_round_threshold=rlm_compression_round_threshold,
            checkpoint_manager=checkpoint_manager,
            enable_checkpointing=enable_checkpointing,
            codebase_path=codebase_path,
            enable_codebase_grounding=enable_codebase_grounding,
            codebase_persist_to_km=codebase_persist_to_km,
            event_hooks=event_hooks,
            hook_manager=hook_manager,
            event_emitter=event_emitter,
            spectator=spectator,
            recorder=recorder,
            loop_id=loop_id,
            strict_loop_scoping=strict_loop_scoping,
            skill_registry=skill_registry,
            enable_skills=enable_skills,
            propulsion_engine=propulsion_engine,
            enable_propulsion=enable_propulsion,
            performance_monitor=performance_monitor,
            enable_performance_monitor=enable_performance_monitor,
            enable_telemetry=enable_telemetry,
            prompt_evolver=prompt_evolver,
            enable_prompt_evolution=enable_prompt_evolution,
            breakpoint_manager=breakpoint_manager,
            trending_topic=trending_topic,
            pulse_manager=pulse_manager,
            auto_fetch_trending=auto_fetch_trending,
            population_manager=population_manager,
            auto_evolve=auto_evolve,
            breeding_threshold=breeding_threshold,
            evidence_collector=evidence_collector,
            org_id=org_id,
            user_id=user_id,
            usage_tracker=usage_tracker,
            broadcast_pipeline=broadcast_pipeline,
            auto_broadcast=auto_broadcast,
            broadcast_min_confidence=broadcast_min_confidence,
            training_exporter=training_exporter,
            auto_export_training=auto_export_training,
            training_export_min_confidence=training_export_min_confidence,
            enable_ml_delegation=enable_ml_delegation,
            ml_delegation_strategy=ml_delegation_strategy,
            ml_delegation_weight=ml_delegation_weight,
            enable_quality_gates=enable_quality_gates,
            quality_gate_threshold=quality_gate_threshold,
            enable_consensus_estimation=enable_consensus_estimation,
            consensus_early_termination_threshold=consensus_early_termination_threshold,
            post_debate_workflow=post_debate_workflow,
            enable_post_debate_workflow=enable_post_debate_workflow,
            post_debate_workflow_threshold=post_debate_workflow_threshold,
            initial_messages=initial_messages,
            enable_auto_execution=enable_auto_execution,
            auto_execution_mode=auto_execution_mode,
            auto_approval_mode=auto_approval_mode,
            auto_max_risk=auto_max_risk,
            enable_unified_memory=enable_unified_memory,
            enable_retention_gate=enable_retention_gate,
            enable_live_explainability=enable_live_explainability,
            enable_sandbox_verification=enable_sandbox_verification,
        )

        # Handle fabric integration - get agents from fabric pool if configured
        agents = _setup_init_fabric_integration(self, cfg.fabric, cfg.fabric_config, agents)
        if not agents:
            raise ValueError("Must specify either 'agents' or both 'fabric' and 'fabric_config'")

        # Initialize core configuration via ArenaInitializer
        initializer = ArenaInitializer(broadcast_callback=self._broadcast_health_event)
        core = initializer.init_core(
            environment=environment,
            agents=agents,
            protocol=protocol,
            memory=cfg.memory,
            event_hooks=cfg.event_hooks,
            hook_manager=cfg.hook_manager,
            event_emitter=cfg.event_emitter,
            spectator=cfg.spectator,
            debate_embeddings=cfg.debate_embeddings,
            insight_store=cfg.insight_store,
            recorder=cfg.recorder,
            agent_weights=cfg.agent_weights,
            loop_id=cfg.loop_id,
            strict_loop_scoping=cfg.strict_loop_scoping,
            circuit_breaker=cfg.circuit_breaker,
            initial_messages=cfg.initial_messages,
            trending_topic=cfg.trending_topic,
            pulse_manager=cfg.pulse_manager,
            auto_fetch_trending=cfg.auto_fetch_trending,
            population_manager=cfg.population_manager,
            auto_evolve=cfg.auto_evolve,
            breeding_threshold=cfg.breeding_threshold,
            evidence_collector=cfg.evidence_collector,
            breakpoint_manager=cfg.breakpoint_manager,
            checkpoint_manager=cfg.checkpoint_manager,
            enable_checkpointing=cfg.enable_checkpointing,
            performance_monitor=cfg.performance_monitor,
            enable_performance_monitor=cfg.enable_performance_monitor,
            enable_telemetry=cfg.enable_telemetry,
            use_airlock=cfg.use_airlock,
            airlock_config=cfg.airlock_config,
            agent_selector=cfg.agent_selector,
            use_performance_selection=cfg.use_performance_selection,
            prompt_evolver=cfg.prompt_evolver,
            enable_prompt_evolution=cfg.enable_prompt_evolution,
            power_sampling_config=cfg.power_sampling_config,
            org_id=cfg.org_id,
            user_id=cfg.user_id,
            usage_tracker=cfg.usage_tracker,
            broadcast_pipeline=cfg.broadcast_pipeline,
            auto_broadcast=cfg.auto_broadcast,
            broadcast_min_confidence=cfg.broadcast_min_confidence,
            training_exporter=cfg.training_exporter,
            auto_export_training=cfg.auto_export_training,
            training_export_min_confidence=cfg.training_export_min_confidence,
            enable_ml_delegation=cfg.enable_ml_delegation,
            ml_delegation_strategy=cfg.ml_delegation_strategy,
            ml_delegation_weight=cfg.ml_delegation_weight,
            enable_quality_gates=cfg.enable_quality_gates,
            quality_gate_threshold=cfg.quality_gate_threshold,
            enable_consensus_estimation=cfg.enable_consensus_estimation,
            consensus_early_termination_threshold=cfg.consensus_early_termination_threshold,
            enable_cartographer=getattr(self, "enable_cartographer", True),
        )
        # Pass autotune_config to core for BudgetCoordinator integration
        core.autotune_config = getattr(cfg, "autotune_config", None)
        _init_apply_core_components(self, core)

        # Propagate thinking_budget from protocol to Anthropic agents
        if self.protocol.thinking_budget:
            for agent in self.agents:
                if hasattr(agent, "thinking_budget") and agent.thinking_budget is None:
                    agent.thinking_budget = self.protocol.thinking_budget

        # Codebase grounding (opt-in, stored directly on Arena)
        self.codebase_path = cfg.codebase_path
        self.enable_codebase_grounding = cfg.enable_codebase_grounding
        self.codebase_persist_to_km = cfg.codebase_persist_to_km

        # Channel integration (initialized per debate run)
        self._channel_integration = None

        # Skills and propulsion (delegates to orchestrator_init)
        _init_skills_and_propulsion(self, cfg)

        # Auto-create Knowledge Mound if not provided (delegates to orchestrator_init)
        km, km_auto = _init_resolve_knowledge_mound(
            cfg, knowledge_mound_param_provided, knowledge_mound_param_none
        )

        # Initialize tracking subsystems
        trackers = initializer.init_trackers(
            protocol=self.protocol,
            loop_id=self.loop_id,
            agent_pool=self.agent_pool,
            position_tracker=cfg.position_tracker,
            position_ledger=cfg.position_ledger,
            enable_position_ledger=cfg.enable_position_ledger,
            elo_system=cfg.elo_system,
            persona_manager=cfg.persona_manager,
            dissent_retriever=cfg.dissent_retriever,
            consensus_memory=cfg.consensus_memory,
            flip_detector=cfg.flip_detector,
            calibration_tracker=cfg.calibration_tracker,
            continuum_memory=cfg.continuum_memory,
            relationship_tracker=cfg.relationship_tracker,
            moment_detector=cfg.moment_detector,
            tier_analytics_tracker=cfg.tier_analytics_tracker,
            knowledge_mound=km,
            auto_create_knowledge_mound=km_auto,
            enable_knowledge_retrieval=cfg.enable_knowledge_retrieval,
            enable_knowledge_ingestion=cfg.enable_knowledge_ingestion,
            enable_knowledge_extraction=cfg.enable_knowledge_extraction,
            extraction_min_confidence=cfg.extraction_min_confidence,
            enable_belief_guidance=cfg.enable_belief_guidance,
            enable_outcome_context=getattr(cfg, "enable_outcome_context", True),
            vertical=cfg.vertical,
            vertical_persona_manager=cfg.vertical_persona_manager,
            auto_detect_vertical=cfg.auto_detect_vertical,
            task=environment.task,
        )
        _init_apply_tracker_components(self, trackers)

        # Store additional config flags
        _init_store_post_tracker_config(
            self, cfg, document_store=document_store, evidence_store=evidence_store
        )

        # Debate strategy, post-debate workflow, hierarchy, RLM limiter
        _setup_init_debate_strategy(self, cfg.enable_adaptive_rounds, cfg.debate_strategy)
        _setup_init_post_debate_workflow(
            self,
            cfg.enable_post_debate_workflow,
            cfg.post_debate_workflow,
            cfg.post_debate_workflow_threshold,
        )
        # Store post-debate coordinator config (opt-in pipeline)
        self.post_debate_config = post_debate_config
        self.disable_post_debate_pipeline = disable_post_debate_pipeline
        # Result routing to originating chat channels
        self.enable_result_routing = enable_result_routing
        _setup_init_agent_hierarchy(self, cfg.enable_agent_hierarchy, cfg.hierarchy_config)
        _setup_init_rlm_limiter(
            self,
            use_rlm_limiter=cfg.use_rlm_limiter,
            rlm_limiter=cfg.rlm_limiter,
            rlm_compression_threshold=cfg.rlm_compression_threshold,
            rlm_max_recent_messages=cfg.rlm_max_recent_messages,
            rlm_summary_level=cfg.rlm_summary_level,
            rlm_compression_round_threshold=cfg.rlm_compression_round_threshold,
        )

        # Meta-Learning: lazy-init MetaLearner when enabled
        if meta_learner is not None:
            self.meta_learner = meta_learner
        elif enable_meta_learning:
            try:
                from aragora.learning.meta import MetaLearner as _MetaLearner

                self.meta_learner = _MetaLearner()
            except ImportError:
                self.meta_learner = None
        else:
            self.meta_learner = None

        # Run remaining subsystem initialization sequence
        _init_run_init_subsystems(self)

    # =========================================================================
    # Factory Methods (delegates to orchestrator_factory)
    # =========================================================================

    @classmethod
    def from_config(cls, environment, agents, protocol=None, config=None) -> "Arena":
        """Create an Arena from an ArenaConfig for cleaner dependency injection."""
        return _factory_from_config(cls, environment, agents, protocol, config)

    @classmethod
    def from_configs(cls, environment, agents, protocol=None, **kwargs) -> "Arena":
        """Create an Arena from grouped config objects."""
        return _factory_from_configs(cls, environment, agents, protocol, **kwargs)

    @classmethod
    def create(cls, environment, agents, protocol=None, **kwargs) -> "Arena":
        """Create an Arena with a clean, consolidated interface."""
        return _factory_create(cls, environment, agents, protocol, **kwargs)

    # =========================================================================
    # Initialization Helpers (thin delegates to extracted modules)
    # =========================================================================

    def _broadcast_health_event(self, event: dict[str, Any]) -> None:
        """Broadcast health events. Delegates to EventEmitter."""
        self._event_emitter.broadcast_health_event(event)

    def _init_user_participation(self) -> None:
        _participation_init_user_participation(self)

    def _init_event_bus(self) -> None:
        _participation_init_event_bus(self)

    @property
    def event_bus(self) -> Any:
        """Public accessor for the debate EventBus.

        Returns the :class:`EventBus` instance used for pub/sub event handling
        during debates.  Server integrations (e.g. TTS bridge) use this to
        subscribe to live debate events such as ``agent_message``.

        Returns ``None`` before the bus has been initialised (i.e. before
        ``__init__`` completes).
        """
        return self._event_bus

    @event_bus.setter
    def event_bus(self, value: Any) -> None:
        self._event_bus = value

    @property
    def user_votes(self) -> deque[dict[str, Any]]:
        return self.audience_manager._votes

    @property
    def user_suggestions(self) -> deque[dict[str, Any]]:
        return self.audience_manager._suggestions

    def _init_roles_and_stances(self) -> None:
        _roles_init_roles_and_stances(self)

    def _init_convergence(self, debate_id: str | None = None) -> None:
        _conv_init_convergence(self, debate_id)

    def _reinit_convergence_for_debate(self, debate_id: str) -> None:
        _conv_reinit_convergence_for_debate(self, debate_id)

    def _cleanup_convergence_cache(self) -> None:
        _conv_cleanup_convergence(self)

    def _init_caches(self) -> None:
        _lifecycle_init_caches(self)

    def _init_lifecycle_manager(self) -> None:
        _lifecycle_init_lifecycle_manager(self)

    def _init_event_emitter(self) -> None:
        _lifecycle_init_event_emitter(self)

    def _init_checkpoint_ops(self) -> None:
        _lifecycle_init_checkpoint_ops(self)

    def _init_checkpoint_bridge(self) -> None:
        self.molecule_orchestrator, self.checkpoint_bridge = _mem_init_checkpoint_bridge(
            self.protocol, self.checkpoint_manager
        )

    def _init_grounded_operations(self) -> None:
        _setup_init_grounded_operations(self)

    def _init_agent_hierarchy(
        self,
        enable_agent_hierarchy: bool,
        hierarchy_config: HierarchyConfig | None,
    ) -> None:
        _setup_init_agent_hierarchy(self, enable_agent_hierarchy, hierarchy_config)

    def _assign_hierarchy_roles(self, ctx: DebateContext, task_type: str | None = None) -> None:
        _agents_assign_hierarchy_roles(ctx, self.enable_agent_hierarchy, self._hierarchy, task_type)

    def _init_rlm_limiter(self, **kwargs: Any) -> None:
        _setup_init_rlm_limiter(self, **kwargs)

    def _init_knowledge_ops(self) -> None:
        _setup_init_knowledge_ops(self)

    def _init_selection_feedback(self) -> None:
        _setup_init_selection_feedback(self)

    def _init_cost_tracking(self) -> None:
        _setup_init_cost_tracking(self)

    def _init_health_registry(self) -> None:
        _setup_init_health_registry(self)

    def _init_prompt_context_builder(self) -> None:
        _context_init_prompt_context_builder(self)

    def _init_context_delegator(self) -> None:
        _context_init_context_delegator(self)

    def _init_phases(self) -> None:
        init_phases(self)
        self.phase_executor = create_phase_executor(self)
        if hasattr(self, "_grounded_ops") and self._grounded_ops:
            self._grounded_ops.evidence_grounder = self.evidence_grounder
        if hasattr(self, "_checkpoint_ops") and self._checkpoint_ops:
            self._checkpoint_ops.memory_manager = self.memory_manager

    def _init_termination_checker(self) -> None:
        _termination_init_termination_checker(self)

    def _init_cross_subscriber_bridge(self) -> None:
        self._cross_subscriber_bridge = _mem_init_cross_subscriber_bridge(self.event_bus)

    # =========================================================================
    # Core Instance Helpers (delegates to orchestrator_state)
    # =========================================================================

    def _require_agents(self) -> list[Agent]:
        return _state_require_agents(self)

    def _sync_prompt_builder_state(self) -> None:
        _state_sync_prompt_builder_state(self)

    def _get_continuum_context(self) -> str:
        return _state_get_continuum_context(self)

    def _extract_debate_domain(self) -> str:
        return _state_extract_debate_domain(self)

    def _select_debate_team(self, requested_agents: list[Agent]) -> list[Agent]:
        return _state_select_debate_team(self, requested_agents)

    def _filter_responses_by_quality(
        self, responses: list[tuple[str, str]], context: str = ""
    ) -> list[tuple[str, str]]:
        return _state_filter_responses_by_quality(self, responses, context)

    def _should_terminate_early(self, responses: list[tuple[str, str]], current_round: int) -> bool:
        return _state_should_terminate_early(self, responses, current_round)

    async def _select_judge(self, proposals: dict[str, str], context: list[Message]) -> Agent:
        return await _state_select_judge(self, proposals, context)

    # =========================================================================
    # Public Checkpoint API
    # =========================================================================

    async def save_checkpoint(
        self,
        debate_id: str,
        phase: str = "manual",
        messages: list[Message] | None = None,
        critiques: list[Critique] | None = None,
        votes: list[Vote] | None = None,
        current_round: int = 0,
        current_consensus: str | None = None,
    ) -> str | None:
        return await _cp_save_checkpoint(
            checkpoint_manager=self.checkpoint_manager,
            debate_id=debate_id,
            env=self.env,
            protocol=self.protocol,
            agents=self.agents,
            phase=phase,
            messages=messages,
            critiques=critiques,
            votes=votes,
            current_round=current_round,
            current_consensus=current_consensus,
        )

    async def restore_from_checkpoint(
        self,
        checkpoint_id: str,
        resumed_by: str = "system",
    ) -> DebateContext | None:
        return await _cp_restore_from_checkpoint(
            checkpoint_manager=self.checkpoint_manager,
            checkpoint_id=checkpoint_id,
            env=self.env,
            agents=self.agents,
            domain=self._extract_debate_domain() if hasattr(self, "_extract_debate_domain") else "",
            hook_manager=self.hook_manager if hasattr(self, "hook_manager") else None,
            org_id=self.org_id if hasattr(self, "org_id") else "",
            resumed_by=resumed_by,
        )

    async def list_checkpoints(
        self,
        debate_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return await _cp_list_checkpoints(
            checkpoint_manager=self.checkpoint_manager,
            debate_id=debate_id,
            limit=limit,
        )

    async def cleanup_checkpoints(self, debate_id: str, keep_latest: int = 1) -> int:
        return await _cp_cleanup_checkpoints(
            checkpoint_manager=self.checkpoint_manager,
            debate_id=debate_id,
            keep_latest=keep_latest,
        )

    # =========================================================================
    # Async Context Manager & Lifecycle
    # =========================================================================

    async def __aenter__(self) -> Arena:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._cleanup()

    def _track_circuit_breaker_metrics(self) -> None:
        self._lifecycle.track_circuit_breaker_metrics()

    def _log_phase_failures(self, execution_result: Any) -> None:
        self._lifecycle.log_phase_failures(execution_result)

    async def _cleanup(self) -> None:
        await self._lifecycle.cleanup()
        await self._teardown_agent_channels()
        if hasattr(self, "context_gatherer") and self.context_gatherer:
            self.context_gatherer.clear_cache()
        self._cleanup_convergence_cache()
        # Close shared HTTP connector to prevent resource leak warnings
        try:
            from aragora.agents.api_agents.common import close_shared_connector

            await close_shared_connector()
        except (ImportError, RuntimeError, OSError):
            pass

    async def _setup_agent_channels(self, ctx: DebateContext, debate_id: str) -> None:
        await _setup_agent_channels(self, ctx, debate_id)

    async def _teardown_agent_channels(self) -> None:
        await _setup_teardown_agent_channels(self)

    # =========================================================================
    # Debate Execution
    # =========================================================================

    async def run(self, correlation_id: str = "") -> DebateResult:
        """Run the full debate and return results."""
        try:
            if self.protocol.timeout_seconds > 0:
                try:
                    return await asyncio.wait_for(
                        self._run_inner(correlation_id=correlation_id),
                        timeout=self.protocol.timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "debate_timeout timeout_seconds=%s", self.protocol.timeout_seconds
                    )
                    return DebateResult(
                        task=self.env.task,
                        messages=getattr(self, "_partial_messages", []),
                        critiques=getattr(self, "_partial_critiques", []),
                        votes=[],
                        dissenting_views=[],
                        rounds_used=getattr(self, "_partial_rounds", 0),
                    )
            return await self._run_inner(correlation_id=correlation_id)
        finally:
            # Close shared HTTP connector to prevent resource leak warnings
            try:
                from aragora.agents.api_agents.common import close_shared_connector

                await close_shared_connector()
            except (ImportError, RuntimeError, OSError):
                pass

    async def _run_inner(self, correlation_id: str = "") -> DebateResult:
        """Internal debate execution orchestrator coordinating all phases."""
        state = await _runner_initialize_debate_context(self, correlation_id)

        # Content moderation: block spam/low-quality prompts before burning API tokens
        if self.protocol.enable_content_moderation:
            try:
                from aragora.moderation import check_debate_content, ContentModerationError

                result = await check_debate_content(self.env.task, context=self.env.context)
                if result.should_block:
                    raise ContentModerationError(f"Debate content blocked: {result.verdict.value}")
            except ImportError:
                logger.warning("Content moderation enabled but aragora.moderation not available")
            except ContentModerationError:
                raise
            except (RuntimeError, ValueError, TypeError, AttributeError, OSError):
                logger.warning(
                    "Content moderation check failed, continuing without moderation",
                    exc_info=True,
                )

        await _runner_setup_debate_infrastructure(self, state)

        # Register debate with operator intervention manager for pause/resume
        try:
            from aragora.debate.operator_intervention import get_operator_manager

            _intervention_mgr = get_operator_manager()
            _intervention_mgr.register(
                state.debate_id,
                total_rounds=getattr(self.protocol, "rounds", 0),
            )
        except ImportError:
            _intervention_mgr = None
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Intervention manager registration skipped: %s", e)
            _intervention_mgr = None

        ACTIVE_DEBATES.inc()

        tracer = get_tracer()
        perf_monitor = get_debate_monitor()
        agent_names = [a.name for a in self.agents]

        with (
            tracer.start_as_current_span("debate") as span,
            perf_monitor.track_debate(state.debate_id, task=self.env.task, agent_names=agent_names),
            n1_detection_scope(f"debate_{state.debate_id}"),
            debate_loader_context(elo_system=self.elo_system) as loaders,
        ):
            state.ctx.data_loaders = loaders
            add_span_attributes(
                span,
                {
                    "debate.id": state.debate_id,
                    "debate.correlation_id": state.correlation_id,
                    "debate.domain": state.domain,
                    "debate.complexity": state.task_complexity.value,
                    "debate.agent_count": len(self.agents),
                    "debate.agents": ",".join(a.name for a in self.agents),
                    "debate.task_length": len(self.env.task),
                },
            )
            try:
                await _runner_execute_debate_phases(self, state, span)
            finally:
                _runner_record_debate_metrics(self, state, span)

        await _runner_handle_debate_completion(self, state)
        return await _runner_cleanup_debate_resources(self, state)
