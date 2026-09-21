"""
Arena integration hooks for event emission.

Provides hooks that connect the Arena debate engine to the event streaming
system, enabling real-time WebSocket broadcasts of debate events.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, cast
from collections.abc import Callable

from aragora.debate.hooks import HookManager
from aragora.events.context import get_current_task_id, streaming_task_context
from aragora.server.errors import safe_error_message as _safe_error_message
from aragora.server.stream.emitter import SyncEventEmitter
from aragora.events.types import StreamEvent, StreamEventType

logger = logging.getLogger(__name__)

# Patterns that indicate confidence levels in agent responses
_CONFIDENCE_PATTERNS: list[tuple[str, float]] = [
    ("i am highly confident", 0.9),
    ("i'm highly confident", 0.9),
    ("with high confidence", 0.85),
    ("i am confident", 0.8),
    ("i'm confident", 0.8),
    ("strongly believe", 0.8),
    ("i believe", 0.65),
    ("likely", 0.6),
    ("uncertain", 0.4),
    ("i'm not sure", 0.3),
    ("unclear", 0.3),
]


def _extract_confidence(text: str) -> float | None:
    """Extract a confidence signal from response text.

    Returns a float [0,1] if a confidence pattern is found, else None.
    """
    lower = text.lower()
    for pattern, score in _CONFIDENCE_PATTERNS:
        if pattern in lower:
            return score
    return None


def wrap_agent_for_streaming(agent: Any, emitter: SyncEventEmitter, debate_id: str) -> Any:
    """Wrap an agent to emit token streaming events.

    If the agent has a generate_stream() method, we override its generate()
    to call generate_stream() and emit TOKEN_* events.

    Args:
        agent: The agent to wrap
        emitter: The SyncEventEmitter to emit events to
        debate_id: The debate ID to include in events

    Returns:
        The agent (possibly modified with streaming support)
    """
    # Check if agent supports streaming
    if not hasattr(agent, "generate_stream"):
        return agent

    # Store original generate method
    original_generate = agent.generate

    async def streaming_generate(prompt: str, context: Any | None = None) -> str:
        """Streaming wrapper that emits TOKEN_* events."""
        # Get current task_id from context variable (set by streaming_task_context)
        task_id = get_current_task_id()

        # Fallback: generate unique ID if context not set (prevents text interleaving)
        if not task_id:
            # Use UUID for truly unique task_id (prevents collision in concurrent streams)
            task_id = f"{debate_id}:{agent.name}:{uuid.uuid4().hex[:8]}"
            logger.warning(
                "Missing task_id for %s, using fallback: %s. Consider wrapping the generate() call with streaming_task_context().",
                agent.name,
                task_id,
            )

        # Emit thinking event — agent is formulating response
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_THINKING,
                data={
                    "step": "Formulating response",
                    "phase": "reasoning",
                },
                agent=agent.name,
                loop_id=debate_id,
            )
        )

        # Emit start event
        emitter.emit(
            StreamEvent(
                type=StreamEventType.TOKEN_START,
                data={
                    "debate_id": debate_id,
                    "agent": agent.name,
                    "timestamp": datetime.now().isoformat(),
                },
                agent=agent.name,
                task_id=task_id,
            )
        )

        full_response = ""
        try:
            # Stream tokens from the agent
            async for token in agent.generate_stream(prompt, context):
                full_response += token
                # Emit token delta event
                emitter.emit(
                    StreamEvent(
                        type=StreamEventType.TOKEN_DELTA,
                        data={
                            "debate_id": debate_id,
                            "agent": agent.name,
                            "token": token,
                        },
                        agent=agent.name,
                        task_id=task_id,
                    )
                )

            if not full_response.strip():
                logger.warning(
                    "Empty streamed response for %s, falling back to non-streaming generate.",
                    agent.name,
                )
                fallback_response = await original_generate(prompt, context)
                if fallback_response:
                    full_response = fallback_response

            # Emit end event
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.TOKEN_END,
                    data={
                        "debate_id": debate_id,
                        "agent": agent.name,
                        "full_response": full_response,
                    },
                    agent=agent.name,
                    task_id=task_id,
                )
            )

            # Emit confidence based on response analysis
            confidence = _extract_confidence(full_response)
            if confidence is not None:
                emitter.emit(
                    StreamEvent(
                        type=StreamEventType.AGENT_CONFIDENCE,
                        data={"confidence": confidence},
                        agent=agent.name,
                        loop_id=debate_id,
                    )
                )

            return full_response

        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            # Emit error as end event
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.TOKEN_END,
                    data={
                        "debate_id": debate_id,
                        "agent": agent.name,
                        "error": _safe_error_message(e, f"token streaming for {agent.name}"),
                        "full_response": full_response,
                    },
                    agent=agent.name,
                    task_id=task_id,
                )
            )
            # Fall back to non-streaming
            if full_response:
                return full_response
            return cast(str, await original_generate(prompt, context))

    # Replace the generate method
    agent.generate = streaming_generate
    return agent


def _create_lifecycle_hooks(
    emitter: SyncEventEmitter,
    loop_id: str,
) -> dict[str, Callable]:
    """Create debate lifecycle hooks (start, end, rounds, messages)."""

    def on_debate_start(task: str, agents: list[str]) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"task": task, "agents": agents},
                loop_id=loop_id,
            )
        )

    def on_round_start(round_num: int) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.ROUND_START,
                data={"round": round_num},
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_message(
        agent: str,
        content: str,
        role: str,
        round_num: int,
        confidence_score: float | None = None,
        reasoning_phase: str | None = None,
    ) -> None:
        data: dict[str, Any] = {"content": content, "role": role}
        if confidence_score is not None:
            data["confidence_score"] = confidence_score
        if reasoning_phase is not None:
            data["reasoning_phase"] = reasoning_phase
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_MESSAGE,
                data=data,
                round=round_num,
                agent=agent,
                loop_id=loop_id,
            )
        )

        # Emit dedicated confidence event for frontend reasoning UI
        if confidence_score is not None:
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.AGENT_CONFIDENCE,
                    data={"confidence": confidence_score},
                    agent=agent,
                    round=round_num,
                    loop_id=loop_id,
                )
            )

        # Emit thinking event if reasoning phase is provided
        if reasoning_phase:
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.AGENT_THINKING,
                    data={"step": content[:200], "phase": reasoning_phase},
                    agent=agent,
                    round=round_num,
                    loop_id=loop_id,
                )
            )

    def on_debate_end(duration: float, rounds: int) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_END,
                data={"duration": duration, "rounds": rounds},
                loop_id=loop_id,
            )
        )

    return {
        "on_debate_start": on_debate_start,
        "on_round_start": on_round_start,
        "on_message": on_message,
        "on_debate_end": on_debate_end,
    }


def _create_preview_hooks(
    emitter: SyncEventEmitter,
    loop_id: str,
) -> dict[str, Callable]:
    """Create preview and synthesis hooks."""

    def on_agent_preview(agents: list[dict]) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_PREVIEW,
                data={"agents": agents, "topology": "collaborative"},
                loop_id=loop_id,
            )
        )

    def on_context_preview(
        trending_topics: list[dict],
        research_status: str = "gathering context...",
        evidence_sources: list[str] | None = None,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.CONTEXT_PREVIEW,
                data={
                    "trending_topics": trending_topics,
                    "research_status": research_status,
                    "evidence_sources": evidence_sources or [],
                },
                loop_id=loop_id,
            )
        )

    def on_synthesis(content: str, confidence: float = 0.0) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.SYNTHESIS,
                data={
                    "content": content,
                    "confidence": confidence,
                    "agent": "synthesis-agent",
                },
                agent="synthesis-agent",
                loop_id=loop_id,
            )
        )

    return {
        "on_agent_preview": on_agent_preview,
        "on_context_preview": on_context_preview,
        "on_synthesis": on_synthesis,
    }


def _create_consensus_hooks(
    emitter: SyncEventEmitter,
    loop_id: str,
) -> dict[str, Callable]:
    """Create consensus, voting, and convergence hooks."""

    def on_vote(agent: str, vote: str, confidence: float) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.VOTE,
                data={"vote": vote, "confidence": confidence},
                agent=agent,
                loop_id=loop_id,
            )
        )

    def on_consensus(
        reached: bool,
        confidence: float,
        answer: str,
        synthesis: str = "",
        status: str = "",
        agent_failures: dict | None = None,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.CONSENSUS,
                data={
                    "reached": reached,
                    "confidence": confidence,
                    "answer": answer,
                    "synthesis": synthesis,
                    "status": status,
                    "agent_failures": agent_failures or {},
                },
                loop_id=loop_id,
            )
        )

    def on_critique(
        agent: str,
        target: str,
        issues: list[str],
        severity: float,
        round_num: int,
        full_content: str | None = None,
        error: str | None = None,
    ) -> None:
        data = {
            "target": target,
            "issues": issues,
            "severity": severity,
            "content": full_content or "\n".join(f"• {issue}" for issue in issues),
        }
        if error:
            data["error"] = error
        emitter.emit(
            StreamEvent(
                type=StreamEventType.CRITIQUE,
                data=data,
                round=round_num,
                agent=agent,
                loop_id=loop_id,
            )
        )

    def on_convergence_check(
        status: str,
        similarity: float,
        per_agent: dict[str, float],
        round_num: int,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.CONSENSUS,
                data={
                    "status": status,
                    "similarity": similarity,
                    "per_agent": per_agent,
                    "is_convergence_check": True,
                },
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_novelty_check(
        avg_novelty: float,
        per_agent: dict[str, float],
        low_novelty_agents: list[str],
        round_num: int,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.PHASE_PROGRESS,
                data={
                    "phase": "novelty_check",
                    "avg_novelty": avg_novelty,
                    "per_agent": per_agent,
                    "low_novelty_agents": low_novelty_agents,
                },
                round=round_num,
                loop_id=loop_id,
            )
        )

    return {
        "on_vote": on_vote,
        "on_consensus": on_consensus,
        "on_critique": on_critique,
        "on_convergence_check": on_convergence_check,
        "on_novelty_check": on_novelty_check,
    }


def _create_monitoring_hooks(
    emitter: SyncEventEmitter,
    loop_id: str,
) -> dict[str, Callable]:
    """Create error, progress, heartbeat, trickster, and rhetorical hooks."""

    def on_agent_error(
        agent: str,
        error_type: str,
        message: str,
        recoverable: bool = True,
        phase: str = "",
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_ERROR,
                data={
                    "error_type": error_type,
                    "message": message,
                    "recoverable": recoverable,
                    "phase": phase,
                },
                agent=agent,
                loop_id=loop_id,
            )
        )

    def on_phase_progress(
        phase: str,
        completed: int,
        total: int,
        current_agent: str = "",
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.PHASE_PROGRESS,
                data={
                    "phase": phase,
                    "completed": completed,
                    "total": total,
                    "current_agent": current_agent,
                    "progress_pct": (completed / total * 100) if total > 0 else 0,
                },
                loop_id=loop_id,
            )
        )

    def on_heartbeat(phase: str = "", status: str = "alive") -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.HEARTBEAT,
                data={
                    "phase": phase,
                    "status": status,
                },
                loop_id=loop_id,
            )
        )

    def on_trickster_intervention(
        intervention_type: str,
        targets: list[str],
        challenge: str,
        round_num: int,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.TRICKSTER_INTERVENTION,
                data={
                    "intervention_type": intervention_type,
                    "targets": targets,
                    "challenge": challenge[:500],
                },
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_hollow_consensus(
        confidence: float,
        indicators: list[str],
        recommendation: str,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.HOLLOW_CONSENSUS,
                data={
                    "confidence": confidence,
                    "indicators": indicators[:5],
                    "recommendation": recommendation[:200],
                },
                loop_id=loop_id,
            )
        )

    def on_rhetorical_observation(
        agent: str,
        patterns: list[str],
        round_num: int,
        analysis: str = "",
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.RHETORICAL_OBSERVATION,
                data={
                    "agent": agent,
                    "patterns": patterns,
                    "round": round_num,
                    "analysis": analysis[:200],
                },
                agent=agent,
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_agent_thinking(
        agent: str,
        step: str,
        phase: str = "reasoning",
        round_num: int = 0,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_THINKING,
                data={
                    "step": step[:500],
                    "phase": phase,
                },
                agent=agent,
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_agent_evidence(
        agent: str,
        source: str,
        relevance: float = 0.0,
        round_num: int = 0,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_EVIDENCE,
                data={
                    "source": source[:300],
                    "relevance": relevance,
                },
                agent=agent,
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_agent_confidence(
        agent: str,
        confidence: float,
        round_num: int = 0,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_CONFIDENCE,
                data={
                    "confidence": confidence,
                },
                agent=agent,
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_agent_reasoning(
        agent: str,
        reasoning_chunk: str,
        chain_position: int = 0,
        total_steps: int = 0,
        round_num: int = 0,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_REASONING,
                data={
                    "reasoning_chunk": reasoning_chunk[:1000],
                    "chain_position": chain_position,
                    "total_steps": total_steps,
                },
                agent=agent,
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_argument_strength(
        agent: str,
        argument_summary: str,
        strength_score: float,
        factors: dict | None = None,
        round_num: int = 0,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.ARGUMENT_STRENGTH,
                data={
                    "argument_summary": argument_summary[:300],
                    "strength_score": strength_score,
                    "factors": factors or {},
                },
                agent=agent,
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_crux_identified(
        crux_description: str,
        agents_disagreeing: list[str],
        positions: dict | None = None,
        severity: float = 0.5,
        round_num: int = 0,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.CRUX_IDENTIFIED,
                data={
                    "crux_description": crux_description[:500],
                    "agents_disagreeing": agents_disagreeing,
                    "positions": positions or {},
                    "severity": severity,
                },
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_intervention_window(
        debate_id: str,
        round_num: int,
        window_type: str = "between_rounds",
        expires_in_seconds: float = 30.0,
        context_summary: str = "",
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.INTERVENTION_WINDOW,
                data={
                    "debate_id": debate_id,
                    "round_num": round_num,
                    "window_type": window_type,
                    "expires_in_seconds": expires_in_seconds,
                    "context_summary": context_summary[:300],
                },
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_intervention_applied(
        intervention_id: str,
        intervention_type: str,
        content_summary: str,
        applied_at_round: int,
    ) -> None:
        emitter.emit(
            StreamEvent(
                type=StreamEventType.INTERVENTION_APPLIED,
                data={
                    "intervention_id": intervention_id,
                    "intervention_type": intervention_type,
                    "content_summary": content_summary[:300],
                    "applied_at_round": applied_at_round,
                },
                round=applied_at_round,
                loop_id=loop_id,
            )
        )

    return {
        "on_agent_error": on_agent_error,
        "on_phase_progress": on_phase_progress,
        "on_heartbeat": on_heartbeat,
        "on_trickster_intervention": on_trickster_intervention,
        "on_hollow_consensus": on_hollow_consensus,
        "on_rhetorical_observation": on_rhetorical_observation,
        "on_agent_thinking": on_agent_thinking,
        "on_agent_evidence": on_agent_evidence,
        "on_agent_confidence": on_agent_confidence,
        "on_agent_reasoning": on_agent_reasoning,
        "on_argument_strength": on_argument_strength,
        "on_crux_identified": on_crux_identified,
        "on_intervention_window": on_intervention_window,
        "on_intervention_applied": on_intervention_applied,
    }


def create_arena_hooks(emitter: SyncEventEmitter, loop_id: str = "") -> dict[str, Callable]:
    """
    Create hook functions for Arena event emission.

    These hooks are called synchronously by Arena at key points during debate.
    They emit events to the emitter queue for async WebSocket broadcast.

    Args:
        emitter: The SyncEventEmitter to emit events to
        loop_id: Debate ID to attach to all events (required for correct routing)

    Returns:
        dict of hook name -> callback function
    """
    hooks: dict[str, Callable] = {}
    hooks.update(_create_lifecycle_hooks(emitter, loop_id))
    hooks.update(_create_preview_hooks(emitter, loop_id))
    hooks.update(_create_consensus_hooks(emitter, loop_id))
    hooks.update(_create_monitoring_hooks(emitter, loop_id))
    return hooks


def create_hook_manager_from_emitter(
    emitter: SyncEventEmitter,
    loop_id: str = "",
) -> "HookManager":
    """
    Create a HookManager that bridges to WebSocket events.

    This function creates a HookManager and registers all standard hook types
    to emit events via the SyncEventEmitter, enabling real-time WebSocket
    broadcasts of debate lifecycle events.

    Args:
        emitter: The SyncEventEmitter to emit events to
        loop_id: Debate ID to attach to all events

    Returns:
        Configured HookManager with WebSocket bridges
    """
    from aragora.debate.hooks import HookManager, HookPriority, HookType

    manager = HookManager()

    # Bridge debate lifecycle hooks
    def on_pre_debate(**kwargs: Any) -> None:
        """Bridge PRE_DEBATE to DEBATE_START event."""
        task = kwargs.get("task", "")
        agents = [a.name if hasattr(a, "name") else str(a) for a in kwargs.get("agents", [])]
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"task": task, "agents": agents},
                loop_id=loop_id,
            )
        )

    def on_post_debate(**kwargs: Any) -> None:
        """Bridge POST_DEBATE to DEBATE_END event."""
        result = kwargs.get("result")
        duration = getattr(result, "duration", 0.0) if result else 0.0
        rounds = getattr(result, "rounds_completed", 0) if result else 0
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_END,
                data={"duration": duration, "rounds": rounds},
                loop_id=loop_id,
            )
        )

    def on_pre_round(**kwargs: Any) -> None:
        """Bridge PRE_ROUND to ROUND_START event."""
        round_num = kwargs.get("round_num", 0)
        emitter.emit(
            StreamEvent(
                type=StreamEventType.ROUND_START,
                data={"round": round_num},
                round=round_num,
                loop_id=loop_id,
            )
        )

    def on_post_round(**kwargs: Any) -> None:
        """Bridge POST_ROUND - no direct event, but useful for logging."""
        round_num = kwargs.get("round_num", 0)
        proposals = kwargs.get("proposals", {})
        logger.debug("Round %s complete with %s proposals", round_num, len(proposals))

    def on_post_consensus(**kwargs: Any) -> None:
        """Bridge POST_CONSENSUS to CONSENSUS event."""
        result = kwargs.get("result")
        if result:
            reached = getattr(result, "reached", None)
            if reached is None:
                reached = getattr(result, "consensus_reached", False)
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.CONSENSUS,
                    data={
                        "reached": reached,
                        "confidence": getattr(result, "confidence", 0.0),
                        "answer": getattr(result, "answer", ""),
                        "status": getattr(result, "status", ""),
                        "agent_failures": getattr(result, "agent_failures", {}),
                    },
                    loop_id=loop_id,
                )
            )

    def on_finding(**kwargs: Any) -> None:
        """Bridge ON_FINDING to audit finding event."""
        finding = kwargs.get("finding")
        if finding:
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.PHASE_PROGRESS,  # Use PHASE_PROGRESS for audit
                    data={
                        "phase": "audit",
                        "event": "finding",
                        "finding_id": getattr(finding, "id", ""),
                        "title": getattr(finding, "title", ""),
                        "severity": getattr(finding, "severity", "info"),
                    },
                    loop_id=loop_id,
                )
            )

    def on_progress(**kwargs: Any) -> None:
        """Bridge ON_PROGRESS to PHASE_PROGRESS event."""
        phase = kwargs.get("phase", "")
        completed = kwargs.get("completed", 0)
        total = kwargs.get("total", 0)
        emitter.emit(
            StreamEvent(
                type=StreamEventType.PHASE_PROGRESS,
                data={
                    "phase": phase,
                    "completed": completed,
                    "total": total,
                    "progress_pct": (completed / total * 100) if total > 0 else 0,
                },
                loop_id=loop_id,
            )
        )

    def on_error(**kwargs: Any) -> None:
        """Bridge ON_ERROR to AGENT_ERROR event."""
        agent = kwargs.get("agent", "unknown")
        error = kwargs.get("error")
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_ERROR,
                data={
                    "error_type": type(error).__name__ if error else "unknown",
                    "message": str(error) if error else "Unknown error",
                    "recoverable": kwargs.get("recoverable", True),
                    "phase": kwargs.get("phase", ""),
                },
                agent=agent if isinstance(agent, str) else getattr(agent, "name", "unknown"),
                loop_id=loop_id,
            )
        )

    def on_cancellation(**kwargs: Any) -> None:
        """Bridge ON_CANCELLATION event."""
        reason = kwargs.get("reason", "User requested")
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_END,
                data={
                    "cancelled": True,
                    "reason": reason,
                },
                loop_id=loop_id,
            )
        )

    # Register all bridges
    manager.register(
        HookType.PRE_DEBATE, on_pre_debate, priority=HookPriority.LOW, name="ws_pre_debate"
    )
    manager.register(
        HookType.POST_DEBATE, on_post_debate, priority=HookPriority.LOW, name="ws_post_debate"
    )

    # Register result router hook (routes results back to originating chat channels)
    try:
        from aragora.server.result_router import register_result_router_hooks

        register_result_router_hooks(manager)
    except ImportError:
        pass  # Result router not available

    manager.register(
        HookType.PRE_ROUND, on_pre_round, priority=HookPriority.LOW, name="ws_pre_round"
    )
    manager.register(
        HookType.POST_ROUND, on_post_round, priority=HookPriority.LOW, name="ws_post_round"
    )
    manager.register(
        HookType.POST_CONSENSUS,
        on_post_consensus,
        priority=HookPriority.LOW,
        name="ws_post_consensus",
    )
    manager.register(
        HookType.ON_FINDING, on_finding, priority=HookPriority.LOW, name="ws_on_finding"
    )
    manager.register(
        HookType.ON_PROGRESS, on_progress, priority=HookPriority.LOW, name="ws_on_progress"
    )
    manager.register(HookType.ON_ERROR, on_error, priority=HookPriority.LOW, name="ws_on_error")
    manager.register(
        HookType.ON_CANCELLATION,
        on_cancellation,
        priority=HookPriority.LOW,
        name="ws_on_cancellation",
    )

    logger.debug("Created HookManager with %s hook types bridged to WebSocket", len(manager.stats))
    return manager


__all__ = [
    "create_arena_hooks",
    "create_hook_manager_from_emitter",
    "wrap_agent_for_streaming",
    "streaming_task_context",
    "get_current_task_id",
]
