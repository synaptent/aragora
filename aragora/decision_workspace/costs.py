"""Per-agent model cost of a decision run, split into actual and estimated spend.

Cost comes from each agent's own token counters during the run, priced with
the billing price table. Agents whose calls go through VibeProxy (an
``openai-api`` agent with a non-direct model transport) run on a
subscription, so their cost is an estimate; every other agent is billed by
its provider and counts as actual spend. When an agent produced output but
its provider reported no token usage, tokens are approximated from text
length (four characters per token) and the entry says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

COST_ACTUAL = "actual"
COST_ESTIMATED = "estimated"
CHARS_PER_TOKEN = 4

_MODEL_FAMILIES = (
    ("claude", "anthropic"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("gemini", "google"),
    ("grok", "xai"),
    ("deepseek", "deepseek"),
    ("mistral", "mistral"),
)


def unwrap_agent(agent: Any) -> Any:
    """The model agent behind resilience wrappers such as the airlock proxy."""
    for _ in range(5):
        inner = getattr(agent, "wrapped_agent", None)
        if inner is None or inner is agent:
            break
        agent = inner
    return agent


def cost_kind(agent: Any) -> str:
    """``estimated`` for VibeProxy-routed agents, ``actual`` for everything else."""
    from aragora.agents.transports.vibeproxy import TransportMode

    policy = getattr(unwrap_agent(agent), "_model_transport_policy", None)
    mode = getattr(policy, "mode", None)
    if mode is not None and mode is not TransportMode.DIRECT:
        return COST_ESTIMATED
    return COST_ACTUAL


def token_usage(agent: Any) -> tuple[int, int]:
    """``(tokens_in, tokens_out)`` the agent has recorded so far."""
    inner = unwrap_agent(agent)
    tokens_in = getattr(inner, "total_tokens_in", 0)
    tokens_out = getattr(inner, "total_tokens_out", 0)
    return (
        tokens_in if isinstance(tokens_in, int) else 0,
        tokens_out if isinstance(tokens_out, int) else 0,
    )


def pricing_key(model: str) -> tuple[str, str]:
    """``(provider, model)`` for the billing price table."""
    from aragora.billing.usage import PROVIDER_PRICING

    name = (model or "").strip()
    if "/" in name:
        return "openrouter", name
    lowered = name.lower()
    provider = next(
        (family for prefix, family in _MODEL_FAMILIES if lowered.startswith(prefix)), "openrouter"
    )
    table = PROVIDER_PRICING.get(provider, {})
    if name not in table and lowered.endswith("-latest") and name[: -len("-latest")] in table:
        name = name[: -len("-latest")]
    return provider, name


def price(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    from aragora.billing.usage import calculate_token_cost

    provider, name = pricing_key(model)
    return calculate_token_cost(provider, name, max(tokens_in, 0), max(tokens_out, 0))


@dataclass(slots=True)
class AgentCost:
    """Accumulated usage and cost of one agent across a run's phases."""

    agent: str
    spec: str | None
    model: str
    kind: str
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_approximated: bool = False
    cost_usd: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "spec": self.spec,
            "model": self.model,
            "kind": self.kind,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_approximated": self.tokens_approximated,
            "cost_usd": float(self.cost_usd),
        }


def phase_tokens(
    tokens_in: int, tokens_out: int, *, chars_in: int = 0, chars_out: int = 0
) -> tuple[int, int, bool]:
    """``(tokens_in, tokens_out, approximated)`` for one phase of one agent.

    When the provider reported no usage but the agent produced text, tokens
    are approximated from ``chars_in`` / ``chars_out``.
    """
    if tokens_in == 0 and tokens_out == 0 and chars_out > 0:
        return chars_in // CHARS_PER_TOKEN, max(1, chars_out // CHARS_PER_TOKEN), True
    return tokens_in, tokens_out, False


class CostLedger:
    """Per-agent costs of one run, one entry per selected agent in panel order."""

    def __init__(self, agents: list[Any], specs: list[str]) -> None:
        self._entries: list[AgentCost] = []
        for agent, spec in zip(agents, specs):
            inner = unwrap_agent(agent)
            self._entries.append(
                AgentCost(
                    agent=str(getattr(agent, "name", None) or getattr(inner, "name", spec)),
                    spec=spec,
                    model=str(getattr(inner, "model", "") or ""),
                    kind=cost_kind(inner),
                )
            )

    def charge(self, index: int, tokens_in: int, tokens_out: int, *, approximated: bool) -> Decimal:
        """Add one phase's usage to agent ``index``; returns the phase cost."""
        entry = self._entries[index]
        cost = price(entry.model, tokens_in, tokens_out)
        entry.tokens_in += tokens_in
        entry.tokens_out += tokens_out
        entry.tokens_approximated = entry.tokens_approximated or approximated
        entry.cost_usd += cost
        return cost

    @property
    def actual_usd(self) -> Decimal:
        return sum((e.cost_usd for e in self._entries if e.kind == COST_ACTUAL), Decimal("0"))

    @property
    def estimated_usd(self) -> Decimal:
        return sum((e.cost_usd for e in self._entries if e.kind == COST_ESTIMATED), Decimal("0"))

    @property
    def total_usd(self) -> Decimal:
        return self.actual_usd + self.estimated_usd

    def to_list(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self._entries]


__all__ = [
    "AgentCost",
    "COST_ACTUAL",
    "COST_ESTIMATED",
    "CostLedger",
    "cost_kind",
    "phase_tokens",
    "price",
    "pricing_key",
    "token_usage",
    "unwrap_agent",
]
