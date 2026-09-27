"""
Debate rounds phase for debate orchestration.

This module extracts the debate round loop (Phase 2) from the
Arena._run_inner() method, handling:
- Role assignment updates per round
- Stance rotation for asymmetric debates
- Critique phase (parallel generation)
- Revision phase (parallel generation)
- Convergence detection
- Termination checks (judge-based, early stopping)
- RLM "ready signal" pattern for agent self-termination
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.config import AGENT_TIMEOUT_SECONDS, MAX_CONCURRENT_CRITIQUES, MAX_CONCURRENT_REVISIONS
from aragora.debate.complexity_governor import get_complexity_governor
from aragora.debate.performance_monitor import get_debate_monitor
from aragora.debate.phases._phase_invariant import require_phase_result
from aragora.debate.phases.convergence_tracker import (
    DebateConvergenceTracker,
)
from aragora.debate.phases.debate_rounds_helpers import (
    DEFAULT_CALLBACK_TIMEOUT,
    REVISION_PHASE_BASE_TIMEOUT as _REVISION_PHASE_BASE_TIMEOUT,
    build_final_synthesis_prompt,
    calculate_phase_timeout,
    compress_debate_context,
    emit_heartbeat,
    execute_final_synthesis_round,
    fire_propulsion_event,
    is_effectively_empty_critique,
    observe_rhetorical_patterns,
    record_adaptive_round,
    refresh_evidence_for_round,
    refresh_with_skills,
    with_callback_timeout,
)
from aragora.debate.stability_detector import (
    BetaBinomialStabilityDetector,
    StabilityConfig,
)
from aragora.events.context import streaming_task_context

# Backward-compatible aliases with underscore prefix
_calculate_phase_timeout = calculate_phase_timeout
_is_effectively_empty_critique = is_effectively_empty_critique
_with_callback_timeout = with_callback_timeout
_record_adaptive_round = record_adaptive_round
# Backward-compatible constant re-export for tests/importers.
REVISION_PHASE_BASE_TIMEOUT = _REVISION_PHASE_BASE_TIMEOUT


if TYPE_CHECKING:
    from aragora.core import Agent, Critique, Message
from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)


def _should_emit_slow_round_warning() -> bool:
    try:
        from aragora.inbox.triage_diagnostics import (
            get_active_triage_diagnostics,
            triage_diagnostics_should_mirror_logs,
        )

        if get_active_triage_diagnostics() is None:
            return True
        return triage_diagnostics_should_mirror_logs()
    except ImportError:
        return True


class DebateRoundsPhase:
    """
    Executes the debate rounds phase.

    This class encapsulates the critique -> revision -> convergence loop
    that was previously in Arena._run_inner().

    Usage:
        debate_rounds = DebateRoundsPhase(
            protocol=arena.protocol,
            circuit_breaker=arena.circuit_breaker,
            convergence_detector=arena.convergence_detector,
            hooks=arena.hooks,
        )
        await debate_rounds.execute(ctx)
    """

    def __init__(
        self,
        protocol: Any = None,
        circuit_breaker: Any = None,
        convergence_detector: Any = None,
        recorder: Any = None,
        hooks: dict | None = None,
        trickster: Any = None,  # EvidencePoweredTrickster for hollow consensus detection
        rhetorical_observer: Any = None,  # RhetoricalAnalysisObserver for pattern detection
        event_emitter: Any = None,  # EventEmitter for broadcasting observations
        novelty_tracker: Any = None,  # NoveltyTracker for semantic novelty detection
        # Callbacks
        update_role_assignments: Callable | None = None,
        assign_stances: Callable | None = None,
        select_critics_for_proposal: Callable | None = None,
        critique_with_agent: Callable | None = None,
        build_revision_prompt: Callable | None = None,
        generate_with_agent: Callable | None = None,
        with_timeout: Callable | None = None,
        notify_spectator: Callable | None = None,
        record_grounded_position: Callable | None = None,
        check_judge_termination: Callable | None = None,
        check_early_stopping: Callable | None = None,
        inject_challenge: Callable | None = None,  # Callback to inject trickster challenges
        refresh_evidence: Callable | None = None,  # Callback to refresh evidence during rounds
        checkpoint_callback: Callable
        | None = None,  # Async callback to save checkpoint after each round
        context_initializer: Any = None,  # ContextInitializer for background task awaiting
        compress_context: Callable | None = None,  # Async callback to compress debate messages
        rlm_compression_round_threshold: int = 3,  # Start compression after this many rounds
        debate_strategy: Any = None,  # DebateStrategy for adaptive round estimation
        skill_registry: Any = None,  # SkillRegistry for skill-based evidence refresh
        enable_skills: bool = False,  # Enable skill invocation during evidence refresh
        propulsion_engine: Any = None,  # PropulsionEngine for push-based work assignment
        enable_propulsion: bool = False,  # Enable propulsion events at stage transitions
        performance_router_bridge: Any = None,  # PerformanceRouterBridge for speed ranking
    ):
        """
        Initialize the debate rounds phase.

        Args:
            protocol: DebateProtocol with rounds, asymmetric settings
            circuit_breaker: CircuitBreaker for agent availability
            convergence_detector: ConvergenceDetector for semantic similarity
            recorder: ReplayRecorder
            hooks: Hook callbacks dict
            trickster: EvidencePoweredTrickster for hollow consensus detection
            rhetorical_observer: RhetoricalAnalysisObserver for pattern detection
            event_emitter: EventEmitter for broadcasting observations
            novelty_tracker: NoveltyTracker for detecting proposal staleness
            update_role_assignments: Callback to update role assignments
            assign_stances: Callback to assign stances for asymmetric debates
            select_critics_for_proposal: Callback to select critics
            critique_with_agent: Async callback for critique generation
            build_revision_prompt: Callback to build revision prompt
            generate_with_agent: Async callback to generate with agent
            with_timeout: Async callback for timeout wrapper
            notify_spectator: Callback for spectator notifications
            record_grounded_position: Callback to record grounded position
            check_judge_termination: Async callback for judge termination
            check_early_stopping: Async callback for early stopping
            inject_challenge: Callback to inject trickster challenge into context
            refresh_evidence: Async callback to refresh evidence based on round claims
            checkpoint_callback: Async callback to save checkpoint after each round
            context_initializer: ContextInitializer for awaiting background research/evidence
            compress_context: Async callback to compress debate messages using RLM
            rlm_compression_round_threshold: Start compression after this many rounds (default 3)
            debate_strategy: Optional DebateStrategy for memory-based round estimation
            skill_registry: Optional SkillRegistry for skill-based evidence refresh
            enable_skills: Enable skill invocation during evidence refresh
            performance_router_bridge: Optional bridge for latency-aware agent ranking
        """
        self.protocol = protocol
        self.debate_strategy = debate_strategy
        self.circuit_breaker = circuit_breaker
        self.convergence_detector = convergence_detector
        self.recorder = recorder
        self.hooks = hooks or {}
        self.trickster = trickster
        self.rhetorical_observer = rhetorical_observer
        self.event_emitter = event_emitter
        self.novelty_tracker = novelty_tracker

        # Callbacks
        self._update_role_assignments = update_role_assignments
        self._assign_stances = assign_stances
        self._select_critics_for_proposal = select_critics_for_proposal
        self._critique_with_agent = critique_with_agent
        self._build_revision_prompt = build_revision_prompt
        self._generate_with_agent = generate_with_agent
        self._with_timeout = with_timeout
        self._notify_spectator = notify_spectator
        self._record_grounded_position = record_grounded_position
        self._check_judge_termination = check_judge_termination
        self._check_early_stopping = check_early_stopping
        self._inject_challenge = inject_challenge
        self._refresh_evidence = refresh_evidence
        self._checkpoint_callback = checkpoint_callback
        self._context_initializer = context_initializer
        self._compress_context = compress_context
        self._rlm_compression_round_threshold = rlm_compression_round_threshold
        self._skill_registry = skill_registry
        self._enable_skills = enable_skills
        self._propulsion_engine = propulsion_engine
        self._enable_propulsion = enable_propulsion
        self._performance_router_bridge = performance_router_bridge

        # Speed policy and per-debate parallelism bounds (all optional protocol fields).
        # No hard maximum cap -- protocol values are respected to support 10+ agent debates.
        self._max_parallel_critiques = self._coerce_int(
            getattr(protocol, "max_parallel_critiques", MAX_CONCURRENT_CRITIQUES),
            default=MAX_CONCURRENT_CRITIQUES,
            minimum=1,
        )
        self._max_parallel_revisions = self._coerce_int(
            getattr(protocol, "max_parallel_revisions", MAX_CONCURRENT_REVISIONS),
            default=MAX_CONCURRENT_REVISIONS,
            minimum=1,
        )
        self._fast_first_routing = bool(getattr(protocol, "fast_first_routing", False))
        self._fast_first_low_contention_agent_threshold = self._coerce_int(
            getattr(protocol, "fast_first_low_contention_agent_threshold", 3),
            default=3,
            minimum=1,
        )
        self._fast_first_max_critics_per_proposal = self._coerce_int(
            getattr(protocol, "fast_first_max_critics_per_proposal", 2),
            default=2,
            minimum=1,
        )
        self._fast_first_min_round = self._coerce_int(
            getattr(protocol, "fast_first_min_round", 2),
            default=2,
            minimum=1,
        )
        self._fast_first_max_total_issues = self._coerce_int(
            getattr(protocol, "fast_first_max_total_issues", 2),
            default=2,
            minimum=0,
        )
        self._fast_first_max_critique_severity = self._coerce_float(
            getattr(protocol, "fast_first_max_critique_severity", 0.2),
            default=0.2,
            minimum=0.0,
        )
        self._fast_first_convergence_threshold = self._coerce_float(
            getattr(protocol, "fast_first_convergence_threshold", 0.9),
            default=0.9,
            minimum=0.0,
            maximum=1.0,
        )
        self._fast_first_early_exit = bool(getattr(protocol, "fast_first_early_exit", True))

        # Internal state
        self._partial_messages: list[Message] = []
        self._partial_critiques: list[Critique] = []

        # Convergence tracker handles convergence, novelty, and RLM ready signals
        self._convergence_tracker = DebateConvergenceTracker(
            convergence_detector=convergence_detector,
            novelty_tracker=novelty_tracker,
            trickster=trickster,
            hooks=self.hooks,
            event_emitter=event_emitter,
            notify_spectator=notify_spectator,
            inject_challenge=inject_challenge,
        )

        # Stability detector for statistical early stopping (Beta-Binomial model)
        # Only initialized if enable_stability_detection is True in protocol
        self._stability_detector: BetaBinomialStabilityDetector | None = None
        if getattr(protocol, "enable_stability_detection", False):
            stability_config = StabilityConfig(
                stability_threshold=getattr(protocol, "stability_threshold", 0.85),
                ks_threshold=getattr(protocol, "stability_ks_threshold", 0.1),
                min_stable_rounds=getattr(protocol, "stability_min_stable_rounds", 1),
                min_rounds_before_check=getattr(protocol, "min_rounds_before_early_stop", 2),
            )
            self._stability_detector = BetaBinomialStabilityDetector(stability_config)

    def _emit_heartbeat(self, phase: str, status: str = "alive") -> None:
        """Emit heartbeat to indicate debate is still running."""
        emit_heartbeat(self.hooks, phase, status)

    def _process_intervention_window(
        self,
        ctx: DebateContext,
        round_num: int,
        total_rounds: int,
    ) -> None:
        """Signal intervention window and apply any queued interventions.

        Called at the start of each round (round boundary) to:
        1. Emit an intervention_window event so the UI knows the user can act
        2. Check for queued interventions and inject them into context

        This is fail-safe: any error is caught and logged without interrupting
        the debate.

        Args:
            ctx: The DebateContext
            round_num: Current round number
            total_rounds: Total number of rounds
        """
        debate_id = getattr(ctx, "debate_id", "") or ""

        # 1. Emit intervention window event
        try:
            if self.event_emitter:
                self.event_emitter.emit_intervention_window(
                    debate_id=debate_id,
                    round_num=round_num,
                    window_type="between_rounds",
                    expires_in_seconds=30.0,
                    context_summary=f"Round {round_num}/{total_rounds}",
                )
            if "on_intervention_window" in self.hooks:
                self.hooks["on_intervention_window"](
                    debate_id=debate_id,
                    round_num=round_num,
                    window_type="between_rounds",
                    expires_in_seconds=30.0,
                    context_summary=f"Round {round_num}/{total_rounds}",
                )
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.debug("intervention_window_emit_failed: %s", e)

        # 2. Apply queued interventions
        try:
            from aragora.debate.intervention import get_intervention_queue

            queue = get_intervention_queue()
            pending = queue.get_pending_interventions(debate_id, current_round=round_num)

            for intervention in pending:
                # Build prompt injection and prepend to context
                prompt_injection = queue.build_intervention_prompt(intervention)

                # Add as a system-level context message
                from aragora.core import Message

                intervention_msg = Message(
                    role="system",
                    agent="intervention",
                    content=prompt_injection,
                    round=round_num,
                )
                ctx.add_message(intervention_msg)

                # Mark as applied
                queue.mark_applied(
                    intervention.intervention_id,
                    round_num=round_num,
                    effect_summary=f"Injected at round {round_num}",
                )

                # Emit applied event
                if self.event_emitter:
                    self.event_emitter.emit_intervention_applied(
                        intervention_id=intervention.intervention_id,
                        intervention_type=intervention.intervention_type.value,
                        content_summary=intervention.content[:200],
                        applied_at_round=round_num,
                    )
                if "on_intervention_applied" in self.hooks:
                    self.hooks["on_intervention_applied"](
                        intervention_id=intervention.intervention_id,
                        intervention_type=intervention.intervention_type.value,
                        content_summary=intervention.content[:200],
                        applied_at_round=round_num,
                    )

                logger.info(
                    "intervention_injected id=%s debate=%s round=%s type=%s",
                    intervention.intervention_id,
                    debate_id,
                    round_num,
                    intervention.intervention_type.value,
                )

        except ImportError:
            pass  # Intervention module not available
        except (RuntimeError, AttributeError, TypeError, ValueError) as e:  # noqa: BLE001
            logger.debug("intervention_processing_failed: %s", e)

    def _observe_rhetorical_patterns(
        self,
        agent: str,
        content: str,
        round_num: int,
        loop_id: str = "",
    ) -> None:
        """Observe content for rhetorical patterns and emit events."""
        observe_rhetorical_patterns(
            self.rhetorical_observer,
            self.event_emitter,
            self.hooks,
            agent,
            content,
            round_num,
            loop_id,
        )

    @staticmethod
    def _coerce_int(
        value: Any,
        default: int,
        minimum: int = 1,
        maximum: int | None = None,
    ) -> int:
        """Safely coerce an integer config value with bounds."""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        parsed = max(minimum, parsed)
        if maximum is not None:
            parsed = min(parsed, maximum)
        return parsed

    @staticmethod
    def _coerce_float(
        value: Any,
        default: float,
        minimum: float = 0.0,
        maximum: float | None = None,
    ) -> float:
        """Safely coerce a float config value with bounds."""
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        parsed = max(minimum, parsed)
        if maximum is not None:
            parsed = min(parsed, maximum)
        return parsed

    async def execute(self, ctx: DebateContext) -> None:
        """
        Execute the debate rounds phase.

        Args:
            ctx: The DebateContext with proposals and result
        """

        result = require_phase_result(ctx)
        proposals = ctx.proposals

        # Determine rounds: use strategy if available, otherwise protocol
        rounds = self.protocol.rounds if self.protocol else 1
        if self.debate_strategy and ctx.env:
            try:
                # Use async version if available
                strategy_rec = await self.debate_strategy.estimate_rounds_async(
                    task=ctx.env.task,
                    default_rounds=rounds,
                )
                if strategy_rec.estimated_rounds != rounds:
                    direction = "increase" if strategy_rec.estimated_rounds > rounds else "decrease"
                    logger.info(
                        "[strategy] Adaptive rounds: %s -> %s (confidence=%s, reason=%s)",
                        rounds,
                        strategy_rec.estimated_rounds,
                        strategy_rec.confidence,
                        strategy_rec.reasoning[:50],
                    )
                    _record_adaptive_round(direction)
                    # Floor adaptive recommendation at 1: a recommendation of 0
                    # (interpreted as "the proposal already produced consensus, no
                    # critique-revision rounds needed") would skip the round loop
                    # entirely and report rounds_completed=0 to downstream consumers,
                    # making a real debate look like one that never ran. We honour
                    # the strategy's signal in metadata but always run at least one
                    # round so the metric is honest. See
                    # docs/plans/2026-04-30-rounds-floor-rca.md
                    # (or .aragora/evolve-round/2026-04-30/dogfood/phase-e-rounds-zero-rca.md
                    # in repos that carry the round receipts).
                    if strategy_rec.estimated_rounds < 1:
                        logger.info(
                            "[strategy] estimate=%s < 1; flooring at 1 to preserve rounds_completed honesty",
                            strategy_rec.estimated_rounds,
                        )
                        rounds = max(1, rounds)
                    else:
                        rounds = strategy_rec.estimated_rounds
                    # Store strategy recommendation in result metadata
                    if hasattr(result, "metadata") and result.metadata is not None:
                        result.metadata["strategy_recommendation"] = {
                            "estimated_rounds": strategy_rec.estimated_rounds,
                            "confidence": strategy_rec.confidence,
                            "reasoning": strategy_rec.reasoning,
                            "relevant_memories": strategy_rec.relevant_memories[:3],
                            "floored_to_one": strategy_rec.estimated_rounds < 1,
                        }
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("[strategy] Round estimation failed, using protocol default: %s", e)

        # Track novelty for initial proposals (round 0 baseline)
        if self.novelty_tracker and proposals:
            self._convergence_tracker.track_novelty(ctx, round_num=0)

        # Get performance monitor for round tracking
        perf_monitor = get_debate_monitor()

        for round_num in range(1, rounds + 1):
            # Check for cancellation before each round
            cancellation_token = getattr(ctx, "cancellation_token", None)
            if cancellation_token and cancellation_token.is_cancelled:
                from aragora.debate.cancellation import DebateCancelled

                raise DebateCancelled(cancellation_token.reason)

            # Check budget before each round (allows graceful pause on budget exceeded)
            budget_check_callback = getattr(ctx, "budget_check_callback", None)
            if budget_check_callback:
                try:
                    allowed, reason = budget_check_callback(round_num)
                    if not allowed:
                        logger.warning(
                            "budget_exceeded_pause round=%s reason=%s", round_num, reason
                        )
                        # Store reason in result metadata for transparency
                        if ctx.result and hasattr(ctx.result, "metadata"):
                            if ctx.result.metadata is None:
                                ctx.result.metadata = {}
                            ctx.result.metadata["budget_pause_reason"] = reason
                            ctx.result.metadata["budget_pause_round"] = round_num
                        # Exit round loop gracefully (don't raise exception)
                        break
                except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                    # Budget check failure should not stop the debate
                    logger.debug("Budget check error (continuing): %s", e)

            logger.info("round_start round=%s", round_num)

            # Track round with performance monitor for detailed phase metrics
            with perf_monitor.track_round(ctx.debate_id, round_num):
                should_continue = await self._execute_round(ctx, perf_monitor, round_num, rounds)
                if not should_continue:
                    logger.info("early_exit_convergence round=%s", round_num)
                    break

    async def _execute_round(
        self,
        ctx: DebateContext,
        perf_monitor,
        round_num: int,
        total_rounds: int,
    ) -> bool:
        """Execute a single debate round with performance tracking.

        Returns:
            True if debate should continue to next round, False if converged/should stop.
        """
        result = require_phase_result(ctx)

        # Record partial-round progress at round start so that DebateState
        # finalization, timeout recovery, and post-failure inspection all see
        # the rounds we *attempted* even if this round raises before its
        # success path sets ``result.rounds_used`` at the end. Without this,
        # a failure inside critique/revision/novelty leaves
        # ``rounds_used == rounds_completed == 0`` even though one or more
        # rounds were partially executed (dogfood-discovered 2026-04-28).
        ctx.partial_rounds = round_num

        # Track round start time for slow debate detection
        _round_start_time = time.time()

        # Trigger PRE_ROUND hook if hook_manager is available
        if ctx.hook_manager:
            try:
                await ctx.hook_manager.trigger("pre_round", ctx=ctx, round_num=round_num)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("PRE_ROUND hook failed: %s", e)

        # Emit heartbeat at round start
        self._emit_heartbeat(f"round_{round_num}", "starting")

        # Update role assignments
        if self._update_role_assignments:
            self._update_role_assignments(round_num=round_num)

        # Notify spectator
        if self._notify_spectator:
            self._notify_spectator(
                "round",
                details=f"Starting Round {round_num}",
                agent="system",
            )

        # Rotate stances if asymmetric debate
        if self.protocol:
            if self.protocol.asymmetric_stances and self.protocol.rotate_stances:
                if self._assign_stances:
                    self._assign_stances(round_num)
                    stances_str = ", ".join(f"{a.name}:{a.stance}" for a in ctx.agents)
                    logger.debug("stances_rotated stances=%s", stances_str)

        # Emit round start event
        if "on_round_start" in self.hooks:
            self.hooks["on_round_start"](round_num)

        # Record round start
        if self.recorder:
            try:
                self.recorder.record_phase_change(f"round_{round_num}_start")
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("Recorder error for round start: %s", e)

        # --- Intervention window: signal UI and apply queued interventions ---
        self._process_intervention_window(ctx, round_num, total_rounds)

        # Await background research/evidence before round 1 critiques
        # This ensures research context is available for critique prompts
        if round_num == 1 and self._context_initializer:
            await self._context_initializer.await_background_context(ctx)

        # Compress context messages using RLM after threshold rounds
        # This keeps context manageable for long debates
        if self._compress_context and round_num >= self._rlm_compression_round_threshold:
            await self._compress_debate_context(ctx, round_num)

        # Round 7 special handling: Final Synthesis
        # Each agent synthesizes the discussion and revises their proposal to final form
        # This skips the normal critique/revision cycle
        if self.protocol and self.protocol.use_structured_phases and round_num == 7:
            round_phase = self.protocol.get_round_phase(round_num)
            if round_phase and "Final Synthesis" in round_phase.name:
                logger.info("round_7_final_synthesis agents=%s", len(ctx.proposers))
                await self._execute_final_synthesis_round(ctx, round_num)
                result.rounds_used = round_num
                return True  # Skip normal critique/revision, move to Round 8 (continue debate)

        # Get and filter critics
        critics = self._get_critics(ctx)

        # Critique phase with performance tracking
        round_critiques: list[Critique] = []
        with perf_monitor.track_phase(ctx.debate_id, "critique"):
            round_critiques = await self._critique_phase(ctx, critics, round_num)

        # Fire propulsion event: critiques ready for next stage
        await self._fire_propulsion_event(
            "critiques_ready",
            ctx,
            round_num,
            {"critique_count": len(self._partial_critiques)},
        )

        # Refresh evidence based on claims made in critiques and proposals
        with perf_monitor.track_phase(ctx.debate_id, "evidence_refresh"):
            await self._refresh_evidence_for_round(ctx, round_num)

        # Fire propulsion event: evidence ready
        evidence_pack = getattr(ctx, "evidence_pack", None)
        evidence_snippets = getattr(evidence_pack, "snippets", []) if evidence_pack else []
        evidence_count = len(evidence_snippets or [])
        await self._fire_propulsion_event(
            "evidence_ready",
            ctx,
            round_num,
            {"evidence_count": evidence_count},
        )

        # Fast-first consensus probe: in low-contention rounds we can exit early
        # before the revision phase if convergence is already strong.
        fast_exit, probed_convergence = self._maybe_fast_first_early_exit(
            ctx=ctx,
            round_num=round_num,
            total_rounds=total_rounds,
            round_critiques=round_critiques,
        )
        if fast_exit:
            result.rounds_used = round_num
            return False

        # Revision phase with performance tracking
        with perf_monitor.track_phase(ctx.debate_id, "revision"):
            await self._revision_phase(ctx, critics, round_num)

        # Fire propulsion event: revisions complete
        await self._fire_propulsion_event(
            "revisions_complete",
            ctx,
            round_num,
            {"proposal_count": len(ctx.proposals)},
        )

        # Track novelty of revised proposals
        self._convergence_tracker.track_novelty(ctx, round_num)

        # Record per-round trajectory for RLM training (if RLM compression is enabled)
        if self._compress_context:
            try:
                from aragora.rlm.debate_integration import get_debate_trajectory_collector

                collector = get_debate_trajectory_collector()
                proposals_data = [
                    {
                        "agent": getattr(p, "agent_name", ""),
                        "content": getattr(p, "content", str(p))[:500],
                    }
                    for p in (ctx.proposals or [])
                ]
                critiques_data = [
                    {
                        "agent": getattr(c, "critic_name", ""),
                        "content": getattr(c, "content", str(c))[:500],
                    }
                    for c in round_critiques
                ]
                convergence_sim = probed_convergence.similarity if probed_convergence else 0.0
                collector.record_round(
                    debate_id=ctx.debate_id,
                    round_num=round_num,
                    proposals=proposals_data,
                    critiques=critiques_data,
                    convergence_similarity=convergence_sim,
                )
            except (ImportError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("Per-round trajectory recording failed: %s", e)

        result.rounds_used = round_num

        # Create checkpoint after each round
        if self._checkpoint_callback:
            try:
                await self._checkpoint_callback(ctx, round_num)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("Checkpoint failed for round %s: %s", round_num, e)

        # Trigger POST_ROUND hook if hook_manager is available
        if ctx.hook_manager:
            try:
                await ctx.hook_manager.trigger(
                    "post_round",
                    ctx=ctx,
                    round_num=round_num,
                    proposals=ctx.proposals,
                )
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("POST_ROUND hook failed: %s", e)

        # Emit heartbeat before convergence check
        self._emit_heartbeat(f"round_{round_num}", "checking_convergence")

        # Convergence detection
        convergence_result = probed_convergence or self._convergence_tracker.check_convergence(
            ctx, round_num
        )
        should_break = convergence_result.converged and not convergence_result.blocked_by_trickster

        # Record round duration for slow debate detection
        _round_duration = time.time() - _round_start_time
        _slow_threshold = perf_monitor.slow_round_threshold
        if _round_duration > _slow_threshold:
            if _should_emit_slow_round_warning():
                logger.warning(
                    "slow_round_detected debate_id=%s round=%s duration=%ss threshold=%ss",
                    ctx.debate_id,
                    round_num,
                    _round_duration,
                    _slow_threshold,
                    extra={
                        "triage_diag_code": "slow_round",
                        "triage_diag_severity": "diagnostic",
                    },
                )
            try:
                from aragora.observability.metrics import (
                    record_slow_round,
                    record_round_latency,
                )

                record_slow_round(phase="in_progress")  # type: ignore[call-arg]
                record_round_latency(_round_duration)
            except ImportError:
                logger.debug("Slow round metrics not available")
        else:
            try:
                from aragora.observability.metrics import record_round_latency

                record_round_latency(_round_duration)
            except ImportError:
                logger.debug("Round latency metrics not available")

        if should_break:
            # Emit early stop event for convergence-based termination
            similarity = convergence_result.similarity if convergence_result else 0.0
            self._emit_early_stop_event(
                ctx,
                round_num,
                "convergence",
                f"Semantic convergence detected (similarity={similarity:.2f})",
            )
            if ctx.result is not None:
                if ctx.result.metadata is None:
                    ctx.result.metadata = {}
                ctx.result.metadata["early_termination"] = True
                ctx.result.metadata["early_termination_source"] = "convergence"
                ctx.result.metadata["early_termination_round"] = round_num
                ctx.result.metadata["early_termination_reason"] = (
                    f"Semantic convergence (similarity={similarity:.2f})"
                )
            return False  # Converged - exit round execution early, stop debate loop

        # Fork detection: when debate is NOT converging and forking is enabled,
        # check if agents have fundamentally diverged and record fork points.
        if not should_break and getattr(ctx, "enable_debate_forking", False):
            try:
                from aragora.debate.forking import ForkDetector

                detector = ForkDetector()
                fork_decision = detector.should_fork(
                    messages=ctx.result.messages if ctx.result else [],
                    round_num=round_num,
                    agents=ctx.agents if hasattr(ctx, "agents") else [],
                )
                if fork_decision and fork_decision.should_fork:
                    branch_agents = [b.get("lead_agent", "") for b in fork_decision.branches]
                    logger.info(
                        "fork_detected round=%s reason=%s agents=%s",
                        round_num,
                        fork_decision.reason,
                        branch_agents,
                    )
                    if ctx.result and ctx.result.metadata is not None:
                        ctx.result.metadata["fork_detected"] = {
                            "round": round_num,
                            "reason": fork_decision.reason,
                            "agents": branch_agents,
                        }
            except (ImportError, Exception) as e:
                logger.debug("Fork detection unavailable: %s", e)

        # Termination checks (only if not last round)
        if round_num < total_rounds:
            source, details = await self._check_termination_conditions(ctx, round_num)
            if source is not None:
                self._emit_early_stop_event(ctx, round_num, source, details)
                # Signal early termination by setting metadata flags
                if ctx.result is not None:
                    if ctx.result.metadata is None:
                        ctx.result.metadata = {}
                    ctx.result.metadata["early_termination"] = True
                    ctx.result.metadata["early_termination_source"] = source
                    ctx.result.metadata["early_termination_round"] = round_num
                    ctx.result.metadata["early_termination_reason"] = details
                return False  # Stop debate loop

        return True  # Continue to next round

    def _get_critics(self, ctx: DebateContext) -> list[Agent]:
        """Get and filter critics for the round."""
        # Get critics - when all agents are proposers, they all critique each other
        critics = [a for a in ctx.agents if a.role in ("critic", "synthesizer")]
        if not critics:
            critics = list(ctx.agents)

        # Filter through circuit breaker
        if self.circuit_breaker:
            try:
                available = self.circuit_breaker.filter_available_agents(critics)
                if len(available) < len(critics):
                    skipped = [c.name for c in critics if c not in available]
                    logger.info("circuit_breaker_skip_critics skipped=%s", skipped)
                critics = available
            except Exception as e:  # noqa: BLE001 - graceful degradation, use unfiltered critics on error
                logger.error("Circuit breaker filter error for critics: %s", e)

        return critics

    def _rank_agents_fast_first(self, agents: list[Agent]) -> list[Agent]:
        """Rank agents for low-latency execution in fast-first mode."""
        if len(agents) <= 1:
            return list(agents)

        ranked = list(agents)

        # Prefer bridge-provided latency rankings when available.
        if self._performance_router_bridge is not None:
            try:
                names = [a.name for a in ranked]
                ranked_names = self._performance_router_bridge.rank_agents_for_task(
                    names,
                    task_type="speed",
                )
                order = {name: idx for idx, (name, _) in enumerate(ranked_names)}
                ranked.sort(key=lambda a: order.get(a.name, len(order)))
            except (ValueError, KeyError, TypeError) as exc:  # noqa: BLE001
                logger.debug("fast_first_bridge_ranking_failed: %s", exc)

        # Fallback tie-breaker: lower timeout implies faster model path.
        ranked.sort(
            key=lambda a: (
                float(getattr(a, "timeout", AGENT_TIMEOUT_SECONDS)),
                getattr(a, "name", ""),
            )
        )
        return ranked

    def _is_low_contention_round(
        self,
        proposal_count: int,
        critic_count: int,
        round_num: int,
    ) -> bool:
        """Determine whether this round qualifies for fast-first routing."""
        if not self._fast_first_routing:
            return False
        if round_num < self._fast_first_min_round:
            return False
        return (
            proposal_count <= self._fast_first_low_contention_agent_threshold and critic_count > 0
        )

    def _maybe_fast_first_early_exit(
        self,
        ctx: DebateContext,
        round_num: int,
        total_rounds: int,
        round_critiques: list[Critique],
    ) -> tuple[bool, Any | None]:
        """Probe convergence before revision in low-contention rounds.

        Returns:
            Tuple of (should_exit, convergence_result_if_probed)
        """
        if not (self._fast_first_routing and self._fast_first_early_exit):
            return False, None
        if round_num < self._fast_first_min_round or round_num >= total_rounds:
            return False, None
        if len(ctx.proposals) > self._fast_first_low_contention_agent_threshold:
            return False, None
        if not round_critiques:
            return False, None

        total_issues = 0
        max_severity = 0.0
        for critique in round_critiques:
            total_issues += len(getattr(critique, "issues", []) or [])
            max_severity = max(
                max_severity,
                self._coerce_float(getattr(critique, "severity", 0.0), default=0.0, minimum=0.0),
            )

        if total_issues > self._fast_first_max_total_issues:
            return False, None
        if max_severity > self._fast_first_max_critique_severity:
            return False, None

        convergence_result = self._convergence_tracker.check_convergence(ctx, round_num)
        similarity = self._coerce_float(
            getattr(
                convergence_result, "similarity", getattr(convergence_result, "avg_similarity", 0.0)
            ),
            default=0.0,
            minimum=0.0,
            maximum=1.0,
        )
        should_exit = bool(getattr(convergence_result, "converged", False)) or (
            similarity >= self._fast_first_convergence_threshold
            and not bool(getattr(convergence_result, "blocked_by_trickster", False))
        )
        if should_exit and ctx.result is not None:
            if ctx.result.metadata is None:
                ctx.result.metadata = {}
            ctx.result.metadata["fast_first_early_exit"] = {
                "round": round_num,
                "total_issues": total_issues,
                "max_severity": max_severity,
                "similarity": similarity,
            }

        return should_exit, convergence_result

    async def _critique_phase(
        self,
        ctx: DebateContext,
        critics: list[Agent],
        round_num: int,
    ) -> list[Critique]:
        """Execute critique phase with parallel generation."""
        from aragora.core import Message

        result = require_phase_result(ctx)
        proposals = ctx.proposals
        round_critiques: list[Critique] = []

        if not self._critique_with_agent:
            logger.warning("No critique_with_agent callback, skipping critiques")
            return round_critiques

        async def generate_critique(critic, proposal_agent, proposal):
            """Generate critique and return (critic, proposal_agent, result_or_error)."""
            logger.debug("critique_generating critic=%s target=%s", critic.name, proposal_agent)
            # Track timing for governor feedback
            start_time = time.perf_counter()
            governor = get_complexity_governor()
            # Use complexity-scaled timeout from governor
            base_timeout = getattr(critic, "timeout", AGENT_TIMEOUT_SECONDS)
            timeout = governor.get_scaled_timeout(float(base_timeout))
            # Use task context to distinguish concurrent streaming from same agent
            task_id = f"{critic.name}:critique:{proposal_agent}"
            try:
                with streaming_task_context(task_id):
                    if self._with_timeout:
                        crit_result = await self._with_timeout(
                            self._critique_with_agent(
                                critic,
                                proposal,
                                ctx.env.task if ctx.env else "",
                                ctx.context_messages,
                                target_agent=proposal_agent,
                            ),
                            critic.name,
                            timeout_seconds=timeout,
                        )
                    else:
                        crit_result = await self._critique_with_agent(
                            critic,
                            proposal,
                            ctx.env.task if ctx.env else "",
                            ctx.context_messages,
                            target_agent=proposal_agent,
                        )
                # Record success to governor
                latency_ms = (time.perf_counter() - start_time) * 1000
                governor.record_agent_response(critic.name, latency_ms, success=True)
                return (critic, proposal_agent, crit_result)
            except asyncio.TimeoutError as e:
                # Record timeout to governor
                governor.record_agent_timeout(critic.name, timeout)
                return (critic, proposal_agent, e)
            except (ConnectionError, OSError, ValueError, TypeError, RuntimeError) as e:
                # Specific agent failure modes: network errors, malformed responses, type mismatches
                latency_ms = (time.perf_counter() - start_time) * 1000
                governor.record_agent_response(critic.name, latency_ms, success=False)
                logger.warning(
                    "critique_agent_error critic=%s target=%s error_type=%s: %s",
                    critic.name,
                    proposal_agent,
                    type(e).__name__,
                    e,
                )
                return (critic, proposal_agent, e)
            except (RuntimeError, AttributeError, ImportError) as e:  # noqa: BLE001
                # Unexpected error - log at error level for investigation
                latency_ms = (time.perf_counter() - start_time) * 1000
                governor.record_agent_response(critic.name, latency_ms, success=False)
                logger.error(
                    "critique_unexpected_error critic=%s target=%s error_type=%s: %s",
                    critic.name,
                    proposal_agent,
                    type(e).__name__,
                    e,
                )
                return (critic, proposal_agent, e)

        # Create critique tasks based on topology with bounded concurrency
        # Semaphore prevents exhausting API rate limits with too many parallel requests
        critique_semaphore = asyncio.Semaphore(self._max_parallel_critiques)

        async def generate_critique_bounded(critic, proposal_agent, proposal):
            """Wrap critique generation with semaphore for bounded concurrency."""
            async with critique_semaphore:
                return await generate_critique(critic, proposal_agent, proposal)

        critique_tasks = []
        # Filter out empty/placeholder proposals to avoid wasting critic resources
        valid_proposals = {
            agent: content
            for agent, content in proposals.items()
            if content and "(Agent produced empty output)" not in content
        }
        if len(valid_proposals) < len(proposals):
            skipped = [a for a in proposals if a not in valid_proposals]
            logger.warning("critique_skip_empty_proposals skipped=%s", skipped)

        low_contention = self._is_low_contention_round(
            proposal_count=len(valid_proposals),
            critic_count=len(critics),
            round_num=round_num,
        )

        for proposal_agent, proposal in valid_proposals.items():
            if self._select_critics_for_proposal:
                selected_critics = self._select_critics_for_proposal(proposal_agent, critics)
            else:
                # Default: all critics except self
                selected_critics = [c for c in critics if c.name != proposal_agent]

            if low_contention:
                selected_critics = self._rank_agents_fast_first(list(selected_critics))[
                    : self._fast_first_max_critics_per_proposal
                ]

            for critic in selected_critics:
                critique_tasks.append(
                    asyncio.create_task(generate_critique_bounded(critic, proposal_agent, proposal))
                )

        # Emit heartbeat before critique phase
        self._emit_heartbeat(f"critique_round_{round_num}", "generating_critiques")

        # Stream output as each critique completes
        critique_count = 0
        total_critiques = len(critique_tasks)
        for completed_task in asyncio.as_completed(critique_tasks):
            try:
                critic, proposal_agent, crit_result = await completed_task
            except asyncio.CancelledError:
                raise
            except (ConnectionError, OSError, ValueError, TypeError, RuntimeError) as e:
                logger.error("critique_task_error error_type=%s: %s", type(e).__name__, e)
                continue
            except Exception as e:  # noqa: BLE001 - phase isolation
                logger.error("critique_task_unexpected error_type=%s: %s", type(e).__name__, e)
                continue

            critique_count += 1
            # Emit heartbeat every 3 critiques to signal progress
            if critique_count % 3 == 0 or critique_count == total_critiques:
                self._emit_heartbeat(
                    f"critique_round_{round_num}",
                    f"completed_{critique_count}_of_{total_critiques}",
                )

            if (
                crit_result is not None
                and not isinstance(crit_result, Exception)
                and _is_effectively_empty_critique(crit_result)
            ):
                provider = getattr(critic, "provider", None) or getattr(
                    critic, "model_type", "unknown"
                )
                logger.warning(
                    "critique_empty_response critic=%s provider=%s target=%s",
                    critic.name,
                    provider,
                    proposal_agent,
                )
                crit_result = None

            if isinstance(crit_result, Exception):
                logger.error(
                    "critique_error critic=%s target=%s error=%s",
                    critic.name,
                    proposal_agent,
                    crit_result,
                )
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure(critic.name)
            elif crit_result is None:
                # Handle timeout/error case where autonomic_executor returned None
                logger.warning(
                    "critique_returned_none critic=%s target=%s", critic.name, proposal_agent
                )
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure(critic.name)

                # Create placeholder critique so the debate can continue
                from aragora.core import Critique

                placeholder_critique = Critique(
                    agent=critic.name,
                    target_agent=proposal_agent,
                    target_content=proposals.get(proposal_agent, "[Proposal unavailable]"),
                    issues=["[Critique unavailable - agent timed out or encountered an error]"],
                    suggestions=[],
                    severity=0.0,
                    reasoning="Critique generation failed due to timeout or agent error.",
                )
                result.critiques.append(placeholder_critique)
                self._partial_critiques.append(placeholder_critique)
                round_critiques.append(placeholder_critique)

                # Emit placeholder critique event
                if "on_critique" in self.hooks:
                    self.hooks["on_critique"](
                        agent=critic.name,
                        target=proposal_agent,
                        issues=placeholder_critique.issues,
                        severity=placeholder_critique.severity,
                        round_num=round_num,
                        full_content=placeholder_critique.to_prompt(),
                    )
            else:
                if self.circuit_breaker:
                    self.circuit_breaker.record_success(critic.name)
                result.critiques.append(crit_result)
                self._partial_critiques.append(crit_result)
                round_critiques.append(crit_result)

                logger.debug(
                    "critique_complete critic=%s target=%s issues=%s severity=%s",
                    critic.name,
                    proposal_agent,
                    len(crit_result.issues),
                    crit_result.severity,
                )

                # Notify spectator
                if self._notify_spectator:
                    self._notify_spectator(
                        "critique",
                        agent=critic.name,
                        details=f"Critiqued {proposal_agent}: {len(crit_result.issues)} issues",
                        metric=crit_result.severity,
                    )

                # Get full critique content
                critique_content = crit_result.to_prompt()

                # Emit critique event (includes full_content for activity feeds)
                # NOTE: Previously also emitted on_message which caused duplicate display.
                # on_critique now includes full_content, so on_message is not needed.
                if "on_critique" in self.hooks:
                    self.hooks["on_critique"](
                        agent=critic.name,
                        target=proposal_agent,
                        issues=crit_result.issues,
                        severity=crit_result.severity,
                        round_num=round_num,
                        full_content=critique_content,
                    )

                # Record critique
                if self.recorder:
                    try:
                        self.recorder.record_turn(critic.name, critique_content, round_num)
                    except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                        logger.debug("Recorder error for critique: %s", e)

                # Add to context
                msg = Message(
                    role="critic",
                    agent=critic.name,
                    content=critique_content,
                    round=round_num,
                )
                ctx.add_message(msg)  # also appends to result.messages (#9661)
                self._partial_messages.append(msg)

        return round_critiques

    async def _revision_phase(
        self,
        ctx: DebateContext,
        critics: list[Agent],
        round_num: int,
    ) -> None:
        """Execute revision phase with parallel generation."""
        from aragora.core import Message

        result = require_phase_result(ctx)
        proposals = ctx.proposals

        if not self._generate_with_agent or not self._build_revision_prompt:
            logger.warning("Missing callbacks for revision phase")
            return

        # Get all critiques from this round for revision
        # NOTE: Critiques have target_agent set to the actual agent name (e.g., "alice", "bob"),
        # not "proposal". We filter per-agent below in the loop.
        all_critiques = list(result.critiques)

        if not all_critiques:
            return

        # Latency optimization (issue #268): pre-build per-agent critique index
        # to avoid O(agents * critiques) filtering in the revision loop below.
        from collections import defaultdict

        _critiques_by_target: dict[str, list] = defaultdict(list)
        for c in all_critiques:
            _critiques_by_target[c.target_agent].append(c)

        # Semaphore prevents exhausting API rate limits with too many parallel requests
        revision_semaphore = asyncio.Semaphore(self._max_parallel_revisions)

        async def generate_revision_bounded(agent, revision_prompt):
            """Wrap revision generation with semaphore for bounded concurrency."""
            # Track timing for governor feedback
            start_time = time.perf_counter()
            governor = get_complexity_governor()
            base_timeout = getattr(agent, "timeout", AGENT_TIMEOUT_SECONDS)
            timeout = governor.get_scaled_timeout(float(base_timeout))
            # Use task context to distinguish concurrent streaming from same agent
            task_id = f"{agent.name}:revision:{round_num}"
            try:
                async with revision_semaphore:
                    with streaming_task_context(task_id):
                        if self._with_timeout:
                            result = await self._with_timeout(
                                self._generate_with_agent(
                                    agent, revision_prompt, ctx.context_messages
                                ),
                                agent.name,
                                timeout_seconds=timeout,
                            )
                        else:
                            result = await self._generate_with_agent(
                                agent, revision_prompt, ctx.context_messages
                            )
                # Record success to governor
                latency_ms = (time.perf_counter() - start_time) * 1000
                governor.record_agent_response(agent.name, latency_ms, success=True)
                return result
            except asyncio.TimeoutError:
                # Record timeout to governor
                governor.record_agent_timeout(agent.name, timeout)
                raise
            except (ConnectionError, OSError, ValueError, TypeError, RuntimeError) as e:
                # Specific agent failure modes
                latency_ms = (time.perf_counter() - start_time) * 1000
                governor.record_agent_response(agent.name, latency_ms, success=False)
                logger.warning(
                    "revision_agent_error agent=%s error_type=%s: %s",
                    agent.name,
                    type(e).__name__,
                    e,
                )
                raise
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                # Unexpected error - log at error level
                latency_ms = (time.perf_counter() - start_time) * 1000
                governor.record_agent_response(agent.name, latency_ms, success=False)
                logger.error(
                    "revision_unexpected_error agent=%s error_type=%s: %s",
                    agent.name,
                    type(e).__name__,
                    e,
                )
                raise

        revision_agents = []
        revision_candidates = list(ctx.proposers)
        if self._is_low_contention_round(
            proposal_count=len(ctx.proposals),
            critic_count=len(critics),
            round_num=round_num,
        ):
            revision_candidates = self._rank_agents_fast_first(revision_candidates)

        for agent in revision_candidates:
            # Use pre-built index for O(1) critique lookup per agent
            agent_critiques = _critiques_by_target.get(agent.name, [])

            # Skip revision if no critiques for this agent
            if not agent_critiques:
                logger.debug("No critiques targeting %s, skipping revision", agent.name)
                continue

            revision_agents.append(agent)

        # Calculate dynamic phase timeout based on number of agents
        base_phase_timeout: float = AGENT_TIMEOUT_SECONDS
        if revision_agents:
            try:
                base_phase_timeout = max(
                    float(getattr(a, "timeout", AGENT_TIMEOUT_SECONDS)) for a in revision_agents
                )
            except (ValueError, TypeError, AttributeError):
                base_phase_timeout = AGENT_TIMEOUT_SECONDS
        phase_timeout = _calculate_phase_timeout(
            len(revision_agents),
            base_phase_timeout,
            self._max_parallel_revisions,
        )

        # Emit heartbeat before revision phase
        self._emit_heartbeat(
            f"revision_round_{round_num}", f"starting_{len(revision_agents)}_agents"
        )

        # Periodic heartbeat task during long-running revisions
        async def heartbeat_during_revisions():
            """Emit heartbeat during revisions to keep connection alive."""
            from aragora.config import HEARTBEAT_INTERVAL_SECONDS

            heartbeat_count = 0
            interval = HEARTBEAT_INTERVAL_SECONDS
            try:
                while True:
                    await asyncio.sleep(interval)
                    heartbeat_count += 1
                    self._emit_heartbeat(
                        f"revision_round_{round_num}",
                        f"in_progress_{heartbeat_count * interval}s",
                    )
            except asyncio.CancelledError:
                logger.debug("Heartbeat task cancelled during revision round %d", round_num)

        # Latency optimization (issue #268): use as_completed instead of gather
        # so that results are processed as they arrive, reducing time-to-first-
        # update and allowing downstream state (proposals dict, messages list)
        # to be populated incrementally.  This matches the pattern already used
        # in the critique and proposal phases.

        # Wrap each task so it carries the originating agent for identification
        # after as_completed reorders them.
        async def _tagged_revision(agent: Agent, revision_prompt: str):
            """Return (agent, result_or_exception) tuple."""
            try:
                rev = await generate_revision_bounded(agent, revision_prompt)
                return (agent, rev)
            except BaseException as exc:
                return (agent, exc)

        tagged_tasks = [
            asyncio.create_task(
                _tagged_revision(agent, revision_prompt),
                name=f"revision_{agent.name}_{round_num}",
            )
            for agent, revision_prompt in zip(
                revision_agents,
                [
                    self._build_revision_prompt(
                        a,
                        proposals.get(a.name, ""),
                        _critiques_by_target.get(a.name, []),
                        round_num,
                    )
                    for a in revision_agents
                ],
            )
        ]

        # Execute all revisions with bounded concurrency and phase-level timeout
        heartbeat_task = asyncio.create_task(heartbeat_during_revisions())
        revision_count = 0
        total_revisions = len(revision_agents)
        _first_revision_logged = False
        _revisions_start = time.perf_counter()

        try:
            for completed_task in asyncio.as_completed(tagged_tasks, timeout=phase_timeout):
                try:
                    agent, revised = await completed_task
                except asyncio.TimeoutError:
                    logger.error(
                        "revision_phase_timeout: phase exceeded %ss limit, agents=%s",
                        phase_timeout,
                        [a.name for a in revision_agents],
                    )
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 - phase isolation
                    logger.error("revision_task_error error=%s", e)
                    continue

                revision_count += 1

                # Track time-to-first-revision for latency visibility
                if not _first_revision_logged:
                    _first_ms = (time.perf_counter() - _revisions_start) * 1000
                    logger.info(
                        "time_to_first_revision_ms=%.1f agent=%s round=%d",
                        _first_ms,
                        agent.name,
                        round_num,
                    )
                    _first_revision_logged = True

                # Emit heartbeat for each completed revision
                self._emit_heartbeat(
                    f"revision_round_{round_num}",
                    f"processed_{revision_count}_of_{total_revisions}",
                )

                if isinstance(revised, BaseException):
                    logger.error("revision_error agent=%s error=%s", agent.name, revised)
                    if self.circuit_breaker:
                        self.circuit_breaker.record_failure(agent.name)
                    continue

                # At this point, revised is confirmed to be str
                revised_str: str = revised
                if self.circuit_breaker:
                    self.circuit_breaker.record_success(agent.name)

                proposals[agent.name] = revised_str
                logger.debug("revision_complete agent=%s length=%s", agent.name, len(revised_str))

                # Notify spectator
                if self._notify_spectator:
                    self._notify_spectator(
                        "propose",
                        agent=agent.name,
                        details=f"Revised proposal ({len(revised_str)} chars)",
                        metric=len(revised_str),
                    )

                # Create message
                msg = Message(
                    role="proposer",
                    agent=agent.name,
                    content=revised_str,
                    round=round_num,
                )
                ctx.add_message(msg)  # also appends to result.messages (#9661)
                self._partial_messages.append(msg)

                # Emit message event
                if "on_message" in self.hooks:
                    self.hooks["on_message"](
                        agent=agent.name,
                        content=revised_str,
                        role="proposer",
                        round_num=round_num,
                    )

                # Record revision
                if self.recorder:
                    try:
                        self.recorder.record_turn(agent.name, revised_str, round_num)
                    except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                        logger.debug("Recorder error for revision: %s", e)

                # Record position for grounded personas
                if self._record_grounded_position:
                    debate_id = (
                        result.id
                        if hasattr(result, "id")
                        else (ctx.env.task[:50] if ctx.env else "")
                    )
                    self._record_grounded_position(
                        agent.name, revised_str, debate_id, round_num, 0.75
                    )

                # Observe rhetorical patterns for audience engagement
                loop_id = ctx.loop_id if hasattr(ctx, "loop_id") else ""
                self._observe_rhetorical_patterns(agent.name, revised_str, round_num, loop_id)
        except asyncio.TimeoutError:
            logger.error(
                "revision_phase_timeout: phase exceeded %ss limit, agents=%s",
                phase_timeout,
                [a.name for a in revision_agents],
            )
        finally:
            # Cancel the heartbeat task now that revisions are done
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                logger.debug("Heartbeat task cleanup completed for round %d", round_num)

    async def _should_terminate(self, ctx: DebateContext, round_num: int) -> bool:
        """Check if debate should terminate early.

        Uses timeout protection on callbacks to prevent indefinite hangs.
        Includes RLM ready signal quorum check for agent self-termination.

        Note: Prefer calling _check_termination_conditions() directly when
        you need the termination source (e.g., for spectator events and metadata).
        This method is retained for backward compatibility.
        """
        source, _details = await self._check_termination_conditions(ctx, round_num)
        return source is not None

    async def _check_termination_conditions(
        self, ctx: DebateContext, round_num: int
    ) -> tuple[str | None, str]:
        """Check all termination conditions and return the source that triggered.

        Returns:
            Tuple of (source, details) where source is None if no termination,
            or one of "rlm_ready", "judge", "agent_vote", "stability".
        """
        # RLM ready signal check (agents self-signal readiness)
        # This is the most responsive - agents explicitly say "I'm done"
        if self._convergence_tracker.check_rlm_ready_quorum(ctx, round_num):
            logger.info("debate_terminate_rlm_ready round=%s", round_num)
            try:
                avg_conf = float(self._convergence_tracker.collective_readiness.avg_confidence)
                return "rlm_ready", f"Agent quorum ready (confidence={avg_conf:.2f})"
            except (TypeError, ValueError):
                return "rlm_ready", "Agent quorum ready"

        # Judge-based termination (with timeout protection)
        if self._check_judge_termination:
            result = await _with_callback_timeout(
                self._check_judge_termination(round_num, ctx.proposals, ctx.context_messages),
                timeout=DEFAULT_CALLBACK_TIMEOUT,
                default=(True, "Judge check timed out"),  # Continue on timeout
            )
            should_continue, reason = result
            if not should_continue:
                return "judge", reason or "Judge determined debate is conclusive"

        # Early stopping (agent votes) with timeout protection
        if self._check_early_stopping:
            should_continue = await _with_callback_timeout(
                self._check_early_stopping(round_num, ctx.proposals, ctx.context_messages),
                timeout=DEFAULT_CALLBACK_TIMEOUT,
                default=True,  # Continue on timeout
            )
            if not should_continue:
                return "agent_vote", "Agents voted to stop early"

        # Statistical stability detection (Beta-Binomial model)
        # Uses KS-distance between vote distributions to detect consensus stability
        if self._stability_detector and hasattr(ctx, "round_votes"):
            round_votes = getattr(ctx, "round_votes", {})
            if round_votes:
                stability_result = self._stability_detector.update(
                    round_votes=round_votes,
                    round_num=round_num,
                )
                if stability_result.recommendation == "stop":
                    logger.info(
                        "debate_terminate_stability round=%s score=%.3f ks=%.3f",
                        round_num,
                        stability_result.stability_score,
                        stability_result.ks_distance,
                    )
                    if "on_stability_stop" in self.hooks:
                        self.hooks["on_stability_stop"](
                            round_num,
                            stability_result.stability_score,
                            stability_result.ks_distance,
                        )
                    return (
                        "stability",
                        f"Vote distribution stabilized "
                        f"(score={stability_result.stability_score:.3f}, "
                        f"ks={stability_result.ks_distance:.3f})",
                    )

        return None, ""

    def _emit_early_stop_event(
        self,
        ctx: DebateContext,
        round_num: int,
        source: str,
        details: str,
    ) -> None:
        """Emit spectator and hook events for early termination.

        Args:
            ctx: The debate context
            round_num: Round number where early stop was triggered
            source: Termination source (rlm_ready, judge, agent_vote, stability)
            details: Human-readable reason for termination
        """
        total_rounds = self.protocol.rounds if self.protocol else 0
        rounds_saved = max(0, total_rounds - round_num)

        logger.info(
            "debate_early_terminated round=%s/%s source=%s details=%s",
            round_num,
            total_rounds,
            source,
            details[:100],
        )

        # Emit spectator event for real-time visualization
        if self._notify_spectator:
            self._notify_spectator(
                "early_stop",
                agent="system",
                details=f"Early stop at round {round_num}/{total_rounds}: {details} "
                f"(source={source}, saved {rounds_saved} rounds)",
                metric=float(round_num),
                round_number=round_num,
            )

        # Emit via EventEmitter for WebSocket clients
        if self.event_emitter:
            self.event_emitter.emit_sync(
                event_type="debate_early_terminated",
                debate_id=ctx.debate_id if hasattr(ctx, "debate_id") else "",
                round_num=round_num,
                total_rounds=total_rounds,
                source=source,
                details=details,
                rounds_saved=rounds_saved,
            )

    async def _refresh_evidence_for_round(self, ctx: DebateContext, round_num: int) -> None:
        """Refresh evidence based on claims made in the current round."""
        await refresh_evidence_for_round(
            ctx,
            round_num,
            self._refresh_evidence,
            self._skill_registry,
            self._enable_skills,
            self._notify_spectator,
            self.hooks,
            self._partial_critiques,
        )

    async def _refresh_with_skills(self, text: str, ctx: DebateContext) -> int:
        """Refresh evidence using skills for claim-specific searches."""
        return await refresh_with_skills(text, ctx, self._skill_registry)

    def get_partial_messages(self) -> list[Message]:
        """Get partial messages for timeout recovery."""
        return self._partial_messages

    def get_partial_critiques(self) -> list[Critique]:
        """Get partial critiques for timeout recovery."""
        return self._partial_critiques

    async def _compress_debate_context(self, ctx: DebateContext, round_num: int) -> None:
        """Compress debate context using RLM cognitive load limiter."""
        await compress_debate_context(
            ctx,
            round_num,
            self._compress_context,
            self.hooks,
            self._notify_spectator,
            self._partial_critiques,
        )

    async def _execute_final_synthesis_round(self, ctx: DebateContext, round_num: int) -> None:
        """Execute Round 7: Final Synthesis."""
        await execute_final_synthesis_round(
            ctx,
            round_num,
            self.circuit_breaker,
            self._generate_with_agent,
            self.hooks,
            self._notify_spectator,
            self._partial_messages,
        )

    def _build_final_synthesis_prompt(
        self,
        agent: Agent,
        current_proposal: str,
        all_proposals: dict,
        critiques: list,
        round_num: int,
    ) -> str:
        """Build prompt for Round 7 final synthesis."""
        return build_final_synthesis_prompt(
            agent, current_proposal, all_proposals, critiques, round_num
        )

    async def _fire_propulsion_event(
        self,
        event_type: str,
        ctx: DebateContext,
        round_num: int,
        data: dict | None = None,
    ) -> None:
        """Fire propulsion event to push work to the next stage."""
        await fire_propulsion_event(
            event_type,
            ctx,
            round_num,
            self._propulsion_engine,
            self._enable_propulsion,
            data or {},
        )
