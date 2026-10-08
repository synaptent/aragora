"""
Feedback phase for debate orchestration.

This module extracts the feedback loops logic (Phase 7) from the
Arena._run_inner() method, handling post-debate updates:
1. ELO match recording
2. Persona performance updates
3. Position ledger resolution
4. Relationship tracking
5. Moment detection
6. Debate embedding indexing
7. Flip detection
8. Continuum memory storage
9. Memory outcome updates
10. Calibration data recording
11. Genome fitness updates (Genesis)
12. Population evolution
13. Pulse outcome recording
14. Memory cleanup
15. Evolution pattern extraction
16. Risk assessment
17. Insight usage recording
18. Consensus outcome storage
19. Crux extraction
20. Training data emission (Tinker integration)
21. Coordinated memory writes (cross-system atomic)
22. Selection feedback loop (performance → selection)
23. Knowledge extraction (claims, relationships from debates)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.debate.phases.consensus_storage import ConsensusStorage
from aragora.debate.phases.feedback_calibration import CalibrationFeedback
from aragora.debate.phases.feedback_elo import EloFeedback
from aragora.debate.phases.feedback_evolution import EvolutionFeedback
from aragora.debate.phases.feedback_knowledge import KnowledgeFeedback
from aragora.debate.phases.feedback_memory import MemoryFeedback
from aragora.debate.phases.feedback_persona import PersonaFeedback
from aragora.debate.phases.training_emitter import TrainingEmitter
from aragora.protocols import (
    BroadcastPipelineProtocol,
    CalibrationTrackerProtocol,
    ConsensusMemoryProtocol,
    DebateEmbeddingsProtocol,
    EloSystemProtocol,
    EventEmitterProtocol,
    FlipDetectorProtocol,
    InsightStoreProtocol,
    MomentDetectorProtocol,
    PersonaManagerProtocol,
    PopulationManagerProtocol,
    PositionLedgerProtocol,
    PromptEvolverProtocol,
    PulseManagerProtocol,
    RelationshipTrackerProtocol,
    TieredMemoryProtocol,
)

if TYPE_CHECKING:
    from aragora.core import Agent
    from aragora.debate.context import DebateContext
    from aragora.memory.consensus import ConsensusStrength

logger = logging.getLogger(__name__)


class FeedbackPhase:
    """
    Executes post-debate feedback loops.

    This class encapsulates all the feedback logic that was previously
    in the final ~200 lines of Arena._run_inner().

    Usage:
        feedback = FeedbackPhase(
            elo_system=arena.elo_system,
            persona_manager=arena.persona_manager,
            position_ledger=arena.position_ledger,
            relationship_tracker=arena.relationship_tracker,
            moment_detector=arena.moment_detector,
            debate_embeddings=arena.debate_embeddings,
            flip_detector=arena.flip_detector,
            continuum_memory=arena.continuum_memory,
            event_emitter=arena.event_emitter,
        )
        await feedback.execute(ctx)
    """

    def __init__(
        self,
        elo_system: EloSystemProtocol | None = None,
        persona_manager: PersonaManagerProtocol | None = None,
        position_ledger: PositionLedgerProtocol | None = None,
        relationship_tracker: RelationshipTrackerProtocol | None = None,
        moment_detector: MomentDetectorProtocol | None = None,
        debate_embeddings: DebateEmbeddingsProtocol | None = None,
        flip_detector: FlipDetectorProtocol | None = None,
        continuum_memory: TieredMemoryProtocol | None = None,
        event_emitter: EventEmitterProtocol | None = None,
        loop_id: str | None = None,
        # Callbacks for orchestrator methods
        emit_moment_event: Callable[[Any], None] | None = None,
        store_debate_outcome_as_memory: Callable[[Any], None] | None = None,
        update_continuum_memory_outcomes: Callable[[Any], None] | None = None,
        index_debate_async: Callable[[dict[str, Any]], Any] | None = None,
        # ConsensusMemory for storing historical outcomes
        consensus_memory: ConsensusMemoryProtocol | None = None,
        # CalibrationTracker for prediction accuracy
        calibration_tracker: CalibrationTrackerProtocol | None = None,
        # Genesis evolution
        population_manager: PopulationManagerProtocol | None = None,
        auto_evolve: bool = True,
        breeding_threshold: float = 0.8,
        # Pulse manager for trending topic analytics
        pulse_manager: PulseManagerProtocol | None = None,
        # Prompt evolution for learning from debates
        prompt_evolver: PromptEvolverProtocol | None = None,
        # Insight store for tracking applied insights
        insight_store: InsightStoreProtocol | None = None,
        # Training data export for Tinker integration
        training_exporter: Callable[[list[dict[str, Any]], str], Any] | None = None,
        # Broadcast auto-trigger for high-quality debates
        broadcast_pipeline: BroadcastPipelineProtocol | None = None,
        auto_broadcast: bool = False,
        broadcast_min_confidence: float = 0.8,
        # Knowledge Mound integration
        knowledge_mound: Any | None = None,  # KnowledgeMound for unified knowledge ingestion
        enable_knowledge_ingestion: bool = True,  # Store debate outcomes in mound
        ingest_debate_outcome: Callable[[Any], Any] | None = None,  # Callback to ingest outcome
        knowledge_bridge_hub: Any | None = None,  # KnowledgeBridgeHub for bridge access
        # Memory Coordination (cross-system atomic writes)
        memory_coordinator: Any | None = None,  # MemoryCoordinator for atomic writes
        enable_coordinated_writes: bool = True,  # Use coordinator instead of individual writes
        coordinator_options: Any | None = None,  # CoordinatorOptions for behavior
        # Selection Feedback Loop
        selection_feedback_loop: Any
        | None = None,  # SelectionFeedbackLoop for performance feedback
        enable_performance_feedback: bool = True,  # Update selection weights based on performance
        # Post-debate workflow automation
        post_debate_workflow: Any | None = None,  # Workflow DAG to trigger after debates
        enable_post_debate_workflow: bool = False,  # Auto-trigger workflow after debates
        post_debate_workflow_threshold: float = 0.7,  # Min confidence to trigger workflow
        # Knowledge extraction from debates (auto-extract claims/relationships)
        enable_knowledge_extraction: bool = True,  # Extract structured knowledge from debates
        extraction_min_confidence: float = 0.3,  # Min debate confidence to trigger extraction
        extraction_promote_threshold: float = 0.6,  # Min claim confidence to promote to mound
        # Auto-receipt generation for SME starter pack
        enable_auto_receipt: bool = True,  # Generate DecisionReceipt after debate
        auto_post_receipt: bool = False,  # Post receipt summary to originating channel
        cost_tracker: Any | None = None,  # CostTracker for populating cost data in receipt
        receipt_base_url: str = "/api/v2/receipts",  # Base URL for receipt links
        # Genesis Ledger for cryptographic debate provenance
        genesis_ledger: Any | None = None,  # GenesisLedger for immutable event recording
        # Meta-Learning for self-tuning hyperparameters
        meta_learner: Any | None = None,  # MetaLearner for auto-tuning learning hyperparameters
        enable_meta_learning: bool = True,  # Evaluate and adjust after each debate
        # Argument Map export
        argument_cartographer: Any
        | None = None,  # ArgumentCartographer for auto-exporting debate maps
    ):
        """
        Initialize the feedback phase.

        Args:
            elo_system: Optional ELOSystem for ranking updates
            persona_manager: Optional PersonaManager for performance tracking
            position_ledger: Optional PositionLedger for position resolution
            relationship_tracker: Optional RelationshipTracker
            moment_detector: Optional MomentDetector for narrative moments
            debate_embeddings: Optional DebateEmbeddings for indexing
            flip_detector: Optional FlipDetector for position flips
            continuum_memory: Optional ContinuumMemory for learning
            event_emitter: Optional EventEmitter for WebSocket events
            loop_id: Optional loop ID for event correlation
            emit_moment_event: Callback to emit moment events
            store_debate_outcome_as_memory: Callback to store debate outcome
            update_continuum_memory_outcomes: Callback to update memory outcomes
            index_debate_async: Async callback to index debate
            consensus_memory: Optional ConsensusMemory for storing historical outcomes
            calibration_tracker: Optional CalibrationTracker for prediction accuracy
            population_manager: Optional PopulationManager for genome fitness tracking
            auto_evolve: If True, trigger evolution after high-confidence debates
            breeding_threshold: Minimum confidence to trigger evolution (default 0.8)
            pulse_manager: Optional PulseManager for trending topic analytics
            prompt_evolver: Optional PromptEvolver for extracting winning patterns
            insight_store: Optional InsightStore for insight usage tracking
            training_exporter: Optional callback for exporting training data to Tinker
            broadcast_pipeline: Optional BroadcastPipeline for audio/video generation
            auto_broadcast: If True, trigger broadcast after high-quality debates
            broadcast_min_confidence: Minimum confidence to trigger broadcast (default 0.8)
            knowledge_mound: Optional KnowledgeMound for unified knowledge ingestion
            enable_knowledge_ingestion: If True, store debate outcomes in mound
            ingest_debate_outcome: Async callback to ingest outcome into mound
            knowledge_bridge_hub: Optional KnowledgeBridgeHub for unified bridge access
        """
        self.elo_system = elo_system
        self.persona_manager = persona_manager
        self.position_ledger = position_ledger
        self.relationship_tracker = relationship_tracker
        self.moment_detector = moment_detector
        self.debate_embeddings = debate_embeddings
        self.flip_detector = flip_detector
        self.continuum_memory = continuum_memory
        self.event_emitter = event_emitter
        self.loop_id = loop_id
        self.consensus_memory = consensus_memory
        self.calibration_tracker = calibration_tracker
        self.population_manager = population_manager
        self.auto_evolve = auto_evolve
        self.breeding_threshold = breeding_threshold
        self.pulse_manager = pulse_manager
        self.prompt_evolver = prompt_evolver
        self.insight_store = insight_store
        self.training_exporter = training_exporter
        self.broadcast_pipeline = broadcast_pipeline
        self.auto_broadcast = auto_broadcast
        self.broadcast_min_confidence = broadcast_min_confidence
        self.knowledge_mound = knowledge_mound
        self.enable_knowledge_ingestion = enable_knowledge_ingestion
        self.knowledge_bridge_hub = knowledge_bridge_hub

        # Memory Coordination
        self.memory_coordinator = memory_coordinator
        self.enable_coordinated_writes = enable_coordinated_writes
        self.coordinator_options = coordinator_options

        # Selection Feedback Loop
        self.selection_feedback_loop = selection_feedback_loop
        self.enable_performance_feedback = enable_performance_feedback

        # Post-debate workflow automation
        self.post_debate_workflow = post_debate_workflow
        self.enable_post_debate_workflow = enable_post_debate_workflow
        self.post_debate_workflow_threshold = post_debate_workflow_threshold

        # Knowledge extraction from debates
        self.enable_knowledge_extraction = enable_knowledge_extraction
        self.extraction_min_confidence = extraction_min_confidence
        self.extraction_promote_threshold = extraction_promote_threshold

        # Auto-receipt generation
        self.enable_auto_receipt = enable_auto_receipt
        self.auto_post_receipt = auto_post_receipt
        self.cost_tracker = cost_tracker
        self.receipt_base_url = receipt_base_url

        # Genesis Ledger
        self.genesis_ledger = genesis_ledger

        # Meta-Learning
        self.meta_learner = meta_learner
        self.enable_meta_learning = enable_meta_learning

        # Argument Map
        self.argument_cartographer = argument_cartographer

        # Callbacks
        self._emit_moment_event = emit_moment_event
        self._store_debate_outcome_as_memory = store_debate_outcome_as_memory
        self._update_continuum_memory_outcomes = update_continuum_memory_outcomes
        self._index_debate_async = index_debate_async
        self._ingest_debate_outcome = ingest_debate_outcome

        # Initialize helper classes for extracted logic
        self._consensus_storage = ConsensusStorage(consensus_memory=consensus_memory)
        self._training_emitter = TrainingEmitter(
            training_exporter=training_exporter,
            event_emitter=event_emitter,
            insight_store=insight_store,
            loop_id=loop_id,
        )
        self._elo_feedback = EloFeedback(
            elo_system=elo_system,
            event_emitter=event_emitter,
            loop_id=loop_id,
        )
        self._persona_feedback = PersonaFeedback(
            persona_manager=persona_manager,
            event_emitter=event_emitter,
            loop_id=loop_id,
        )
        self._evolution_feedback = EvolutionFeedback(
            population_manager=population_manager,
            prompt_evolver=prompt_evolver,
            event_emitter=event_emitter,
            elo_system=elo_system,
            loop_id=loop_id,
            auto_evolve=auto_evolve,
            breeding_threshold=breeding_threshold,
        )
        self._memory_feedback = MemoryFeedback(
            continuum_memory=continuum_memory,
            store_debate_outcome_as_memory=store_debate_outcome_as_memory,
            update_continuum_memory_outcomes=update_continuum_memory_outcomes,
            memory_coordinator=memory_coordinator,
            enable_coordinated_writes=enable_coordinated_writes,
            coordinator_options=coordinator_options,
        )
        self._calibration_feedback = CalibrationFeedback(
            calibration_tracker=calibration_tracker,
            event_emitter=event_emitter,
            knowledge_mound=knowledge_mound,
            loop_id=loop_id,
        )
        # Save direct reference to CalibrationFeedback's original _store method
        # so FeedbackPhase._store_calibration_in_mound can delegate without
        # circular calls when tests patch the FeedbackPhase version.
        self._calibration_store_impl = CalibrationFeedback._store_calibration_in_mound.__get__(
            self._calibration_feedback, CalibrationFeedback
        )
        # Wire CalibrationFeedback's mound storage through FeedbackPhase so
        # existing test patches on FeedbackPhase._store_calibration_in_mound
        # still intercept the call.  Uses instance method resolution so
        # unittest.mock.patch on the class attribute works correctly.
        _phase_ref = self
        self._calibration_feedback._store_calibration_in_mound = (  # type: ignore[method-assign]
            lambda ctx_arg, deltas: _phase_ref._store_calibration_in_mound(ctx_arg, deltas)  # type: ignore[assignment]
        )
        self._knowledge_feedback = KnowledgeFeedback(
            knowledge_mound=knowledge_mound,
            enable_knowledge_ingestion=enable_knowledge_ingestion,
            ingest_debate_outcome=ingest_debate_outcome,
            knowledge_bridge_hub=knowledge_bridge_hub,
            enable_knowledge_extraction=enable_knowledge_extraction,
            extraction_min_confidence=extraction_min_confidence,
            extraction_promote_threshold=extraction_promote_threshold,
        )

    async def execute(self, ctx: DebateContext) -> None:
        """
        Execute all feedback loops.

        Args:
            ctx: The DebateContext with completed debate
        """
        if not ctx.result:
            logger.warning("FeedbackPhase called without result")
            return

        # 1. Record ELO match results (delegated to EloFeedback)
        self._elo_feedback.record_elo_match(ctx)

        # 1b. Record voting accuracy for agents (delegated to EloFeedback)
        self._elo_feedback.record_voting_accuracy(ctx)

        # 1c. Apply learning efficiency bonuses (delegated to EloFeedback)
        self._elo_feedback.apply_learning_bonuses(ctx)

        # 1d. Apply Trickster evidence quality adjustments to ELO
        self._apply_trickster_elo_feedback(ctx)

        # 1d-2. Propagate Trickster hollow consensus flag to result metadata
        self._propagate_hollow_consensus_to_metadata(ctx)

        # 1e. Apply RhetoricalObserver quality signals to ELO
        self._apply_rhetorical_observer_feedback(ctx)

        # 2. Update PersonaManager (delegated to PersonaFeedback)
        self._persona_feedback.update_persona_performance(ctx)

        # 3. Resolve positions in PositionLedger
        self._resolve_positions(ctx)

        # 4. Update relationship metrics
        self._update_relationships(ctx)

        # 5. Detect narrative moments
        self._detect_moments(ctx)

        # 6. Index debate in embeddings
        await self._index_debate(ctx)

        # 7. Detect position flips
        self._detect_flips(ctx)

        # 8. Store debate outcome in ConsensusMemory for historical retrieval
        consensus_id = self._consensus_storage.store_consensus_outcome(ctx)
        if consensus_id:
            setattr(ctx, "_last_consensus_id", consensus_id)

        # 9. Store belief cruxes for future seeding
        self._consensus_storage.store_cruxes(ctx, consensus_id)

        # 9b. Absorb consensus into cross-debate epistemic graph
        self._memory_feedback.absorb_into_epistemic_graph(ctx)

        # 10. Store debate outcome in ContinuumMemory
        self._memory_feedback.store_memory(ctx)

        # 11. Update memory outcomes
        self._memory_feedback.update_memory_outcomes(ctx)

        # 12. Record calibration data for prediction accuracy
        self._calibration_feedback.record_calibration(ctx)

        # 12b. Bidirectional calibration feedback (consensus-based adjustment)
        self._calibration_feedback.apply_calibration_feedback(ctx)

        # 12c. Auto-calibration: treat each agent's consensus alignment as
        # a domain-specific prediction, so every debate becomes a calibration
        # event (not just explicit tournaments).
        self._calibration_feedback.record_consensus_calibration(ctx)

        # 12d. Update calibration feedback for agent selection system.
        # Computes prediction accuracy, updates Brier scores, and stores
        # calibration deltas in KnowledgeMound via CalibrationFusionAdapter.
        self._calibration_feedback.update_calibration_feedback(ctx)

        # 13. Update genome fitness for Genesis evolution (delegated to EvolutionFeedback)
        self._evolution_feedback.update_genome_fitness(ctx)

        # 13b. Record debate and fitness in GenesisLedger (cryptographic provenance)
        self._record_genesis_ledger_events(ctx)

        # 14. Maybe trigger population evolution (delegated to EvolutionFeedback)
        await self._evolution_feedback.maybe_evolve_population(ctx)

        # 14b. Promote evolved specialists to SpecialistRegistry for team selection
        self._promote_evolved_specialists(ctx)

        # 15. Record pulse outcome if debate was on a trending topic
        self._record_pulse_outcome(ctx)

        # 16. Run periodic memory cleanup
        self._memory_feedback.run_memory_cleanup(ctx)

        # 17. Record evolution patterns from high-confidence debates (delegated to EvolutionFeedback)
        self._evolution_feedback.record_evolution_patterns(ctx)

        # 18. Assess domain risks and emit warnings
        self._assess_risks(ctx)

        # 19. Record insight usage for learning loop (B2)
        await self._training_emitter.record_insight_usage(ctx)

        # 20. Emit training data for Tinker fine-tuning
        await self._training_emitter.emit_training_data(ctx)

        # 21. Ingest debate outcome into Knowledge Mound
        await self._knowledge_feedback.ingest_knowledge_outcome(ctx)

        # 22. Extract structured knowledge from debate (claims, relationships)
        await self._knowledge_feedback.extract_knowledge_from_debate(ctx)

        # 23. Store collected evidence in Knowledge Mound via EvidenceBridge
        await self._knowledge_feedback.store_evidence_in_mound(ctx)

        # 24. Observe debate for culture patterns
        await self._knowledge_feedback.observe_debate_culture(ctx)

        # 25. Auto-trigger broadcast for high-quality debates
        await self._maybe_trigger_broadcast(ctx)

        # 26. Execute coordinated memory writes (alternative to individual writes)
        await self._memory_feedback.execute_coordinated_writes(ctx)

        # 27. Update selection feedback loop with debate outcome
        await self._update_selection_feedback(ctx)

        # 28. Trigger post-debate workflow for high-quality debates
        await self._maybe_trigger_workflow(ctx)

        # 29. Generate and optionally post decision receipt
        await self._generate_and_post_receipt(ctx)

        # 30. Run PostDebateCoordinator pipeline (explain → plan → execute)
        await self._run_post_debate_coordinator(ctx)

        # 31. Validate KM entries used in debate against outcome
        await self._knowledge_feedback.validate_km_outcome(ctx)

        # 31b. Direct KM confidence reinforcement for used items
        await self._knowledge_feedback.reinforce_km_confidence(ctx)

        # 32. Update introspection data based on debate performance
        self._update_introspection_feedback(ctx)

        # 33. Evaluate and adjust meta-learning hyperparameters
        self._evaluate_meta_learning(ctx)

        # 34. Export argument map (mermaid + JSON) for debate visualization
        self._export_argument_map(ctx)

        # 35. Auto-generate DecisionMemo for completed debates
        self._generate_decision_memo(ctx)

        # 36. Record convergence speed metrics for future round optimization
        self._record_convergence_history(ctx)

        # 37. Queue outcome-driven improvement suggestions into the Nomic Loop
        self._queue_outcome_feedback(ctx)

        # 38. Synthesize cross-adapter knowledge and store back into KM
        await self._synthesize_and_store_knowledge(ctx)

    def _record_convergence_history(self, ctx: DebateContext) -> None:
        """Record convergence speed metrics for the completed debate.

        Stores the number of rounds, convergence status, and final
        similarity so that future debates on similar topics can
        estimate optimal round counts via the convergence history store.
        """
        result = ctx.result
        if not result:
            return

        try:
            from aragora.debate.convergence.history import get_convergence_history_store

            store = get_convergence_history_store()
            if store is None:
                return

            topic = ctx.env.task
            total_rounds = getattr(result, "rounds_used", 0) or 0
            final_similarity = getattr(ctx, "convergence_similarity", 0.0) or 0.0
            converged_early = getattr(ctx, "converged_early", False)

            # Determine convergence round
            convergence_round = 0
            if converged_early and total_rounds > 0:
                convergence_round = total_rounds
            elif getattr(ctx, "convergence_status", "") == "converged":
                convergence_round = total_rounds

            # Collect per-round similarity if available
            per_round_similarity: list[float] = getattr(ctx, "_per_round_similarity", []) or []

            store.store(
                topic=topic,
                convergence_round=convergence_round,
                total_rounds=total_rounds,
                final_similarity=final_similarity,
                per_round_similarity=per_round_similarity,
                debate_id=ctx.debate_id,
            )

            logger.info(
                "[convergence_history] Recorded metrics: rounds=%d/%d, "
                "similarity=%.2f, converged=%s",
                convergence_round,
                total_rounds,
                final_similarity,
                converged_early or ctx.convergence_status == "converged",
            )

        except ImportError:
            pass  # Convergence history store not available
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[convergence_history] Failed to record metrics: %s", e)

    def _queue_outcome_feedback(self, ctx: DebateContext) -> None:
        """Queue outcome-driven improvement suggestions into the Nomic Loop.

        When auto_outcome_feedback is enabled in the protocol's post-debate
        config, analyzes systematic errors from past outcomes and queues
        improvement goals for the MetaPlanner to act on.
        """
        protocol = getattr(ctx, "protocol", None)
        post_config = getattr(protocol, "post_debate_config", None)
        if not post_config or not getattr(post_config, "auto_outcome_feedback", False):
            return

        try:
            from aragora.nomic.outcome_feedback import OutcomeFeedbackBridge

            bridge = OutcomeFeedbackBridge()
            queued = bridge.queue_improvement_suggestions()
            if queued:
                logger.info(
                    "[outcome_feedback] Queued %d improvement suggestions from debate %s",
                    queued,
                    ctx.debate_id,
                )
        except (ImportError, OSError) as e:
            logger.debug("[outcome_feedback] OutcomeFeedbackBridge not available: %s", e)
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[outcome_feedback] Feedback queueing failed: %s", e)

    async def _synthesize_and_store_knowledge(self, ctx: DebateContext) -> None:
        """Synthesize cross-adapter knowledge and store the result back into KM.

        After all adapters have written debate outcomes, runs cross-adapter
        synthesis to produce a consolidated knowledge summary. This summary is
        stored as a fact node in KnowledgeMound so that future debates benefit
        from accumulated synthesis (not just raw adapter data).
        """
        if not self.knowledge_bridge_hub or not self.knowledge_mound:
            return

        topic = getattr(ctx.env, "task", None)
        if not topic:
            return

        try:
            import asyncio

            synthesis = await asyncio.wait_for(
                self.knowledge_bridge_hub.synthesize_for_debate(
                    topic=topic,
                    domain=getattr(ctx.env, "domain", "general"),
                    max_items=8,
                ),
                timeout=8.0,
            )

            if not synthesis or len(synthesis) < 20:
                return

            # Store synthesis result as a fact node for future debate enrichment
            debate_id = getattr(ctx, "debate_id", "unknown")
            try:
                from aragora.knowledge.mound.adapters.factory import get_adapter

                insight_adapter = get_adapter("insights", self.knowledge_mound)
                if insight_adapter and hasattr(insight_adapter, "store"):
                    insight_adapter.store(
                        {
                            "content": synthesis[:2000],
                            "source": f"cross-adapter-synthesis-{debate_id}",
                            "confidence": getattr(ctx.result, "confidence", 0.5),
                            "metadata": {
                                "type": "synthesis",
                                "debate_id": debate_id,
                                "topic": topic[:200],
                            },
                        }
                    )
                    logger.info(
                        "[km_synthesis] Stored cross-adapter synthesis for debate %s (%d chars)",
                        debate_id,
                        len(synthesis),
                    )
            except (ImportError, AttributeError, TypeError, ValueError) as e:
                logger.debug("[km_synthesis] Storage failed: %s", e)

        except asyncio.TimeoutError:
            logger.debug("[km_synthesis] Synthesis timed out for topic: %s", topic[:100])
        except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.debug("[km_synthesis] Synthesis failed: %s", e)

    def _update_introspection_feedback(self, ctx: DebateContext) -> None:
        """Update agent introspection data based on debate performance.

        Records debate outcomes back into persona/reputation data so that
        introspection snapshots evolve across debates. Agents that perform
        well in specific domains get their expertise scores boosted.
        """
        if not self.persona_manager:
            return

        result = ctx.result
        if not result:
            return

        try:
            agents = ctx.agents or []
            winner = getattr(result, "winner", None)
            consensus = result.consensus_reached

            for agent in agents:
                agent_name = agent.name if hasattr(agent, "name") else str(agent)
                is_winner = winner and agent_name == getattr(winner, "name", winner)

                if hasattr(self.persona_manager, "record_debate_outcome"):
                    self.persona_manager.record_debate_outcome(
                        agent_name=agent_name,
                        won=is_winner,
                        consensus_reached=consensus,
                        domain=getattr(ctx.env, "domain", "general") if ctx.env else "general",
                    )
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            logger.debug("[introspection] Feedback update failed: %s", e)

    def _evaluate_meta_learning(self, ctx: DebateContext) -> None:
        """Evaluate learning efficiency and auto-tune hyperparameters.

        Uses MetaLearner to:
        1. Evaluate pattern retention, forgetting rate, tier efficiency
        2. Adjust surprise weights, tier thresholds, decay half-lives
        3. Apply tuned hyperparameters back to ContinuumMemory
        """
        if not self.meta_learner or not self.enable_meta_learning:
            return

        result = ctx.result
        if not result:
            return

        try:
            cycle_results: dict[str, Any] = {
                "cycle": getattr(ctx, "debate_number", 1),
                "consensus_rate": 1.0 if result.consensus_reached else 0.0,
                "avg_calibration": getattr(result, "avg_calibration", 0.5),
                "confidence": getattr(result, "confidence", 0.5),
                "rounds": getattr(result, "rounds_completed", 0),
            }

            # Add debate-level metrics for tuning
            protocol = getattr(ctx, "protocol", None)
            max_rounds = getattr(protocol, "rounds", 3) or 3
            rounds_completed = getattr(result, "rounds_completed", max_rounds)
            cycle_results["debate_efficiency"] = (
                rounds_completed / max_rounds if max_rounds > 0 else 1.0
            )

            agents = getattr(ctx, "agents", []) or []
            unique_models = len(set(getattr(a, "model", str(a)) for a in agents)) if agents else 1
            cycle_results["agent_diversity_score"] = unique_models / max(len(agents), 1)
            cycle_results["avg_confidence"] = getattr(result, "confidence", 0.5)

            metrics = self.meta_learner.evaluate_learning_efficiency(
                self.continuum_memory, cycle_results
            )

            adjustments = self.meta_learner.adjust_hyperparameters(metrics)

            if adjustments:
                logger.info(
                    "[meta_learning] Adjusted hyperparameters: %s",
                    "; ".join(f"{k}: {v}" for k, v in adjustments.items()),
                )

                if self.continuum_memory and hasattr(self.continuum_memory, "hyperparams"):
                    tuned = self.meta_learner.get_current_hyperparams()
                    for key, value in tuned.items():
                        if hasattr(self.continuum_memory.hyperparams, key):
                            setattr(self.continuum_memory.hyperparams, key, value)
                    logger.debug(
                        "[meta_learning] Applied %d tuned params to ContinuumMemory",
                        len(tuned),
                    )

            # Store debate tuning for team_selector
            try:
                arena = getattr(ctx, "arena", None)
                if arena and hasattr(self.meta_learner, "get_debate_tuning"):
                    arena._meta_tuning = self.meta_learner.get_debate_tuning()
            except (AttributeError, TypeError):
                pass
        except (TypeError, ValueError, AttributeError, RuntimeError, OSError) as e:
            logger.debug("[meta_learning] Evaluation failed: %s", e)

    def _export_argument_map(self, ctx: DebateContext) -> None:
        """Export argument map as mermaid and JSON for debate visualization.

        When an ArgumentCartographer is available, exports:
        - Mermaid diagram for rendering in docs/dashboards
        - JSON graph for API access and replay
        Emits an event with the exported data for real-time clients.
        """
        if not self.argument_cartographer:
            return

        result = ctx.result
        if not result:
            return

        try:
            debate_id = getattr(result, "id", None) or getattr(ctx, "debate_id", "unknown")
            node_count = len(getattr(self.argument_cartographer, "nodes", {}))
            if node_count == 0:
                return

            mermaid = self.argument_cartographer.export_mermaid()
            self.argument_cartographer.export_json()

            logger.info(
                "[argument_map] Exported map for debate %s: %d nodes, %d edges",
                debate_id,
                node_count,
                len(getattr(self.argument_cartographer, "edges", [])),
            )

            # Emit event for real-time clients
            if self.event_emitter:
                try:
                    from aragora.events.types import StreamEvent, StreamEventType

                    self.event_emitter.emit(
                        StreamEvent(
                            type=StreamEventType.ARGUMENT_MAP_UPDATED,
                            data={
                                "debate_id": debate_id,
                                "mermaid": mermaid[:2000],  # Truncate for event payload
                                "node_count": node_count,
                                "edge_count": len(getattr(self.argument_cartographer, "edges", [])),
                            },
                        )
                    )
                except (ImportError, AttributeError, TypeError):
                    pass
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[argument_map] Export failed: %s", e)

    def _generate_decision_memo(self, ctx: DebateContext) -> None:
        """Auto-generate DecisionMemo for completed debates.

        Creates a structured summary of debate conclusions for
        stakeholder communication and the decision-to-PR pipeline.
        """
        result = ctx.result
        if not result:
            return

        try:
            from aragora.pipeline.pr_generator import DecisionMemo

            debate_id = getattr(result, "id", None) or getattr(ctx, "debate_id", "unknown")
            task = getattr(ctx.env, "task", "") if ctx.env else ""

            proposals = getattr(result, "proposals", {})
            key_decisions = []
            if isinstance(proposals, dict):
                for agent, proposal in list(proposals.items())[:3]:
                    key_decisions.append(f"[{agent}] {str(proposal)[:200]}")

            dissenting = []
            for critique in getattr(result, "critiques", [])[:3]:
                dissenting.append(getattr(critique, "text", str(critique))[:150])

            memo = DecisionMemo(
                debate_id=debate_id,
                title=task[:100] if task else "Untitled debate",
                summary=getattr(result, "final_answer", "") or "",
                key_decisions=key_decisions,
                rationale=getattr(result, "rationale", "") or "",
                supporting_evidence=[],
                dissenting_views=dissenting,
                open_questions=[],
                consensus_confidence=getattr(result, "confidence", 0.0),
                rounds_used=getattr(result, "rounds_used", 0),
                agent_count=len(getattr(ctx, "agents", []) or []),
            )

            if hasattr(result, "metadata") and isinstance(result.metadata, dict):
                result.metadata["decision_memo"] = memo
            logger.info(
                "[pipeline] Generated DecisionMemo for debate %s (%.0f%% confidence)",
                debate_id,
                memo.consensus_confidence * 100,
            )
        except (ImportError, TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[pipeline] DecisionMemo generation failed: %s", e)

    async def _maybe_trigger_workflow(self, ctx: DebateContext) -> None:
        """Trigger post-debate workflow for high-quality debates.

        When enabled via enable_post_debate_workflow, this method:
        1. Checks if debate confidence meets workflow threshold
        2. Triggers the workflow engine asynchronously (fire-and-forget)
        3. Logs success/failure without blocking debate completion

        Workflows can be used for automated refinement, documentation,
        knowledge extraction, or other post-debate processing.
        """
        if not self.post_debate_workflow or not self.enable_post_debate_workflow:
            return

        result = ctx.result
        if not result:
            return

        # Check confidence threshold
        confidence = getattr(result, "confidence", 0.0)
        if confidence < self.post_debate_workflow_threshold:
            logger.debug(
                "[workflow] Skipping workflow: confidence %.2f < threshold %.2f",
                confidence,
                self.post_debate_workflow_threshold,
            )
            return

        # Fire-and-forget workflow to not block debate completion
        _wf_task = asyncio.create_task(self._run_workflow_async(ctx))
        _wf_task.add_done_callback(
            lambda t: logger.warning("[workflow] Post-debate workflow failed: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )
        ctx.post_debate_workflow_triggered = True  # type: ignore[attr-defined]
        logger.info(
            "[workflow] Triggered post-debate workflow for debate %s (confidence=%.2f)",
            ctx.debate_id,
            confidence,
        )

    async def _run_workflow_async(self, ctx: DebateContext) -> None:
        """Run workflow engine asynchronously.

        This is a fire-and-forget task so it doesn't block debate completion.
        Failures are logged but don't affect the debate result.
        """
        try:
            from aragora.workflow.engine import get_workflow_engine

            engine = get_workflow_engine()
            workflow_input = {
                "debate_id": ctx.debate_id,
                "task": ctx.env.task,
                "result": {
                    "winner": ctx.result.winner if ctx.result else None,
                    "confidence": ctx.result.confidence if ctx.result else 0.0,
                    "consensus_reached": ctx.result.consensus_reached if ctx.result else False,
                    "final_answer": ctx.result.final_answer if ctx.result else "",
                },
                "domain": ctx.domain,
                "agents": [a.name for a in ctx.agents] if ctx.agents else [],
            }

            workflow_result = await engine.execute(
                definition=self.post_debate_workflow,
                inputs=workflow_input,
            )

            if workflow_result.success:
                logger.info(
                    "[workflow] Completed workflow for %s: output=%s",
                    ctx.debate_id,
                    str(workflow_result.final_output)[:200]
                    if workflow_result.final_output
                    else "None",
                )
            else:
                logger.warning(
                    "[workflow] Workflow failed for %s: %s",
                    ctx.debate_id,
                    workflow_result.error,
                )

        except ImportError:
            logger.debug("[workflow] WorkflowEngine not available")
        except Exception as e:  # noqa: BLE001 - phase isolation
            logger.warning("[workflow] Post-debate workflow failed: %s", e)

    async def _generate_and_post_receipt(self, ctx: DebateContext) -> Any | None:
        """Generate decision receipt and optionally post to originating channel.

        When enabled via enable_auto_receipt, this method:
        1. Creates a DecisionReceipt from the DebateResult
        2. Includes cost data if cost_tracker is available
        3. Stores the receipt in the receipt store
        4. Optionally posts a summary to the originating chat channel

        Args:
            ctx: The DebateContext with completed debate

        Returns:
            DecisionReceipt if generated, None otherwise
        """
        if not self.enable_auto_receipt:
            return None

        result = ctx.result
        if not result:
            return None

        try:
            from aragora.gauntlet.receipt_models import DecisionReceipt

            # Build cost summary from DebateCostTracker if available
            cost_summary = None
            if self.cost_tracker:
                try:
                    from aragora.billing.debate_costs import get_debate_cost_tracker

                    dct = get_debate_cost_tracker()
                    summary = dct.get_debate_cost(ctx.debate_id)
                    if summary and summary.total_calls > 0:
                        cost_summary = summary.to_dict()
                except (ImportError, TypeError, ValueError, AttributeError) as e:
                    logger.debug("[receipt] DebateCostTracker cost extraction failed: %s", e)

                # Fallback: build minimal cost_summary from CostTracker buffer
                if cost_summary is None:
                    try:
                        debate_costs = await self.cost_tracker.get_debate_cost(ctx.debate_id)
                        if debate_costs and float(debate_costs.get("total_cost_usd", 0)) > 0:
                            cost_summary = debate_costs
                    except (TypeError, ValueError, AttributeError) as e:
                        logger.debug("[receipt] CostTracker cost extraction failed: %s", e)

            # Generate receipt from debate result
            receipt = DecisionReceipt.from_debate_result(
                result=result,
                cost_summary=cost_summary,
            )

            # Attach explainability data
            try:
                from aragora.explainability.builder import ExplanationBuilder

                builder = ExplanationBuilder()
                decision = await builder.build(result, ctx)
                existing_explainability = (
                    dict(receipt.explainability) if isinstance(receipt.explainability, dict) else {}
                )
                try:
                    from aragora.gauntlet.receipt_models import normalize_live_explainability

                    live_explainability = normalize_live_explainability(
                        existing_explainability.get("live_explainability")
                    )
                    if live_explainability is None:
                        existing_explainability.pop("live_explainability", None)
                    else:
                        existing_explainability["live_explainability"] = live_explainability
                except ImportError:
                    existing_explainability.pop("live_explainability", None)
                receipt.explainability = {
                    **existing_explainability,
                    "summary": builder.generate_summary(decision),
                    "evidence_chain": [e.to_dict() for e in decision.get_top_evidence(5)],
                    "vote_pivots": [v.to_dict() for v in decision.get_pivotal_votes()],
                    "confidence_attribution": [
                        c.to_dict() for c in decision.get_major_confidence_factors()
                    ],
                    "counterfactuals": [
                        c.to_dict() for c in decision.get_high_sensitivity_counterfactuals()
                    ],
                    "scores": {
                        "evidence_quality": decision.evidence_quality_score,
                        "agent_agreement": decision.agent_agreement_score,
                        "belief_stability": decision.belief_stability_score,
                    },
                }

                # Persist explanation to Knowledge Mound via ExplainabilityAdapter
                if self.enable_knowledge_extraction:
                    try:
                        from aragora.knowledge.mound.adapters.explainability_adapter import (
                            get_explainability_adapter,
                        )

                        task_str = ctx.env.task if ctx.env else ""
                        adapter = get_explainability_adapter()
                        adapter.store_explanation(decision, task=task_str)
                        logger.info(
                            "[explainability] Persisted explanation for debate %s to KM",
                            ctx.debate_id,
                        )
                    except (ImportError, RuntimeError, ValueError, TypeError) as e:
                        logger.debug("[explainability] KM persistence failed: %s", e)

            except (ImportError, RuntimeError, ValueError, TypeError) as e:
                logger.debug("[receipt] Explainability not available: %s", e)

            # Sign the receipt
            try:
                signed_receipt = receipt.sign()
                receipt_data = signed_receipt.to_dict()
            except (ImportError, ValueError) as e:
                logger.debug("[receipt] Signing failed, using unsigned: %s", e)
                receipt_data = {"receipt": receipt.to_dict()}

            # Store receipt in receipt store
            try:
                from aragora.storage.receipt_store import get_receipt_store

                store = get_receipt_store()
                store.save(receipt_data.get("receipt", receipt.to_dict()))
                logger.info(
                    "[receipt] Generated receipt %s for debate %s",
                    receipt.receipt_id,
                    ctx.debate_id,
                )
            except ImportError:
                logger.debug("[receipt] Receipt store not available")
            except Exception as e:  # noqa: BLE001 - phase isolation
                logger.warning("[receipt] Failed to store receipt: %s", e)

            # Post to originating channel if enabled
            if self.auto_post_receipt:
                try:
                    from aragora.server.debate_origin import (
                        get_debate_origin,
                        post_receipt_to_channel,
                    )

                    origin = get_debate_origin(ctx.debate_id)
                    if origin:
                        receipt_url = f"{self.receipt_base_url}/{receipt.receipt_id}"
                        await post_receipt_to_channel(origin, receipt, receipt_url)
                        logger.info(
                            "[receipt] Posted receipt to %s:%s",
                            origin.platform,
                            origin.channel_id,
                        )
                except ImportError:
                    logger.debug("[receipt] Debate origin module not available")
                except Exception as e:  # noqa: BLE001 - phase isolation
                    logger.warning("[receipt] Failed to post receipt: %s", e)

            # Store receipt reference in context
            setattr(ctx, "_last_receipt", receipt)
            return receipt

        except ImportError:
            logger.debug("[receipt] DecisionReceipt module not available")
            return None
        except Exception as e:  # noqa: BLE001 - phase isolation
            logger.warning("[receipt] Receipt generation failed: %s", e)
            return None

    async def _validate_km_outcome(self, ctx: DebateContext) -> None:
        """Validate KM outcome. Delegates to KnowledgeFeedback."""
        await self._knowledge_feedback.validate_km_outcome(ctx)

    async def _reinforce_km_confidence(self, ctx: DebateContext) -> None:
        """Reinforce KM confidence. Delegates to KnowledgeFeedback."""
        await self._knowledge_feedback.reinforce_km_confidence(ctx)

    async def _execute_coordinated_writes(self, ctx: DebateContext) -> None:
        """Execute coordinated writes. Delegates to MemoryFeedback."""
        await self._memory_feedback.execute_coordinated_writes(ctx)

    async def _update_selection_feedback(self, ctx: DebateContext) -> None:
        """Update selection feedback loop with debate outcome.

        Records debate performance metrics and computes selection weight
        adjustments for participating agents based on their performance.
        """
        if not self.selection_feedback_loop or not self.enable_performance_feedback:
            return

        result = ctx.result
        if not result:
            return

        try:
            adjustments = self.selection_feedback_loop.process_debate_outcome(
                debate_id=ctx.debate_id,
                participants=[a.name for a in ctx.agents],
                winner=result.winner,
                domain=ctx.domain,
            )

            if adjustments:
                logger.debug(
                    "[feedback] Updated selection weights for %d agents",
                    len(adjustments),
                )

                # Emit selection feedback event
                self._emit_selection_feedback_event(ctx, adjustments)

        except (ValueError, KeyError, TypeError, RuntimeError) as e:  # noqa: BLE001
            logger.debug("[feedback] Selection feedback update failed: %s", e)

    def _emit_selection_feedback_event(
        self, ctx: DebateContext, adjustments: dict[str, float]
    ) -> None:
        """Emit SELECTION_FEEDBACK event for real-time monitoring."""
        if not self.event_emitter:
            return

        try:
            from aragora.events.types import StreamEvent, StreamEventType

            self.event_emitter.emit(
                StreamEvent(
                    type=StreamEventType.SELECTION_FEEDBACK,
                    loop_id=self.loop_id,
                    data={
                        "debate_id": ctx.debate_id,
                        "adjustments": adjustments,
                        "domain": ctx.domain,
                        "winner": ctx.result.winner if ctx.result else None,
                    },
                )
            )
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            logger.debug("Selection feedback event emission error: %s", e)

    async def _ingest_knowledge_outcome(self, ctx: DebateContext) -> None:
        """Ingest knowledge outcome. Delegates to KnowledgeFeedback."""
        await self._knowledge_feedback.ingest_knowledge_outcome(ctx)

    async def _extract_knowledge_from_debate(self, ctx: DebateContext) -> None:
        """Extract knowledge from debate. Delegates to KnowledgeFeedback."""
        await self._knowledge_feedback.extract_knowledge_from_debate(ctx)

    async def _store_evidence_in_mound(self, ctx: DebateContext) -> None:
        """Store evidence in mound. Delegates to KnowledgeFeedback."""
        await self._knowledge_feedback.store_evidence_in_mound(ctx)

    async def _observe_debate_culture(self, ctx: DebateContext) -> None:
        """Observe debate culture. Delegates to KnowledgeFeedback."""
        await self._knowledge_feedback.observe_debate_culture(ctx)

    async def _maybe_trigger_broadcast(self, ctx: DebateContext) -> None:
        """Trigger broadcast for high-quality debates.

        When enabled via auto_broadcast, this method:
        1. Checks if debate confidence meets broadcast threshold
        2. Triggers the broadcast pipeline asynchronously (fire-and-forget)
        3. Logs success/failure without blocking debate completion

        This enables automatic podcast/video generation for noteworthy debates.
        """
        if not self.broadcast_pipeline or not self.auto_broadcast:
            return

        result = ctx.result
        if not result:
            return

        # Check confidence threshold
        confidence = getattr(result, "confidence", 0.0)
        if confidence < self.broadcast_min_confidence:
            logger.debug(
                "[broadcast] Skipping broadcast: confidence %.2f < threshold %.2f",
                confidence,
                self.broadcast_min_confidence,
            )
            return

        # Fire-and-forget broadcast to not block debate completion
        _broadcast_task = asyncio.create_task(self._broadcast_async(ctx))
        _broadcast_task.add_done_callback(
            lambda t: logger.warning("[broadcast] Auto-broadcast failed: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )
        logger.info(
            "[broadcast] Triggered auto-broadcast for debate %s (confidence=%.2f)",
            ctx.debate_id,
            confidence,
        )

    async def _broadcast_async(self, ctx: DebateContext) -> None:
        """Run broadcast pipeline asynchronously.

        This is a fire-and-forget task so it doesn't block debate completion.
        Failures are logged but don't affect the debate result.
        """
        pipeline = self.broadcast_pipeline
        if pipeline is None:
            return

        try:
            from aragora.broadcast.pipeline import BroadcastOptions

            options = BroadcastOptions(
                audio_enabled=True,
                generate_rss_episode=True,
            )

            pipeline_result = await pipeline.run(
                ctx.debate_id,
                options,
            )

            if pipeline_result.success:
                logger.info(
                    "[broadcast] Successfully generated broadcast for %s: audio=%s",
                    ctx.debate_id,
                    pipeline_result.audio_path,
                )
            else:
                logger.warning(
                    "[broadcast] Broadcast failed for %s: %s",
                    ctx.debate_id,
                    pipeline_result.error_message,
                )

        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.warning("[broadcast] Auto-broadcast failed: %s", e)

    def _assess_risks(self, ctx: DebateContext) -> None:
        """Assess domain-specific risks and emit RISK_WARNING events.

        Analyzes the debate topic for safety-sensitive domains (medical, legal,
        financial, etc.) and emits warnings for real-time panel updates.
        """
        if not self.event_emitter:
            return

        try:
            from aragora.debate.risk_assessor import assess_debate_risk
            from aragora.events.types import StreamEvent, StreamEventType

            # Assess risks for the debate topic
            risks = assess_debate_risk(ctx.env.task, domain=ctx.domain)

            for risk in risks:
                self.event_emitter.emit(
                    StreamEvent(
                        type=StreamEventType.RISK_WARNING,
                        loop_id=self.loop_id,
                        data={
                            "level": risk.level.value,
                            "domain": risk.domain,
                            "category": risk.category,
                            "description": risk.description,
                            "mitigations": risk.mitigations,
                            "confidence": risk.confidence,
                            "debate_id": ctx.debate_id,
                        },
                    )
                )

            if risks:
                logger.info(
                    "[risk] Identified %d risks for debate %s: %s",
                    len(risks),
                    ctx.debate_id,
                    [r.level.value for r in risks],
                )

        except ImportError:
            logger.debug("Risk assessment unavailable: module not found")
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("Risk assessment error: %s", e)

    def _record_calibration(self, ctx: DebateContext) -> None:
        """Record calibration data. Delegates to CalibrationFeedback."""
        self._calibration_feedback.record_calibration(ctx)

    def _emit_calibration_update(self, ctx: DebateContext, recorded_count: int) -> None:
        """Emit CALIBRATION_UPDATE event. Delegates to CalibrationFeedback."""
        self._calibration_feedback._emit_calibration_update(ctx, recorded_count)

    def _apply_calibration_feedback(self, ctx: DebateContext) -> None:
        """Apply calibration feedback. Delegates to CalibrationFeedback."""
        self._calibration_feedback.apply_calibration_feedback(ctx)

    def _record_consensus_calibration(self, ctx: DebateContext) -> None:
        """Record consensus calibration. Delegates to CalibrationFeedback."""
        self._calibration_feedback.record_consensus_calibration(ctx)

    def _update_calibration_feedback(self, ctx: DebateContext) -> None:
        """Update calibration feedback. Delegates to CalibrationFeedback."""
        self._calibration_feedback.update_calibration_feedback(ctx)

    def _store_calibration_in_mound(
        self,
        ctx: DebateContext,
        calibration_deltas: dict[str, dict[str, float]],
    ) -> None:
        """Store calibration in mound. Delegates to CalibrationFeedback."""
        self._calibration_store_impl(ctx, calibration_deltas)

    def _record_pulse_outcome(self, ctx: DebateContext) -> None:
        """Record pulse outcome if the debate was on a trending topic.

        This enables analytics on which trending topics lead to productive debates.
        """
        if not self.pulse_manager:
            return

        result = ctx.result
        if not result:
            return

        # Check if the debate has a trending topic attached
        trending_topic = getattr(ctx, "trending_topic", None)
        if not trending_topic:
            # Also check arena for backwards compatibility
            arena = getattr(ctx, "arena", None)
            if arena:
                trending_topic = getattr(arena, "trending_topic", None)

        if not trending_topic:
            return

        try:
            self.pulse_manager.record_debate_outcome(
                topic=getattr(trending_topic, "topic", str(trending_topic)),
                platform=getattr(trending_topic, "platform", "unknown"),
                debate_id=ctx.debate_id,
                consensus_reached=result.consensus_reached,
                confidence=result.confidence,
                rounds_used=result.rounds_used,
                category=getattr(trending_topic, "category", ""),
                volume=getattr(trending_topic, "volume", 0),
            )
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.warning("[pulse] Failed to record outcome: %s", e)

    def _run_memory_cleanup(self, ctx: DebateContext) -> None:
        """Run memory cleanup. Delegates to MemoryFeedback."""
        self._memory_feedback.run_memory_cleanup(ctx)

    # =========================================================================
    # ELO Feedback Methods (delegated to EloFeedback helper)
    # Kept for backward compatibility
    # =========================================================================

    def _record_elo_match(self, ctx: DebateContext) -> None:
        """Record ELO match results. Delegates to EloFeedback."""
        self._elo_feedback.record_elo_match(ctx)

    def _emit_match_recorded_event(self, ctx: DebateContext, participants: list[str]) -> None:
        """Emit MATCH_RECORDED event. Delegates to EloFeedback."""
        self._elo_feedback._emit_match_recorded_event(ctx, participants)

    def _record_voting_accuracy(self, ctx: DebateContext) -> None:
        """Record voting accuracy. Delegates to EloFeedback."""
        self._elo_feedback.record_voting_accuracy(ctx)

    def _apply_learning_bonuses(self, ctx: DebateContext) -> None:
        """Apply learning bonuses. Delegates to EloFeedback."""
        self._elo_feedback.apply_learning_bonuses(ctx)

    def _apply_trickster_elo_feedback(self, ctx: DebateContext) -> None:
        """Apply Trickster evidence quality signals as ELO adjustments.

        Agents that triggered trickster interventions (hollow consensus,
        evidence gaps, echo chambers) receive ELO penalties proportional
        to intervention severity. Agents with high evidence quality
        receive small bonuses via a confidence-weighted match.
        """
        if not self.elo_system:
            return

        # Get trickster from context (set by DebateRoundsPhase)
        trickster = getattr(ctx, "_trickster", None)
        if trickster is None:
            return

        try:
            # Get penalty adjustments from trickster signals
            elo_adjustments = trickster.get_elo_adjustments()
            evidence_scores = trickster.get_evidence_quality_scores()

            if not elo_adjustments and not evidence_scores:
                return

            participants = [a.name for a in ctx.agents]

            # Build match scores: evidence quality as positive signal,
            # trickster penalties as negative adjustment
            scores: dict[str, float] = {}
            for agent_name in participants:
                base_score = evidence_scores.get(agent_name, 0.5)
                penalty = elo_adjustments.get(agent_name, 0.0)
                # Combine: good evidence → higher score, penalties → lower
                scores[agent_name] = max(0.0, min(1.0, base_score + penalty))

            if scores and any(s != 0.5 for s in scores.values()):
                self.elo_system.record_match(
                    debate_id=f"{ctx.debate_id}_trickster",
                    participants=participants,
                    scores=scores,
                    domain=ctx.domain,
                    confidence_weight=0.3,  # Lower weight than main match
                )
                logger.info(
                    "trickster_elo_feedback debate=%s adjustments=%d",
                    ctx.debate_id,
                    len(elo_adjustments),
                )
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
            logger.warning("Trickster ELO feedback failed: %s", e)

    def _propagate_hollow_consensus_to_metadata(self, ctx: DebateContext) -> None:
        """Bridge Trickster hollow consensus detection to result metadata.

        PostDebateCoordinator reads result.metadata["hollow_consensus_detected"]
        to trigger staking slashes. Without this bridge, hollow consensus is
        tracked by Trickster internally but never flows to post-debate actions.
        """
        trickster = getattr(ctx, "_trickster", None)
        if trickster is None:
            return

        result = ctx.result
        if not result or not hasattr(result, "metadata"):
            return

        try:
            stats = trickster.get_stats()
            hollow_count = stats.get("hollow_alerts_detected", 0)
            if isinstance(result.metadata, dict):
                result.metadata["hollow_consensus_detected"] = hollow_count > 0
                if hollow_count > 0:
                    result.metadata["hollow_alerts_count"] = hollow_count
                    logger.info(
                        "hollow_consensus propagated to metadata: %d alerts (debate %s)",
                        hollow_count,
                        ctx.debate_id,
                    )
        except (TypeError, ValueError, AttributeError) as e:
            logger.debug("Failed to propagate hollow consensus to metadata: %s", e)

    def _apply_rhetorical_observer_feedback(self, ctx: DebateContext) -> None:
        """Apply RhetoricalObserver quality signals as ELO adjustments.

        Maps rhetorical pattern diversity and quality into per-agent scores:
        - Pattern diversity (more varied rhetoric → higher score)
        - Pattern quality (synthesis/evidence > rebuttal > questions)
        - Combined into a confidence-weighted ELO match (weight=0.2)
        """
        if not self.elo_system:
            return

        rhetorical_observer = getattr(ctx, "_rhetorical_observer", None)
        if rhetorical_observer is None:
            return

        try:
            dynamics = rhetorical_observer.get_debate_dynamics()
            agent_styles = dynamics.get("agent_styles", {})
            if not agent_styles:
                return

            participants = [a.name for a in ctx.agents]
            scores: dict[str, float] = {}

            # Quality boost per dominant rhetorical pattern
            _pattern_boost: dict[str, float] = {
                "synthesis": 0.15,
                "appeal_to_evidence": 0.12,
                "appeal_to_authority": 0.10,
                "technical_depth": 0.08,
                "concession": 0.05,
                "qualification": 0.03,
                "analogy": 0.05,
                "rebuttal": 0.0,
                "rhetorical_question": -0.02,
            }

            for agent_name in participants:
                style_info = agent_styles.get(agent_name, {})
                base_score = 0.5  # neutral baseline
                # Diversity bonus: +0.05 per unique pattern, max +0.2
                diversity = style_info.get("pattern_diversity", 0)
                base_score += min(0.2, diversity * 0.05)
                # Pattern quality bonus
                dominant = style_info.get("dominant_pattern", "")
                base_score += _pattern_boost.get(dominant, 0.0)
                scores[agent_name] = max(0.0, min(1.0, base_score))

            if scores and any(s != 0.5 for s in scores.values()):
                self.elo_system.record_match(
                    debate_id=f"{ctx.debate_id}_rhetorical",
                    participants=participants,
                    scores=scores,
                    domain=ctx.domain,
                    confidence_weight=0.2,  # Lower weight than trickster (0.3)
                )
                logger.info(
                    "rhetorical_observer_elo_feedback debate=%s agents=%d",
                    ctx.debate_id,
                    len(scores),
                )
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
            logger.warning("RhetoricalObserver ELO feedback failed: %s", e)

    async def _run_post_debate_coordinator(self, ctx: DebateContext) -> None:
        """Run PostDebateCoordinator pipeline: explain → plan → notify → execute.

        Bridges debate consensus into the implementation pipeline by creating
        a DecisionPlan from the debate result and optionally executing it
        through the ExecutionBridge. This closes the debate→action loop.
        """
        coordinator = getattr(ctx, "_post_debate_coordinator", None)
        if coordinator is None:
            return

        result = ctx.result
        if not result:
            return

        try:
            confidence = getattr(result, "confidence", 0.0)
            task_str = ctx.env.task if ctx.env else ""

            coordinator_result = coordinator.run(
                debate_id=ctx.debate_id,
                debate_result=result,
                agents=ctx.agents,
                confidence=confidence,
                task=task_str,
            )

            # Store result on context for downstream access
            ctx._post_debate_result = coordinator_result  # type: ignore[attr-defined]

            if coordinator_result.success:
                logger.info(
                    "post_debate_coordinator debate=%s plan=%s exec=%s",
                    ctx.debate_id,
                    coordinator_result.plan is not None,
                    coordinator_result.execution_result is not None,
                )

                # If a plan was created but not auto-executed, store it for
                # later execution via the ExecutionBridge
                if coordinator_result.plan and not coordinator_result.execution_result:
                    await self._store_pending_plan(ctx, coordinator_result.plan)
            else:
                logger.warning(
                    "post_debate_coordinator errors debate=%s: %s",
                    ctx.debate_id,
                    coordinator_result.errors,
                )
        except ImportError:
            logger.debug("PostDebateCoordinator dependencies not available")
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.warning("PostDebateCoordinator failed: %s", e)

    async def _store_pending_plan(self, ctx: DebateContext, plan_data: dict[str, Any]) -> None:
        """Store a plan created by PostDebateCoordinator for later execution.

        Plans that aren't auto-executed get persisted to the PlanStore
        so they can be approved and executed via ExecutionBridge later.
        """
        try:
            from aragora.pipeline.stores import get_plan_store

            store = get_plan_store()
            plan_obj = plan_data.get("plan")
            if plan_obj and hasattr(plan_obj, "id"):
                await store.save(plan_obj)
                logger.info(
                    "pending_plan_stored debate=%s plan=%s",
                    ctx.debate_id,
                    plan_obj.id,
                )
        except ImportError:
            logger.debug("PlanStore not available for pending plan storage")
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.warning("Failed to store pending plan: %s", e)

    # =========================================================================
    # Persona Feedback Methods (delegated to PersonaFeedback helper)
    # Kept for backward compatibility
    # =========================================================================

    def _update_persona_performance(self, ctx: DebateContext) -> None:
        """Update PersonaManager. Delegates to PersonaFeedback."""
        self._persona_feedback.update_persona_performance(ctx)

    def _check_trait_emergence(self, ctx: DebateContext) -> None:
        """Check trait emergence. Delegates to PersonaFeedback."""
        self._persona_feedback.check_trait_emergence(ctx)

    def _detect_emerging_traits(self, agent_name: str, ctx: DebateContext) -> list[dict[str, Any]]:
        """Detect emerging traits. Delegates to PersonaFeedback."""
        return self._persona_feedback.detect_emerging_traits(agent_name, ctx)

    def _resolve_positions(self, ctx: DebateContext) -> None:
        """Resolve positions in PositionLedger."""
        if not self.position_ledger:
            return

        result = ctx.result
        if not result.final_answer:
            return

        try:
            for agent in ctx.agents:
                positions = self.position_ledger.get_agent_positions(agent.name)
                for pos in positions[-5:]:  # Last 5 positions
                    if pos.debate_id == ctx.debate_id:
                        outcome = "correct" if agent.name == result.winner else "contested"
                        self.position_ledger.resolve_position(
                            position_id=pos.id,
                            outcome=outcome,
                            resolution_source=f"debate:{ctx.debate_id}",
                        )
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
            logger.warning("Position resolution failed: %s", e)

    def _update_relationships(self, ctx: DebateContext) -> None:
        """Update relationship metrics from debate."""
        if not self.relationship_tracker:
            return

        try:
            result = ctx.result

            # Extract critiques from messages
            critiques = []
            if result.messages:
                for msg in result.messages:
                    if getattr(msg, "role", "") == "critic":
                        critiques.append(
                            {
                                "agent": getattr(msg, "agent", "unknown"),
                                "target": getattr(msg, "target_agent", None),
                            }
                        )

            # Build vote mapping
            votes = {}
            for v in result.votes:
                canonical = ctx.choice_mapping.get(v.choice, v.choice)
                votes[v.agent] = canonical

            self.relationship_tracker.update_from_debate(
                debate_id=ctx.debate_id,
                participants=[agent.name for agent in ctx.agents],
                winner=result.winner,
                votes=votes,
                critiques=critiques,
            )
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
            logger.warning("Relationship tracking failed: %s", e)

    def _detect_moments(self, ctx: DebateContext) -> None:
        """Detect significant narrative moments."""
        if not self.moment_detector:
            return

        try:
            result = ctx.result

            # Upset victories
            if result.winner and self.elo_system:
                for agent in ctx.agents:
                    if agent.name != result.winner:
                        moment = self.moment_detector.detect_upset_victory(
                            winner=result.winner,
                            loser=agent.name,
                            debate_id=ctx.debate_id,
                        )
                        if moment:
                            self.moment_detector.record_moment(moment)
                            if self._emit_moment_event:
                                self._emit_moment_event(moment)

            # Calibration vindications
            for v in result.votes:
                if v.confidence >= 0.85:
                    canonical = ctx.choice_mapping.get(v.choice, v.choice)
                    was_correct = canonical == result.winner
                    if was_correct:
                        moment = self.moment_detector.detect_calibration_vindication(
                            agent_name=v.agent,
                            prediction_confidence=v.confidence,
                            was_correct=True,
                            domain=ctx.domain,
                            debate_id=ctx.debate_id,
                        )
                        if moment:
                            self.moment_detector.record_moment(moment)
                            if self._emit_moment_event:
                                self._emit_moment_event(moment)

        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
            logger.warning("Moment detection failed: %s", e)

    async def _index_debate(self, ctx: DebateContext) -> None:
        """Index debate in embeddings for historical retrieval."""
        if not self.debate_embeddings:
            return

        try:
            result = ctx.result

            # Build transcript
            transcript_parts = []
            if result.messages:
                for msg in result.messages[:30]:
                    agent_name = getattr(msg, "agent", "unknown")
                    content = getattr(msg, "content", str(msg))[:500]
                    transcript_parts.append(f"{agent_name}: {content}")

            artifact = {
                "id": ctx.debate_id,
                "task": ctx.env.task,
                "domain": ctx.domain,
                "winner": result.winner,
                "final_answer": result.final_answer or "",
                "confidence": result.confidence,
                "agents": [a.name for a in ctx.agents],
                "transcript": "\n".join(transcript_parts),
                "rounds_used": result.rounds_used,
                "consensus_reached": result.consensus_reached,
            }

            if self._index_debate_async:
                task = asyncio.create_task(self._index_debate_async(artifact))
                task.add_done_callback(
                    lambda t: (
                        logger.warning("Debate indexing failed: %s", t.exception())
                        if t.exception()
                        else None
                    )
                )

        except (
            TypeError,
            ValueError,
            AttributeError,
            KeyError,
            RuntimeError,
            OSError,
            ConnectionError,
        ) as e:
            logger.warning("Embedding indexing failed: %s", e)

    def _detect_flips(self, ctx: DebateContext) -> None:
        """Detect position flips for all participating agents."""
        if not self.flip_detector:
            return

        try:
            for agent in ctx.agents:
                flips = self.flip_detector.detect_flips_for_agent(agent.name)
                if flips:
                    logger.info(
                        "[flip] Detected %d position changes for %s", len(flips), agent.name
                    )
                    self._emit_flip_events(ctx, agent.name, flips)

        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
            logger.warning("Flip detection failed: %s", e)

    def _emit_flip_events(self, ctx: DebateContext, agent_name: str, flips: list) -> None:
        """Emit FLIP_DETECTED events to WebSocket."""
        if not self.event_emitter:
            return

        try:
            from aragora.events.types import StreamEvent, StreamEventType

            for flip in flips:
                self.event_emitter.emit(
                    StreamEvent(
                        type=StreamEventType.FLIP_DETECTED,
                        loop_id=self.loop_id,
                        data={
                            "agent": agent_name,
                            "flip_type": getattr(flip, "flip_type", "unknown"),
                            "original_claim": getattr(flip, "original_claim", "")[:200],
                            "new_claim": getattr(flip, "new_claim", "")[:200],
                            "original_confidence": getattr(flip, "original_confidence", 0.0),
                            "new_confidence": getattr(flip, "new_confidence", 0.0),
                            "similarity_score": getattr(flip, "similarity_score", 0.0),
                            "domain": getattr(flip, "domain", None),
                            "debate_id": ctx.result.id if ctx.result else ctx.debate_id,
                        },
                    )
                )
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            logger.warning("Flip event emission error: %s", e)

    def _store_memory(self, ctx: DebateContext) -> None:
        """Store memory. Delegates to MemoryFeedback."""
        self._memory_feedback.store_memory(ctx)

    def _update_memory_outcomes(self, ctx: DebateContext) -> None:
        """Update memory outcomes. Delegates to MemoryFeedback."""
        self._memory_feedback.update_memory_outcomes(ctx)

    def _absorb_into_epistemic_graph(self, ctx: DebateContext) -> None:
        """Absorb into epistemic graph. Delegates to MemoryFeedback."""
        self._memory_feedback.absorb_into_epistemic_graph(ctx)

    # =========================================================================
    # Evolution Feedback Methods (delegated to EvolutionFeedback helper)
    # Kept for backward compatibility
    # =========================================================================

    def _update_genome_fitness(self, ctx: DebateContext) -> None:
        """Update genome fitness. Delegates to EvolutionFeedback."""
        self._evolution_feedback.update_genome_fitness(ctx)

    def _check_agent_prediction(
        self,
        agent: Agent,
        ctx: DebateContext,
    ) -> bool:
        """Check agent prediction. Delegates to EvolutionFeedback."""
        return self._evolution_feedback._check_agent_prediction(agent, ctx)

    async def _maybe_evolve_population(self, ctx: DebateContext) -> None:
        """Maybe evolve population. Delegates to EvolutionFeedback."""
        await self._evolution_feedback.maybe_evolve_population(ctx)

    async def _evolve_async(self, population: Any) -> None:
        """Evolve population async. Delegates to EvolutionFeedback."""
        await self._evolution_feedback._evolve_async(population)

    def _record_evolution_patterns(self, ctx: DebateContext) -> None:
        """Record evolution patterns. Delegates to EvolutionFeedback."""
        self._evolution_feedback.record_evolution_patterns(ctx)

    # =========================================================================
    # Genesis Ledger + Specialist promotion
    # =========================================================================

    def _record_genesis_ledger_events(self, ctx: DebateContext) -> None:
        """Record debate events in the GenesisLedger for cryptographic provenance.

        Records: debate start/end, consensus outcome, and fitness updates
        in the immutable event chain. This creates an auditable trail of
        how agents evolved and which debates influenced their evolution.
        """
        if not self.genesis_ledger:
            return

        result = ctx.result
        if not result:
            return

        try:
            # Record debate completion with consensus info
            agent_names = [a.name for a in ctx.agents] if ctx.agents else []
            self.genesis_ledger.record_debate_start(
                debate_id=ctx.debate_id,
                task=getattr(ctx.env, "task", ""),
                agents=agent_names,
            )

            # Record consensus if reached
            if result.consensus_reached:
                consensus_proof = getattr(result, "consensus_proof", None)
                if consensus_proof:
                    self.genesis_ledger.record_consensus(
                        debate_id=ctx.debate_id,
                        proof=consensus_proof,
                    )

            # Record fitness updates for agents with genomes
            for agent in ctx.agents:
                genome_id = getattr(agent, "genome_id", None)
                if not genome_id:
                    continue
                # Look up current fitness from population manager
                if self.population_manager:
                    try:
                        pop = self.population_manager.get_or_create_population([agent.name])
                        genome = pop.get_by_id(genome_id) if pop else None
                        if genome:
                            self.genesis_ledger.record_fitness_update(
                                genome_id=genome_id,
                                old_fitness=genome.fitness_score,
                                new_fitness=genome.fitness_score,
                                reason=f"debate:{ctx.debate_id}",
                            )
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass

            logger.debug(
                "[genesis_ledger] Recorded provenance for debate %s (%d agents)",
                ctx.debate_id,
                len(agent_names),
            )

        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
            logger.debug("[genesis_ledger] Event recording failed: %s", e)

    def _promote_evolved_specialists(self, ctx: DebateContext) -> None:
        """Promote evolved agent genomes to SpecialistRegistry for team selection.

        After population evolution, genomes with high domain fitness should be
        registered as specialists so TeamSelector gives them bonus scores in
        their strong domains. This creates the loop:

            Debate performance → Genome fitness → Population evolution →
            Specialist promotion → TeamSelector bonus → Better team composition
        """
        if not self.population_manager:
            return

        try:
            from aragora.ranking.specialist_registry import get_specialist_registry

            registry = get_specialist_registry()
        except ImportError:
            return

        result = ctx.result
        if not result:
            return

        for agent in ctx.agents:
            genome_id = getattr(agent, "genome_id", None)
            if not genome_id:
                continue

            try:
                # Get genome's domain expertise
                pop = self.population_manager.get_or_create_population([agent.name])
                genome = pop.get_by_id(genome_id) if pop else None
                if not genome:
                    continue

                # Use genome expertise to check/promote specialist status
                expertise = getattr(genome, "expertise", {}) or {}
                top_domains = sorted(expertise.items(), key=lambda x: x[1], reverse=True)[:3]

                for dom, score in top_domains:
                    if score >= 0.7:
                        # Synthesize an ELO-like score from expertise for specialist check
                        synthetic_elo = 1500.0 + (score * 300)
                        registry.check_and_promote(
                            agent_name=agent.name,
                            domain=dom,
                            elo_rating=synthetic_elo,
                        )

            except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
                logger.debug(
                    "[specialist] Promotion check failed for %s: %s",
                    agent.name,
                    e,
                )

    # =========================================================================
    # Backward-compatible delegate methods
    # These proxy to extracted helper classes while maintaining the same API
    # that existing tests and callers rely on.
    # =========================================================================

    def _store_consensus_outcome(self, ctx: DebateContext) -> None:
        """Delegate to ConsensusStorage for backward compatibility."""
        consensus_id = self._consensus_storage.store_consensus_outcome(ctx)
        if consensus_id:
            setattr(ctx, "_last_consensus_id", consensus_id)

    def _confidence_to_strength(self, confidence: float) -> ConsensusStrength:
        """Delegate to ConsensusStorage for backward compatibility."""
        return self._consensus_storage._confidence_to_strength(confidence)

    def _store_cruxes(self, ctx: DebateContext) -> None:
        """Delegate to ConsensusStorage for backward compatibility."""
        self._consensus_storage.store_cruxes(ctx)

    async def _record_insight_usage(self, ctx: DebateContext) -> None:
        """Delegate to TrainingEmitter for backward compatibility."""
        await self._training_emitter.record_insight_usage(ctx)

    async def _emit_training_data(self, ctx: DebateContext) -> None:
        """Delegate to TrainingEmitter for backward compatibility."""
        await self._training_emitter.emit_training_data(ctx)
