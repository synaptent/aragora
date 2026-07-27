"""
Subsystem coordinator for Arena tracking and detection systems.

This module extracts subsystem management from the Arena god object,
following the Single Responsibility Principle. The coordinator handles:

1. **Position Tracking**: PositionTracker, PositionLedger
2. **Agent Ranking**: ELO system, calibration tracking
3. **Memory Systems**: ConsensusMemory, DissentRetriever, ContinuumMemory
4. **Detection Systems**: FlipDetector, MomentDetector
5. **Relationship Tracking**: RelationshipTracker, TierAnalyticsTracker

Usage:
    # Create coordinator with optional pre-configured subsystems
    coordinator = SubsystemCoordinator(
        protocol=protocol,
        loop_id="debate-123",
        elo_system=elo,  # Pre-configured
        enable_position_ledger=True,  # Auto-create
    )

    # Access subsystems (lazy initialization)
    ledger = coordinator.position_ledger
    if coordinator.has_calibration:
        tracker = coordinator.calibration_tracker

    # After debate, update tracking
    coordinator.on_debate_complete(ctx, result)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from aragora.agents.calibration import CalibrationTracker
    from aragora.agents.learning.sdpo import SDPOLearner, TrajectoryRecord
    from aragora.agents.learning.sdpo_calibration import (
        SDPOCalibrationBridge,
        SDPOCalibrationConfig,
    )
    from aragora.agents.grounded import MomentDetector
    from aragora.agents.positions import PositionLedger
    from aragora.agents.truth_grounding import PositionTracker
    from aragora.billing.calibration_cost_bridge import (
        CalibrationTracker as BillingCalibrationTracker,
    )
    from aragora.core import DebateResult
    from aragora.insights.flip_detector import FlipDetector
    from aragora.debate.context import DebateContext
    from aragora.debate.protocol import DebateProtocol
    from aragora.memory.consensus import ConsensusMemory, DissentRetriever
    from aragora.memory.continuum import ContinuumMemory
    from aragora.memory.tier_analytics import TierAnalyticsTracker
    from aragora.ranking.elo import EloSystem
    from aragora.relationships.tracker import RelationshipTracker


@runtime_checkable
class Resettable(Protocol):
    """Protocol for objects that can be reset."""

    def reset(self) -> None:
        """Reset internal state."""
        ...


logger = logging.getLogger(__name__)


@dataclass
class SubsystemCoordinator:
    """Coordinates tracking and detection subsystems for Arena.

    Provides a centralized place to manage optional subsystems that enhance
    debate capabilities. Handles lazy initialization and graceful fallbacks.

    Subsystems are grouped by function:

    **Position Systems** (track agent stances):
    - position_tracker: Real-time position tracking during debate
    - position_ledger: Persistent record of all positions across debates

    **Agent Ranking** (track agent skill):
    - elo_system: ELO ratings for agent skill ranking
    - calibration_tracker: Prediction accuracy tracking

    **Memory Systems** (cross-debate learning):
    - consensus_memory: Historical debate outcomes
    - dissent_retriever: Historical minority viewpoints
    - continuum_memory: Cross-debate learning memory

    **Detection Systems** (identify patterns):
    - flip_detector: Position reversal detection
    - moment_detector: Significant moment identification

    **Relationship Systems** (agent interactions):
    - relationship_tracker: Inter-agent relationship tracking
    - tier_analytics_tracker: Memory tier ROI analysis
    """

    # Protocol reference for breakpoint configuration
    protocol: DebateProtocol | None = None
    loop_id: str = ""

    # Position tracking subsystems
    position_tracker: PositionTracker | None = None
    position_ledger: PositionLedger | None = None
    enable_position_ledger: bool = False

    # Agent ranking subsystems
    elo_system: EloSystem | None = None
    calibration_tracker: CalibrationTracker | None = None
    enable_calibration: bool = False

    # SDPO learning (self-distillation for calibration)
    sdpo_learner: SDPOLearner | None = None
    sdpo_bridge: SDPOCalibrationBridge | None = None
    sdpo_calibration_config: SDPOCalibrationConfig | None = None
    enable_sdpo: bool = True

    # Persona management
    persona_manager: Any | None = None

    # Memory subsystems
    consensus_memory: ConsensusMemory | None = None
    dissent_retriever: DissentRetriever | None = None
    continuum_memory: ContinuumMemory | None = None

    # Detection subsystems
    flip_detector: FlipDetector | None = None
    moment_detector: MomentDetector | None = None
    enable_moment_detection: bool = False

    # Relationship subsystems
    relationship_tracker: RelationshipTracker | None = None
    tier_analytics_tracker: TierAnalyticsTracker | None = None

    # Hook system
    hook_manager: Any | None = None  # HookManager for lifecycle hooks
    hook_handler_registry: Any | None = None  # HookHandlerRegistry for auto-wiring
    enable_hook_handlers: bool = True  # Auto-register default handlers if hook_manager provided

    # ==========================================================================
    # Phase 9: Cross-Pollination Bridges
    # These bridges connect subsystems for self-improving feedback loops
    # ==========================================================================

    # Performance → Agent Router Bridge
    performance_router_bridge: Any | None = None  # PerformanceRouterBridge
    enable_performance_router: bool = True  # Auto-create if performance_monitor available
    performance_monitor: Any | None = None  # AgentPerformanceMonitor (source)
    agent_router: Any | None = None  # AgentRouter (target)

    # Outcome → Complexity Governor Bridge
    outcome_complexity_bridge: Any | None = None  # OutcomeComplexityBridge
    enable_outcome_complexity: bool = True  # Auto-create if outcome_tracker available
    outcome_tracker: Any | None = None  # OutcomeTracker (source)
    complexity_governor: Any | None = None  # ComplexityGovernor (target)

    # Analytics → Team Selection Bridge
    analytics_selection_bridge: Any | None = None  # AnalyticsSelectionBridge
    enable_analytics_selection: bool = True  # Auto-create if analytics available
    analytics_coordinator: Any | None = None  # AnalyticsCoordinator (source)
    team_selector: Any | None = None  # TeamSelector (target)

    # Performance → Selection Feedback Loop (auto-creates SelectionFeedbackLoop)
    enable_performance_feedback: bool = True  # Auto-create SelectionFeedbackLoop if None
    feedback_loop_weight: float = 0.25  # Weight for feedback adjustments (0.0-1.0)
    feedback_loop_decay: float = 0.9  # Decay factor for old feedback
    feedback_loop_min_debates: int = 2  # Min debates before applying feedback

    # Novelty → Selection Feedback Bridge
    novelty_selection_bridge: Any | None = None  # NoveltySelectionBridge
    enable_novelty_selection: bool = True  # Auto-create if novelty_tracker available
    novelty_tracker: Any | None = None  # NoveltyTracker (source)
    selection_feedback_loop: Any | None = None  # SelectionFeedbackLoop (target)

    # Relationship → Bias Mitigation Bridge
    relationship_bias_bridge: Any | None = None  # RelationshipBiasBridge
    enable_relationship_bias: bool = True  # Auto-create if relationship_tracker available
    # relationship_tracker already defined above (source)
    # bias_mitigation target is implicit in vote processing

    # RLM → Selection Feedback Bridge
    rlm_selection_bridge: Any | None = None  # RLMSelectionBridge
    enable_rlm_selection: bool = True  # Auto-create if rlm_bridge available
    rlm_bridge: Any | None = None  # RLMBridge (source)
    # selection_feedback_loop already defined above (target)

    # Calibration → Cost Optimizer Bridge
    calibration_cost_bridge: Any | None = None  # CalibrationCostBridge
    enable_calibration_cost: bool = True  # Auto-create if calibration_tracker available
    # calibration_tracker already defined above (source)
    cost_tracker: Any | None = None  # CostTracker (target)

    # ==========================================================================
    # Phase 10: Bidirectional Knowledge Mound Integration
    # ==========================================================================

    # Knowledge Mound core
    knowledge_mound: Any | None = None  # KnowledgeMound instance
    enable_km_bidirectional: bool = True  # Master switch for bidirectional sync

    # Bidirectional Coordinator
    km_coordinator: Any | None = None  # BidirectionalCoordinator
    enable_km_coordinator: bool = True  # Auto-create if KM available

    # KM Adapters (for manual configuration)
    km_continuum_adapter: Any | None = None
    km_elo_adapter: Any | None = None
    km_belief_adapter: Any | None = None
    km_insights_adapter: Any | None = None
    km_critique_adapter: Any | None = None
    km_pulse_adapter: Any | None = None
    km_obsidian_adapter: Any | None = None

    # KM Configuration
    km_sync_interval_seconds: int = 300  # 5 minutes
    km_min_confidence_for_reverse: float = 0.7
    km_parallel_sync: bool = True

    # Internal state
    _initialized: bool = field(default=False, repr=False)
    _init_errors: list = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        """Initialize subsystems after dataclass fields are set."""
        self._auto_init_subsystems()
        self._initialized = True

    # =========================================================================
    # Property accessors with capability checks
    # =========================================================================

    @property
    def has_position_tracking(self) -> bool:
        """Check if position tracking is available."""
        return self.position_tracker is not None or self.position_ledger is not None

    @property
    def has_elo(self) -> bool:
        """Check if ELO ranking is available."""
        return self.elo_system is not None

    @property
    def has_calibration(self) -> bool:
        """Check if calibration tracking is available."""
        return self.calibration_tracker is not None

    @property
    def has_consensus_memory(self) -> bool:
        """Check if consensus memory is available."""
        return self.consensus_memory is not None

    @property
    def has_dissent_retrieval(self) -> bool:
        """Check if dissent retrieval is available."""
        return self.dissent_retriever is not None

    @property
    def has_moment_detection(self) -> bool:
        """Check if moment detection is available."""
        return self.moment_detector is not None

    @property
    def has_relationship_tracking(self) -> bool:
        """Check if relationship tracking is available."""
        return self.relationship_tracker is not None

    @property
    def has_continuum_memory(self) -> bool:
        """Check if cross-debate memory is available."""
        return self.continuum_memory is not None

    # =========================================================================
    # Phase 9: Cross-Pollination Bridge Capability Checks
    # =========================================================================

    @property
    def has_performance_router_bridge(self) -> bool:
        """Check if performance-based routing bridge is available."""
        return self.performance_router_bridge is not None

    @property
    def has_outcome_complexity_bridge(self) -> bool:
        """Check if outcome-complexity bridge is available."""
        return self.outcome_complexity_bridge is not None

    @property
    def has_analytics_selection_bridge(self) -> bool:
        """Check if analytics-selection bridge is available."""
        return self.analytics_selection_bridge is not None

    @property
    def has_novelty_selection_bridge(self) -> bool:
        """Check if novelty-selection bridge is available."""
        return self.novelty_selection_bridge is not None

    @property
    def has_relationship_bias_bridge(self) -> bool:
        """Check if relationship-bias bridge is available."""
        return self.relationship_bias_bridge is not None

    @property
    def has_rlm_selection_bridge(self) -> bool:
        """Check if RLM-selection bridge is available."""
        return self.rlm_selection_bridge is not None

    @property
    def has_calibration_cost_bridge(self) -> bool:
        """Check if calibration-cost bridge is available."""
        return self.calibration_cost_bridge is not None

    @property
    def active_bridges_count(self) -> int:
        """Count of active cross-pollination bridges."""
        return sum(
            [
                self.has_performance_router_bridge,
                self.has_outcome_complexity_bridge,
                self.has_analytics_selection_bridge,
                self.has_novelty_selection_bridge,
                self.has_relationship_bias_bridge,
                self.has_rlm_selection_bridge,
                self.has_calibration_cost_bridge,
            ]
        )

    # =========================================================================
    # Phase 10: Knowledge Mound Capability Checks
    # =========================================================================

    @property
    def has_knowledge_mound(self) -> bool:
        """Check if Knowledge Mound is available."""
        return self.knowledge_mound is not None

    @property
    def has_km_coordinator(self) -> bool:
        """Check if KM bidirectional coordinator is available."""
        return self.km_coordinator is not None

    @property
    def has_km_bidirectional(self) -> bool:
        """Check if full KM bidirectional sync is available."""
        return self.has_knowledge_mound and self.has_km_coordinator

    @property
    def active_km_adapters_count(self) -> int:
        """Count of active KM adapters registered with coordinator."""
        adapters = [
            self.km_continuum_adapter,
            self.km_elo_adapter,
            self.km_belief_adapter,
            self.km_insights_adapter,
            self.km_critique_adapter,
            self.km_pulse_adapter,
            self.km_obsidian_adapter,
        ]
        return sum(1 for a in adapters if a is not None)

    # =========================================================================
    # Auto-initialization methods
    # =========================================================================

    def _auto_init_subsystems(self) -> None:
        """Auto-initialize subsystems based on flags and dependencies."""
        # Position ledger
        if self.enable_position_ledger and self.position_ledger is None:
            self._auto_init_position_ledger()

        # Calibration tracker
        if self.enable_calibration and self.calibration_tracker is None:
            self._auto_init_calibration_tracker()

        # SDPO learning bridge (uses calibration tracker when available)
        if self.enable_sdpo and self.sdpo_learner is None:
            self._auto_init_sdpo()

        # Dissent retriever (requires consensus_memory)
        if self.consensus_memory is not None and self.dissent_retriever is None:
            self._auto_init_dissent_retriever()

        # Moment detector (benefits from elo_system)
        if self.enable_moment_detection and self.moment_detector is None:
            self._auto_init_moment_detector()

        # Hook handler registry (requires hook_manager)
        if self.hook_manager is not None and self.enable_hook_handlers:
            self._auto_init_hook_handlers()

        # =======================================================================
        # Phase 9: Cross-Pollination Bridges
        # =======================================================================

        # Performance → Router bridge
        if self.enable_performance_router and self.performance_router_bridge is None:
            self._auto_init_performance_router_bridge()

        # Outcome → Complexity bridge
        if self.enable_outcome_complexity and self.outcome_complexity_bridge is None:
            self._auto_init_outcome_complexity_bridge()

        # Analytics → Selection bridge
        if self.enable_analytics_selection and self.analytics_selection_bridge is None:
            self._auto_init_analytics_selection_bridge()

        # Selection Feedback Loop (must be before bridges that consume it)
        if self.enable_performance_feedback and self.selection_feedback_loop is None:
            self._auto_init_selection_feedback_loop()

        # Novelty → Selection Feedback bridge
        if self.enable_novelty_selection and self.novelty_selection_bridge is None:
            self._auto_init_novelty_selection_bridge()

        # Relationship → Bias Mitigation bridge
        if self.enable_relationship_bias and self.relationship_bias_bridge is None:
            self._auto_init_relationship_bias_bridge()

        # RLM → Selection Feedback bridge
        if self.enable_rlm_selection and self.rlm_selection_bridge is None:
            self._auto_init_rlm_selection_bridge()

        # Calibration → Cost bridge
        if self.enable_calibration_cost and self.calibration_cost_bridge is None:
            self._auto_init_calibration_cost_bridge()

        # Wire feedback loop into TeamSelector if both available
        if self.selection_feedback_loop and self.team_selector:
            self._wire_feedback_to_team_selector()

        # Wire KM adapters into TeamSelector if KM available
        if self.knowledge_mound and self.team_selector:
            self._auto_wire_km_adapters_to_team_selector()

        # =======================================================================
        # Phase 10: Bidirectional Knowledge Mound
        # =======================================================================

        # KM Bidirectional Coordinator
        if self.enable_km_coordinator and self.enable_km_bidirectional:
            if self.km_coordinator is None:
                self._auto_init_km_coordinator()

    def _auto_init_position_ledger(self) -> None:
        """Auto-initialize PositionLedger for tracking agent positions.

        PositionLedger tracks every position agents take across debates,
        including outcomes and reversals.
        """
        try:
            from aragora.agents.positions import PositionLedger

            self.position_ledger = PositionLedger()
            logger.debug("Auto-initialized PositionLedger for position tracking")
        except ImportError:
            logger.warning("PositionLedger not available - position tracking disabled")
            self._init_errors.append("PositionLedger import failed")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.warning("PositionLedger auto-init failed: %s", e)
            self._init_errors.append(f"PositionLedger init failed: {e}")

    def _auto_init_calibration_tracker(self) -> None:
        """Auto-initialize CalibrationTracker for prediction accuracy."""
        try:
            from aragora.agents.calibration import CalibrationTracker

            self.calibration_tracker = CalibrationTracker()
            logger.debug("Auto-initialized CalibrationTracker for prediction calibration")
        except ImportError:
            logger.warning("CalibrationTracker not available - calibration disabled")
            self._init_errors.append("CalibrationTracker import failed")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.warning("CalibrationTracker auto-init failed: %s", e)
            self._init_errors.append(f"CalibrationTracker init failed: {e}")

    def _auto_init_sdpo(self) -> None:
        """Auto-initialize SDPO learner and optional calibration bridge."""
        try:
            from aragora.agents.learning.sdpo import SDPOLearner, SDPOConfig
            from aragora.agents.learning.sdpo_calibration import (
                SDPOCalibrationBridge,
                SDPOCalibrationConfig,
            )

            sdpo_config = SDPOConfig()
            self.sdpo_learner = self.sdpo_learner or SDPOLearner(config=sdpo_config)

            if self.calibration_tracker is not None:
                bridge_config = self.sdpo_calibration_config or SDPOCalibrationConfig()
                self.sdpo_bridge = SDPOCalibrationBridge(
                    sdpo_learner=self.sdpo_learner,
                    calibration_tracker=self.calibration_tracker,
                    config=bridge_config,
                )

            logger.debug("Auto-initialized SDPO learner for calibration feedback")
        except ImportError:
            logger.debug("SDPO not available - skipping SDPO initialization")
            self._init_errors.append("SDPO import failed")
        except (RuntimeError, TypeError, ValueError, AttributeError) as e:
            logger.warning("SDPO auto-init failed: %s", e)
            self._init_errors.append(f"SDPO init failed: {e}")

    def _auto_init_dissent_retriever(self) -> None:
        """Auto-initialize DissentRetriever for historical minority views.

        The DissentRetriever enables seeding new debates with historical minority
        views, helping agents avoid past groupthink.
        """
        try:
            from aragora.memory.consensus import DissentRetriever

            self.dissent_retriever = DissentRetriever(self.consensus_memory)
            logger.debug("Auto-initialized DissentRetriever for historical minority views")
        except ImportError:
            logger.debug("DissentRetriever not available - historical dissent disabled")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.warning("DissentRetriever auto-init failed: %s", e)
            self._init_errors.append(f"DissentRetriever init failed: {e}")

    def _auto_init_moment_detector(self) -> None:
        """Auto-initialize MomentDetector for significant moment detection."""
        try:
            from aragora.agents.grounded import MomentDetector

            self.moment_detector = MomentDetector(
                elo_system=self.elo_system,
                position_ledger=self.position_ledger,
                relationship_tracker=self.relationship_tracker,
            )
            logger.debug("Auto-initialized MomentDetector for significant moment detection")
        except ImportError:
            logger.debug("MomentDetector not available")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.debug("MomentDetector auto-init failed: %s", e)
            self._init_errors.append(f"MomentDetector init failed: {e}")

    def _auto_init_hook_handlers(self) -> None:
        """Auto-initialize HookHandlerRegistry to wire subsystems to HookManager.

        Creates a registry that connects available subsystems to the hook lifecycle,
        enabling automatic event propagation across components.
        """
        if self.hook_handler_registry is not None:
            # Already have a registry
            return

        try:
            from aragora.debate.hook_handlers import HookHandlerRegistry

            # Collect available subsystems for the registry
            subsystems: dict[str, Any] = {}
            if self.continuum_memory:
                subsystems["continuum_memory"] = self.continuum_memory
            if self.consensus_memory:
                subsystems["consensus_memory"] = self.consensus_memory
            if self.calibration_tracker:
                subsystems["calibration_tracker"] = self.calibration_tracker
            if self.flip_detector:
                subsystems["flip_detector"] = self.flip_detector
            if self.elo_system:
                subsystems["elo_system"] = self.elo_system
            if self.relationship_tracker:
                subsystems["relationship_tracker"] = self.relationship_tracker
            if self.tier_analytics_tracker:
                subsystems["tier_analytics_tracker"] = self.tier_analytics_tracker

            self.hook_handler_registry = HookHandlerRegistry(
                hook_manager=self.hook_manager,
                subsystems=subsystems,
            )
            count = self.hook_handler_registry.register_all()
            logger.debug("Auto-initialized HookHandlerRegistry with %s handlers", count)
        except ImportError:
            logger.debug("HookHandlerRegistry not available")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.debug("HookHandlerRegistry auto-init failed: %s", e)
            self._init_errors.append(f"HookHandlerRegistry init failed: {e}")

    # =========================================================================
    # Phase 9: Cross-Pollination Bridge Auto-Initialization
    # =========================================================================

    def _auto_init_performance_router_bridge(self) -> None:
        """Auto-initialize PerformanceRouterBridge for performance-based routing."""
        if self.performance_monitor is None:
            # No source data available
            return

        try:
            from aragora.debate.performance_router_bridge import (
                create_performance_router_bridge,
            )

            self.performance_router_bridge = create_performance_router_bridge(
                performance_monitor=self.performance_monitor,
                agent_router=self.agent_router,
            )
            logger.debug("Auto-initialized PerformanceRouterBridge")
        except ImportError:
            logger.debug("PerformanceRouterBridge not available")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.debug("PerformanceRouterBridge auto-init failed: %s", e)
            self._init_errors.append(f"PerformanceRouterBridge init failed: {e}")

    def _auto_init_outcome_complexity_bridge(self) -> None:
        """Auto-initialize OutcomeComplexityBridge for outcome-based complexity governance."""
        if self.outcome_tracker is None:
            # No source data available
            return

        try:
            from aragora.debate.outcome_complexity_bridge import (
                create_outcome_complexity_bridge,
            )

            self.outcome_complexity_bridge = create_outcome_complexity_bridge(
                outcome_tracker=self.outcome_tracker,
                complexity_governor=self.complexity_governor,
            )
            logger.debug("Auto-initialized OutcomeComplexityBridge")
        except ImportError:
            logger.debug("OutcomeComplexityBridge not available")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.debug("OutcomeComplexityBridge auto-init failed: %s", e)
            self._init_errors.append(f"OutcomeComplexityBridge init failed: {e}")

    def _auto_init_analytics_selection_bridge(self) -> None:
        """Auto-initialize AnalyticsSelectionBridge for analytics-driven team selection."""
        if self.analytics_coordinator is None:
            # No source data available
            return

        try:
            from aragora.debate.analytics_selection_bridge import (
                create_analytics_selection_bridge,
            )

            self.analytics_selection_bridge = create_analytics_selection_bridge(
                analytics_coordinator=self.analytics_coordinator,
                team_selector=self.team_selector,
            )
            logger.debug("Auto-initialized AnalyticsSelectionBridge")
        except ImportError:
            logger.debug("AnalyticsSelectionBridge not available")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.debug("AnalyticsSelectionBridge auto-init failed: %s", e)
            self._init_errors.append(f"AnalyticsSelectionBridge init failed: {e}")

    def _auto_init_selection_feedback_loop(self) -> None:
        """Auto-initialize SelectionFeedbackLoop for performance-based selection weights.

        Creates a SelectionFeedbackLoop when enable_performance_feedback is True
        and no pre-configured loop was provided. Uses feedback_loop_weight,
        feedback_loop_decay, and feedback_loop_min_debates from coordinator config.
        """
        try:
            from aragora.debate.selection_feedback import (
                FeedbackLoopConfig,
                SelectionFeedbackLoop,
            )

            config = FeedbackLoopConfig(
                performance_to_selection_weight=self.feedback_loop_weight,
                feedback_decay_factor=self.feedback_loop_decay,
                min_debates_for_feedback=self.feedback_loop_min_debates,
            )
            self.selection_feedback_loop = SelectionFeedbackLoop(
                config=config,
                elo_system=self.elo_system,
                calibration_tracker=self.calibration_tracker,
            )
            logger.debug("Auto-initialized SelectionFeedbackLoop")
        except ImportError:
            logger.debug("SelectionFeedbackLoop not available")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.debug("SelectionFeedbackLoop auto-init failed: %s", e)
            self._init_errors.append(f"SelectionFeedbackLoop init failed: {e}")

    def _wire_feedback_to_team_selector(self) -> None:
        """Wire SelectionFeedbackLoop into TeamSelector for feedback-weighted scoring."""
        try:
            self.team_selector.feedback_loop = self.selection_feedback_loop
            if hasattr(self.team_selector, "config"):
                self.team_selector.config.enable_feedback_weights = True
            logger.debug("Wired SelectionFeedbackLoop into TeamSelector")
        except (AttributeError, TypeError) as e:
            logger.debug("Failed to wire feedback loop to TeamSelector: %s", e)

    def _auto_wire_km_adapters_to_team_selector(self) -> None:
        """Auto-wire KM PerformanceAdapter into TeamSelector.

        Queries the KnowledgeMound's adapter factory for PerformanceAdapter.
        If available, injects it into TeamSelector for KM-driven expertise
        scoring. Also wires the ranking_adapter (which uses the same
        PerformanceAdapter, since RankingAdapter is a deprecated alias).
        Gracefully skips when KM is unavailable or adapters cannot be created.
        """
        if not self.knowledge_mound or not self.team_selector:
            return

        try:
            from aragora.knowledge.mound.adapters.factory import AdapterFactory

            factory = AdapterFactory()  # type: ignore[call-arg]
            created = factory.create_from_subsystems(elo_system=self.elo_system)

            # Wire PerformanceAdapter if created and not already set
            perf = created.get("performance")
            if perf and not self.team_selector.performance_adapter:
                self.team_selector.performance_adapter = perf.adapter
                logger.debug("Auto-wired PerformanceAdapter into TeamSelector")

            # Wire as ranking_adapter too (PerformanceAdapter subsumes RankingAdapter)
            if perf and not self.team_selector.ranking_adapter:
                self.team_selector.ranking_adapter = perf.adapter
                logger.debug("Auto-wired RankingAdapter (via PerformanceAdapter) into TeamSelector")

        except ImportError:
            logger.debug("KM adapter factory not available, skipping auto-wire")
        except (TypeError, ValueError, RuntimeError, AttributeError) as e:
            logger.debug("KM adapter auto-wire failed: %s", e)

    def _auto_init_novelty_selection_bridge(self) -> None:
        """Auto-initialize NoveltySelectionBridge for novelty-based selection feedback."""
        if self.novelty_tracker is None:
            # No source data available
            return

        try:
            from aragora.debate.novelty_selection_bridge import (
                create_novelty_selection_bridge,
            )

            self.novelty_selection_bridge = create_novelty_selection_bridge(
                novelty_tracker=self.novelty_tracker,
                selection_feedback=self.selection_feedback_loop,
            )
            logger.debug("Auto-initialized NoveltySelectionBridge")
        except ImportError:
            logger.debug("NoveltySelectionBridge not available")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.debug("NoveltySelectionBridge auto-init failed: %s", e)
            self._init_errors.append(f"NoveltySelectionBridge init failed: {e}")

    def _auto_init_relationship_bias_bridge(self) -> None:
        """Auto-initialize RelationshipBiasBridge for echo chamber detection and bias mitigation."""
        if self.relationship_tracker is None:
            # No source data available
            return

        try:
            from aragora.debate.relationship_bias_bridge import (
                create_relationship_bias_bridge,
            )

            self.relationship_bias_bridge = create_relationship_bias_bridge(
                relationship_tracker=self.relationship_tracker,
            )
            logger.debug("Auto-initialized RelationshipBiasBridge")
        except ImportError:
            logger.debug("RelationshipBiasBridge not available")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.debug("RelationshipBiasBridge auto-init failed: %s", e)
            self._init_errors.append(f"RelationshipBiasBridge init failed: {e}")

    def _auto_init_rlm_selection_bridge(self) -> None:
        """Auto-initialize RLMSelectionBridge for RLM-efficient agent selection."""
        if self.rlm_bridge is None:
            # No source data available
            return

        try:
            from aragora.rlm.rlm_selection_bridge import create_rlm_selection_bridge

            self.rlm_selection_bridge = create_rlm_selection_bridge(
                rlm_bridge=self.rlm_bridge,
                selection_feedback=self.selection_feedback_loop,
            )
            logger.debug("Auto-initialized RLMSelectionBridge")
        except ImportError:
            logger.debug("RLMSelectionBridge not available")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.debug("RLMSelectionBridge auto-init failed: %s", e)
            self._init_errors.append(f"RLMSelectionBridge init failed: {e}")

    def _auto_init_calibration_cost_bridge(self) -> None:
        """Auto-initialize CalibrationCostBridge for calibration-based cost optimization."""
        if self.calibration_tracker is None:
            # No source data available
            return

        try:
            from aragora.billing.calibration_cost_bridge import (
                create_calibration_cost_bridge,
            )

            self.calibration_cost_bridge = create_calibration_cost_bridge(
                calibration_tracker=cast("BillingCalibrationTracker", self.calibration_tracker),
                cost_tracker=self.cost_tracker,
            )
            logger.debug("Auto-initialized CalibrationCostBridge")
        except ImportError:
            logger.debug("CalibrationCostBridge not available")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.debug("CalibrationCostBridge auto-init failed: %s", e)
            self._init_errors.append(f"CalibrationCostBridge init failed: {e}")

    def _auto_init_km_coordinator(self) -> None:
        """Auto-initialize BidirectionalCoordinator for KM sync.

        BidirectionalCoordinator manages bidirectional data flow between
        the Knowledge Mound and connected subsystems (adapters).

        The coordinator is configured with:
        - sync_interval_seconds: How often to run bidirectional sync
        - min_confidence_for_reverse: Minimum confidence for reverse flow
        - parallel_sync: Whether to run adapter syncs in parallel

        After initialization, adapters are registered if available.
        """
        try:
            from aragora.knowledge.mound.bidirectional_coordinator import (
                BidirectionalCoordinator,
                CoordinatorConfig,
            )

            # Create configuration from SubsystemCoordinator fields
            config = CoordinatorConfig(
                sync_interval_seconds=self.km_sync_interval_seconds,
                min_confidence_for_reverse=self.km_min_confidence_for_reverse,
                parallel_sync=self.km_parallel_sync,
            )

            # Initialize coordinator with config and optional KM reference
            self.km_coordinator = BidirectionalCoordinator(
                config=config,
                knowledge_mound=self.knowledge_mound,
            )

            # Register available adapters
            self._register_km_adapters()

            logger.debug("Auto-initialized BidirectionalCoordinator for KM sync")
        except ImportError:
            logger.debug("BidirectionalCoordinator not available")
        except (TypeError, ValueError, RuntimeError) as e:
            logger.debug("BidirectionalCoordinator auto-init failed: %s", e)
            self._init_errors.append(f"BidirectionalCoordinator init failed: {e}")

    def _register_km_adapters(self) -> None:
        """Register available KM adapters with the BidirectionalCoordinator.

        Adapters are registered in priority order:
        1. ContinuumAdapter (highest impact on memory quality)
        2. ELOAdapter (critical for agent selection)
        3. BeliefAdapter (improves crux detection)
        4. InsightsAdapter (improves consistency analysis)
        5. CritiqueAdapter (boosts successful patterns)
        6. PulseAdapter (improves topic scheduling)

        Each adapter provides:
        - forward_method: Source → KM sync
        - reverse_method: KM → Source sync (optional)
        """
        if self.km_coordinator is None:
            return

        # Register pre-configured adapters or create them dynamically

        # 1. Continuum adapter (memory tier management)
        if self.km_continuum_adapter is not None:
            try:
                self.km_coordinator.register_adapter(
                    name="continuum",
                    adapter=self.km_continuum_adapter,
                    forward_method="sync_to_km",
                    reverse_method="update_continuum_from_km",
                    priority=1,
                )
                logger.debug("Registered ContinuumAdapter with KM coordinator")
            except (RuntimeError, TypeError, ValueError, AttributeError) as e:
                logger.debug("ContinuumAdapter registration failed: %s", e)

        # 2. ELO adapter (ranking adjustments)
        if self.km_elo_adapter is not None:
            try:
                self.km_coordinator.register_adapter(
                    name="elo",
                    adapter=self.km_elo_adapter,
                    forward_method="sync_to_km",
                    reverse_method="update_elo_from_km_patterns",
                    priority=2,
                )
                logger.debug("Registered ELOAdapter with KM coordinator")
            except (RuntimeError, TypeError, ValueError, AttributeError) as e:
                logger.debug("ELOAdapter registration failed: %s", e)

        # 3. Belief adapter (belief network calibration)
        if self.km_belief_adapter is not None:
            try:
                self.km_coordinator.register_adapter(
                    name="belief",
                    adapter=self.km_belief_adapter,
                    forward_method="sync_to_km",
                    reverse_method="update_belief_thresholds_from_km",
                    priority=3,
                )
                logger.debug("Registered BeliefAdapter with KM coordinator")
            except (RuntimeError, TypeError, ValueError, AttributeError) as e:
                logger.debug("BeliefAdapter registration failed: %s", e)

        # 4. Insights adapter (flip detection thresholds)
        if self.km_insights_adapter is not None:
            try:
                self.km_coordinator.register_adapter(
                    name="insights",
                    adapter=self.km_insights_adapter,
                    forward_method="sync_to_km",
                    reverse_method="update_flip_thresholds_from_km",
                    priority=4,
                )
                logger.debug("Registered InsightsAdapter with KM coordinator")
            except (RuntimeError, TypeError, ValueError, AttributeError) as e:
                logger.debug("InsightsAdapter registration failed: %s", e)

        # 5. Critique adapter (pattern boosting)
        if self.km_critique_adapter is not None:
            try:
                self.km_coordinator.register_adapter(
                    name="critique",
                    adapter=self.km_critique_adapter,
                    forward_method="sync_to_km",
                    reverse_method="boost_pattern_from_km",
                    priority=5,
                )
                logger.debug("Registered CritiqueAdapter with KM coordinator")
            except (RuntimeError, TypeError, ValueError, AttributeError) as e:
                logger.debug("CritiqueAdapter registration failed: %s", e)

        # 6. Pulse adapter (topic scheduling feedback)
        if self.km_pulse_adapter is not None:
            try:
                self.km_coordinator.register_adapter(
                    name="pulse",
                    adapter=self.km_pulse_adapter,
                    forward_method="sync_to_km",
                    reverse_method="sync_validations_from_km",
                    priority=6,
                )
                logger.debug("Registered PulseAdapter with KM coordinator")
            except (RuntimeError, TypeError, ValueError, AttributeError) as e:
                logger.debug("PulseAdapter registration failed: %s", e)

        # 7. Obsidian adapter (optional local vault ingestion)
        if self.km_obsidian_adapter is not None:
            try:
                self.km_coordinator.register_adapter(
                    name="obsidian",
                    adapter=self.km_obsidian_adapter,
                    forward_method="sync_to_km",
                    reverse_method=None,
                    priority=0,
                )
                logger.debug("Registered ObsidianAdapter with KM coordinator")
            except (RuntimeError, TypeError, ValueError, AttributeError) as e:
                logger.debug("ObsidianAdapter registration failed: %s", e)

        registered = (
            self.km_coordinator.adapter_count
            if hasattr(self.km_coordinator, "adapter_count")
            else 0
        )
        logger.debug("Registered %d KM adapters with coordinator", registered)

    # =========================================================================
    # Lifecycle hooks
    # =========================================================================

    def on_debate_start(self, ctx: DebateContext) -> None:
        """Called when a debate starts.

        Args:
            ctx: The debate context being initialized
        """
        # Reset moment detector for new debate if it supports reset
        if self.moment_detector and isinstance(self.moment_detector, Resettable):
            try:
                self.moment_detector.reset()
            except (RuntimeError, AttributeError, TypeError) as e:
                logger.debug("MomentDetector reset failed: %s", e)

    def on_round_complete(
        self,
        ctx: DebateContext,
        round_num: int,
        positions: dict[str, str],
    ) -> None:
        """Called when a debate round completes.

        Args:
            ctx: The debate context
            round_num: The round number that completed
            positions: Agent name -> position mapping
        """
        # Record positions in ledger
        if self.position_ledger:
            for agent_name, position in positions.items():
                try:
                    self.position_ledger.record_position(
                        agent_name=agent_name,
                        claim=position,
                        confidence=0.5,  # Default confidence when not specified
                        debate_id=ctx.debate_id,
                        round_num=round_num,
                    )
                except (RuntimeError, ValueError, TypeError, AttributeError) as e:
                    logger.debug("Position recording failed: %s", e)

    def on_debate_complete(
        self,
        ctx: DebateContext,
        result: DebateResult,
    ) -> None:
        """Called when a debate completes.

        Updates all tracking subsystems with debate outcome.

        Args:
            ctx: The debate context
            result: The final debate result
        """
        # Update consensus memory
        if self.consensus_memory and result:
            try:
                # Get task from environment
                task = ctx.env.task if ctx.env else ""
                consensus_text = getattr(result, "consensus", "") or ""
                confidence = getattr(result, "consensus_confidence", 0.0)
                participants = [a.name for a in ctx.agents] if ctx.agents else []

                # Import ConsensusStrength for the call
                from aragora.memory.consensus import ConsensusStrength

                # Determine strength based on confidence
                if confidence >= 0.9:
                    strength = ConsensusStrength.UNANIMOUS
                elif confidence >= 0.8:
                    strength = ConsensusStrength.STRONG
                elif confidence >= 0.6:
                    strength = ConsensusStrength.MODERATE
                elif confidence >= 0.5:
                    strength = ConsensusStrength.WEAK
                else:
                    strength = ConsensusStrength.SPLIT

                self.consensus_memory.store_consensus(
                    topic=task,
                    conclusion=consensus_text,
                    strength=strength,
                    confidence=confidence,
                    participating_agents=participants,
                    agreeing_agents=participants,  # Simplified: assume all agree at consensus
                    metadata={"debate_id": ctx.debate_id},
                )
            except Exception as e:  # noqa: BLE001 - graceful degradation, consensus memory update is non-critical
                logger.warning("Consensus memory update failed: %s", e)

        # Update calibration if agents made predictions
        if self.calibration_tracker and result:
            try:
                # Record prediction outcomes for calibration
                predictions: dict[str, Any] = getattr(result, "predictions", {})
                actual_outcome = getattr(result, "consensus", "")
                for agent_name, prediction in predictions.items():
                    # CalibrationTracker.record_prediction expects:
                    # (agent, confidence, correct, domain, debate_id, position_id)
                    predicted_value = (
                        prediction.get("prediction", "")
                        if isinstance(prediction, dict)
                        else str(prediction)
                    )
                    pred_confidence = (
                        prediction.get("confidence", 0.5) if isinstance(prediction, dict) else 0.5
                    )
                    is_correct = predicted_value == actual_outcome
                    self.calibration_tracker.record_prediction(
                        agent=agent_name,
                        confidence=pred_confidence,
                        correct=is_correct,
                        domain=ctx.domain,
                        debate_id=ctx.debate_id,
                    )
            except (RuntimeError, ValueError, TypeError, AttributeError, KeyError) as e:
                logger.debug("Calibration update failed: %s", e)

        # SDPO retrospective learning from debate trajectory
        if self.sdpo_learner and result:
            try:
                trajectory = self._build_sdpo_trajectory(ctx, result)
                if trajectory is not None:
                    self._schedule_async(self._process_sdpo_trajectory(trajectory))
            except Exception as e:  # noqa: BLE001 - graceful degradation, SDPO learning is non-critical
                logger.debug("SDPO trajectory processing failed: %s", e)

        # Update continuum memory with debate outcome
        if self.continuum_memory and result:
            try:
                # ContinuumMemory uses add() method
                # Store the debate outcome as a memory entry
                task = ctx.env.task if ctx.env else ""
                consensus_text = getattr(result, "consensus", "") or ""
                confidence = getattr(result, "consensus_confidence", 0.0)

                from aragora.memory.continuum import MemoryTier

                self.continuum_memory.add(
                    id=f"debate:{ctx.debate_id}",
                    content=f"Debate outcome: {consensus_text[:200]}",
                    tier=MemoryTier.MEDIUM,
                    importance=confidence,
                    metadata={
                        "debate_id": ctx.debate_id,
                        "task": task,
                        "consensus": consensus_text,
                        "confidence": confidence,
                    },
                )
            except Exception as e:  # noqa: BLE001 - graceful degradation, continuum memory update is non-critical
                logger.debug("Continuum memory update failed: %s", e)

        # Update selection feedback loop with debate outcome
        if self.selection_feedback_loop and result:
            try:
                participants = [a.name for a in ctx.agents] if ctx.agents else []
                winner = getattr(result, "winner", None)
                if isinstance(winner, str):
                    winner_name = winner
                else:
                    winner_name = getattr(winner, "name", None) if winner else None
                confidence = getattr(result, "consensus_confidence", 0.0)

                self.selection_feedback_loop.process_debate_outcome(
                    debate_id=ctx.debate_id,
                    participants=participants,
                    winner=winner_name,
                    domain=getattr(ctx, "domain", "general") or "general",
                    confidence=confidence,
                )
            except (RuntimeError, ValueError, TypeError, AttributeError) as e:
                logger.debug("Selection feedback loop update failed: %s", e)

    # ---------------------------------------------------------------------
    # SDPO helpers
    # ---------------------------------------------------------------------

    def _schedule_async(self, coro: Any) -> None:
        """Schedule an async task without blocking."""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
            task.add_done_callback(
                lambda t: logger.error(
                    "Debate subsystem async task failed: %s",
                    t.exception(),
                )
                if not t.cancelled() and t.exception()
                else None
            )
        except RuntimeError:
            try:
                asyncio.run(coro)
            except (RuntimeError, ValueError, TypeError) as e:
                logger.debug("Failed to run async task: %s", e)

    def _build_sdpo_trajectory(
        self,
        ctx: DebateContext,
        result: DebateResult,
    ) -> TrajectoryRecord | None:
        """Construct an SDPO trajectory from debate messages."""
        try:
            from aragora.agents.learning.sdpo import TrajectoryRecord, ActionType
        except (ImportError, AttributeError) as e:
            logger.debug("SDPO types unavailable: %s", e)
            return None

        task = ctx.env.task if ctx.env else getattr(result, "task", "") or ""
        started_at = (
            datetime.fromtimestamp(ctx.start_time, tz=timezone.utc)
            if getattr(ctx, "start_time", 0)
            else datetime.now(timezone.utc)
        )

        trajectory = TrajectoryRecord(
            id=f"traj_{ctx.debate_id}",
            task=task,
            started_at=started_at,
        )

        role_map = {
            "proposer": ActionType.PROPOSE,
            "critic": ActionType.CRITIQUE,
            "synthesizer": ActionType.SYNTHESIZE,
            "judge": ActionType.JUDGE,
        }

        for msg in getattr(result, "messages", []) or []:
            action = role_map.get(getattr(msg, "role", ""), ActionType.OTHER)
            trajectory.record_step(
                agent=getattr(msg, "agent", "unknown"),
                action=action,
                content=getattr(msg, "content", ""),
                confidence=0.5,
                metadata={
                    "round": getattr(msg, "round", 0),
                    "timestamp": getattr(msg, "timestamp", None),
                },
            )

        raw_conf = getattr(result, "confidence", None)
        if not isinstance(raw_conf, (int, float)):
            raw_conf = getattr(result, "consensus_confidence", None)
        if not isinstance(raw_conf, (int, float)):
            raw_conf = 0.0
        confidence = float(raw_conf)
        success = bool(getattr(result, "consensus_reached", False) or False)
        raw_feedback = getattr(result, "final_answer", None)
        if not isinstance(raw_feedback, str):
            raw_feedback = None
        raw_consensus = getattr(result, "consensus", None)
        if not isinstance(raw_consensus, str):
            raw_consensus = ""
        feedback = raw_feedback or raw_consensus

        trajectory.set_outcome(
            success=success,
            quality_score=confidence,
            feedback=feedback or "",
            metadata={
                "debate_id": ctx.debate_id,
                "consensus_reached": success,
                "confidence": confidence,
            },
        )

        return trajectory

    async def _process_sdpo_trajectory(self, trajectory: TrajectoryRecord) -> None:
        """Evaluate and persist SDPO trajectory insights."""
        if self.sdpo_learner is None:
            return

        try:
            self.sdpo_learner.buffer.add(trajectory)
            insights = await self.sdpo_learner.evaluate_trajectory(trajectory)
            if insights:
                self.sdpo_learner.update_calibration(insights)
            if self.sdpo_bridge is not None:
                await self.sdpo_bridge.sync_trajectory_to_calibration(trajectory)
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("SDPO trajectory processing failed: %s", e)

    # =========================================================================
    # Query methods
    # =========================================================================

    def get_historical_dissent(
        self,
        task: str,
        limit: int = 3,
    ) -> list[dict]:
        """Get historical minority viewpoints related to a task.

        Args:
            task: The debate task/question
            limit: Maximum number of dissenting views to return

        Returns:
            List of dissenting view records with position, agent, outcome
        """
        if not self.dissent_retriever:
            return []

        try:
            # DissentRetriever uses retrieve_for_new_debate() method
            result = self.dissent_retriever.retrieve_for_new_debate(task)
            # Extract relevant dissents from the result dict
            dissents = result.get("relevant_dissents", [])
            return dissents[:limit]
        except Exception as e:  # noqa: BLE001 - graceful degradation, return empty on error
            logger.debug("Dissent retrieval failed: %s", e)
            return []

    def get_agent_calibration_weight(self, agent_name: str) -> float:
        """Get calibration weight for an agent.

        Higher weights indicate better prediction accuracy.

        Args:
            agent_name: Name of the agent

        Returns:
            Weight between 0.5 and 2.0, default 1.0
        """
        if not self.calibration_tracker:
            return 1.0

        try:
            # CalibrationTracker uses get_calibration_summary() method
            summary = self.calibration_tracker.get_calibration_summary(agent_name)
            if summary and summary.total_predictions > 0:
                # Convert calibration score to weight
                # CalibrationSummary has brier_score (lower is better)
                # Convert: perfect (0.0) -> weight 1.5, poor (0.25) -> weight 0.8
                # Using 1 - brier_score as calibration quality
                calibration_quality = 1.0 - min(summary.brier_score, 0.5)
                return 0.5 + calibration_quality  # Range: 0.5 to 1.5
            return 1.0
        except Exception as e:  # noqa: BLE001 - graceful degradation, return default weight on error
            logger.debug("Could not get calibration weight for %s: %s", agent_name, e)
            return 1.0

    def get_continuum_context(self, task: str, limit: int = 5) -> str:
        """Get cross-debate context from continuum memory.

        Args:
            task: The debate task for context retrieval
            limit: Maximum number of relevant memories

        Returns:
            Formatted context string or empty string
        """
        if not self.continuum_memory:
            return ""

        try:
            memories = self.continuum_memory.retrieve(query=task, limit=limit)
            if not memories:
                return ""

            # Format memories for prompt injection
            # ContinuumMemory.retrieve() returns list[ContinuumMemoryEntry]
            lines = ["Relevant learnings from past debates:"]
            for mem in memories:
                # ContinuumMemoryEntry has content attribute and metadata dict
                summary = mem.metadata.get("summary", "") if mem.metadata else ""
                content = summary or mem.content
                lines.append(f"- {content}")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001 - graceful degradation, return empty on error
            logger.debug("Continuum context retrieval failed: %s", e)
            return ""

    # =========================================================================
    # Diagnostics
    # =========================================================================

    @property
    def has_hook_handlers(self) -> bool:
        """Check if hook handlers are registered."""
        return self.hook_handler_registry is not None and getattr(
            self.hook_handler_registry, "is_registered", False
        )

    def get_status(self) -> dict:
        """Get status of all subsystems.

        Returns:
            Dictionary with subsystem availability and any init errors
        """
        hook_count = 0
        if self.hook_handler_registry:
            hook_count = getattr(self.hook_handler_registry, "registered_count", 0)

        return {
            "subsystems": {
                "position_tracker": self.position_tracker is not None,
                "position_ledger": self.position_ledger is not None,
                "elo_system": self.elo_system is not None,
                "calibration_tracker": self.calibration_tracker is not None,
                "sdpo_learner": self.sdpo_learner is not None,
                "consensus_memory": self.consensus_memory is not None,
                "dissent_retriever": self.dissent_retriever is not None,
                "continuum_memory": self.continuum_memory is not None,
                "flip_detector": self.flip_detector is not None,
                "moment_detector": self.moment_detector is not None,
                "relationship_tracker": self.relationship_tracker is not None,
                "tier_analytics_tracker": self.tier_analytics_tracker is not None,
                "persona_manager": self.persona_manager is not None,
                "hook_manager": self.hook_manager is not None,
                "hook_handler_registry": self.hook_handler_registry is not None,
            },
            "capabilities": {
                "position_tracking": self.has_position_tracking,
                "elo_ranking": self.has_elo,
                "calibration": self.has_calibration,
                "sdpo": self.sdpo_learner is not None,
                "consensus_memory": self.has_consensus_memory,
                "dissent_retrieval": self.has_dissent_retrieval,
                "moment_detection": self.has_moment_detection,
                "relationship_tracking": self.has_relationship_tracking,
                "continuum_memory": self.has_continuum_memory,
                "hook_handlers": self.has_hook_handlers,
            },
            "cross_pollination_bridges": {
                "performance_router": self.has_performance_router_bridge,
                "outcome_complexity": self.has_outcome_complexity_bridge,
                "analytics_selection": self.has_analytics_selection_bridge,
                "novelty_selection": self.has_novelty_selection_bridge,
                "relationship_bias": self.has_relationship_bias_bridge,
                "rlm_selection": self.has_rlm_selection_bridge,
                "calibration_cost": self.has_calibration_cost_bridge,
            },
            "knowledge_mound": {
                "available": self.has_knowledge_mound,
                "coordinator_active": self.has_km_coordinator,
                "bidirectional_enabled": self.has_km_bidirectional,
                "adapters": {
                    "continuum": self.km_continuum_adapter is not None,
                    "elo": self.km_elo_adapter is not None,
                    "belief": self.km_belief_adapter is not None,
                    "insights": self.km_insights_adapter is not None,
                    "critique": self.km_critique_adapter is not None,
                    "pulse": self.km_pulse_adapter is not None,
                    "obsidian": self.km_obsidian_adapter is not None,
                },
                "active_adapters_count": self.active_km_adapters_count,
                "config": {
                    "sync_interval_seconds": self.km_sync_interval_seconds,
                    "min_confidence_for_reverse": self.km_min_confidence_for_reverse,
                    "parallel_sync": self.km_parallel_sync,
                },
            },
            "active_bridges_count": self.active_bridges_count,
            "hook_handlers_registered": hook_count,
            "init_errors": self._init_errors,
            "initialized": self._initialized,
        }


@dataclass
class SubsystemConfig:
    """Configuration for creating SubsystemCoordinator.

    This provides a clean way to configure subsystems before
    creating the coordinator.
    """

    # Enable flags
    enable_position_ledger: bool = False
    enable_calibration: bool = False
    enable_sdpo: bool = True
    enable_moment_detection: bool = False
    enable_hook_handlers: bool = True

    # Phase 9: Cross-Pollination Bridge enable flags
    enable_performance_feedback: bool = True
    enable_performance_router: bool = True
    enable_outcome_complexity: bool = True
    enable_analytics_selection: bool = True
    enable_novelty_selection: bool = True
    enable_relationship_bias: bool = True
    enable_rlm_selection: bool = True
    enable_calibration_cost: bool = True

    # Performance feedback config
    feedback_loop_weight: float = 0.25
    feedback_loop_decay: float = 0.9
    feedback_loop_min_debates: int = 2

    # Pre-configured subsystems (optional)
    position_tracker: Any | None = None
    position_ledger: Any | None = None
    elo_system: Any | None = None
    calibration_tracker: Any | None = None
    sdpo_learner: Any | None = None
    sdpo_bridge: Any | None = None
    sdpo_calibration_config: Any | None = None
    persona_manager: Any | None = None
    consensus_memory: Any | None = None
    dissent_retriever: Any | None = None
    continuum_memory: Any | None = None
    flip_detector: Any | None = None
    moment_detector: Any | None = None
    relationship_tracker: Any | None = None
    tier_analytics_tracker: Any | None = None
    hook_manager: Any | None = None
    hook_handler_registry: Any | None = None

    # Phase 9: Cross-Pollination Bridge sources and pre-configured bridges
    performance_monitor: Any | None = None
    agent_router: Any | None = None
    performance_router_bridge: Any | None = None
    outcome_tracker: Any | None = None
    complexity_governor: Any | None = None
    outcome_complexity_bridge: Any | None = None
    analytics_coordinator: Any | None = None
    team_selector: Any | None = None
    analytics_selection_bridge: Any | None = None
    novelty_tracker: Any | None = None
    selection_feedback_loop: Any | None = None
    novelty_selection_bridge: Any | None = None
    relationship_bias_bridge: Any | None = None
    rlm_bridge: Any | None = None
    rlm_selection_bridge: Any | None = None
    cost_tracker: Any | None = None
    calibration_cost_bridge: Any | None = None

    # Phase 10: Bidirectional Knowledge Mound Integration
    enable_km_bidirectional: bool = True  # Master switch for bidirectional sync
    enable_km_coordinator: bool = True  # Auto-create coordinator if KM available
    knowledge_mound: Any | None = None  # KnowledgeMound instance
    km_coordinator: Any | None = None  # BidirectionalCoordinator
    km_continuum_adapter: Any | None = None
    km_elo_adapter: Any | None = None
    km_belief_adapter: Any | None = None
    km_insights_adapter: Any | None = None
    km_critique_adapter: Any | None = None
    km_pulse_adapter: Any | None = None
    km_obsidian_adapter: Any | None = None
    km_sync_interval_seconds: int = 300  # 5 minutes
    km_min_confidence_for_reverse: float = 0.7
    km_parallel_sync: bool = True

    def create_coordinator(
        self,
        protocol: DebateProtocol | None = None,
        loop_id: str = "",
    ) -> SubsystemCoordinator:
        """Create SubsystemCoordinator from this configuration.

        Args:
            protocol: The debate protocol (for breakpoint config)
            loop_id: Loop ID for multi-loop scoping

        Returns:
            Configured SubsystemCoordinator instance
        """
        return SubsystemCoordinator(
            protocol=protocol,
            loop_id=loop_id,
            position_tracker=self.position_tracker,
            position_ledger=self.position_ledger,
            enable_position_ledger=self.enable_position_ledger,
            elo_system=self.elo_system,
            calibration_tracker=self.calibration_tracker,
            enable_calibration=self.enable_calibration,
            sdpo_learner=self.sdpo_learner,
            sdpo_bridge=self.sdpo_bridge,
            sdpo_calibration_config=self.sdpo_calibration_config,
            enable_sdpo=self.enable_sdpo,
            persona_manager=self.persona_manager,
            consensus_memory=self.consensus_memory,
            dissent_retriever=self.dissent_retriever,
            continuum_memory=self.continuum_memory,
            flip_detector=self.flip_detector,
            moment_detector=self.moment_detector,
            enable_moment_detection=self.enable_moment_detection,
            relationship_tracker=self.relationship_tracker,
            tier_analytics_tracker=self.tier_analytics_tracker,
            hook_manager=self.hook_manager,
            hook_handler_registry=self.hook_handler_registry,
            enable_hook_handlers=self.enable_hook_handlers,
            # Phase 9: Cross-Pollination Bridges
            enable_performance_feedback=self.enable_performance_feedback,
            feedback_loop_weight=self.feedback_loop_weight,
            feedback_loop_decay=self.feedback_loop_decay,
            feedback_loop_min_debates=self.feedback_loop_min_debates,
            performance_monitor=self.performance_monitor,
            agent_router=self.agent_router,
            performance_router_bridge=self.performance_router_bridge,
            enable_performance_router=self.enable_performance_router,
            outcome_tracker=self.outcome_tracker,
            complexity_governor=self.complexity_governor,
            outcome_complexity_bridge=self.outcome_complexity_bridge,
            enable_outcome_complexity=self.enable_outcome_complexity,
            analytics_coordinator=self.analytics_coordinator,
            team_selector=self.team_selector,
            analytics_selection_bridge=self.analytics_selection_bridge,
            enable_analytics_selection=self.enable_analytics_selection,
            novelty_tracker=self.novelty_tracker,
            selection_feedback_loop=self.selection_feedback_loop,
            novelty_selection_bridge=self.novelty_selection_bridge,
            enable_novelty_selection=self.enable_novelty_selection,
            relationship_bias_bridge=self.relationship_bias_bridge,
            enable_relationship_bias=self.enable_relationship_bias,
            rlm_bridge=self.rlm_bridge,
            rlm_selection_bridge=self.rlm_selection_bridge,
            enable_rlm_selection=self.enable_rlm_selection,
            cost_tracker=self.cost_tracker,
            calibration_cost_bridge=self.calibration_cost_bridge,
            enable_calibration_cost=self.enable_calibration_cost,
            # Phase 10: Bidirectional Knowledge Mound
            enable_km_bidirectional=self.enable_km_bidirectional,
            enable_km_coordinator=self.enable_km_coordinator,
            knowledge_mound=self.knowledge_mound,
            km_coordinator=self.km_coordinator,
            km_continuum_adapter=self.km_continuum_adapter,
            km_elo_adapter=self.km_elo_adapter,
            km_belief_adapter=self.km_belief_adapter,
            km_insights_adapter=self.km_insights_adapter,
            km_critique_adapter=self.km_critique_adapter,
            km_pulse_adapter=self.km_pulse_adapter,
            km_obsidian_adapter=self.km_obsidian_adapter,
            km_sync_interval_seconds=self.km_sync_interval_seconds,
            km_min_confidence_for_reverse=self.km_min_confidence_for_reverse,
            km_parallel_sync=self.km_parallel_sync,
        )


__all__ = ["SubsystemCoordinator", "SubsystemConfig"]
