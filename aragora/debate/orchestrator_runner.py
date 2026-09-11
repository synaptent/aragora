"""Debate execution runner extracted from Arena.

Contains _DebateExecutionState and the _run_inner helper methods that
coordinate debate initialization, infrastructure setup, phase execution,
metrics recording, completion handling, and resource cleanup.
"""

from __future__ import annotations

import asyncio
import copy
import os
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from aragora.core import DebateResult
from aragora.core_types import (
    DebateStatus,
    DebateStatusSource,
    legacy_debate_status,
    normalize_debate_status,
)
from aragora.debate.complexity_governor import (
    classify_task_complexity,
    get_complexity_governor,
)
from aragora.debate.context import DebateContext
from aragora.logging_config import LogContext, get_logger as get_structured_logger
from aragora.observability.tracing import add_span_attributes
from aragora.pipeline.execution_mode import ExecutionMode as SafetyMode
from aragora.observability.metrics.debate_slo import (
    record_debate_completion_slo,
    update_debate_success_rate,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

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
    debate_status: str = DebateStatus.PENDING.value
    debate_start_time: float = 0.0


def _apply_result_debate_state(
    result: DebateResult | None,
    *,
    debate_status: DebateStatus | str,
    legacy_status: str | None = None,
    source: DebateStatusSource = DebateStatusSource.LIVE,
) -> None:
    """Synchronize canonical and legacy debate state fields on the result."""
    if result is None:
        return

    canonical = normalize_debate_status(debate_status)
    result.debate_status = canonical.value
    result.debate_status_source = source.value
    result.status = legacy_status or legacy_debate_status(
        canonical,
        consensus_reached=bool(getattr(result, "consensus_reached", False)),
    )


_NON_BLOCKING_KM_INIT_ERRORS = (
    asyncio.TimeoutError,
    TimeoutError,
    ConnectionError,
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
    ImportError,
)
# Culture hint enrichment is a best-effort boundary around KM/storage/client
# adapters that may raise provider-specific ordinary exceptions. This alias
# deliberately excludes BaseException subclasses such as cancellation.
_CULTURE_HINT_FAILURE = Exception

# Bound on awaiting the fire-and-forget KM culture-profile retrieval task
# (scheduled by the culture_to_debate reaction during _init_km_context) before
# falling back to whatever get_culture_hints already has. Keeps a slow KM
# backend from stalling debate start while still closing the race where the
# read otherwise always ran before the retrieval task got a turn.
_CULTURE_HINTS_WAIT_TIMEOUT_S = 2.0


def _read_arena_attr(arena: Arena, name: str, default: Any = None) -> Any:
    """Prefer explicitly assigned arena attributes over MagicMock fallbacks."""
    arena_dict = getattr(arena, "__dict__", None)
    if isinstance(arena_dict, dict) and name in arena_dict:
        return arena_dict[name]
    return getattr(arena, name, default)


def _build_km_metadata_template(arena: Arena) -> dict[str, Any]:
    """Construct truthful KM metadata defaults for the default debate route."""
    template = _read_arena_attr(arena, "_km_metadata_template", None)
    if isinstance(template, dict):
        return copy.deepcopy(template)

    knowledge_mound_present = _read_arena_attr(arena, "knowledge_mound", None) is not None
    retrieval_enabled = bool(_read_arena_attr(arena, "enable_knowledge_retrieval", True))
    writeback_enabled = bool(_read_arena_attr(arena, "enable_knowledge_ingestion", True))
    supermemory_enabled = bool(_read_arena_attr(arena, "enable_supermemory", False))

    return {
        "knowledge_mound_present": knowledge_mound_present,
        "supermemory_enabled": supermemory_enabled,
        "context_handoff": {
            "status": "pending" if knowledge_mound_present else "not_configured",
            "non_blocking": True,
        },
        "retrieval": {
            "enabled": retrieval_enabled,
            "status": (
                "pending"
                if retrieval_enabled and knowledge_mound_present
                else "disabled"
                if not retrieval_enabled
                else "not_configured"
            ),
            "observed_context_chars": 0,
            "observed_item_count": 0,
        },
        "writeback": {
            "enabled": writeback_enabled,
            "status": "pending" if writeback_enabled else "disabled",
            "attempts": 0,
        },
    }


def _get_km_metadata(ctx: DebateContext, arena: Arena) -> dict[str, Any]:
    """Get or initialize debate-scoped KM metadata."""
    metadata = getattr(ctx, "_knowledge_management_metadata", None)
    if isinstance(metadata, dict):
        return metadata
    metadata = _build_km_metadata_template(arena)
    setattr(ctx, "_knowledge_management_metadata", metadata)
    return metadata


def _clear_stale_km_prompt_state(arena: Arena) -> None:
    """Reset shared prompt-builder KM state before a new debate starts."""
    prompt_builder = _read_arena_attr(arena, "prompt_builder", None)
    if prompt_builder and hasattr(prompt_builder, "set_knowledge_context"):
        try:
            prompt_builder.set_knowledge_context("", [])
        except (RuntimeError, TypeError, AttributeError):
            pass


def _update_observed_km_retrieval(
    arena: Arena,
    ctx: DebateContext,
    km_metadata: dict[str, Any],
) -> None:
    """Record whether the finalized debate actually carried KM context."""
    retrieval = km_metadata.setdefault("retrieval", {})
    if not retrieval.get("enabled", False):
        retrieval["status"] = "disabled"
        retrieval["observed_context_chars"] = 0
        retrieval["observed_item_count"] = 0
        return

    context_handoff = km_metadata.get("context_handoff", {})
    handoff_status = context_handoff.get("status")

    prompt_builder = _read_arena_attr(arena, "prompt_builder", None) or getattr(
        ctx, "_prompt_builder", None
    )
    knowledge_context = ""
    if prompt_builder and hasattr(prompt_builder, "get_knowledge_mound_context"):
        try:
            raw_context = prompt_builder.get_knowledge_mound_context()
            if isinstance(raw_context, str):
                knowledge_context = raw_context
        except (RuntimeError, TypeError, AttributeError):
            knowledge_context = ""

    raw_item_ids = getattr(ctx, "_km_item_ids_used", None) or []
    item_ids = list(raw_item_ids) if isinstance(raw_item_ids, (list, tuple, set)) else []

    retrieval["observed_context_chars"] = len(knowledge_context)
    retrieval["observed_item_count"] = len(item_ids)

    if knowledge_context or item_ids:
        retrieval["status"] = "succeeded"
        retrieval.pop("error_type", None)
        retrieval.pop("error", None)
    elif handoff_status == "failed":
        retrieval["status"] = "failed"
        retrieval["error_type"] = context_handoff.get("error_type")
        retrieval["error"] = context_handoff.get("error")
    elif not km_metadata.get("knowledge_mound_present", False):
        retrieval["status"] = "not_configured"
    else:
        retrieval["status"] = "not_observed"


def _attach_truthful_km_metadata(
    arena: Arena,
    ctx: DebateContext,
    result: DebateResult,
) -> None:
    """Attach truthful KM state to the finalized debate result metadata."""
    km_metadata = _get_km_metadata(ctx, arena)
    _update_observed_km_retrieval(arena, ctx, km_metadata)

    writeback = km_metadata.setdefault("writeback", {})
    if not writeback.get("enabled", False):
        writeback["status"] = "disabled"
    elif (
        writeback.get("status") in {"pending", "pending_background"}
        and not km_metadata.get("knowledge_mound_present", False)
        and not km_metadata.get("supermemory_enabled", False)
    ):
        writeback["status"] = "not_configured"

    metadata = getattr(result, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["knowledge_management"] = km_metadata
    result.metadata = metadata


def _extract_agent_token_usage(agent: Any) -> tuple[int, int]:
    """Best-effort token extraction across agent implementations."""

    def _coerce_non_negative_int(value: Any) -> int:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, float):
            return max(int(value), 0)
        if isinstance(value, Decimal):
            return max(int(value), 0)
        if isinstance(value, str):
            try:
                return max(int(value), 0)
            except ValueError:
                return 0
        return 0

    metrics = getattr(agent, "metrics", None)
    agent_tokens_in = _coerce_non_negative_int(getattr(agent, "total_tokens_in", 0))
    agent_tokens_out = _coerce_non_negative_int(getattr(agent, "total_tokens_out", 0))
    if metrics is not None:
        tokens_in = _coerce_non_negative_int(getattr(metrics, "total_input_tokens", 0))
        tokens_out = _coerce_non_negative_int(getattr(metrics, "total_output_tokens", 0))
        if tokens_in == 0 and tokens_out == 0 and (agent_tokens_in > 0 or agent_tokens_out > 0):
            return agent_tokens_in, agent_tokens_out
    else:
        tokens_in = agent_tokens_in
        tokens_out = agent_tokens_out

    return tokens_in, tokens_out


async def _record_debate_telemetry(
    arena: Arena,
    state: _DebateExecutionState,
) -> None:
    """Persist debate completion into the billing and analytics stores."""

    def _coerce_optional_str(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        if isinstance(value, int | float):
            return str(value)
        return None

    def _coerce_non_negative_float(value: Any) -> float:
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, int | float):
            return max(float(value), 0.0)
        if isinstance(value, Decimal):
            return max(float(value), 0.0)
        if isinstance(value, str):
            try:
                return max(float(value), 0.0)
            except ValueError:
                return 0.0
        return 0.0

    ctx = state.ctx
    result = ctx.result
    if result is None:
        return

    duration_seconds = _coerce_non_negative_float(getattr(result, "duration_seconds", 0.0))
    debate_start_time = _coerce_non_negative_float(getattr(state, "debate_start_time", 0.0))
    if duration_seconds <= 0 and debate_start_time > 0:
        duration_seconds = max(time.perf_counter() - debate_start_time, 0.0)

    rounds_used = max(int(getattr(result, "rounds_used", 0) or 0), 0)
    total_messages = len(getattr(result, "messages", []) or [])
    total_votes = len(getattr(result, "votes", []) or [])
    org_id = _coerce_optional_str(getattr(arena, "org_id", "") or getattr(ctx, "org_id", "")) or ""
    user_id = _coerce_optional_str(getattr(arena, "user_id", ""))
    provider_routing = None
    if isinstance(getattr(result, "metadata", None), dict):
        provider_routing = result.metadata.get("provider_routing")

    telemetry_metadata = {
        "status": state.debate_status,
        "confidence": _coerce_non_negative_float(getattr(result, "confidence", 0.0)),
        "consensus_reached": bool(getattr(result, "consensus_reached", False)),
        "message_count": total_messages,
        "vote_count": total_votes,
    }
    if provider_routing:
        telemetry_metadata["provider_routing"] = provider_routing

    if org_id:
        try:
            from aragora.billing.usage_metering_integration import record_debate_tokens
            from aragora.services.usage_metering import get_usage_meter

            usage_summary = await record_debate_tokens(
                org_id=org_id,
                debate_id=state.debate_id,
                agents=arena.agents,
                user_id=user_id,
                rounds=rounds_used,
                duration_seconds=max(int(round(duration_seconds)), 0),
                metadata=telemetry_metadata,
            )
            await get_usage_meter().flush_all()
            if not isinstance(result.metadata, dict):
                result.metadata = {}
            result.metadata["usage_metering"] = usage_summary
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.debug("usage_metering_record_failed (non-critical): %s", e)

    try:
        from aragora.analytics.debate_analytics import get_debate_analytics
        from aragora.billing.usage import calculate_token_cost

        analytics = get_debate_analytics()
        total_cost = Decimal(
            str(_coerce_non_negative_float(getattr(result, "total_cost_usd", 0.0)))
        )
        await analytics.record_debate(
            debate_id=state.debate_id,
            rounds=rounds_used,
            consensus_reached=bool(getattr(result, "consensus_reached", False)),
            duration_seconds=duration_seconds,
            agents=[getattr(agent, "name", str(agent)) for agent in arena.agents],
            status=state.debate_status,
            org_id=org_id or None,
            user_id=user_id,
            protocol=_coerce_optional_str(
                getattr(getattr(arena, "protocol", None), "consensus", None)
            ),
            total_messages=total_messages,
            total_votes=total_votes,
            total_cost=total_cost,
        )

        governor = get_complexity_governor()
        per_agent_cost = (
            getattr(result, "per_agent_cost", {}) if isinstance(result.per_agent_cost, dict) else {}
        )
        for agent in arena.agents:
            agent_name = getattr(agent, "name", str(agent))
            tokens_in, tokens_out = _extract_agent_token_usage(agent)
            governor_metrics = getattr(governor, "agent_metrics", {}).get(agent_name)
            response_time_ms = (
                _coerce_non_negative_float(getattr(governor_metrics, "avg_latency_ms", 0.0))
                if governor_metrics is not None
                else 0.0
            )
            provider = (
                _coerce_optional_str(
                    getattr(agent, "provider", None) or getattr(agent, "agent_type", "unknown")
                )
                or "unknown"
            )
            model = _coerce_optional_str(getattr(agent, "model", "unknown")) or "unknown"

            if agent_name in per_agent_cost:
                cost = Decimal(str(_coerce_non_negative_float(per_agent_cost[agent_name])))
            else:
                cost = calculate_token_cost(provider, model, tokens_in, tokens_out)

            if tokens_in <= 0 and tokens_out <= 0 and response_time_ms <= 0 and cost <= 0:
                continue

            await analytics.record_agent_activity(
                agent_id=agent_name,
                debate_id=state.debate_id,
                response_time_ms=response_time_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=cost,
                error=False,
                agent_name=agent_name,
                provider=str(provider),
                model=str(model),
            )
    except (ImportError, RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
        logger.debug("debate_analytics_record_failed (non-critical): %s", e)


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


async def _run_cross_verification(
    result: DebateResult,
    agents: list[Any],
) -> None:
    """Run cross-verification on the final answer to detect hallucinations."""
    try:
        from aragora.debate.cross_verification import CrossVerificationEngine

        if not agents:
            return
        engine = CrossVerificationEngine(verifier=agents[0])
        task = getattr(result, "task", "") or ""
        context = task
        cv_result = await engine.verify(result.final_answer or "", context=context)

        if result.metadata is None or not isinstance(result.metadata, dict):
            result.metadata = {}
        result.metadata["cross_verification"] = {
            "grounding_delta": cv_result.grounding_delta,
            "hallucination_risk": cv_result.hallucination_risk,
            "adversarial_resistance": cv_result.adversarial_resistance,
            "is_grounded": cv_result.is_grounded,
        }
        logger.info(
            "cross_verification_complete grounding_delta=%.3f hallucination_risk=%.3f grounded=%s",
            cv_result.grounding_delta,
            cv_result.hallucination_risk,
            cv_result.is_grounded,
        )
    except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as e:
        logger.debug("cross_verification_skipped: %s", e)


async def _populate_result_tokens_from_agents(
    result: DebateResult,
    agents: list[Any],
) -> None:
    """Fallback: sum per-agent token counters when cost tracker has no data."""
    if getattr(result, "total_tokens", 0):
        return
    total = 0
    for agent in agents:
        total += getattr(agent, "total_tokens_in", 0) + getattr(agent, "total_tokens_out", 0)
    if total > 0:
        result.total_tokens = total


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
    _clear_stale_km_prompt_state(arena)

    # Start this debate's served-model record empty. Agents are reusable
    # across debates, so a fallback observed in an earlier debate must not
    # be reported in this one's receipt (see reset_served_model_logs).
    reset_served_model_logs(arena.agents)

    # Extract domain early for metrics
    domain = arena._extract_debate_domain()
    km_metadata = _build_km_metadata_template(arena)

    # Initialize Knowledge Mound context. Latency optimization (issue #268):
    # this used to run strictly before culture-hint retrieval; _init_km_context
    # now returns the culture_to_debate reaction's in-flight retrieval task (if
    # any) instead of leaving it fire-and-forget, so hint retrieval below can
    # wait on that specific task (bounded) rather than racing it blind.
    async def _init_km() -> "asyncio.Task[Any] | None":
        return await arena._init_km_context(debate_id, domain)

    _gather_results = await asyncio.gather(_init_km(), return_exceptions=True)
    # KM init failures should not block the default debate route; report them
    # truthfully in result metadata instead of inventing successful enrichment.
    km_init_result = _gather_results[0]
    pending_culture_task: asyncio.Task[Any] | None = None
    if isinstance(km_init_result, BaseException):
        if isinstance(km_init_result, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise km_init_result
        if isinstance(km_init_result, _NON_BLOCKING_KM_INIT_ERRORS):
            km_metadata["context_handoff"] = {
                "status": "failed",
                "non_blocking": True,
                "error_type": type(km_init_result).__name__,
                "error": str(km_init_result),
            }
            logger.warning(
                "Knowledge Mound context initialization failed (non-blocking) for debate %s: %s",
                debate_id,
                km_init_result,
            )
        else:
            raise km_init_result
    else:
        pending_culture_task = km_init_result
        if km_metadata["context_handoff"].get("status") == "pending":
            km_metadata["context_handoff"]["status"] = "succeeded"

    # Give any in-flight culture-profile retrieval a bounded chance to land
    # before reading hints back, then apply whatever is available. Both steps
    # are best-effort: culture hints must never block or fail debate start.
    if pending_culture_task is not None:
        try:
            await asyncio.wait_for(
                asyncio.shield(pending_culture_task), timeout=_CULTURE_HINTS_WAIT_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            logger.debug(
                "Culture profile retrieval still pending after %.1fs for debate %s; "
                "proceeding without it",
                _CULTURE_HINTS_WAIT_TIMEOUT_S,
                debate_id,
            )
        except Exception as e:  # noqa: BLE001 - culture hints are best-effort and must never fail
            # debate start regardless of which exception type a KM/storage backend raises.
            logger.debug("Culture profile retrieval task failed while awaited: %s", e)

    try:
        culture_hints = arena._get_culture_hints(debate_id)
        if culture_hints:
            arena._apply_culture_hints(culture_hints)
    except _CULTURE_HINT_FAILURE as e:
        logger.debug(
            "Culture hint retrieval/application failed (non-critical) for debate %s: %s",
            debate_id,
            e,
        )

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
    ctx._knowledge_management_metadata = km_metadata  # type: ignore[attr-defined]

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

    # Apply ProviderRouter hints to agent ranking via TeamSelector
    provider_hints = getattr(arena, "_provider_hints", None)
    if provider_hints:
        selector = getattr(arena, "agent_selector", None)
        if selector is not None and hasattr(selector, "select"):
            try:
                ranked = selector.select(
                    arena.agents,
                    domain=domain,
                    task=arena.env.task,
                    provider_hints=provider_hints,
                )
                if ranked:
                    arena.agents = ranked
                    ctx.agents = ranked
                    logger.debug(
                        "ProviderRouter hints applied: ranked %d agents",
                        len(ranked),
                    )
            except (ValueError, TypeError, AttributeError, RuntimeError) as e:
                logger.warning("Provider hint ranking failed, using original order: %s", e)

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
    state.debate_status = DebateStatus.RUNNING.value
    ctx.result = DebateResult(
        task=arena.env.task,
        consensus_reached=False,
        confidence=0.0,
        messages=[],
        critiques=[],
        votes=[],
        rounds_used=0,
        final_answer="",
        status=DebateStatus.RUNNING.value,
        debate_status=DebateStatus.RUNNING.value,
        debate_status_source=DebateStatusSource.LIVE.value,
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
        state.debate_status = DebateStatus.COMPLETED.value
        _apply_result_debate_state(
            ctx.result,
            debate_status=DebateStatus.COMPLETED,
        )

        # Emit latency profile after successful execution
        if latency_profiler and latency_profiler.records:
            profile_summary = latency_profiler.report()
            if hasattr(ctx, "result") and ctx.result and isinstance(ctx.result.metadata, dict):
                ctx.result.metadata["latency_profile"] = profile_summary

    except asyncio.TimeoutError:
        # Timeout recovery - use partial results from context
        if ctx.result is not None:
            ctx.result.messages = ctx.partial_messages
            ctx.result.critiques = ctx.partial_critiques
            ctx.result.rounds_used = ctx.partial_rounds
        state.debate_status = DebateStatus.BLOCKED.value
        _apply_result_debate_state(
            ctx.result,
            debate_status=DebateStatus.BLOCKED,
            legacy_status="timeout",
        )
        span.set_attribute("debate.status", "timeout")
        logger.warning("Debate timed out, returning partial results")

    except EarlyStopError:
        state.debate_status = DebateStatus.BLOCKED.value
        _apply_result_debate_state(
            ctx.result,
            debate_status=DebateStatus.BLOCKED,
            legacy_status="aborted",
        )
        span.set_attribute("debate.status", "aborted")
        raise

    except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as e:
        state.debate_status = DebateStatus.FAILED.value
        _apply_result_debate_state(
            ctx.result,
            debate_status=DebateStatus.FAILED,
            legacy_status="error",
        )
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
    from aragora.server.metrics import ACTIVE_DEBATES, track_debate_outcome

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
    if state.debate_status == DebateStatus.COMPLETED.value:
        outcome = "consensus" if consensus_reached else "no_consensus"
    elif state.debate_status == DebateStatus.BLOCKED.value:
        outcome = "blocked"
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


#: What ``collect_served_models`` records for an agent whose requested model
#: was never put on the wire: the CLI answered from its own default and
#: nothing in this process can name it. Deliberately not a model id -- a
#: receipt must be able to say "unknown", not guess (wave-6 ruling, agents,
#: on #9989).
UNKNOWN_CLI_DEFAULT_MODEL = "unknown (CLI default)"


def reset_served_model_logs(agents: "Sequence[Any]") -> None:
    """Clear every agent's debate-scoped served-model log at debate start.

    Agents are supplied by the caller, and the Arena keeps whatever list it
    was constructed with: the same agent object can serve several debates in
    one process (``arena.run()`` is callable more than once, and long-lived
    servers reuse a roster). A fresh agent per debate is therefore NOT
    guaranteed, so without this reset one debate's server-side fallback would
    be reported in the next debate's receipt.

    Duck-typed and best-effort: an agent that keeps no log is skipped.
    """
    for agent in agents:
        reset = getattr(agent, "reset_served_model_log", None)
        if not callable(reset):
            continue
        try:
            reset()
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.debug(
                "reset_served_model_log failed for agent %s: %s",
                getattr(agent, "name", "?"),
                e,
            )


def _served_models_from_log(log: Any, requested: str) -> dict[str, Any] | None:
    """Summarize an agent's per-call served-model log for the receipt.

    Returns ``{"requested": id, "served": [distinct served ids], "calls": n,
    "fallback_calls": m}``, or ``None`` when the agent answered as asked on
    every call (``m == 0``) -- an agent that never swapped model earns no
    receipt entry, which keeps flag-off receipts byte-identical.

    ``served`` lists every DISTINCT id the server echoed across the debate in
    first-seen order, including the requested model's own echo on the calls
    that were answered as asked: a debate where round 1 fell back and round 2
    did not is two models' work, and the receipt has to name both. A call the
    server answered without echoing any id contributes nothing to the list
    but is still counted in ``calls``.
    """
    if not isinstance(log, list) or not log:
        return None
    calls = 0
    fallback_calls = 0
    served: list[str] = []
    for observation in log:
        if not isinstance(observation, dict):
            continue
        calls += 1
        if observation.get("fallback"):
            fallback_calls += 1
        served_id = observation.get("served")
        if isinstance(served_id, str) and served_id and served_id not in served:
            served.append(served_id)
    if fallback_calls == 0:
        return None
    return {
        "requested": requested,
        "served": served,
        "calls": calls,
        "fallback_calls": fallback_calls,
    }


def collect_served_models(agents: "Sequence[Any]") -> dict[str, dict[str, Any]]:
    """``{agent name: {"requested": id, "served": [ids], ...}}`` for every
    agent whose answer did not come from the requested model.

    Three ways that happens:

    * the provider answered with a DIFFERENT model on at least one call. The
      agent keeps an ordered per-call ``served_model_log`` for the current
      debate (reset by :func:`reset_served_model_logs`), and the entry
      carries ``calls`` and ``fallback_calls`` alongside the distinct served
      ids -- a debate-wide claim needs debate-wide evidence. Reading the
      agent's last call instead reported "no fallback" for a debate whose
      round-1 proposal came from a different model, because a later matching
      call cleared the single last-call value (finding C-P2 on #9989).
    * the provider answered with a different model but the agent keeps no
      log (a third-party agent implementing only ``last_served_model``). Its
      entry names that one served id; ``calls``/``fallback_calls`` are
      omitted rather than guessed, because nothing here can know them.
    * the requested model never reached the provider in the first place. A
      CLI agent whose command builder does not put ``self.model`` on the
      command line answers from the CLI's own default, so the served model
      is ``UNKNOWN_CLI_DEFAULT_MODEL``; the agent flags that as
      ``metadata["model_pinned_on_wire"] = False`` (see
      ``aragora.agents.cli_agents.CLIAgent.SENDS_MODEL_ON_WIRE``). Without
      this branch a receipt attributed the output to a model code the CLI
      never received. Counts are omitted here too: the CLI agent counts no
      calls.

    Agents that implement none of the three -- every other agent today --
    are skipped, not guessed at.
    """
    served_models: dict[str, dict[str, Any]] = {}
    for agent in agents:
        requested = getattr(agent, "model", None)
        if not isinstance(requested, str) or not requested:
            continue
        metadata = getattr(agent, "metadata", None)
        if isinstance(metadata, dict) and metadata.get("model_pinned_on_wire") is False:
            served_models[agent.name] = {
                "requested": requested,
                "served": [UNKNOWN_CLI_DEFAULT_MODEL],
            }
            continue
        from_log = _served_models_from_log(getattr(agent, "served_model_log", None), requested)
        if from_log is not None:
            served_models[agent.name] = from_log
            continue
        served = getattr(agent, "last_served_model", None)
        if isinstance(served, str) and served:
            served_models[agent.name] = {"requested": requested, "served": [served]}
    return served_models


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
    km_metadata = _get_km_metadata(ctx, arena)

    # Notify subsystem coordinator of debate completion
    if ctx.result:
        arena._trackers.on_debate_complete(ctx, ctx.result)

    # Trigger extensions (billing, training export)
    arena.extensions.on_debate_complete(ctx, ctx.result, arena.agents)

    # Populate DebateResult cost fields from cost tracker
    if ctx.result:
        await _populate_result_cost(ctx.result, state.debate_id, arena.extensions)
        await _populate_result_tokens_from_agents(ctx.result, arena.agents)
        await _record_debate_telemetry(arena, state)

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
        result = ctx.result
        writeback = km_metadata.setdefault("writeback", {})
        writeback_enabled = bool(writeback.get("enabled", False))
        km_writeback_available = bool(km_metadata.get("knowledge_mound_present", False)) or bool(
            km_metadata.get("supermemory_enabled", False)
        )

        if not writeback_enabled:
            writeback["status"] = "disabled"
        elif not km_writeback_available:
            writeback["status"] = "not_configured"
        else:
            writeback["status"] = "pending_background"

            async def _km_ingest_background() -> None:
                _ingestion_succeeded = False
                _last_error: Exception | None = None
                for _attempt in range(3):
                    writeback["attempts"] = _attempt + 1
                    try:
                        await arena._ingest_debate_outcome(result)
                        writeback["status"] = "succeeded"
                        writeback.pop("error", None)
                        writeback.pop("error_type", None)
                        _ingestion_succeeded = True
                        break
                    except (ConnectionError, OSError, ValueError, TypeError, AttributeError) as e:
                        _last_error = e
                        if _attempt < 2:
                            await asyncio.sleep(2**_attempt)  # 1s, 2s backoff
                if not _ingestion_succeeded and _last_error is not None:
                    writeback["status"] = "failed"
                    writeback["error_type"] = type(_last_error).__name__
                    writeback["error"] = str(_last_error)
                    logger.warning(
                        "Knowledge Mound ingestion failed after 3 attempts for debate %s: %s",
                        state.debate_id,
                        _last_error,
                    )
                    try:
                        from aragora.knowledge.mound.ingestion_queue import IngestionDeadLetterQueue

                        dlq = IngestionDeadLetterQueue()
                        result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
                        dlq.enqueue(state.debate_id, result_dict, str(_last_error))
                    except (ImportError, OSError, ValueError, TypeError, RuntimeError) as dlq_err:
                        logger.debug("DLQ enqueue failed: %s", dlq_err)

            if os.environ.get("PYTEST_CURRENT_TEST"):
                await _km_ingest_background()
                setattr(ctx, "_km_ingest_task", None)
            else:
                _km_task = asyncio.create_task(_km_ingest_background())
                setattr(ctx, "_km_ingest_task", _km_task)
                _km_task.add_done_callback(
                    lambda t: logger.warning(
                        "[km-ingest] Background ingestion error: %s", t.exception()
                    )
                    if not t.cancelled() and t.exception()
                    else None
                )
    else:
        writeback = km_metadata.setdefault("writeback", {})
        if writeback.get("enabled", False):
            writeback["status"] = "skipped_no_result"

    # Capture epistemic settlement metadata for future review
    if ctx.result:
        result = ctx.result
        try:
            from aragora.debate.settlement import EpistemicSettlementTracker

            tracker = EpistemicSettlementTracker()
            settlement = tracker.capture_settlement(result)
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
                confidence = getattr(result, "confidence", 0.0)
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
        result = ctx.result

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
                    receipt_dict = result.to_dict() if hasattr(result, "to_dict") else {}
                    bundle = generator.generate(receipt_dict)
                    if hasattr(result, "metadata") and isinstance(result.metadata, dict):
                        result.metadata["compliance_artifacts"] = bundle.to_dict()
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
            success = state.debate_status == DebateStatus.COMPLETED.value
            if ctx.result is not None:
                await arena._update_debate_bead(state.gupp_bead_id, ctx.result, success)
            await arena._complete_hook_tracking(
                state.gupp_bead_id,
                state.gupp_hook_entries,
                success,
                error_msg="" if success else f"Debate {state.debate_status}",
            )
            if success and ctx.result is not None:
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
            execution_mode=effective_config.execution_mode,
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
        # Perf optimization: run the post-debate coordinator pipeline as a
        # fire-and-forget background task.  The pipeline performs non-critical
        # enrichment (explanation, canvas, LLM-as-Judge, improvement queueing)
        # that should not block the debate response.  Receipt persistence is
        # already handled above via _km_ingest_background and the KM ingestion
        # task.  Only when `ARAGORA_SYNC_POST_DEBATE=1` is set (e.g. for tests
        # or CI) do we run it synchronously on the critical path.
        _sync_post_debate = os.environ.get("ARAGORA_SYNC_POST_DEBATE", "0") == "1"

        def _run_post_debate_pipeline() -> None:
            try:
                from aragora.debate.post_debate_coordinator import PostDebateCoordinator

                settlement_tracker = None
                if getattr(effective_config, "auto_settlement_tracking", False):
                    try:
                        settlement_tracker = getattr(arena, "settlement_tracker", None)
                        if settlement_tracker is None:
                            from aragora.debate.settlement import SettlementTracker
                            from aragora.debate.settlement_hooks import (
                                EventBusSettlementHook,
                                LoggingSettlementHook,
                                SettlementHookRegistry,
                            )

                            hook_registry = SettlementHookRegistry()
                            hook_registry.register(LoggingSettlementHook())
                            event_bus = getattr(arena, "event_bus", None)
                            if event_bus is not None:
                                hook_registry.register(EventBusSettlementHook(event_bus))

                            settlement_tracker = SettlementTracker(
                                elo_system=getattr(arena, "elo_system", None),
                                calibration_tracker=getattr(arena, "calibration_tracker", None),
                                knowledge_mound=getattr(arena, "knowledge_mound", None),
                                hooks=hook_registry,
                            )
                            setattr(arena, "settlement_tracker", settlement_tracker)
                    except ImportError:
                        logger.debug("Settlement tracker wiring unavailable")
                    except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as st_err:
                        logger.debug("Settlement tracker wiring unavailable: %s", st_err)
                        settlement_tracker = None

                coordinator = PostDebateCoordinator(
                    config=effective_config,
                    settlement_tracker=settlement_tracker,
                    knowledge_mound=getattr(arena, "knowledge_mound", None),
                )
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

        if _sync_post_debate:
            _run_post_debate_pipeline()
        else:
            # Fire-and-forget: run in thread pool so it doesn't block the response
            loop = asyncio.get_running_loop()
            _post_debate_future = loop.run_in_executor(None, _run_post_debate_pipeline)
            _post_debate_future.add_done_callback(
                lambda f: logger.warning(
                    "[post-debate] Background pipeline error: %s", f.exception()
                )
                if not f.cancelled() and f.exception()
                else None
            )

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

    # Run cross-verification on final answer if explicitly enabled.
    cross_verification_enabled = getattr(arena, "enable_cross_verification", False)
    if not isinstance(cross_verification_enabled, bool):
        cross_verification_enabled = False
    if ctx.result and ctx.result.final_answer and cross_verification_enabled:
        await _run_cross_verification(ctx.result, arena.agents)

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

    # Collect the model each provider ACTUALLY answered with, whenever that
    # was not the id we asked for. Two ways it happens, and the block names
    # both: a provider answered with a DIFFERENT model (Anthropic's
    # server-side refusal fallback, on by default for Fable 5.1 / Opus 5), or
    # the requested id never reached the provider at all because the agent's
    # CLI takes no model flag -- recorded as UNKNOWN_CLI_DEFAULT_MODEL,
    # "unknown (CLI default)", because a receipt must be able to say
    # "unknown" rather than guess. Either way a receipt that attributes the
    # decision to the requested id is wrong about which model made it.
    #
    # The claim is debate-wide, so it comes from each agent's debate-scoped
    # per-call log (cleared at debate start) rather than from its last call:
    # an agent whose round-1 proposal fell back and whose round-2 critique
    # did not is two models' work, and reading the last call reported "no
    # fallback" (finding C-P2). An empty dict here therefore means BOTH
    # things: every agent's model reached its provider, and every provider
    # answered as asked, on every call of this debate. Non-empty entries
    # carry "calls"/"fallback_calls" when the source can count them --
    # see collect_served_models and _served_models_from_log.
    if ctx.result and arena.agents:
        served_models = collect_served_models(arena.agents)
        if served_models:
            metadata = getattr(ctx.result, "metadata", None)
            if not isinstance(metadata, dict):
                try:
                    setattr(ctx.result, "metadata", {})
                except (AttributeError, TypeError):
                    metadata = None
                else:
                    metadata = getattr(ctx.result, "metadata", None)
            if isinstance(metadata, dict):
                metadata["served_models"] = served_models
                logger.info(
                    "served_models_attached debate_id=%s agents=%s",
                    state.debate_id,
                    len(served_models),
                )

    # Queue for Supabase background sync
    if ctx.result is not None:
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
    if state.debate_status == DebateStatus.COMPLETED.value and getattr(
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
    _apply_result_debate_state(
        result,
        debate_status=state.debate_status,
        legacy_status=(
            None
            if state.debate_status == DebateStatus.COMPLETED.value
            else str(getattr(result, "status", "") or "").strip() or None
        ),
    )
    if result:
        _attach_truthful_km_metadata(arena, ctx, result)

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
        from aragora.pipeline.executor import PlanExecutor, get_plan, store_plan
        from aragora.pipeline.risk_register import RiskLevel
        from aragora.server.decision_integrity_utils import (
            ensure_decision_plan_backbone_run,
            execute_decision_plan_with_backbone,
            sync_decision_plan_backbone_receipt,
        )

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
        plan_metadata = dict(getattr(plan, "metadata", {}) or {})
        for key in ("backbone_entrypoint", "backbone_run_id", "source_id", "source_surface"):
            plan_metadata.pop(key, None)
        source_id = str(result.debate_id or getattr(plan, "debate_id", "") or plan.id)
        plan_metadata["source_surface"] = "arena_auto_execute"
        plan_metadata["source_id"] = source_id
        plan.metadata = plan_metadata
        run_id = ensure_decision_plan_backbone_run(
            plan,
            auth_context=getattr(arena, "auth_context", None),
            source_surface="arena_auto_execute",
            source_id=source_id,
        )
        store_plan(plan)
        sync_decision_plan_backbone_receipt(plan, append_event=False)

        # Store plan reference on result metadata
        if not isinstance(result.metadata, dict):
            result.metadata = {}
        result.metadata["decision_plan_id"] = plan.id
        result.metadata["decision_plan_run_id"] = run_id
        result.metadata["decision_plan_status"] = (
            plan.status.value if hasattr(plan.status, "value") else str(plan.status)
        )

        # Execute if auto-approved or no approval needed
        if not plan.requires_human_approval:
            executor = PlanExecutor(execution_mode=execution_mode)  # type: ignore[arg-type]
            launch, outcome = await execute_decision_plan_with_backbone(
                plan,
                executor=executor,
                auth_context=getattr(arena, "auth_context", None),
                execution_mode=execution_mode,
                safety_mode=SafetyMode.AUTONOMOUS,
            )
            refreshed_plan = get_plan(plan.id) or plan
            result.metadata["decision_plan_status"] = (
                refreshed_plan.status.value
                if hasattr(refreshed_plan.status, "value")
                else str(refreshed_plan.status)
            )
            result.metadata["decision_plan_run_id"] = launch.get("run_id") or run_id
            result.metadata["execution_id"] = launch.get("execution_id")
            result.metadata["correlation_id"] = launch.get("correlation_id")
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
