"""Golden 5 — simplified API surface for Aragora.

Provides six thin wrapper functions so newcomers can run a debate, store
and recall memories, review content, chain workflows, and extract audit
receipts without understanding Arena/Environment/DebateProtocol internals.

Every subsystem import is **lazy** (inside the function body) so that
``import aragora`` stays fast regardless of which subsystems are installed.

Usage::

    from aragora import debate, remember, recall, review, workflow, receipt

    result = await debate("Should we adopt microservices?")
    entry  = await remember(result)
    hits   = await recall("microservices tradeoffs")
    report = await review("draft-rfc.md")
    r      = receipt(result)

    wf = workflow("migration").step("audit").step("plan").step("execute")
    await wf.run()
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.core_types import DebateResult
    from aragora.gauntlet.receipt_models import DecisionReceipt
    from aragora.gauntlet.result import GauntletResult
    from aragora.memory.continuum.entry import ContinuumMemoryEntry


# ---------------------------------------------------------------------------
# debate
# ---------------------------------------------------------------------------


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
    from aragora.core_types import Environment
    from aragora.debate.orchestrator import Arena
    from aragora.protocols.debate import DebateProtocol

    if isinstance(agents, int):
        from aragora.agents.demo_agent import DemoAgent
        from aragora.core_types import AgentRole

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


# ---------------------------------------------------------------------------
# remember
# ---------------------------------------------------------------------------


async def remember(
    result: DebateResult | str,
    *,
    tier: str = "slow",
    importance: float = 0.8,
) -> ContinuumMemoryEntry:
    """Store a debate result (or arbitrary text) in continuum memory.

    Args:
        result: A :class:`~aragora.core_types.DebateResult` or a plain
            string to store.
        tier: Memory tier — ``"fast"``, ``"medium"``, ``"slow"``, or
            ``"glacial"``.
        importance: Importance score between 0.0 and 1.0.

    Returns:
        The newly created :class:`~aragora.memory.continuum.entry.ContinuumMemoryEntry`.
    """
    from aragora.memory.continuum.core import ContinuumMemory
    from aragora.memory.tier_manager import MemoryTier

    if isinstance(result, str):
        content = result
        memory_id = f"golden-{uuid.uuid4().hex[:12]}"
    else:
        content = getattr(result, "final_answer", str(result))
        memory_id = getattr(result, "debate_id", None) or f"golden-{uuid.uuid4().hex[:12]}"

    memory_tier = MemoryTier(tier)
    cms = ContinuumMemory()
    return await cms.store(
        key=memory_id,
        content=content,
        tier=memory_tier,
        importance=importance,
    )


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


async def recall(
    query: str,
    *,
    limit: int = 10,
) -> list[ContinuumMemoryEntry]:
    """Retrieve memories matching *query* from continuum memory.

    Args:
        query: Natural-language search query.
        limit: Maximum number of entries to return.

    Returns:
        A list of :class:`~aragora.memory.continuum.entry.ContinuumMemoryEntry`
        objects ranked by relevance.
    """
    from aragora.memory.continuum.core import ContinuumMemory

    cms = ContinuumMemory()
    return cms.retrieve(query=query, limit=limit)


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------


async def review(
    content: str,
    *,
    context: str = "",
) -> GauntletResult:
    """Review content via the Gauntlet adversarial validation engine.

    If *content* looks like a file path and the file exists, its contents
    are read automatically.

    Args:
        content: Either a string of text to review or a file path.
        context: Additional context for the validation.

    Returns:
        A :class:`~aragora.gauntlet.result.GauntletResult` with findings.
    """
    import os

    from aragora.gauntlet.runner import GauntletRunner

    if os.path.isfile(content):
        with open(content, encoding="utf-8", errors="replace") as fh:
            content = fh.read()

    runner = GauntletRunner()
    return await runner.run(content, context=context)


# ---------------------------------------------------------------------------
# workflow
# ---------------------------------------------------------------------------


class WorkflowHandle:
    """Lightweight chainable workflow builder.

    Usage::

        wf = workflow("release")
        wf.step("lint").step("test").step("deploy")
        await wf.run()
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.steps: list[str] = []

    def step(self, name: str) -> WorkflowHandle:
        """Append a named step and return *self* for chaining."""
        self.steps.append(name)
        return self

    async def run(self) -> dict[str, Any]:
        """Execute the workflow steps sequentially.

        Each step is run as an independent debate with the step name as the
        task, collecting results into a dict keyed by step name.
        """
        results: dict[str, Any] = {}
        for step_name in self.steps:
            results[step_name] = await debate(f"[{self.name}] Execute step: {step_name}")
        return results

    def __repr__(self) -> str:
        return f"WorkflowHandle({self.name!r}, steps={self.steps!r})"


def workflow(name: str) -> WorkflowHandle:
    """Create a chainable workflow builder.

    Args:
        name: Descriptive name for the workflow.

    Returns:
        A :class:`WorkflowHandle` that supports ``.step()`` chaining and
        ``.run()`` execution.
    """
    return WorkflowHandle(name)


# ---------------------------------------------------------------------------
# receipt
# ---------------------------------------------------------------------------


def receipt(result: Any) -> DecisionReceipt:
    """Extract an audit receipt from a debate or gauntlet result.

    Accepts either a :class:`~aragora.core_types.DebateResult` (uses
    ``DecisionReceipt.from_debate_result``) or a
    :class:`~aragora.gauntlet.result.GauntletResult` (uses
    ``DecisionReceipt.from_result``).

    Args:
        result: A debate or gauntlet result object.

    Returns:
        A :class:`~aragora.gauntlet.receipt_models.DecisionReceipt`.

    Raises:
        TypeError: If *result* is not a recognised result type.
    """
    from aragora.gauntlet.receipt_models import DecisionReceipt as ReceiptCls

    # Duck-type: GauntletResult has gauntlet_id; DebateResult has debate_id
    if hasattr(result, "gauntlet_id"):
        return ReceiptCls.from_result(result)
    if hasattr(result, "debate_id"):
        return ReceiptCls.from_debate_result(result)
    raise TypeError(
        f"Cannot create receipt from {type(result).__name__}. "
        "Expected a DebateResult or GauntletResult."
    )


__all__ = [
    "WorkflowHandle",
    "debate",
    "recall",
    "receipt",
    "remember",
    "review",
    "workflow",
]
