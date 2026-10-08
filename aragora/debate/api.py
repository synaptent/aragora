"""The ``debate`` call behind ``aragora.debate(...)`` and :func:`aragora.golden.debate`."""

from __future__ import annotations

import sys
from typing import Any

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
    _restore_callable_package()

    if isinstance(agents, int):
        roles: list[AgentRole] = ["proposer", "critic", "synthesizer"]
        agent_list: list[Any] = [
            DemoAgent(name=f"agent-{i + 1}", role=roles[i % len(roles)]) for i in range(agents)
        ]
    else:
        agent_list = list(agents)

    env = Environment(task=task)
    protocol = DebateProtocol(rounds=rounds, consensus=consensus)
    arena = Arena(environment=env, agents=agent_list, protocol=protocol)
    return await arena.run()


def _restore_callable_package() -> None:
    # aragora/__init__.py resolves ``aragora.debate`` lazily through aragora.golden and caches
    # the result. Resolving it imports this package, so the cache overwrites the package
    # binding that import made with this function, and ``aragora.debate.<name>`` stops
    # working. When the body lived in aragora.golden, its first run imported the package and
    # put the (callable) package back; doing the same here keeps that behaviour.
    root = sys.modules.get("aragora")
    package = sys.modules.get(__package__ or "")
    if root is not None and package is not None and vars(root).get("debate") is debate:
        vars(root)["debate"] = package


__all__ = ["debate"]
