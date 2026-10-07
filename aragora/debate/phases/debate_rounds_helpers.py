"""
Helper functions and secondary methods for the debate rounds phase.

Contains:
- Module-level helper functions (timeout calculation, empty critique check, etc.)
- Evidence refresh logic (_refresh_evidence_for_round, _refresh_with_skills)
- Context compression (_compress_debate_context)
- Final synthesis round (_execute_final_synthesis_round, _build_final_synthesis_prompt)
- Propulsion event firing (_fire_propulsion_event)
- Rhetorical pattern observation (_observe_rhetorical_patterns)
- Heartbeat emission (_emit_heartbeat)

These are extracted from debate_rounds.py for modularity.
The DebateRoundsPhase class delegates to these functions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.config import AGENT_TIMEOUT_SECONDS, MAX_CONCURRENT_REVISIONS

if TYPE_CHECKING:
    from aragora.core import Agent, Critique, Message
    from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)

# Timeout for async callbacks that can hang (evidence refresh, judge termination, etc.)
DEFAULT_CALLBACK_TIMEOUT = 30.0

# Base timeout for the entire revision phase gather (prevents indefinite stalls)
# Actual timeout is calculated dynamically based on agent count
REVISION_PHASE_BASE_TIMEOUT = 120.0


def calculate_phase_timeout(
    num_agents: int,
    agent_timeout: float,
    max_concurrent: int = MAX_CONCURRENT_REVISIONS,
) -> float:
    """Calculate dynamic phase timeout based on agent count.

    Ensures phase timeout exceeds (agents / max_concurrent) * agent_timeout.
    This prevents the phase from timing out before all agents can complete.

    Args:
        num_agents: Number of agents in the phase
        agent_timeout: Per-agent timeout in seconds

    Returns:
        Phase timeout in seconds
    """
    # With bounded concurrency, worst case is sequential execution
    # Add 60s buffer for gather overhead and safety margin
    effective_parallelism = max(1, max_concurrent)
    calculated = (num_agents / effective_parallelism) * agent_timeout + 60.0
    return max(calculated, REVISION_PHASE_BASE_TIMEOUT)


def is_effectively_empty_critique(critique: Critique) -> bool:
    """Return True if critique only contains placeholder/empty content."""
    has_suggestions_field = hasattr(critique, "suggestions")
    raw_issues = getattr(critique, "issues", []) or []
    raw_suggestions = getattr(critique, "suggestions", []) or []
    issues = [i.strip() for i in raw_issues if isinstance(i, str) and i.strip()]
    suggestions = [s.strip() for s in raw_suggestions if isinstance(s, str) and s.strip()]
    if not issues and not suggestions:
        # Some lightweight test doubles do not model suggestions/reasoning fields;
        # treat those as non-empty to avoid false positives.
        return has_suggestions_field
    if len(issues) == 1:
        normalized = issues[0].strip().lower()
        if normalized in (
            "agent response was empty",
            "(agent produced empty output)",
            "agent produced empty output",
        ):
            return not suggestions
    return False


async def with_callback_timeout(coro, timeout: float = DEFAULT_CALLBACK_TIMEOUT, default=None):
    """Execute coroutine with timeout, returning default on timeout.

    This prevents debates from stalling indefinitely when callbacks
    like evidence refresh or judge termination hang.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Callback timed out after %ss, using default: %s", timeout, default)
        return default


def record_adaptive_round(direction: str) -> None:
    """Record adaptive round change metric with lazy import."""
    try:
        from aragora.observability.metrics import record_adaptive_round_change

        record_adaptive_round_change(direction)
    except ImportError:
        logger.debug("Adaptive round metrics not available")


def emit_heartbeat(hooks: dict, phase: str, status: str = "alive") -> None:
    """Emit heartbeat to indicate debate is still running.

    Prevents frontend timeouts during long-running operations.
    """
    if "on_heartbeat" in hooks:
        try:
            hooks["on_heartbeat"](phase=phase, status=status)
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.debug("Heartbeat emission failed: %s", e)


def observe_rhetorical_patterns(
    rhetorical_observer: Any,
    event_emitter: Any,
    hooks: dict,
    agent: str,
    content: str,
    round_num: int,
    loop_id: str = "",
) -> None:
    """Observe content for rhetorical patterns and emit events."""
    if not rhetorical_observer:
        return

    try:
        observations = rhetorical_observer.observe(
            agent=agent,
            content=content,
            round_num=round_num,
        )

        if not observations:
            return

        # Extract pattern names and build observation data
        patterns = [obs.pattern.value for obs in observations]
        observation_data = [o.to_dict() for o in observations]
        # Use first observation's commentary as analysis if available
        analysis = observations[0].audience_commentary if observations else ""

        # Emit events for rhetorical observations via EventEmitter
        # Use emit_sync since this is not an async context
        if event_emitter:
            event_emitter.emit_sync(
                event_type="rhetorical_observation",
                debate_id=loop_id,
                agent=agent,
                round=round_num,
                patterns=patterns,
                observations=observation_data,
                analysis=analysis,
            )

        # Also call hook for arena_hooks-based WebSocket broadcast
        if "on_rhetorical_observation" in hooks:
            hooks["on_rhetorical_observation"](
                agent=agent,
                patterns=patterns,
                round_num=round_num,
                analysis=analysis,
            )

        # Log for debugging
        for obs in observations:
            logger.debug(
                "rhetorical_pattern agent=%s pattern=%s confidence=%s",
                agent,
                obs.pattern.value,
                obs.confidence,
            )

    except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
        logger.debug("Rhetorical observation failed: %s", e)


async def refresh_evidence_for_round(
    ctx: DebateContext,
    round_num: int,
    refresh_evidence_callback: Callable | None,
    skill_registry: Any,
    enable_skills: bool,
    notify_spectator: Callable | None,
    hooks: dict,
    partial_critiques: list[Critique],
) -> None:
    """Refresh evidence based on claims made in the current round.

    Extracts factual claims from proposals and critiques, then
    searches for new evidence to support or refute those claims.
    The fresh evidence is injected into the context for the revision phase.

    Args:
        ctx: The DebateContext with proposals and critiques
        round_num: Current round number
        refresh_evidence_callback: Async callback to refresh evidence
        skill_registry: Optional SkillRegistry for skill-based evidence refresh
        enable_skills: Whether skills are enabled
        notify_spectator: Callback for spectator notifications
        hooks: Hook callbacks dict
        partial_critiques: Recent critiques from the debate
    """
    if not refresh_evidence_callback:
        return

    # Only refresh evidence every other round to avoid API overload
    if round_num % 2 == 0:
        return

    try:
        # Collect text from proposals and recent critiques
        texts_to_analyze = []

        # Add proposal content
        for agent_name, proposal in ctx.proposals.items():
            if proposal:
                texts_to_analyze.append(proposal[:2000])  # Limit per proposal

        # Add recent critique content
        for critique in partial_critiques[-5:]:  # Last 5 critiques
            critique_text = (
                critique.to_prompt() if hasattr(critique, "to_prompt") else str(critique)
            )
            texts_to_analyze.append(critique_text[:1000])

        if not texts_to_analyze:
            return

        combined_text = "\n".join(texts_to_analyze)

        # Call the refresh callback with timeout protection
        refreshed = await with_callback_timeout(
            refresh_evidence_callback(combined_text, ctx, round_num),
            timeout=DEFAULT_CALLBACK_TIMEOUT,
            default=0,  # Return 0 snippets on timeout
        )

        # Also invoke skills for evidence refresh if enabled
        skill_snippets = 0
        if enable_skills and skill_registry:
            skill_snippets = await refresh_with_skills(combined_text, ctx, skill_registry)

        total_refreshed = (refreshed or 0) + skill_snippets

        if total_refreshed:
            logger.info("evidence_refreshed round=%s new_snippets=%s", round_num, total_refreshed)

            # Notify spectator
            if notify_spectator:
                notify_spectator(
                    "evidence",
                    details=f"Refreshed evidence: {total_refreshed} new sources",
                    metric=total_refreshed,
                    agent="system",
                )

            # Emit evidence refresh event
            if "on_evidence_refresh" in hooks:
                hooks["on_evidence_refresh"](
                    round_num=round_num,
                    new_snippets=total_refreshed,
                )

    except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
        logger.warning("Evidence refresh failed for round %s: %s", round_num, e)


async def refresh_with_skills(
    text: str,
    ctx: DebateContext,
    skill_registry: Any,
) -> int:
    """Refresh evidence using skills for claim-specific searches.

    Args:
        text: Combined text from proposals and critiques
        ctx: The DebateContext
        skill_registry: SkillRegistry for skill-based evidence refresh

    Returns:
        Number of new evidence snippets from skills
    """
    if not skill_registry:
        return 0

    try:
        from aragora.reasoning.evidence_collector import EvidenceSnippet
        from aragora.skills import SkillCapability, SkillContext, SkillStatus

        # Create skill execution context
        skill_ctx = SkillContext(
            user_id="debate-system",
            permissions=["debate:evidence"],
            config={"source": "evidence_refresh", "text_length": len(text)},
        )

        # Find debate-compatible skills
        debate_skills = []
        for manifest in skill_registry.list_skills():
            if SkillCapability.EXTERNAL_API in manifest.capabilities:
                if "debate" in manifest.tags:
                    debate_skills.append(manifest)
                elif manifest.name in ("web_search", "search", "research"):
                    debate_skills.append(manifest)

        if not debate_skills:
            return 0

        # Extract key claims/queries from text (simple heuristic)
        query = text[:500] if len(text) > 500 else text

        snippets_added = 0
        for skill_manifest in debate_skills[:2]:  # Limit to 2 skills per refresh
            try:
                result = await asyncio.wait_for(
                    skill_registry.invoke(
                        skill_manifest.name,
                        {"query": query},
                        skill_ctx,
                    ),
                    timeout=8.0,
                )

                if result.status == SkillStatus.SUCCESS and result.data:
                    snippet = EvidenceSnippet(
                        content=str(result.data)[:2000],
                        source=f"skill:{skill_manifest.name}",
                        relevance=0.65,
                        metadata={
                            "skill": skill_manifest.name,
                            "refresh": True,
                        },
                    )

                    if ctx.evidence_pack:
                        ctx.evidence_pack.snippets.append(snippet)
                        snippets_added += 1

            except asyncio.TimeoutError:
                logger.debug("[skills] Refresh timeout for %s", skill_manifest.name)
            except Exception as e:  # noqa: BLE001 - phase isolation
                logger.debug("[skills] Refresh error for %s: %s", skill_manifest.name, e)

        if snippets_added:
            logger.info("[skills] Refreshed %s evidence snippets from skills", snippets_added)

        return snippets_added

    except ImportError as e:
        logger.debug("[skills] Refresh skipped (missing imports): %s", e)
        return 0
    except Exception as e:  # noqa: BLE001 - phase isolation
        logger.warning("[skills] Refresh error: %s", e)
        return 0


async def compress_debate_context(
    ctx: DebateContext,
    round_num: int,
    compress_context_callback: Callable | None,
    hooks: dict,
    notify_spectator: Callable | None,
    partial_critiques: list[Critique],
) -> None:
    """Compress debate context using RLM cognitive load limiter.

    Called at the start of each round after the threshold to keep
    context manageable for long debates. Old messages are summarized
    while recent messages are kept at full detail.

    Args:
        ctx: The DebateContext with messages to compress
        round_num: Current round number
        compress_context_callback: Async callback to compress debate messages
        hooks: Hook callbacks dict
        notify_spectator: Callback for spectator notifications
        partial_critiques: Recent critiques for compression
    """
    if not compress_context_callback:
        return

    # Only compress if there are enough messages to warrant it
    if len(ctx.context_messages) < 10:
        return

    try:
        # Emit heartbeat to signal compression is happening
        emit_heartbeat(hooks, f"round_{round_num}", "compressing_context")

        # Call Arena's compress_debate_messages method
        compressed_msgs, compressed_crits = await with_callback_timeout(
            compress_context_callback(
                messages=ctx.context_messages,
                critiques=partial_critiques,
            ),
            timeout=DEFAULT_CALLBACK_TIMEOUT,
            default=(ctx.context_messages, partial_critiques),
        )

        # Update context with compressed messages
        if compressed_msgs is not ctx.context_messages:
            original_count = len(ctx.context_messages)
            ctx.context_messages = list(compressed_msgs)
            logger.info(
                "[rlm] Compressed context: %s -> %s messages",
                original_count,
                len(ctx.context_messages),
            )

            # Notify spectator about compression
            if notify_spectator:
                notify_spectator(
                    "context_compression",
                    details=f"Compressed {original_count} → {len(ctx.context_messages)} messages",
                    agent="system",
                )

            # Emit hook for WebSocket clients
            if "on_context_compression" in hooks:
                hooks["on_context_compression"](
                    round_num=round_num,
                    original_count=original_count,
                    compressed_count=len(ctx.context_messages),
                )

    except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
        logger.warning("[rlm] Context compression failed: %s", e)
        # Continue without compression - don't break the debate


async def execute_final_synthesis_round(
    ctx: DebateContext,
    round_num: int,
    circuit_breaker: Any,
    generate_with_agent: Callable | None,
    hooks: dict,
    notify_spectator: Callable | None,
    partial_messages: list[Message],
) -> None:
    """Execute Round 7: Final Synthesis.

    Each agent synthesizes the discussion and revises their proposal to final form.
    This is different from normal rounds - agents write their polished final position
    incorporating insights from the entire debate.

    Args:
        ctx: The DebateContext with proposals and critiques
        round_num: Round number (should be 7)
        circuit_breaker: CircuitBreaker for agent availability
        generate_with_agent: Async callback to generate with agent
        hooks: Hook callbacks dict
        notify_spectator: Callback for spectator notifications
        partial_messages: List to append partial messages to
    """
    from aragora.core import Message

    result = ctx.result
    proposals = ctx.proposals

    # Get all proposers
    proposers = ctx.proposers if ctx.proposers else ctx.agents

    # Filter through circuit breaker
    if circuit_breaker:
        try:
            available = circuit_breaker.filter_available_agents(list(proposers))
            if len(available) < len(proposers):
                skipped = [p.name for p in proposers if p not in available]
                logger.info("circuit_breaker_skip_synthesis skipped=%s", skipped)
            proposers = available
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.error("Circuit breaker filter error for synthesis: %s", e)

    # Each proposer writes their final synthesis
    for agent in proposers:
        try:
            # Get critiques from result or round_critiques
            all_critiques: list[Critique] = []
            if result and result.critiques:
                all_critiques = list(result.critiques)
            elif ctx.round_critiques:
                all_critiques = list(ctx.round_critiques)

            prompt = build_final_synthesis_prompt(
                agent=agent,
                current_proposal=proposals.get(agent.name, ""),
                all_proposals=proposals,
                critiques=all_critiques,
                round_num=round_num,
            )

            # Generate final synthesis with timeout
            if not generate_with_agent:
                logger.warning(
                    "No generate_with_agent callback for final synthesis of %s", agent.name
                )
                continue

            base_timeout = float(getattr(agent, "timeout", AGENT_TIMEOUT_SECONDS))
            final_proposal = await asyncio.wait_for(
                generate_with_agent(agent, prompt, ctx.context_messages),
                timeout=base_timeout,
            )

            if final_proposal:
                proposals[agent.name] = final_proposal

                # Record as message
                msg = Message(
                    role="final_synthesis",
                    agent=agent.name,
                    content=final_proposal,
                    round=round_num,
                )
                ctx.add_message(msg)  # also appends to result.messages (#9661)
                partial_messages.append(msg)

                # Emit event
                if "on_message" in hooks:
                    hooks["on_message"](
                        agent=agent.name,
                        content=final_proposal,
                        role="final_synthesis",
                        round_num=round_num,
                        full_content=final_proposal,
                    )

                logger.info("final_synthesis_complete agent=%s", agent.name)

        except asyncio.TimeoutError:
            logger.warning("Final synthesis timeout for agent %s", agent.name)
        except (ConnectionError, OSError, ValueError, TypeError, RuntimeError) as e:
            logger.error(
                "synthesis_agent_error agent=%s error_type=%s: %s",
                agent.name,
                type(e).__name__,
                e,
            )
        except Exception as e:  # noqa: BLE001 - phase isolation
            logger.error(
                "synthesis_unexpected_error agent=%s error_type=%s: %s",
                agent.name,
                type(e).__name__,
                e,
            )

    # Notify spectator
    if notify_spectator:
        notify_spectator(
            "final_synthesis",
            details="All agents have submitted final syntheses",
            agent="system",
        )


def build_final_synthesis_prompt(
    agent: Agent,
    current_proposal: str,
    all_proposals: dict,
    critiques: list,
    round_num: int,
) -> str:
    """Build prompt for Round 7 final synthesis.

    Args:
        agent: The agent writing the synthesis
        current_proposal: Agent's current proposal
        all_proposals: All proposals from all agents
        critiques: List of critiques from the debate
        round_num: Round number (7)

    Returns:
        Formatted prompt for final synthesis
    """
    # Get other agents' proposals
    other_proposals = "\n\n".join(
        f"**{name}:** {prop[:1200]}..."
        for name, prop in all_proposals.items()
        if name != agent.name and prop
    )

    # Get recent critique summaries
    critique_summary = "\n".join(
        f"- {getattr(c, 'critic', 'Unknown')} on {getattr(c, 'target', 'Unknown')}: {getattr(c, 'summary', str(c)[:200])}"
        for c in critiques[-15:]  # Last 15 critiques
    )

    return f"""## ROUND 7: FINAL SYNTHESIS

You are {agent.name}. This is your FINAL opportunity to revise your proposal.

After 6 rounds of debate, critique, and refinement, you must now present your
polished, definitive position that incorporates the strongest insights from
the entire discussion.

### Your Current Proposal
{current_proposal[:2000] if current_proposal else "(No previous proposal)"}

### Other Agents' Current Positions
{other_proposals if other_proposals else "(No other proposals available)"}

### Key Critiques from the Debate
{critique_summary if critique_summary else "(No critiques recorded)"}

### Your Task
Write your FINAL, POLISHED proposal that:

1. **Incorporates the strongest points** raised by other agents during the debate
2. **Addresses the most compelling critiques** of your position
3. **Presents your clearest, most defensible position** with supporting reasoning
4. **Acknowledges remaining uncertainties** honestly and explicitly
5. **Provides actionable conclusions** where applicable

This is your final word. Make it count. Be thorough but focused.
Write in a clear, confident voice while acknowledging genuine complexity."""


async def fire_propulsion_event(
    event_type: str,
    ctx: DebateContext,
    round_num: int,
    propulsion_engine: Any,
    enable_propulsion: bool,
    data: dict | None = None,
) -> None:
    """Fire propulsion event to push work to the next stage.

    Triggers propulsion events at key stage transitions for reactive debate flow
    via the Gastown pattern.

    Args:
        event_type: Event type (e.g., "critiques_ready", "revisions_complete")
        ctx: The DebateContext
        round_num: Current round number
        propulsion_engine: PropulsionEngine instance
        enable_propulsion: Whether propulsion is enabled
        data: Additional data to include in payload
    """
    if not enable_propulsion or not propulsion_engine:
        return

    try:
        from aragora.debate.propulsion import PropulsionPayload, PropulsionPriority

        # Build payload data
        payload_data = {
            "round_num": round_num,
            "debate_id": getattr(ctx, "debate_id", None),
            "task": ctx.env.task[:200] if ctx.env else None,
        }
        if data:
            payload_data.update(data)

        # Create payload
        payload = PropulsionPayload(
            data=payload_data,
            priority=PropulsionPriority.NORMAL,
            source_stage=f"debate_rounds_round_{round_num}",
            source_molecule_id=getattr(ctx, "debate_id", None),
        )

        # Fire the propulsion event
        results = await propulsion_engine.propel(event_type, payload)

        if results:
            success_count = sum(1 for r in results if r.success)
            logger.info(
                "[propulsion] %s fired round=%s handlers=%s success=%s",
                event_type,
                round_num,
                len(results),
                success_count,
            )
    except ImportError:
        logger.debug("[propulsion] PropulsionEngine imports unavailable")
    except Exception as e:  # noqa: BLE001 - phase isolation
        logger.warning("[propulsion] Failed to fire %s: %s", event_type, e)
