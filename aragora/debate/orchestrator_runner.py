"""Debate execution runner extracted from Arena.

Contains _DebateExecutionState and the _run_inner helper methods that
coordinate debate initialization, infrastructure setup, phase execution,
metrics recording, completion handling, and resource cleanup.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aragora.core import DebateResult
from aragora.debate.complexity_governor import (
    classify_task_complexity,
    get_complexity_governor,
)
from aragora.debate.context import DebateContext
from aragora.logging_config import LogContext, get_logger as get_structured_logger
from aragora.observability.tracing import add_span_attributes
from aragora.server.metrics import (
    ACTIVE_DEBATES,
    track_debate_outcome,
)
from aragora.observability.metrics.debate_slo import (
    record_debate_completion_slo,
    update_debate_success_rate,
)

if TYPE_CHECKING:
    from aragora.debate.orchestrator import Arena

logger = get_structured_logger(__name__)

# ThinkPRM integration -- availability flag and helper functions

try:
    from aragora.verification.think_prm import (
        ProcessVerificationResult,
        ThinkPRMConfig,
        ThinkPRMVerifier,
    )

    THINK_PRM_AVAILABLE = True
except ImportError:
    THINK_PRM_AVAILABLE = False


def _convert_messages_to_think_prm_rounds(
    messages: list,
) -> list[dict]:
    """Convert debate Messages into ThinkPRM round format.

    Groups messages by round number and formats them as contribution dicts
    expected by ThinkPRMVerifier.verify_debate_process().

    Args:
        messages: List of aragora.core.Message objects with round attribute.

    Returns:
        List of round dicts, each with a 'contributions' list.
    """
    if not messages:
        return []

    # Group by round number
    rounds_map: dict[int, list[dict]] = {}
    for msg in messages:
        round_num = getattr(msg, "round", 0) or 0
        if round_num not in rounds_map:
            rounds_map[round_num] = []
        rounds_map[round_num].append(
            {
                "content": getattr(msg, "content", ""),
                "agent_id": getattr(msg, "agent", "unknown"),
                "dependencies": [],
            }
        )

    # Sort by round number and return
    return [{"contributions": rounds_map[r]} for r in sorted(rounds_map.keys())]


async def _run_think_prm_verification(
    arena: Arena,
    ctx: DebateContext,
) -> ProcessVerificationResult | None:
    """Run ThinkPRM verification on completed debate rounds.

    Args:
        arena: The Arena instance with agents and protocol config.
        ctx: DebateContext with context_messages and debate_id.

    Returns:
        ProcessVerificationResult or None if verification cannot run.
    """
    if not THINK_PRM_AVAILABLE:
        return None

    agents = getattr(arena, "agents", [])
    if not agents:
        return None

    messages = getattr(ctx, "context_messages", [])
    if not messages:
        return None

    # Convert messages to ThinkPRM round format
    rounds = _convert_messages_to_think_prm_rounds(messages)
    if not rounds:
        return None

    # Find the verifier agent
    protocol = getattr(arena, "protocol", None)
    verifier_agent_id = getattr(protocol, "think_prm_verifier_agent", "claude")
    parallel = getattr(protocol, "think_prm_parallel", True)
    max_parallel = getattr(protocol, "think_prm_max_parallel", 3)

    # Use the autonomic executor's generate method as the query function
    autonomic = getattr(arena, "autonomic", None)
    if autonomic is None:
        return None

    # Find the agent to use for verification
    verifier = None
    for agent in agents:
        if getattr(agent, "name", None) == verifier_agent_id:
            verifier = agent
            break
    if verifier is None and agents:
        verifier = agents[0]  # Fallback to first agent

    async def query_fn(agent_id: str, prompt: str, max_tokens: int = 1000) -> str:
        return await autonomic.generate(verifier, prompt, [])

    # Set the debate_id on round data for result tracking
    if rounds:
        rounds[0]["debate_id"] = getattr(ctx, "debate_id", "unknown")

    # Configure and run verifier
    config = ThinkPRMConfig(
        verifier_agent_id=verifier_agent_id,
        parallel_verification=parallel,
        max_parallel=max_parallel,
    )
    prm_verifier = ThinkPRMVerifier(config)

    try:
        result = await prm_verifier.verify_debate_process(rounds, query_fn)
        # Override debate_id from context
        result.debate_id = getattr(ctx, "debate_id", "unknown")
        return result
    except (ValueError, TypeError, RuntimeError, OSError) as e:
        logger.warning("think_prm_verification_failed: %s", e)
        return None


@dataclass
class _DebateExecutionState:
    """Internal state for debate execution passed between _run_inner helper methods."""

    debate_id: str
    correlation_id: str
    domain: str
    task_complexity: Any  # TaskComplexity enum
    ctx: DebateContext
    gupp_bead_id: str | None = None
    gupp_hook_entries: dict[str, str] = field(default_factory=dict)
    debate_status: str = "completed"
    debate_start_time: float = 0.0


async def _populate_result_cost(
    result: DebateResult,
    debate_id: str,
    extensions: Any,
) -> None:
    """Populate DebateResult cost fields from cost tracker data.

    Called after extensions.on_debate_complete() to ensure the result
    object carries accurate cost information for downstream consumers
    (DecisionPlanFactory, budget coordinator, etc.).

    Uses DebateCostTracker (via extensions) as the primary source for
    per-agent breakdowns, falling back to the global CostTracker buffer.
    """
    try:
        # Primary source: DebateCostTracker (has per-agent, per-round, per-model)
        debate_summary = None
        get_summary = getattr(extensions, "get_debate_cost_summary", None)
        if get_summary is not None:
            debate_summary = get_summary(debate_id)

        if debate_summary is not None:
            total = float(debate_summary.total_cost_usd)
            if total > 0:
                result.total_cost_usd = total
            result.total_tokens = debate_summary.total_tokens_in + debate_summary.total_tokens_out
            per_agent: dict[str, float] = {}
            for name, breakdown in debate_summary.per_agent.items():
                per_agent[name] = float(breakdown.total_cost_usd)
            if per_agent:
                result.per_agent_cost = per_agent
        else:
            # Fallback: global CostTracker buffer
            cost_tracker = getattr(extensions, "cost_tracker", None)
            if cost_tracker is not None:
                debate_costs = await cost_tracker.get_debate_cost(debate_id)
                if debate_costs:
                    total = float(debate_costs.get("total_cost_usd", 0))
                    if total > 0:
                        result.total_cost_usd = total

                    cost_by_agent = debate_costs.get("cost_by_agent", {})
                    if cost_by_agent:
                        result.per_agent_cost = {str(k): float(v) for k, v in cost_by_agent.items()}

        # Carry budget limit through to result
        budget_limit = getattr(extensions, "debate_budget_limit_usd", None)
        if budget_limit is not None:
            result.budget_limit_usd = budget_limit

    except (ValueError, TypeError, KeyError, AttributeError) as e:
        logger.debug("cost_population_failed (non-critical): %s", e)


def _persist_debate_cost_to_km(debate_id: str, extensions: Any) -> None:
    """Persist debate cost summary to Knowledge Mound via CostAdapter.

    Stores the DebateCostSummary as a KM snapshot so that historical
    per-debate costs are available for trend analysis and anomaly detection.
    """
    try:
        get_summary = getattr(extensions, "get_debate_cost_summary", None)
        if get_summary is None:
            return
        summary = get_summary(debate_id)
        if summary is None:
            return

        from aragora.billing.cost_tracker import get_cost_tracker

        tracker = get_cost_tracker()
        km_adapter = getattr(tracker, "_km_adapter", None)
        if km_adapter is None:
            return

        store_fn = getattr(km_adapter, "store_debate_cost_summary", None)
        if store_fn is not None:
            store_fn(summary.to_dict())
            logger.debug("debate_cost_persisted_to_km debate=%s", debate_id)
    except (ImportError, RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
        logger.debug("debate_cost_km_persist_failed (non-critical): %s", e)


async def initialize_debate_context(
    arena: Arena,
    correlation_id: str,
) -> _DebateExecutionState:
    """Initialize debate context and return execution state.

    Sets up:
    - Debate ID and correlation ID
    - Convergence detector (debate-scoped cache)
    - Knowledge Mound context
    - Culture hints
    - DebateContext with all dependencies
    - BeliefNetwork (if enabled)
    - Task complexity classification
    - Question domain classification
    - Agent selection and hierarchy roles
    - Agent-to-agent channels
    """
    import uuid

    debate_id = str(uuid.uuid4())
    if not correlation_id:
        correlation_id = f"corr-{debate_id[:8]}"

    _init_start = time.perf_counter()

    # Reinitialize convergence detector with debate-scoped cache
    arena._reinit_convergence_for_debate(debate_id)

    # Extract domain early for metrics
    domain = arena._extract_debate_domain()

    # Initialize Knowledge Mound context and culture hints concurrently.
    # Latency optimization (issue #268): these two independent I/O
    # operations ran sequentially before; gather them in parallel.
    async def _init_km() -> None:
        await arena._init_km_context(debate_id, domain)

    async def _init_culture() -> None:
        culture_hints = arena._get_culture_hints(debate_id)
        if culture_hints:
            arena._apply_culture_hints(culture_hints)

    _gather_results = await asyncio.gather(_init_km(), _init_culture(), return_exceptions=True)
    # KM init (index 0) is critical – propagate its errors.
    # Culture hints (index 1) are best-effort.
    if isinstance(_gather_results[0], BaseException):
        raise _gather_results[0]

    _init_elapsed_ms = (time.perf_counter() - _init_start) * 1000
    logger.debug("debate_context_setup elapsed_ms=%.1f", _init_elapsed_ms)

    # Create shared context for all phases
    ctx = DebateContext(
        env=arena.env,
        agents=arena.agents,
        start_time=time.time(),
        debate_id=debate_id,
        correlation_id=correlation_id,
        domain=domain,
        hook_manager=arena.hook_manager,
        org_id=arena.org_id,
        auth_context=getattr(arena, "auth_context", None),
        budget_check_callback=lambda round_num: arena._budget_coordinator.check_budget_mid_debate(
            debate_id, round_num
        ),
    )
    ctx.molecule_orchestrator = arena.molecule_orchestrator
    ctx.checkpoint_bridge = arena.checkpoint_bridge

    # Wire PromptBuilder onto context so ContextInitializer can inject
    # Knowledge Mound context as a structured prompt section
    ctx._prompt_builder = arena.prompt_builder  # type: ignore[attr-defined]

    # Initialize BeliefNetwork with KM seeding if enabled
    if getattr(arena.protocol, "enable_km_belief_sync", False):
        ctx.belief_network = arena._setup_belief_network(
            debate_id=debate_id,
            topic=arena.env.task,
            seed_from_km=True,
        )

    # Classify task complexity and configure adaptive timeouts
    task_complexity = classify_task_complexity(arena.env.task)
    governor = get_complexity_governor()
    governor.set_task_complexity(task_complexity)

    # Wire governor to API agents for per-agent adaptive timeout management
    from aragora.agents.api_agents.base import APIAgent

    for agent in arena.agents:
        if isinstance(agent, APIAgent):
            agent.set_complexity_governor(governor)

    # Classify question domain for accurate persona selection.
    # Latency optimization (issue #268): when LLM classification is enabled
    # it is dispatched as a background task so that it does not block the
    # time-to-first-proposal.  The keyword-based fallback runs synchronously
    # and is fast enough to complete inline.
    if arena.prompt_builder:
        try:
            from aragora.utils.env import is_offline_mode

            use_llm = bool(getattr(arena.protocol, "enable_llm_question_classification", True))
            if is_offline_mode():
                use_llm = False

            if use_llm:
                # Run fast heuristic classification first (keyword-based,
                # sub-millisecond) so agents always have a domain before
                # their first prompt is built.
                _classify_start = time.perf_counter()
                await arena.prompt_builder.classify_question_async(use_llm=False)
                _classify_ms = (time.perf_counter() - _classify_start) * 1000
                logger.debug("question_classification_heuristic elapsed_ms=%.1f", _classify_ms)

                # Dispatch LLM classification in the background -- proposals
                # can start before it finishes.
                async def _bg_classify() -> None:
                    try:
                        await arena.prompt_builder.classify_question_async(use_llm=True)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                    except Exception:  # noqa: BLE001, S110 - best-effort background classification; failure is non-critical
                        logger.debug("Background question classification failed", exc_info=True)

                ctx.background_classification_task = asyncio.create_task(_bg_classify())  # type: ignore[attr-defined]
            else:
                await arena.prompt_builder.classify_question_async(use_llm=False)
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logger.warning("Question classification timed out: %s", e)
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning("Question classification failed with data error: %s", e)
        except (RuntimeError, OSError, ImportError) as e:
            logger.exception("Unexpected question classification error: %s", e)
        except Exception as e:  # noqa: BLE001 - final fallback after specific handlers above
            logger.warning("Question classification failed (API or other error): %s", e)

    # Apply performance-based agent selection if enabled
    if arena.use_performance_selection:
        arena.agents = arena._select_debate_team(arena.agents)
        ctx.agents = arena.agents

        # Capture agent selection score breakdown for transparency
        selector = getattr(arena, "agent_selector", None)
        if selector is not None:
            reasoning = getattr(selector, "_last_selection_reasoning", None)
            if reasoning and ctx.result is not None:
                if not isinstance(getattr(ctx.result, "metadata", None), dict):
                    ctx.result.metadata = {}
                ctx.result.metadata["selection_reasoning"] = reasoning

    # Assign hierarchy roles to agents (Gastown pattern)
    arena._assign_hierarchy_roles(ctx, task_type=domain)

    # Initialize agent-to-agent channels
    await arena._setup_agent_channels(ctx, debate_id)

    return _DebateExecutionState(
        debate_id=debate_id,
        correlation_id=correlation_id,
        domain=domain,
        task_complexity=task_complexity,
        ctx=ctx,
    )


async def setup_debate_infrastructure(
    arena: Arena,
    state: _DebateExecutionState,
) -> None:
    """Set up debate infrastructure before execution.

    Handles:
    - Structured logging for debate start
    - Trackers notification
    - Agent preview emission
    - Budget validation
    - GUPP hook tracking initialization
    - Initial result creation
    """
    ctx = state.ctx

    # Structured logging for debate lifecycle
    with LogContext(trace_id=state.correlation_id):
        logger.info(
            "debate_start",
            debate_id=state.debate_id,
            complexity=state.task_complexity.value,
            agent_count=len(arena.agents),
            agents=[a.name for a in arena.agents],
            domain=state.domain,
            task_length=len(arena.env.task),
        )

    # Notify subsystem coordinator of debate start
    arena._trackers.on_debate_start(ctx)

    # Emit agent preview for quick UI feedback
    arena._emit_agent_preview()

    # Reset autotuner timer at debate start (if configured)
    if getattr(arena._budget_coordinator, "autotuner", None) is not None:
        arena._budget_coordinator.autotuner.start()

    # Check budget before starting debate (may raise BudgetExceededError)
    arena._budget_coordinator.check_budget_before_debate(
        state.debate_id,
        num_agents=len(arena.agents),
        rounds=arena.protocol.rounds,
    )

    # Pre-debate compliance policy check
    try:
        from aragora.debate.extensions import check_pre_debate_compliance

        compliance_monitor = getattr(arena, "compliance_monitor", None)
        compliance_result = check_pre_debate_compliance(
            debate_id=state.debate_id,
            task=arena.env.task,
            domain=state.domain,
            compliance_monitor=compliance_monitor,
        )
        for warning in compliance_result.warnings:
            logger.warning("compliance_warning: %s", warning)
        if not compliance_result.allowed:
            raise RuntimeError(
                f"Debate blocked by compliance policy: {'; '.join(compliance_result.issues)}"
            )
    except ImportError:
        pass  # Compliance module not available
    except RuntimeError:
        raise  # Re-raise compliance block
    except (ValueError, TypeError, AttributeError, OSError) as e:
        logger.debug("Pre-debate compliance check failed (non-critical): %s", e)

    # Initialize per-debate budget tracking in extensions
    arena.extensions.setup_debate_budget(state.debate_id)

    # Wire per-call cost tracking into the AutonomicExecutor so that
    # every agent call records its cost with round number and operation.
    try:
        from aragora.billing.debate_costs import get_debate_cost_tracker

        debate_cost_tracker = get_debate_cost_tracker()
        arena.autonomic.set_debate_cost_tracker(debate_cost_tracker, state.debate_id)
    except (ImportError, RuntimeError, TypeError, AttributeError) as e:
        logger.debug("Per-call cost tracking setup skipped: %s", e)

    # Initialize GUPP hook tracking for crash recovery
    if getattr(arena.protocol, "enable_hook_tracking", False):
        try:
            state.gupp_bead_id = await arena._create_pending_debate_bead(
                state.debate_id, arena.env.task
            )
            if state.gupp_bead_id:
                state.gupp_hook_entries = await arena._init_hook_tracking(
                    state.debate_id, state.gupp_bead_id
                )
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.debug("GUPP initialization failed (non-critical): %s", e)

    # Initialize result early for timeout recovery
    ctx.result = DebateResult(
        task=arena.env.task,
        consensus_reached=False,
        confidence=0.0,
        messages=[],
        critiques=[],
        votes=[],
        rounds_used=0,
        final_answer="",
    )

    # Initialize LiveExplainabilityStream if enabled
    if getattr(arena, "enable_live_explainability", False):
        try:
            from aragora.explainability.live_stream import LiveExplainabilityStream

            stream = LiveExplainabilityStream(
                event_emitter=getattr(arena, "_event_emitter", None),
            )
            arena.live_explainability_stream = stream

            # Subscribe to EventBus events for real-time factor tracking
            event_bus = getattr(arena, "event_bus", None)
            if event_bus is not None:
                _subscribe_live_explainability(event_bus, stream)
                logger.info(
                    "live_explainability_initialized debate_id=%s",
                    state.debate_id,
                )
        except (ImportError, RuntimeError, ValueError, TypeError) as e:
            logger.debug("LiveExplainabilityStream init failed (non-critical): %s", e)
            arena.live_explainability_stream = None

    # Initialize ActiveIntrospectionTracker if enabled
    if getattr(arena, "enable_introspection", False):
        try:
            from aragora.introspection.active import ActiveIntrospectionTracker

            tracker = ActiveIntrospectionTracker()
            arena.active_introspection_tracker = tracker

            # Subscribe to EventBus events for real-time agent tracking
            event_bus = getattr(arena, "event_bus", None)
            if event_bus is not None:
                _subscribe_active_introspection(event_bus, tracker)
                logger.info(
                    "active_introspection_initialized debate_id=%s",
                    state.debate_id,
                )
        except (ImportError, RuntimeError, ValueError, TypeError) as e:
            logger.debug("ActiveIntrospectionTracker init failed (non-critical): %s", e)
            arena.active_introspection_tracker = None

    # Record start time for metrics
    state.debate_start_time = time.perf_counter()


def _subscribe_active_introspection(event_bus: Any, tracker: Any) -> None:
    """Subscribe ActiveIntrospectionTracker handlers to EventBus events.

    Maps debate event types to the tracker's methods for real-time
    agent self-awareness tracking during active debates.
    """
    from aragora.debate.event_bus import DebateEvent
    from aragora.introspection.active import RoundMetrics

    def _on_agent_message(event: DebateEvent) -> None:
        agent = event.data.get("agent", "unknown")
        round_num = event.data.get("round_num", 0)
        role = event.data.get("role", "")

        # Track proposals and critiques as round metrics
        metrics = RoundMetrics(round_number=round_num)
        if role == "proposer":
            metrics.proposals_made = 1
        elif role == "critic":
            metrics.critiques_given = 1

        if metrics.proposals_made > 0 or metrics.critiques_given > 0:
            tracker.update_round(agent, round_num, metrics)

    def _on_round_start(event: DebateEvent) -> None:
        # round_start is informational; no tracker action needed
        pass

    def _on_round_end(event: DebateEvent) -> None:
        round_num = event.data.get("round_num", 0)
        if hasattr(tracker, "update_round"):
            # Record round completion for all tracked agents
            for agent_name in list(tracker.get_all_summaries().keys()):
                summary = tracker.get_summary(agent_name)
                if summary and summary.rounds_completed < round_num:
                    tracker.update_round(
                        agent_name,
                        round_num,
                        RoundMetrics(round_number=round_num),
                    )

    event_bus.subscribe_sync("agent_message", _on_agent_message)
    event_bus.subscribe_sync("round_start", _on_round_start)
    event_bus.subscribe_sync("round_end", _on_round_end)


def _subscribe_live_explainability(event_bus: Any, stream: Any) -> None:
    """Subscribe LiveExplainabilityStream handlers to EventBus events.

    Maps debate event types to the stream's on_* methods for real-time
    factor decomposition during active debates.
    """
    from aragora.debate.event_bus import DebateEvent

    def _on_agent_message(event: DebateEvent) -> None:
        role = event.data.get("role", "proposer")
        agent = event.data.get("agent", "unknown")
        content = event.data.get("content", "")
        round_num = event.data.get("round_num", 0)

        if role == "proposer":
            stream.on_proposal(agent, content, round_num=round_num)
        elif role == "critic":
            stream.on_critique(agent, content, round_num=round_num)
        elif role in ("reviser", "refiner"):
            stream.on_refinement(agent, content, round_num=round_num)

    def _on_vote(event: DebateEvent) -> None:
        agent = event.data.get("agent", "unknown")
        choice = event.data.get("choice", "")
        confidence = event.data.get("confidence", 0.5)
        round_num = event.data.get("round_num", 0)
        reasoning = event.data.get("reasoning", "")
        stream.on_vote(
            agent,
            choice,
            confidence=confidence,
            round_num=round_num,
            reasoning=reasoning,
        )

    def _on_consensus(event: DebateEvent) -> None:
        confidence = event.data.get("confidence", 0.0)
        position = event.data.get("position", "")
        stream.on_consensus(conclusion=position, confidence=confidence)

    event_bus.subscribe_sync("agent_message", _on_agent_message)
    event_bus.subscribe_sync("vote", _on_vote)
    event_bus.subscribe_sync("consensus", _on_consensus)


async def execute_debate_phases(
    arena: Arena,
    state: _DebateExecutionState,
    span: Any,
) -> None:
    """Execute all debate phases with tracing and error handling.

    Args:
        arena: The Arena instance
        state: The debate execution state
        span: OpenTelemetry span for tracing
    """
    from aragora.exceptions import EarlyStopError

    ctx = state.ctx

    # Initialize LatencyProfiler for per-phase timing (non-invasive)
    latency_profiler = None
    try:
        from aragora.debate.optimizations import LatencyProfiler

        latency_profiler = LatencyProfiler()
        # Store on context for downstream access (e.g., result metadata)
        ctx.latency_profiler = latency_profiler  # type: ignore[attr-defined]

        # Wire profiler into PhaseExecutor via metrics callback
        original_callback = arena.phase_executor._config.metrics_callback

        def _profiling_metrics_callback(metric_name: str, value: float) -> None:
            # Extract phase name from metric (e.g., "phase_proposal_duration_ms")
            if metric_name.startswith("phase_") and metric_name.endswith("_duration_ms"):
                phase_name = metric_name[6:-12]  # strip prefix/suffix
                record = latency_profiler.phase(phase_name)
                # Record already has timing from PhaseExecutor; store duration directly
                record._record.duration_ms = value
                record._record.start_time = time.perf_counter() - value / 1000
                record._record.end_time = time.perf_counter()
            if original_callback:
                original_callback(metric_name, value)

        arena.phase_executor._config.metrics_callback = _profiling_metrics_callback
    except (ImportError, AttributeError, TypeError) as e:
        logger.debug("LatencyProfiler not available: %s", e)

    try:
        # Check operator intervention pause before starting phase execution
        try:
            from aragora.debate.operator_intervention import get_operator_manager

            _intervention = get_operator_manager()
            await _intervention.wait_if_paused(state.debate_id)
        except ImportError:
            pass
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Intervention pause check skipped: %s", e)

        # Execute all phases via PhaseExecutor with OpenTelemetry tracing
        execution_result = await arena.phase_executor.execute(
            ctx,
            debate_id=state.debate_id,
        )
        arena._log_phase_failures(execution_result)

        # Emit latency profile after successful execution
        if latency_profiler and latency_profiler.records:
            profile_summary = latency_profiler.report()
            if hasattr(ctx, "result") and ctx.result and isinstance(ctx.result.metadata, dict):
                ctx.result.metadata["latency_profile"] = profile_summary

    except asyncio.TimeoutError:
        # Timeout recovery - use partial results from context
        ctx.result.messages = ctx.partial_messages
        ctx.result.critiques = ctx.partial_critiques
        ctx.result.rounds_used = ctx.partial_rounds
        state.debate_status = "timeout"
        span.set_attribute("debate.status", "timeout")
        logger.warning("Debate timed out, returning partial results")

    except EarlyStopError:
        state.debate_status = "aborted"
        span.set_attribute("debate.status", "aborted")
        raise

    except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as e:
        state.debate_status = "error"
        span.set_attribute("debate.status", "error")
        span.record_exception(e)
        # Mark debate as failed in intervention manager
        try:
            from aragora.debate.operator_intervention import get_operator_manager

            get_operator_manager().mark_failed(state.debate_id)
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError):
            pass
        raise


def record_debate_metrics(
    arena: Arena,
    state: _DebateExecutionState,
    span: Any,
) -> None:
    """Record debate metrics in the finally block.

    Args:
        arena: The Arena instance
        state: The debate execution state
        span: OpenTelemetry span for tracing
    """
    ACTIVE_DEBATES.dec()
    duration = time.perf_counter() - state.debate_start_time
    ctx = state.ctx

    # Get consensus info from result
    consensus_reached = getattr(ctx.result, "consensus_reached", False)
    confidence = getattr(ctx.result, "confidence", 0.0)

    # Add final attributes to span
    add_span_attributes(
        span,
        {
            "debate.status": state.debate_status,
            "debate.duration_seconds": duration,
            "debate.consensus_reached": consensus_reached,
            "debate.confidence": confidence,
            "debate.message_count": len(ctx.result.messages) if ctx.result else 0,
        },
    )

    track_debate_outcome(
        status=state.debate_status,
        domain=state.domain,
        duration_seconds=duration,
        consensus_reached=consensus_reached,
        confidence=confidence,
    )

    # Record SLO-specific metrics for percentile tracking (p50/p95/p99)
    if state.debate_status == "completed":
        outcome = "consensus" if consensus_reached else "no_consensus"
    elif state.debate_status == "timeout":
        outcome = "timeout"
    else:
        outcome = "error"
    record_debate_completion_slo(duration, outcome)
    update_debate_success_rate(consensus_reached)

    # Structured logging for debate completion
    logger.info(
        "debate_end",
        debate_id=state.debate_id,
        status=state.debate_status,
        duration_seconds=round(duration, 3),
        consensus_reached=consensus_reached,
        confidence=round(confidence, 3),
        rounds_used=ctx.result.rounds_used if ctx.result else 0,
        message_count=len(ctx.result.messages) if ctx.result else 0,
        domain=state.domain,
    )

    arena._track_circuit_breaker_metrics()


async def handle_debate_completion(
    arena: Arena,
    state: _DebateExecutionState,
) -> None:
    """Handle post-debate completion tasks.

    Includes:
    - Trackers notification
    - Extensions triggering (billing, training export)
    - Budget recording
    - Knowledge Mound ingestion
    - GUPP hook completion
    - Bead creation
    - Supabase sync queuing
    """
    ctx = state.ctx

    # Notify subsystem coordinator of debate completion
    if ctx.result:
        arena._trackers.on_debate_complete(ctx, ctx.result)

    # Trigger extensions (billing, training export)
    arena.extensions.on_debate_complete(ctx, ctx.result, arena.agents)

    # Populate DebateResult cost fields from cost tracker
    if ctx.result:
        await _populate_result_cost(ctx.result, state.debate_id, arena.extensions)

    # Persist debate cost summary to Knowledge Mound via CostAdapter
    if ctx.result:
        _persist_debate_cost_to_km(state.debate_id, arena.extensions)

    # Record debate cost against organization budget
    if ctx.result:
        arena._budget_coordinator.record_debate_cost(
            state.debate_id, ctx.result, extensions=arena.extensions
        )

    # Ingest high-confidence consensus into Knowledge Mound (background, non-blocking)
    if ctx.result:

        async def _km_ingest_background() -> None:
            _ingestion_succeeded = False
            _last_error: Exception | None = None
            for _attempt in range(3):
                try:
                    await arena._ingest_debate_outcome(ctx.result)
                    _ingestion_succeeded = True
                    break
                except (ConnectionError, OSError, ValueError, TypeError, AttributeError) as e:
                    _last_error = e
                    if _attempt < 2:
                        await asyncio.sleep(2**_attempt)  # 1s, 2s backoff
            if not _ingestion_succeeded and _last_error is not None:
                logger.warning(
                    "Knowledge Mound ingestion failed after 3 attempts for debate %s: %s",
                    state.debate_id,
                    _last_error,
                )
                try:
                    from aragora.knowledge.mound.ingestion_queue import IngestionDeadLetterQueue

                    dlq = IngestionDeadLetterQueue()
                    result_dict = ctx.result.to_dict() if hasattr(ctx.result, "to_dict") else {}
                    dlq.enqueue(state.debate_id, result_dict, str(_last_error))
                except (ImportError, OSError, ValueError, TypeError, RuntimeError) as dlq_err:
                    logger.debug("DLQ enqueue failed: %s", dlq_err)

        _km_task = asyncio.create_task(_km_ingest_background())
        setattr(ctx, "_km_ingest_task", _km_task)
        _km_task.add_done_callback(
            lambda t: logger.warning("[km-ingest] Background ingestion error: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )

    # Capture epistemic settlement metadata for future review
    if ctx.result:
        try:
            from aragora.debate.settlement import EpistemicSettlementTracker

            tracker = EpistemicSettlementTracker()
            settlement = tracker.capture_settlement(ctx.result)
            logger.debug("Settlement captured for debate %s", state.debate_id)
            # Record settlement metrics
            try:
                from aragora.observability.metrics.settlement import (
                    record_settlement_captured,
                    record_settlement_confidence,
                    record_settlement_falsifiers,
                )

                record_settlement_captured(
                    status=getattr(settlement, "status", "settled") if settlement else "settled"
                )
                confidence = getattr(ctx.result, "confidence", 0.0)
                if confidence:
                    record_settlement_confidence(confidence)
                falsifier_count = len(getattr(settlement, "falsifiers", [])) if settlement else 0
                record_settlement_falsifiers(falsifier_count)
            except (ImportError, RuntimeError, ValueError, TypeError, AttributeError):
                pass
        except ImportError:
            pass
        except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.debug("Settlement capture skipped: %s", e)

    # Register debate with intervention manager for operator controls
    try:
        from aragora.debate.operator_intervention import get_operator_manager

        mgr = get_operator_manager()
        if mgr.get_status(state.debate_id):
            mgr.mark_completed(state.debate_id)
    except ImportError:
        pass
    except (RuntimeError, ValueError, TypeError, AttributeError) as e:
        logger.debug("Intervention cleanup skipped: %s", e)

    # Auto-attach compliance artifacts for regulated domains (background, non-blocking)
    if ctx.result and getattr(ctx, "domain", "general") in {
        "healthcare",
        "finance",
        "legal",
        "compliance",
    }:

        def _attach_compliance() -> None:
            try:
                from aragora.compliance.eu_ai_act import (
                    ComplianceArtifactGenerator,
                    RiskClassifier,
                )

                classifier = RiskClassifier()
                task_desc = getattr(ctx.env, "task", "")
                risk = classifier.classify(task_desc)
                risk_levels = {"minimal": 0, "limited": 1, "high": 2, "unacceptable": 3}
                if risk_levels.get(risk.risk_level.value, 0) >= 1:
                    generator = ComplianceArtifactGenerator()
                    receipt_dict = ctx.result.to_dict() if hasattr(ctx.result, "to_dict") else {}
                    bundle = generator.generate(receipt_dict)
                    if hasattr(ctx.result, "metadata") and isinstance(ctx.result.metadata, dict):
                        ctx.result.metadata["compliance_artifacts"] = bundle.to_dict()
                    logger.info(
                        "Attached compliance artifacts for debate %s (risk=%s)",
                        state.debate_id,
                        risk.risk_level.value,
                    )
            except ImportError:
                logger.debug("Compliance module not available for auto-attach")
            except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
                logger.debug("Compliance auto-attach failed (non-critical): %s", e)

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _attach_compliance)

    # Complete GUPP hook tracking for crash recovery
    if state.gupp_bead_id and state.gupp_hook_entries:
        try:
            success = state.debate_status == "completed"
            await arena._update_debate_bead(state.gupp_bead_id, ctx.result, success)
            await arena._complete_hook_tracking(
                state.gupp_bead_id,
                state.gupp_hook_entries,
                success,
                error_msg="" if success else f"Debate {state.debate_status}",
            )
            if success:
                ctx.result.bead_id = state.gupp_bead_id
        except (ConnectionError, OSError, ValueError, TypeError, AttributeError) as e:
            logger.debug("GUPP completion failed (non-critical): %s", e)
    # Create a Bead if GUPP didn't already create one
    elif ctx.result and not state.gupp_bead_id:
        try:
            bead_id = await arena._create_debate_bead(ctx.result)
            if bead_id:
                ctx.result.bead_id = bead_id
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as e:
            logger.debug("Bead creation failed (non-critical): %s", e)

    # Post-debate workflow fallback: run if FeedbackPhase didn't trigger it
    if (
        getattr(arena, "enable_post_debate_workflow", False)
        and getattr(arena, "post_debate_workflow", None)
        and not getattr(ctx, "post_debate_workflow_triggered", False)
    ):
        try:
            workflow = arena.post_debate_workflow
            threshold = getattr(arena, "post_debate_workflow_threshold", 0.0)
            confidence = getattr(ctx.result, "confidence", 0.0) if ctx.result else 0.0
            if confidence >= threshold:
                import asyncio as _asyncio

                async def _run_fallback_workflow() -> None:
                    try:
                        await workflow.execute({"debate_result": ctx.result})
                    except (
                        RuntimeError,
                        ValueError,
                        TypeError,
                        OSError,
                        ConnectionError,
                    ) as wf_err:
                        logger.debug("Post-debate workflow fallback failed: %s", wf_err)

                _fallback_task = _asyncio.create_task(_run_fallback_workflow())
                _fallback_task.add_done_callback(
                    lambda t: logger.warning(
                        "[workflow-fallback] Background workflow failed: %s", t.exception()
                    )
                    if not t.cancelled() and t.exception()
                    else None
                )
                logger.info(
                    "[workflow-fallback] Triggered post-debate workflow for debate %s",
                    state.debate_id,
                )
        except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.debug("Post-debate workflow fallback setup failed: %s", e)

    # Run post-debate coordinator pipeline (default-on, opt-out via disable_post_debate_pipeline)
    from aragora.debate.post_debate_coordinator import DEFAULT_POST_DEBATE_CONFIG, PostDebateConfig

    post_debate_config = getattr(arena, "post_debate_config", None)
    effective_config = (
        post_debate_config if post_debate_config is not None else DEFAULT_POST_DEBATE_CONFIG
    )

    # Bridge AutoExecutionConfig → PostDebateConfig: when enable_auto_execution
    # is set on the Arena, propagate it to the PostDebateConfig so that the
    # coordinator can actually execute plans and create PRs.
    if getattr(arena, "enable_auto_execution", False) and isinstance(
        effective_config, PostDebateConfig
    ):
        auto_mode = getattr(arena, "auto_approval_mode", "risk_based")
        getattr(arena, "auto_max_risk", "low")
        effective_config = PostDebateConfig(
            auto_explain=effective_config.auto_explain,
            auto_create_plan=True,
            auto_notify=effective_config.auto_notify,
            auto_execute_plan=True,
            auto_create_pr=True,
            pr_min_confidence=effective_config.pr_min_confidence,
            auto_build_integrity_package=True,
            auto_persist_receipt=effective_config.auto_persist_receipt,
            auto_gauntlet_validate=effective_config.auto_gauntlet_validate,
            gauntlet_min_confidence=effective_config.gauntlet_min_confidence,
            auto_queue_improvement=True,
            improvement_min_confidence=effective_config.improvement_min_confidence,
            plan_min_confidence=effective_config.plan_min_confidence,
            plan_approval_mode=auto_mode,
            auto_execution_bridge=effective_config.auto_execution_bridge,
            execution_bridge_min_confidence=effective_config.execution_bridge_min_confidence,
        )

    # Propagate prompt-level context-taint signals into debate metadata so
    # execution safety gates can treat untrusted context as tainted.
    if ctx.result:
        try:
            prompt_builder = getattr(arena, "prompt_builder", None)
            if prompt_builder is not None and hasattr(prompt_builder, "get_context_taint_report"):
                report = prompt_builder.get_context_taint_report()
                if isinstance(report, dict) and report.get("context_taint_detected"):
                    if not isinstance(ctx.result.metadata, dict):
                        ctx.result.metadata = {}
                    ctx.result.metadata["context_taint_detected"] = True
                    ctx.result.metadata["context_taint_patterns"] = report.get(
                        "context_taint_patterns", []
                    )
                    ctx.result.metadata["context_taint_sources"] = report.get(
                        "context_taint_sources", []
                    )
        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.debug("Context taint metadata propagation skipped: %s", e)
    if not getattr(arena, "disable_post_debate_pipeline", False) and ctx.result:
        try:
            from aragora.debate.post_debate_coordinator import PostDebateCoordinator

            coordinator = PostDebateCoordinator(config=effective_config)
            task = getattr(ctx.env, "task", "") if ctx.env else ""
            confidence = getattr(ctx.result, "confidence", 0.0)
            post_result = coordinator.run(
                debate_id=state.debate_id,
                debate_result=ctx.result,
                agents=arena.agents,
                confidence=confidence,
                task=task,
            )
            if not post_result.success:
                logger.warning(
                    "post_debate_coordinator_errors debate_id=%s errors=%s",
                    state.debate_id,
                    post_result.errors,
                )
            else:
                logger.info(
                    "post_debate_coordinator_complete debate_id=%s",
                    state.debate_id,
                )
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.debug("Post-debate coordinator pipeline failed (non-critical): %s", e)

    # Attach active introspection summary to result
    introspection_tracker = getattr(arena, "active_introspection_tracker", None)
    if introspection_tracker is not None and ctx.result:
        try:
            all_summaries = introspection_tracker.get_all_summaries()
            if all_summaries:
                ctx.result.metadata["introspection"] = {
                    agent_name: summary.to_dict() for agent_name, summary in all_summaries.items()
                }
                logger.info(
                    "introspection_attached debate_id=%s agents=%s",
                    state.debate_id,
                    len(all_summaries),
                )
        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.debug("Introspection summary failed (non-critical): %s", e)

    # Attach live explainability snapshot to result
    live_stream = getattr(arena, "live_explainability_stream", None)
    if live_stream is not None and ctx.result:
        try:
            snapshot = live_stream.get_snapshot()
            if snapshot is not None:
                ctx.result.metadata["live_explainability"] = {
                    "factors": snapshot.top_factors,
                    "narrative": snapshot.narrative,
                    "leading_position": snapshot.leading_position,
                    "agent_agreement": snapshot.agent_agreement,
                    "evidence_quality": snapshot.evidence_quality,
                    "position_confidence": snapshot.position_confidence,
                    "round_num": snapshot.round_num,
                    "evidence_count": snapshot.evidence_count,
                    "vote_count": snapshot.vote_count,
                    "belief_shifts": snapshot.belief_shifts,
                }
                logger.info(
                    "live_explainability_attached debate_id=%s factors=%s",
                    state.debate_id,
                    len(snapshot.top_factors),
                )
        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.debug("Live explainability snapshot failed (non-critical): %s", e)

    # Collect extended thinking traces from Anthropic agents
    if ctx.result and arena.agents:
        thinking_traces: dict[str, str] = {}
        for agent in arena.agents:
            trace = getattr(agent, "_last_thinking_trace", None)
            if trace:
                thinking_traces[agent.name] = trace
        if thinking_traces:
            metadata = getattr(ctx.result, "metadata", None)
            if not isinstance(metadata, dict):
                try:
                    setattr(ctx.result, "metadata", {})
                except (AttributeError, TypeError):
                    metadata = None
                else:
                    metadata = getattr(ctx.result, "metadata", None)
            if isinstance(metadata, dict):
                metadata["thinking_traces"] = thinking_traces
                logger.info(
                    "thinking_traces_attached debate_id=%s agents=%s",
                    state.debate_id,
                    len(thinking_traces),
                )

    # Queue for Supabase background sync
    arena._queue_for_supabase_sync(ctx, ctx.result)


async def cleanup_debate_resources(
    arena: Arena,
    state: _DebateExecutionState,
) -> DebateResult:
    """Clean up debate resources and finalize result.

    Handles:
    - Checkpoint cleanup (on success)
    - Convergence cache cleanup
    - Agent channel teardown
    - Result finalization
    - Translation (if enabled)

    Returns:
        The finalized DebateResult
    """
    ctx = state.ctx

    async def _drain_background_task(task: Any, *, timeout_s: float = 0.75) -> None:
        """Await/cancel debate-scoped background tasks to avoid task leaks."""
        if task is None:
            return
        if task.done():
            if not task.cancelled():
                try:
                    task.exception()
                except (RuntimeError, TypeError):
                    pass
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, RuntimeError):
                pass
        except (RuntimeError, TypeError):
            pass

    # Drain debate-scoped background tasks. They are only useful while the debate
    # is active; after completion they should not outlive this coroutine.
    await _drain_background_task(
        getattr(ctx, "background_classification_task", None), timeout_s=0.75
    )
    await _drain_background_task(getattr(ctx, "background_research_task", None), timeout_s=0.75)
    await _drain_background_task(getattr(ctx, "background_evidence_task", None), timeout_s=0.75)
    for _attr in (
        "background_classification_task",
        "background_research_task",
        "background_evidence_task",
    ):
        if hasattr(ctx, _attr):
            setattr(ctx, _attr, None)

    # In pytest runs, ensure background KM ingest doesn't outlive the test event
    # loop and emit "Task was destroyed but it is pending!" warnings.
    km_task = getattr(ctx, "_km_ingest_task", None)
    if km_task is not None and os.environ.get("PYTEST_CURRENT_TEST"):
        await _drain_background_task(km_task, timeout_s=0.75)

    # Clean up checkpoints after successful completion
    if state.debate_status == "completed" and getattr(
        arena.protocol, "checkpoint_cleanup_on_success", True
    ):
        try:
            keep_count = getattr(arena.protocol, "checkpoint_keep_on_success", 0)
            deleted = await arena.cleanup_checkpoints(state.debate_id, keep_latest=keep_count)
            if deleted > 0:
                logger.debug("[checkpoint] Cleaned up %s checkpoints for completed debate", deleted)
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.debug("[checkpoint] Cleanup failed (non-critical): %s", e)

    # Clear per-debate cost tracker reference from AutonomicExecutor
    arena.autonomic.set_debate_cost_tracker(None, "")

    # Cleanup debate-scoped embedding cache to free memory
    arena._cleanup_convergence_cache()
    await arena._teardown_agent_channels()

    # Finalize the result
    result = ctx.finalize_result()

    # Translate conclusions if multi-language support is enabled
    if result and getattr(arena.protocol, "enable_translation", False):
        await arena._translate_conclusions(result)

    # Auto-execute decision plan if enabled
    if result and getattr(arena, "enable_auto_execution", False):
        result = await _auto_execute_plan(arena, result)

    # Route result to originating channel (Slack, Teams, webhook, etc.)
    # Opt-in via ArenaConfig.enable_result_routing or debate_origin metadata on the env.
    _result_routing_enabled = getattr(arena, "enable_result_routing", False)
    if not _result_routing_enabled:
        # Also check for debate_origin metadata on the environment (inline origin)
        _env_metadata = getattr(arena.env, "metadata", None) or {}
        _result_routing_enabled = bool(_env_metadata.get("debate_origin"))
    if result and _result_routing_enabled:
        try:
            from aragora.server.result_router import route_result

            # If the environment carries inline debate_origin metadata and no
            # origin was registered in the store yet, register it now so the
            # router can look it up by debate_id.
            _env_meta = getattr(arena.env, "metadata", None) or {}
            _origin_meta = _env_meta.get("debate_origin")
            if isinstance(_origin_meta, dict) and _origin_meta.get("platform"):
                try:
                    from aragora.server.debate_origin import register_debate_origin

                    register_debate_origin(
                        debate_id=state.debate_id,
                        platform=_origin_meta["platform"],
                        channel_id=_origin_meta.get("channel_id", ""),
                        user_id=_origin_meta.get("user_id", ""),
                        metadata=_origin_meta.get("metadata", {}),
                    )
                except (ImportError, OSError, RuntimeError, ValueError, TypeError) as reg_err:
                    logger.debug("[result_routing] Origin registration failed: %s", reg_err)

            if hasattr(result, "to_dict"):
                result_dict = result.to_dict()
            else:
                result_dict = {
                    "debate_id": state.debate_id,
                    "winner": getattr(result, "winner", None),
                    "consensus_reached": getattr(result, "consensus_reached", False),
                    "final_answer": getattr(result, "final_answer", ""),
                    "confidence": getattr(result, "confidence", 0.0),
                }
            success = await route_result(state.debate_id, result_dict)
            if success:
                logger.info("[result_routing] Routed debate %s result to origin", state.debate_id)
            else:
                logger.debug(
                    "[result_routing] No origin found or routing skipped for debate %s",
                    state.debate_id,
                )
        except (ImportError, RuntimeError, OSError, TypeError, ValueError) as e:
            logger.debug("[result_routing] Failed (non-critical): %s", e)

    # Data classification: tag result with sensitivity metadata (opt-in)
    if result and getattr(arena, "enable_data_classification", False):
        try:
            from aragora.compliance.data_classification import PolicyEnforcer

            _enforcer = PolicyEnforcer()
            result_dict = result.to_dict() if hasattr(result, "to_dict") else {"_raw": str(result)}
            classified = _enforcer.classify_debate_result(result_dict)
            result.metadata["_classification"] = classified.get("_classification", {})
            logger.debug("[data_classification] Tagged debate result with classification metadata")
        except (ImportError, RuntimeError, OSError, TypeError, ValueError, AttributeError) as e:
            logger.debug("[data_classification] Classification failed (non-critical): %s", e)

    return result


async def _auto_execute_plan(
    arena: Arena,
    result: DebateResult,
) -> DebateResult:
    """Generate and optionally execute a DecisionPlan from debate result.

    Creates a DecisionPlan via DecisionPlanFactory.from_debate_result(),
    stores plan metadata on the result, and executes the plan through
    PlanExecutor if no human approval is required.

    Args:
        arena: Arena instance with auto-execution config attributes.
        result: The finalized DebateResult from the debate.

    Returns:
        The DebateResult with plan metadata attached.
    """
    try:
        # Enforce execution safety gate before autonomous execution.
        from aragora.debate.execution_safety import (
            ExecutionSafetyPolicy,
            evaluate_auto_execution_safety,
        )
        from aragora.pipeline.decision_plan import DecisionPlanFactory
        from aragora.pipeline.decision_plan.core import ApprovalMode
        from aragora.pipeline.executor import PlanExecutor
        from aragora.pipeline.risk_register import RiskLevel

        approval_mode_map = {
            "always": ApprovalMode.ALWAYS,
            "risk_based": ApprovalMode.RISK_BASED,
            "confidence_based": ApprovalMode.CONFIDENCE_BASED,
            "never": ApprovalMode.NEVER,
        }
        risk_level_map = {
            "low": RiskLevel.LOW,
            "medium": RiskLevel.MEDIUM,
            "high": RiskLevel.HIGH,
            "critical": RiskLevel.CRITICAL,
        }

        approval_mode_str = getattr(arena, "auto_approval_mode", "risk_based")
        max_risk_str = getattr(arena, "auto_max_risk", "low")
        execution_mode: str = getattr(arena, "auto_execution_mode", "workflow")
        post_cfg = getattr(arena, "post_debate_config", None)

        gate_policy = ExecutionSafetyPolicy(
            require_verified_signed_receipt=getattr(
                post_cfg,
                "execution_gate_require_verified_signed_receipt",
                True,
            ),
            require_receipt_signer_allowlist=getattr(
                post_cfg,
                "execution_gate_enforce_receipt_signer_allowlist",
                False,
            ),
            allowed_receipt_signer_keys=getattr(
                post_cfg,
                "execution_gate_allowed_receipt_signer_keys",
                (),
            ),
            require_signed_receipt_timestamp=getattr(
                post_cfg,
                "execution_gate_require_signed_receipt_timestamp",
                True,
            ),
            receipt_max_age_seconds=getattr(
                post_cfg,
                "execution_gate_receipt_max_age_seconds",
                86400,
            ),
            receipt_max_future_skew_seconds=getattr(
                post_cfg,
                "execution_gate_receipt_max_future_skew_seconds",
                120,
            ),
            min_provider_diversity=getattr(post_cfg, "execution_gate_min_provider_diversity", 2),
            min_model_family_diversity=getattr(
                post_cfg, "execution_gate_min_model_family_diversity", 2
            ),
            block_on_context_taint=getattr(post_cfg, "execution_gate_block_on_context_taint", True),
            block_on_high_severity_dissent=getattr(
                post_cfg, "execution_gate_block_on_high_severity_dissent", True
            ),
            high_severity_dissent_threshold=getattr(
                post_cfg, "execution_gate_high_severity_dissent_threshold", 0.7
            ),
        )
        gate_decision = evaluate_auto_execution_safety(
            result,
            agents=getattr(arena, "agents", None),
            policy=gate_policy,
        )

        if not isinstance(result.metadata, dict):
            result.metadata = {}
        gate_dict = gate_decision.to_dict()
        result.metadata["execution_gate"] = gate_dict
        if gate_decision.signed_receipt is not None:
            result.metadata["signed_consensus_receipt"] = gate_decision.signed_receipt

        try:
            from aragora.server.metrics import track_execution_gate_decision

            track_execution_gate_decision(
                gate_dict,
                path="arena_auto_execute",
                domain=str(getattr(result, "domain", "general") or "general"),
            )
        except ImportError:
            logger.debug("Execution gate metrics unavailable")
        except (ValueError, TypeError, AttributeError, RuntimeError):
            logger.debug("Execution gate metrics emission failed", exc_info=True)

        if not gate_decision.allow_auto_execution:
            result.metadata["auto_execution_blocked"] = "execution_gate"
            logger.warning(
                "auto_execution_blocked debate_id=%s reasons=%s",
                result.debate_id,
                gate_decision.reason_codes,
            )
            return result

        plan = DecisionPlanFactory.from_debate_result(
            result,
            approval_mode=approval_mode_map.get(approval_mode_str, ApprovalMode.RISK_BASED),
            max_auto_risk=risk_level_map.get(max_risk_str, RiskLevel.LOW),
        )

        # Store plan reference on result metadata
        if not isinstance(result.metadata, dict):
            result.metadata = {}
        result.metadata["decision_plan_id"] = plan.id
        result.metadata["decision_plan_status"] = (
            plan.status.value if hasattr(plan.status, "value") else str(plan.status)
        )

        # Execute if auto-approved or no approval needed
        if not plan.requires_human_approval:
            executor = PlanExecutor(execution_mode=execution_mode)  # type: ignore[arg-type]
            outcome = await executor.execute(plan)
            result.metadata["plan_outcome"] = {
                "success": outcome.success,
                "tasks_completed": outcome.tasks_completed,
                "tasks_total": outcome.tasks_total,
            }

        logger.info(
            "auto_execution plan_id=%s status=%s debate_id=%s",
            plan.id,
            plan.status,
            result.debate_id,
        )

    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError, OSError) as e:
        logger.warning("auto_execution_failed error=%s: %s", type(e).__name__, e)
        if not isinstance(result.metadata, dict):
            result.metadata = {}
        result.metadata["auto_execution_error"] = type(e).__name__

    return result
