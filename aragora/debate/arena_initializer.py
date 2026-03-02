"""
Arena initialization logic.

Extracts the _init_core and _init_trackers methods from Arena
to reduce orchestrator.py file size and improve testability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Union, cast
from collections.abc import Callable

from aragora.debate.agent_pool import AgentPool, AgentPoolConfig
from aragora.debate.chaos_theater import DramaLevel, get_chaos_director
from aragora.debate.extensions import ArenaExtensions
from aragora.debate.immune_system import get_immune_system
from aragora.debate.optional_imports import OptionalImports
from aragora.debate.protocol import CircuitBreaker, DebateProtocol
from aragora.debate.safety import resolve_auto_evolve, resolve_prompt_evolution
from aragora.debate.subsystem_coordinator import SubsystemCoordinator
from aragora.spectate.stream import SpectatorStream

if TYPE_CHECKING:
    from aragora.agents.airlock import AirlockProxy
    from aragora.core import Agent, Environment
    from aragora.debate.autonomic_executor import AutonomicExecutor
    from aragora.debate.event_bridge import EventEmitterBridge
    from aragora.evolution.evolver import PromptEvolver as PromptEvolverType
    from aragora.types.protocols import EventEmitterProtocol

logger = logging.getLogger(__name__)

# Type alias for agents that may be wrapped with airlock
AgentLike = Union["Agent", "AirlockProxy"]

# Optional evolution import for prompt self-improvement
# Declare PromptEvolver with proper type before the conditional import
_PromptEvolver: type[PromptEvolverType] | None = None
try:
    from aragora.evolution.evolver import PromptEvolver as _ImportedPromptEvolver

    _PromptEvolver = _ImportedPromptEvolver
    PROMPT_EVOLVER_AVAILABLE = True
except ImportError:
    PROMPT_EVOLVER_AVAILABLE = False

# Expose as PromptEvolver for backward compatibility
PromptEvolver = _PromptEvolver


@dataclass
class CoreComponents:
    """Container for core Arena components initialized by ArenaInitializer."""

    env: Environment
    agents: list[Agent]
    protocol: DebateProtocol
    memory: Any
    hooks: dict
    hook_manager: Any
    event_emitter: EventEmitterProtocol | None
    spectator: SpectatorStream
    debate_embeddings: Any
    insight_store: Any
    recorder: Any
    agent_weights: dict[str, float]
    loop_id: str
    strict_loop_scoping: bool
    circuit_breaker: CircuitBreaker
    agent_pool: AgentPool
    immune_system: Any
    chaos_director: Any
    performance_monitor: Any
    prompt_evolver: Any
    autonomic: AutonomicExecutor
    initial_messages: list
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
    extensions: ArenaExtensions
    cartographer: Any
    event_bridge: EventEmitterBridge
    # ML Integration
    enable_ml_delegation: bool
    ml_delegation_weight: float
    enable_quality_gates: bool
    quality_gate_threshold: float
    enable_consensus_estimation: bool
    consensus_early_termination_threshold: float
    enable_stability_detection: bool
    stability_threshold: float
    stability_min_rounds: int
    stability_agreement_threshold: float
    stability_conflict_confidence: float
    ml_delegation_strategy: Any = None
    ml_quality_gate: Any = None
    ml_consensus_estimator: Any = None
    autotune_config: Any = None


@dataclass
class TrackerComponents:
    """Container for tracking subsystems initialized by ArenaInitializer."""

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
    coordinator: SubsystemCoordinator
    # Vertical personas
    vertical: Any = None  # Vertical enum
    vertical_persona_manager: Any = None  # VerticalPersonaManager


class ArenaInitializer:
    """Handles Arena initialization to reduce orchestrator complexity."""

    def __init__(self, broadcast_callback: Callable[[dict], None]):
        """Initialize with broadcast callback for health events.

        Args:
            broadcast_callback: Function to broadcast health events to WebSocket
        """
        self._broadcast_callback = broadcast_callback

    def init_core(
        self,
        environment: Environment,
        agents: list[Agent],
        protocol: DebateProtocol | None,
        memory,
        event_hooks: dict | None,
        hook_manager,
        event_emitter: EventEmitterProtocol | None,
        spectator: SpectatorStream | None,
        debate_embeddings,
        insight_store,
        recorder,
        agent_weights: dict[str, float] | None,
        loop_id: str,
        strict_loop_scoping: bool,
        circuit_breaker: CircuitBreaker | None,
        initial_messages: list | None,
        trending_topic,
        pulse_manager,
        auto_fetch_trending: bool,
        population_manager,
        auto_evolve: bool,
        breeding_threshold: float,
        evidence_collector,
        breakpoint_manager,
        checkpoint_manager,
        enable_checkpointing: bool,
        performance_monitor,
        enable_performance_monitor: bool,
        enable_telemetry: bool,
        use_airlock: bool,
        airlock_config,
        agent_selector,
        use_performance_selection: bool,
        prompt_evolver,
        enable_prompt_evolution: bool,
        power_sampling_config: Any | None = None,
        org_id: str = "",
        user_id: str = "",
        usage_tracker=None,
        broadcast_pipeline=None,
        auto_broadcast: bool = False,
        broadcast_min_confidence: float = 0.8,
        training_exporter=None,
        auto_export_training: bool = False,
        training_export_min_confidence: float = 0.75,
        # ML Integration (stable - enabled by default)
        enable_ml_delegation: bool = True,
        ml_delegation_strategy=None,
        ml_delegation_weight: float = 0.3,
        enable_quality_gates: bool = True,
        quality_gate_threshold: float = 0.6,
        enable_consensus_estimation: bool = True,
        consensus_early_termination_threshold: float = 0.85,
        enable_stability_detection: bool = False,
        stability_threshold: float = 0.85,
        stability_min_rounds: int = 2,
        stability_agreement_threshold: float = 0.75,
        stability_conflict_confidence: float = 0.7,
        enable_cartographer: bool = True,
        enable_chaos_theater: bool = True,
    ) -> CoreComponents:
        """Initialize core Arena components.

        Returns:
            CoreComponents dataclass with all initialized components
        """
        from aragora.debate.autonomic_executor import AutonomicExecutor
        from aragora.debate.event_bridge import EventEmitterBridge

        auto_evolve = resolve_auto_evolve(auto_evolve)
        enable_prompt_evolution = resolve_prompt_evolution(enable_prompt_evolution)

        from aragora.debate.protocol import resolve_default_protocol

        protocol = resolve_default_protocol(protocol)

        # Wrap agents with airlock protection if enabled
        if use_airlock:
            from aragora.agents.airlock import AirlockConfig, wrap_agents

            airlock_cfg = airlock_config or AirlockConfig()
            # AirlockProxy delegates to Agent via __getattr__, making it duck-type compatible
            agents = cast(list["Agent"], wrap_agents(agents, airlock_cfg))
            logger.debug("[airlock] Wrapped %s agents with resilience layer", len(agents))

        hooks = event_hooks or {}
        spectator = spectator or SpectatorStream(enabled=False)
        agent_weights = agent_weights or {}
        circuit_breaker = circuit_breaker or CircuitBreaker()

        # Agent pool for lifecycle management and team selection
        agent_pool = AgentPool(
            agents=agents,
            config=AgentPoolConfig(circuit_breaker=circuit_breaker),
        )

        # Transparent immune system for health monitoring and broadcasting
        immune_system = get_immune_system()

        # Chaos director for theatrical failure messages
        # Can be disabled for programmatic/Nomic Loop usage where real errors matter
        chaos_director = get_chaos_director(DramaLevel.MODERATE) if enable_chaos_theater else None

        # Performance monitor for agent telemetry
        if performance_monitor:
            perf_monitor = performance_monitor
        elif enable_performance_monitor:
            from aragora.agents.performance_monitor import AgentPerformanceMonitor

            perf_monitor = AgentPerformanceMonitor()
        else:
            perf_monitor = None

        # Prompt evolver for self-improvement via pattern extraction
        if prompt_evolver:
            evolver = prompt_evolver
        elif enable_prompt_evolution and PROMPT_EVOLVER_AVAILABLE:
            evolver = PromptEvolver()
            logger.debug("[evolution] Auto-created PromptEvolver for pattern extraction")
        else:
            evolver = None

        autonomic = AutonomicExecutor(
            circuit_breaker=circuit_breaker,
            immune_system=immune_system,
            chaos_director=chaos_director,
            performance_monitor=perf_monitor,
            enable_telemetry=enable_telemetry,
            event_hooks=hooks,
            power_sampling_config=power_sampling_config,
        )

        # Checkpoint manager for debate resume support
        if checkpoint_manager:
            ckpt_manager = checkpoint_manager
        elif enable_checkpointing:
            from aragora.debate.checkpoint import CheckpointManager, DatabaseCheckpointStore

            ckpt_manager = CheckpointManager(store=DatabaseCheckpointStore())
            logger.debug("[checkpoint] Auto-created CheckpointManager with database store")
        else:
            ckpt_manager = None

        # Create extensions handler (billing, broadcast, training)
        extensions = ArenaExtensions(
            org_id=org_id,
            user_id=user_id,
            usage_tracker=usage_tracker,
            broadcast_pipeline=broadcast_pipeline,
            auto_broadcast=auto_broadcast,
            broadcast_min_confidence=broadcast_min_confidence,
            training_exporter=training_exporter,
            auto_export_training=auto_export_training,
            training_export_min_confidence=training_export_min_confidence,
        )

        # Auto-initialize BreakpointManager if enable_breakpoints is True
        if protocol.enable_breakpoints and breakpoint_manager is None:
            breakpoint_manager = self._auto_init_breakpoint_manager(protocol)

        # ArgumentCartographer for debate graph visualization
        AC = OptionalImports.get_argument_cartographer() if enable_cartographer else None
        cartographer = AC() if AC else None

        # Event bridge for coordinating spectator/websocket/cartographer
        event_bridge = EventEmitterBridge(
            spectator=spectator,
            event_emitter=event_emitter,
            cartographer=cartographer,
            loop_id=loop_id,
        )

        # Connect immune system to event bridge for WebSocket broadcasting
        immune_system.set_broadcast_callback(self._broadcast_callback)

        # Initialize ML components
        ml_strategy = ml_delegation_strategy
        ml_quality = None
        ml_consensus = None

        if (
            enable_ml_delegation
            or enable_quality_gates
            or enable_consensus_estimation
            or enable_stability_detection
        ):
            ml_strategy, ml_quality, ml_consensus = self._init_ml_integration(
                enable_ml_delegation=enable_ml_delegation,
                ml_delegation_strategy=ml_delegation_strategy,
                ml_delegation_weight=ml_delegation_weight,
                enable_quality_gates=enable_quality_gates,
                quality_gate_threshold=quality_gate_threshold,
                enable_consensus_estimation=enable_consensus_estimation,
                consensus_early_termination_threshold=consensus_early_termination_threshold,
                enable_stability_detection=enable_stability_detection,
                stability_threshold=stability_threshold,
                stability_min_rounds=stability_min_rounds,
                stability_agreement_threshold=stability_agreement_threshold,
                stability_conflict_confidence=stability_conflict_confidence,
                elo_system=None,  # Set later in init_trackers
                calibration_tracker=None,  # Set later in init_trackers
            )

        return CoreComponents(
            env=environment,
            agents=agents,
            protocol=protocol,
            memory=memory,
            hooks=hooks,
            hook_manager=hook_manager,
            event_emitter=event_emitter,
            spectator=spectator,
            debate_embeddings=debate_embeddings,
            insight_store=insight_store,
            recorder=recorder,
            agent_weights=agent_weights,
            loop_id=loop_id,
            strict_loop_scoping=strict_loop_scoping,
            circuit_breaker=circuit_breaker,
            agent_pool=agent_pool,
            immune_system=immune_system,
            chaos_director=chaos_director,
            performance_monitor=perf_monitor,
            prompt_evolver=evolver,
            autonomic=autonomic,
            initial_messages=initial_messages or [],
            trending_topic=trending_topic,
            pulse_manager=pulse_manager,
            auto_fetch_trending=auto_fetch_trending,
            population_manager=population_manager,
            auto_evolve=auto_evolve,
            breeding_threshold=breeding_threshold,
            evidence_collector=evidence_collector,
            breakpoint_manager=breakpoint_manager,
            agent_selector=agent_selector,
            use_performance_selection=use_performance_selection,
            checkpoint_manager=ckpt_manager,
            org_id=org_id,
            user_id=user_id,
            extensions=extensions,
            cartographer=cartographer,
            event_bridge=event_bridge,
            enable_ml_delegation=enable_ml_delegation,
            ml_delegation_weight=ml_delegation_weight,
            enable_quality_gates=enable_quality_gates,
            quality_gate_threshold=quality_gate_threshold,
            enable_consensus_estimation=enable_consensus_estimation,
            consensus_early_termination_threshold=consensus_early_termination_threshold,
            enable_stability_detection=enable_stability_detection,
            stability_threshold=stability_threshold,
            stability_min_rounds=stability_min_rounds,
            stability_agreement_threshold=stability_agreement_threshold,
            stability_conflict_confidence=stability_conflict_confidence,
            ml_delegation_strategy=ml_strategy,
            ml_quality_gate=ml_quality,
            ml_consensus_estimator=ml_consensus,
        )

    def init_trackers(
        self,
        protocol: DebateProtocol,
        loop_id: str,
        agent_pool: AgentPool,
        position_tracker,
        position_ledger,
        enable_position_ledger: bool,
        elo_system,
        persona_manager,
        dissent_retriever,
        consensus_memory,
        flip_detector,
        calibration_tracker,
        continuum_memory,
        relationship_tracker,
        moment_detector,
        tier_analytics_tracker=None,
        knowledge_mound=None,
        auto_create_knowledge_mound: bool = True,
        enable_knowledge_retrieval: bool = True,
        enable_knowledge_ingestion: bool = True,
        enable_knowledge_extraction: bool = False,
        extraction_min_confidence: float = 0.3,
        enable_belief_guidance: bool = True,
        vertical=None,
        vertical_persona_manager=None,
        auto_detect_vertical: bool = True,
        task: str = "",
        enable_outcome_context: bool = True,
    ) -> TrackerComponents:
        """Initialize tracking subsystems.

        Returns:
            TrackerComponents dataclass with all initialized trackers
        """
        # Auto-initialize MomentDetector when elo_system available but no detector provided
        if moment_detector is None and elo_system:
            moment_detector = self._auto_init_moment_detector(
                elo_system, position_ledger, relationship_tracker
            )

        # Auto-initialize KnowledgeMound when enabled and retrieval/ingestion is enabled
        if (
            auto_create_knowledge_mound
            and (enable_knowledge_retrieval or enable_knowledge_ingestion)
            and knowledge_mound is None
        ):
            knowledge_mound = self._auto_init_knowledge_mound()

        # Auto-upgrade to ELO-ranked judge selection when elo_system is available
        if elo_system and protocol.judge_selection == "random":
            protocol.judge_selection = "elo_ranked"

        # Auto-initialize CalibrationTracker when enable_calibration is True
        if protocol.enable_calibration and calibration_tracker is None:
            calibration_tracker = self._auto_init_calibration_tracker()

        # Auto-initialize DissentRetriever when consensus_memory is available
        if consensus_memory and dissent_retriever is None:
            dissent_retriever = self._auto_init_dissent_retriever(consensus_memory)

        # Update AgentPool with ELO and calibration systems if available
        if elo_system or calibration_tracker:
            agent_pool.set_scoring_systems(
                elo_system=elo_system,
                calibration_tracker=calibration_tracker,
            )

        # Sync topology setting from protocol to AgentPool
        topology = getattr(protocol, "topology", "full_mesh")
        agent_pool._config.topology = topology

        # Auto-initialize PositionLedger when enable_position_ledger is True
        if enable_position_ledger and position_ledger is None:
            position_ledger = self._auto_init_position_ledger()

        # Create SubsystemCoordinator with all initialized subsystems
        coordinator = SubsystemCoordinator(
            protocol=protocol,
            loop_id=loop_id,
            position_tracker=position_tracker,
            position_ledger=position_ledger,
            elo_system=elo_system,
            calibration_tracker=calibration_tracker,
            consensus_memory=consensus_memory,
            dissent_retriever=dissent_retriever,
            continuum_memory=continuum_memory,
            flip_detector=flip_detector,
            moment_detector=moment_detector,
            relationship_tracker=relationship_tracker,
            tier_analytics_tracker=tier_analytics_tracker,
            # Disable auto-init since we already initialized everything
            enable_position_ledger=False,
            enable_calibration=False,
            enable_moment_detection=False,
        )

        # Auto-detect vertical from task if enabled and no vertical specified
        detected_vertical = vertical
        if auto_detect_vertical and not vertical and task:
            try:
                from aragora.agents.vertical_personas import VerticalPersonaManager

                if vertical_persona_manager is None:
                    vertical_persona_manager = VerticalPersonaManager()
                detected_vertical = vertical_persona_manager.detect_vertical_from_task(task)
                logger.debug("Auto-detected vertical: %s", detected_vertical.value)
            except (ImportError, AttributeError) as e:
                logger.debug("Vertical auto-detection unavailable: %s", e)

        return TrackerComponents(
            position_tracker=position_tracker,
            position_ledger=position_ledger,
            elo_system=elo_system,
            persona_manager=persona_manager,
            dissent_retriever=dissent_retriever,
            consensus_memory=consensus_memory,
            flip_detector=flip_detector,
            calibration_tracker=calibration_tracker,
            continuum_memory=continuum_memory,
            relationship_tracker=relationship_tracker,
            moment_detector=moment_detector,
            tier_analytics_tracker=tier_analytics_tracker,
            knowledge_mound=knowledge_mound,
            enable_knowledge_retrieval=enable_knowledge_retrieval,
            enable_knowledge_ingestion=enable_knowledge_ingestion,
            enable_knowledge_extraction=enable_knowledge_extraction,
            extraction_min_confidence=extraction_min_confidence,
            enable_belief_guidance=enable_belief_guidance,
            coordinator=coordinator,
            vertical=detected_vertical,
            vertical_persona_manager=vertical_persona_manager,
        )

    def _auto_init_breakpoint_manager(self, protocol: DebateProtocol):
        """Auto-initialize BreakpointManager when enable_breakpoints is True."""
        try:
            from aragora.debate.breakpoints import BreakpointConfig, BreakpointManager

            config = protocol.breakpoint_config or BreakpointConfig()
            manager = BreakpointManager(config=config)
            logger.debug("Auto-initialized BreakpointManager for human-in-the-loop breakpoints")
            return manager
        except ImportError:
            logger.warning("BreakpointManager not available - breakpoints disabled")
            return None
        except (TypeError, ValueError, RuntimeError) as e:
            logger.warning("BreakpointManager auto-init failed: %s", e)
            return None

    def _auto_init_position_ledger(self):
        """Auto-initialize PositionLedger."""
        temp = SubsystemCoordinator(enable_position_ledger=True)
        return temp.position_ledger

    def _auto_init_calibration_tracker(self):
        """Auto-initialize CalibrationTracker."""
        temp = SubsystemCoordinator(enable_calibration=True)
        return temp.calibration_tracker

    def _auto_init_dissent_retriever(self, consensus_memory):
        """Auto-initialize DissentRetriever."""
        temp = SubsystemCoordinator(consensus_memory=consensus_memory)
        return temp.dissent_retriever

    def _auto_init_moment_detector(self, elo_system, position_ledger, relationship_tracker):
        """Auto-initialize MomentDetector."""
        temp = SubsystemCoordinator(
            elo_system=elo_system,
            position_ledger=position_ledger,
            relationship_tracker=relationship_tracker,
            enable_moment_detection=True,
        )
        return temp.moment_detector

    def _auto_init_knowledge_mound(self):
        """Auto-initialize KnowledgeMound for knowledge retrieval/ingestion."""
        try:
            from aragora.knowledge.mound import get_knowledge_mound

            mound = get_knowledge_mound(workspace_id="debate", auto_initialize=True)
            logger.debug("Auto-initialized KnowledgeMound for debate knowledge integration")
            return mound
        except ImportError:
            logger.warning("KnowledgeMound not available - knowledge integration disabled")
            return None
        except (TypeError, ValueError, RuntimeError) as e:
            logger.warning("KnowledgeMound auto-init failed: %s", e)
            return None

    def _init_ml_integration(
        self,
        enable_ml_delegation: bool,
        ml_delegation_strategy,
        ml_delegation_weight: float,
        enable_quality_gates: bool,
        quality_gate_threshold: float,
        enable_consensus_estimation: bool,
        consensus_early_termination_threshold: float,
        enable_stability_detection: bool,
        stability_threshold: float,
        stability_min_rounds: int,
        stability_agreement_threshold: float,
        stability_conflict_confidence: float,
        elo_system,
        calibration_tracker,
    ) -> tuple[Any, Any, Any]:
        """Initialize ML integration components.

        Returns:
            Tuple of (ml_delegation_strategy, ml_quality_gate, ml_consensus_estimator)
        """
        strategy = ml_delegation_strategy
        quality_gate = None
        consensus_estimator = None

        try:
            from aragora.debate.ml_integration import (
                MLDelegationStrategy,
                QualityGate,
                ConsensusEstimator,
            )

            if enable_ml_delegation and strategy is None:
                strategy = MLDelegationStrategy(
                    elo_system=elo_system,
                    calibration_tracker=calibration_tracker,
                    ml_weight=ml_delegation_weight,
                )
                logger.debug("[ml] Initialized MLDelegationStrategy")

            if enable_quality_gates:
                quality_gate = QualityGate(threshold=quality_gate_threshold)
                logger.debug(
                    "[ml] Initialized QualityGate with threshold=%s", quality_gate_threshold
                )

            if enable_consensus_estimation:
                consensus_estimator = ConsensusEstimator(
                    early_termination_threshold=consensus_early_termination_threshold,
                    enable_stability_detection=enable_stability_detection,
                    stability_threshold=stability_threshold,
                    stability_min_rounds=stability_min_rounds,
                    stability_agreement_threshold=stability_agreement_threshold,
                    stability_conflict_confidence=stability_conflict_confidence,
                )
                logger.debug(
                    "[ml] Initialized ConsensusEstimator with threshold=%s",
                    consensus_early_termination_threshold,
                )

        except ImportError as e:
            logger.warning("[ml] ML integration not available: %s", e)

        return strategy, quality_gate, consensus_estimator
