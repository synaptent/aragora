"""Per-agent run costs: price lookup, actual versus estimated, approximation."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from aragora.agents.transports.vibeproxy import TransportMode
from aragora.decision_workspace.costs import (
    COST_ACTUAL,
    COST_ESTIMATED,
    CostLedger,
    cost_kind,
    phase_tokens,
    price,
    pricing_key,
    token_usage,
    unwrap_agent,
)


def _agent(name, model, mode=None, tokens=(0, 0)):
    agent = SimpleNamespace(
        name=name, model=model, total_tokens_in=tokens[0], total_tokens_out=tokens[1]
    )
    if mode is not None:
        agent._model_transport_policy = SimpleNamespace(mode=mode)
    return agent


@pytest.mark.parametrize(
    "model, expected",
    [
        ("grok-4-latest", ("xai", "grok-4")),
        ("grok-4", ("xai", "grok-4")),
        ("gpt-5.5", ("openai", "gpt-5.5")),
        ("claude-haiku-4-5-20251001", ("anthropic", "claude-haiku-4-5-20251001")),
        ("gemini-3-flash", ("google", "gemini-3-flash")),
        ("deepseek/deepseek-v4-pro", ("openrouter", "deepseek/deepseek-v4-pro")),
    ],
)
def test_models_price_under_their_provider(model, expected):
    assert pricing_key(model) == expected


def test_grok_is_priced_at_the_grok_4_rate():
    assert price("grok-4-latest", 1_000_000, 1_000_000) == Decimal("18.00")


@pytest.mark.parametrize(
    "mode, kind",
    [
        (TransportMode.PREFER, COST_ESTIMATED),
        (TransportMode.REQUIRED, COST_ESTIMATED),
        (TransportMode.DIRECT, COST_ACTUAL),
        (None, COST_ACTUAL),
    ],
)
def test_vibeproxy_routed_agents_are_estimated_and_others_actual(mode, kind):
    assert cost_kind(_agent("a", "gpt-5.5", mode)) == kind


def test_wrapped_agents_are_read_through_the_wrapper():
    inner = _agent("grok", "grok-4-latest", tokens=(10, 5))
    wrapper = SimpleNamespace(name="grok", wrapped_agent=inner)
    assert unwrap_agent(wrapper) is inner
    assert token_usage(wrapper) == (10, 5)


def test_unreported_usage_is_approximated_from_text():
    assert phase_tokens(0, 0, chars_in=400, chars_out=80) == (100, 20, True)
    assert phase_tokens(12, 3, chars_in=400, chars_out=80) == (12, 3, False)
    assert phase_tokens(0, 0) == (0, 0, False)


def test_ledger_splits_actual_and_estimated_spend():
    openai = _agent("openai-api", "gpt-5.5", TransportMode.PREFER)
    grok = _agent("grok", "grok-4-latest")
    ledger = CostLedger([openai, grok], ["openai-api|gpt-5.5", "grok"])
    ledger.charge(0, 1_000_000, 0, approximated=False)
    ledger.charge(1, 0, 1_000_000, approximated=True)
    assert ledger.estimated_usd == Decimal("5.00")
    assert ledger.actual_usd == Decimal("15.00")
    assert ledger.total_usd == Decimal("20.00")
    first, second = ledger.to_list()
    assert (first["spec"], first["kind"], first["cost_usd"]) == (
        "openai-api|gpt-5.5",
        "estimated",
        5.0,
    )
    assert (second["kind"], second["tokens_approximated"]) == ("actual", True)
