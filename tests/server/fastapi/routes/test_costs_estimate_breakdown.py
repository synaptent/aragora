"""The ``POST /costs/estimate`` breakdown must sum to the total it reports.

2026-09-05 wave-2 re-review: the output half was costed with ``tokens_in=0``,
which asks ``calculate_token_cost`` for a FLAT-rate quote. Above a documented
long-context threshold the model is billed at its tiered rates, so the two
halves stopped adding up -- gpt-6-astra at 300k in / 10k out reported
6.00 + 0.50 against a real total of 6.75.

The route is exercised through its own handler coroutine rather than an HTTP
client so the assertion is about the arithmetic, not about routing or auth.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from aragora.billing.usage import calculate_token_cost
from aragora.server.fastapi.routes.costs import EstimateRequest, estimate_cost


def _estimate(model: str, tokens_per_round: int, rounds: int, agents: int, provider: str):
    body = EstimateRequest(
        model=model,
        rounds=rounds,
        agents=agents,
        estimated_tokens_per_round=tokens_per_round,
        provider=provider,
    )
    return asyncio.run(estimate_cost(request=MagicMock(), body=body, auth=MagicMock())).data


def test_breakdown_sums_to_total_at_a_long_context_input() -> None:
    # 300_000 input tokens: above gpt-6-astra's 272k long-context threshold.
    data = _estimate("gpt-6-astra", 100_000, 3, 1, "openai")
    assert data.tokens_input == 300_000
    total = data.estimated_cost_usd
    assert total == pytest.approx(
        float(calculate_token_cost("openai", "gpt-6-astra", 300_000, 90_000))
    )
    assert data.breakdown["input_cost"] + data.breakdown["output_cost"] == pytest.approx(
        total, abs=1e-9
    )
    # The input half is genuinely tiered, not flat.
    assert data.breakdown["input_cost"] == pytest.approx(300_000 / 1_000_000 * 20.0)


def test_breakdown_sums_to_total_below_the_threshold_too() -> None:
    data = _estimate("gpt-6-astra", 1_000, 3, 1, "openai")
    assert data.tokens_input == 3_000
    assert data.breakdown["input_cost"] + data.breakdown["output_cost"] == pytest.approx(
        data.estimated_cost_usd, abs=1e-9
    )
    # Flat rate below the threshold.
    assert data.breakdown["input_cost"] == pytest.approx(3_000 / 1_000_000 * 10.0)


def test_breakdown_sums_to_total_for_a_flat_priced_model() -> None:
    data = _estimate("claude-fable-5-1", 100_000, 3, 1, "anthropic")
    assert data.breakdown["input_cost"] + data.breakdown["output_cost"] == pytest.approx(
        data.estimated_cost_usd, abs=1e-9
    )
