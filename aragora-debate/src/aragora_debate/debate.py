"""High-level Debate API -- the 5-line interface to adversarial multi-model debates.

Usage::

    from aragora_debate import Debate, create_agent

    debate = Debate(topic="Should we migrate to microservices?")
    debate.add_agent(create_agent("anthropic", model="claude-sonnet-4-5-20250929"))
    debate.add_agent(create_agent("openai", model="gpt-4o"))
    result = await debate.run()
    print(result.receipt.to_markdown())

This module wraps the full :class:`Arena` orchestrator with a minimal API.
"""

from __future__ import annotations

from typing import Any

from aragora_debate.arena import Arena
from aragora_debate.types import (
    Agent,
    ConsensusMethod,
    DebateConfig,
    DebateResult,
)


class Debate:
    """Run a multi-model adversarial debate with a minimal API.

    Parameters
    ----------
    topic : str
        The question or decision to debate.
    context : str
        Optional background information provided to all agents.
    rounds : int
        Number of debate rounds (propose -> critique -> vote).
    consensus : str
        Consensus method: ``"majority"``, ``"supermajority"``, ``"unanimous"``,
        ``"judge"``, or ``"weighted"``.
    early_stopping : bool
        Stop early when consensus is reached.
    enable_trickster : bool
        Enable hollow-consensus detection and challenge injection.
    enable_convergence : bool
        Enable convergence tracking across rounds.
    convergence_threshold : float
        Similarity threshold for convergence detection (0.0-1.0).
    trickster_sensitivity : float
        Sensitivity for trickster interventions (0.0-1.0).
    on_event : callable | None
        Callback invoked for every debate event.

    Example
    -------
    ::

        debate = Debate("Should we use Kafka or RabbitMQ?")
        debate.add_agent(create_agent("anthropic", name="analyst"))
        debate.add_agent(create_agent("openai", name="challenger"))
        result = await debate.run()
        print(result.receipt.to_markdown())
    """

    def __init__(
        self,
        topic: str,
        *,
        context: str = "",
        rounds: int = 3,
        consensus: str = "majority",
        early_stopping: bool = True,
        enable_trickster: bool = False,
        enable_convergence: bool = False,
        convergence_threshold: float = 0.85,
        trickster_sensitivity: float = 0.5,
        on_event: Any = None,
    ) -> None:
        self.topic = topic
        self.context = context
        self._on_event = on_event
        self._agents: list[Agent] = []
        self._config = DebateConfig(
            rounds=rounds,
            consensus_method=ConsensusMethod(consensus),
            early_stopping=early_stopping,
            enable_trickster=enable_trickster,
            enable_convergence=enable_convergence,
            convergence_threshold=convergence_threshold,
            trickster_sensitivity=trickster_sensitivity,
        )

    def add_agent(self, agent: Agent) -> Debate:
        """Add an agent to the debate. Returns self for chaining."""
        self._agents.append(agent)
        return self

    async def run(self) -> DebateResult:
        """Execute the debate and return the result with decision receipt.

        Raises
        ------
        ValueError
            If fewer than 2 agents have been added.
        """
        if len(self._agents) < 2:
            raise ValueError(f"A debate requires at least 2 agents, got {len(self._agents)}")

        arena = Arena(
            question=self.topic,
            agents=self._agents,
            config=self._config,
            context=self.context,
            on_event=self._on_event,
        )
        return await arena.run()

    @property
    def agents(self) -> list[Agent]:
        """The agents currently registered for this debate."""
        return list(self._agents)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

_AGENT_COUNTER: dict[str, int] = {}


def _auto_name(provider: str) -> str:
    """Generate a unique default name for an agent."""
    count = _AGENT_COUNTER.get(provider, 0) + 1
    _AGENT_COUNTER[provider] = count
    if count == 1:
        return provider
    return f"{provider}-{count}"


def create_agent(
    provider: str,
    *,
    name: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    system_prompt: str = "",
    stance: str = "neutral",
    **kwargs: Any,
) -> Agent:
    """Create a debate agent for the given LLM provider.

    Parameters
    ----------
    provider : str
        Provider name: ``"anthropic"`` (Claude), ``"openai"`` (GPT),
        ``"mistral"``, ``"gemini"``, or ``"mock"`` (deterministic, for testing).
    name : str | None
        Agent display name. Auto-generated if not provided.
    model : str | None
        Model ID.  Defaults to each provider's recommended model.
    api_key : str | None
        API key.  Falls back to the standard env var for each provider.
    system_prompt : str
        Custom system prompt for the agent.
    stance : str
        Debate stance: ``"affirmative"``, ``"negative"``, or ``"neutral"``.
    **kwargs
        Additional provider-specific arguments (e.g. ``max_tokens``,
        ``temperature``).

    Returns
    -------
    Agent
        A configured agent ready for debate.

    Raises
    ------
    ValueError
        If the provider is not recognized.
    ImportError
        If the provider's SDK package is not installed.
    """
    agent_name = name or _auto_name(provider)
    prov = provider.lower().strip()

    if prov in ("anthropic", "claude"):
        from aragora_debate.agents import ClaudeAgent

        return ClaudeAgent(
            name=agent_name,
            model=model or "claude-sonnet-4-5-20250929",
            api_key=api_key,
            system_prompt=system_prompt,
            stance=stance,
            **kwargs,
        )

    if prov in ("openai", "gpt"):
        from aragora_debate.agents import OpenAIAgent

        return OpenAIAgent(
            name=agent_name,
            model=model or "gpt-4o",
            api_key=api_key,
            system_prompt=system_prompt,
            stance=stance,
            **kwargs,
        )

    if prov == "mistral":
        from aragora_debate.agents import MistralAgent

        return MistralAgent(
            name=agent_name,
            model=model or "mistral-large-latest",
            api_key=api_key,
            system_prompt=system_prompt,
            stance=stance,
            **kwargs,
        )

    if prov == "gemini":
        from aragora_debate.agents import GeminiAgent

        return GeminiAgent(
            name=agent_name,
            model=model or "gemini-3.1-pro-preview",
            api_key=api_key,
            system_prompt=system_prompt,
            stance=stance,
            **kwargs,
        )

    if prov == "mock":
        from aragora_debate._mock import MockAgent

        return MockAgent(
            name=agent_name,
            system_prompt=system_prompt,
            stance=stance,
            **{k: v for k, v in kwargs.items() if k in ("proposal", "vote_for", "critique_issues")},
        )

    raise ValueError(
        f"Unknown provider {provider!r}. "
        f"Supported: 'anthropic', 'openai', 'mistral', 'gemini', 'mock'"
    )
