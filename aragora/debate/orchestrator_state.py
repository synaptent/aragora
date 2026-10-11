"""State accessor and query helpers for Arena.

Extracted from orchestrator.py to reduce its size. Contains property-like
accessors, state queries, team selection, quality filtering, early termination,
and judge selection logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aragora.debate.judge_selector import JudgeSelector
from aragora.debate.sanitization import OutputSanitizer

from aragora.debate.orchestrator_agents import (
    filter_responses_by_quality as _agents_filter_responses_by_quality,
    select_debate_team as _agents_select_debate_team,
    should_terminate_early as _agents_should_terminate_early,
)
from aragora.debate.orchestrator_setup import (
    compute_domain_from_task as _compute_domain_from_task,
)

if TYPE_CHECKING:
    from aragora.core import Agent, Message
    from aragora.debate.orchestrator import Arena


def require_agents(arena: Arena) -> list[Agent]:
    """Return agents list, raising error if empty.

    Args:
        arena: Arena instance.

    Returns:
        Non-empty list of agents.

    Raises:
        ValueError: If no agents are available.
    """
    if not arena.agents:
        raise ValueError("No agents available - Arena requires at least one agent")
    return arena.agents


def sync_prompt_builder_state(arena: Arena) -> None:
    """Sync Arena state to PromptBuilder before building prompts.

    Args:
        arena: Arena instance.
    """
    arena.prompt_builder.current_role_assignments = arena.current_role_assignments
    arena.prompt_builder._historical_context_cache = arena._cache.historical_context
    arena.prompt_builder._continuum_context_cache = get_continuum_context(arena)
    arena.prompt_builder.user_suggestions = list(arena.user_suggestions)
    arena.prompt_builder.mode_sequence = getattr(arena, "mode_sequence", None)


def get_continuum_context(arena: Arena) -> str:
    """Retrieve relevant memories from ContinuumMemory for debate context.

    Args:
        arena: Arena instance.

    Returns:
        Formatted continuum memory context string.
    """
    return arena._context_delegator.get_continuum_context()


def extract_debate_domain(arena: Arena) -> str:
    """Extract domain from the debate task. Cached at instance and module level.

    Args:
        arena: Arena instance.

    Returns:
        Domain string extracted from the debate task.

    Raises:
        RuntimeError: If cached debate domain is None (cache corruption).
    """
    if arena._cache.has_debate_domain():
        if arena._cache.debate_domain is None:
            raise RuntimeError("Cached debate domain is None - cache may be corrupted")
        return arena._cache.debate_domain
    domain = _compute_domain_from_task(arena.env.task.lower())
    arena._cache.debate_domain = domain
    return domain


def select_debate_team(arena: Arena, requested_agents: list[Agent]) -> list[Agent]:
    """Select debate team based on domain and ML delegation.

    Args:
        arena: Arena instance.
        requested_agents: List of agents to select from.

    Returns:
        Selected list of agents for the debate.
    """
    return _agents_select_debate_team(
        agents=requested_agents,
        env=arena.env,
        extract_domain_fn=lambda: extract_debate_domain(arena),
        enable_ml_delegation=arena.enable_ml_delegation,
        ml_delegation_strategy=arena._ml_delegation_strategy,
        protocol=arena.protocol,
        use_performance_selection=arena.use_performance_selection,
        agent_pool=arena.agent_pool,
    )


def filter_responses_by_quality(
    arena: Arena, responses: list[tuple[str, str]], context: str = ""
) -> list[tuple[str, str]]:
    """Filter responses using ML quality gate.

    Args:
        arena: Arena instance.
        responses: List of (agent_name, response) tuples.
        context: Optional context string for quality evaluation.

    Returns:
        Filtered list of responses that pass quality threshold.
    """
    return _agents_filter_responses_by_quality(
        responses=responses,
        enable_quality_gates=arena.enable_quality_gates,
        ml_quality_gate=arena._ml_quality_gate,
        task=arena.env.task,
        context=context,
    )


def should_terminate_early(
    arena: Arena, responses: list[tuple[str, str]], current_round: int
) -> bool:
    """Check if debate should terminate early based on consensus estimation.

    Args:
        arena: Arena instance.
        responses: List of (agent_name, response) tuples.
        current_round: Current debate round number.

    Returns:
        True if debate should terminate early.
    """
    return _agents_should_terminate_early(
        responses=responses,
        current_round=current_round,
        enable_consensus_estimation=arena.enable_consensus_estimation,
        ml_consensus_estimator=arena._ml_consensus_estimator,
        protocol=arena.protocol,
        task=arena.env.task,
    )


async def select_judge(arena: Arena, proposals: dict[str, str], context: list[Message]) -> Agent:
    """Select judge based on protocol.judge_selection setting.

    Args:
        arena: Arena instance.
        proposals: Dict mapping agent names to their proposals.
        context: List of messages for context.

    Returns:
        Selected judge Agent.
    """

    async def generate_wrapper(agent: Agent, prompt: str, ctx: list[Message]) -> str:
        return await agent.generate(prompt, ctx)

    selector = JudgeSelector(
        agents=require_agents(arena),
        elo_system=arena.elo_system,
        judge_selection=arena.protocol.judge_selection,
        generate_fn=generate_wrapper,
        build_vote_prompt_fn=lambda candidates, props: arena.prompt_builder.build_judge_vote_prompt(
            candidates, props
        ),
        sanitize_fn=OutputSanitizer.sanitize_agent_output,
        consensus_memory=arena.consensus_memory,
    )
    judge = await selector.select_judge(proposals, context)
    if judge is None:
        raise RuntimeError("Judge selection returned no agent")
    return judge
