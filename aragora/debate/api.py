"""The ``debate`` call behind ``aragora.debate(...)`` and :func:`aragora.golden.debate`."""

from __future__ import annotations

from typing import Any, cast

from aragora.agents.demo_agent import DemoAgent
from aragora.core_types import AgentRole, DebateResult, Environment
from aragora.debate.orchestrator import Arena
from aragora.protocols.debate import DebateProtocol


async def debate(
    task: str,
    *,
    agents: int | list[Any] = 3,
    rounds: int = 3,
    consensus: str = "majority",
) -> DebateResult:
    """Run a multi-agent debate and return the result.

    Args:
        task: The question or problem to debate.
        agents: Either an ``int`` (auto-creates that many DemoAgents) or an
            explicit list of agent instances.
        rounds: Number of debate rounds.
        consensus: Consensus strategy — ``"majority"``, ``"unanimous"``,
            ``"judge"``, or ``"none"``.

    Returns:
        A :class:`~aragora.core_types.DebateResult` with the final answer,
        confidence, messages, votes, and more.
    """
    if isinstance(agents, int):
        roles: list[AgentRole] = ["proposer", "critic", "synthesizer"]
        agent_list: list[Any] = [
            DemoAgent(name=f"agent-{i + 1}", role=roles[i % len(roles)]) for i in range(agents)
        ]
    else:
        agent_list = list(agents)

    env = Environment(task=task)
    # The public signature accepts any str; DebateProtocol narrows it to a Literal.
    protocol = DebateProtocol(rounds=rounds, consensus=cast(Any, consensus))
    arena = Arena(environment=env, agents=agent_list, protocol=protocol)
    return await arena.run()


__all__ = ["debate"]
