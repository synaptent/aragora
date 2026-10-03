"""
Debate Cost Estimation Handler.

Provides a pre-creation cost estimate based on agent count, round count,
and model selection. Uses PROVIDER_PRICING from the billing module.
"""

import logging
from decimal import Decimal
from typing import Any

from aragora.billing.usage import PROVIDER_PRICING, calculate_token_cost
from aragora.server.handlers.base import HandlerResult, error_response, json_response

logger = logging.getLogger(__name__)

# Average token estimates per round per agent (based on historical data)
AVG_INPUT_TOKENS_PER_ROUND = 2000  # system prompt + context + prior messages
AVG_OUTPUT_TOKENS_PER_ROUND = 800  # agent response
SYSTEM_PROMPT_TOKENS = 500  # one-time system prompt overhead per agent

# Model -> (provider, model_key) mapping for cost lookup
MODEL_PROVIDER_MAP: dict[str, tuple[str, str]] = {
    "claude-fable-5": ("anthropic", "claude-fable-5"),
    "anthropic/claude-fable-5": ("anthropic", "claude-fable-5"),
    "claude-opus-5": ("anthropic", "claude-opus-5"),
    "anthropic/claude-opus-5": ("anthropic", "claude-opus-5"),
    "claude-opus-4": ("anthropic", "claude-opus-4"),
    "claude-opus-4.8": ("anthropic", "claude-opus-4.8"),
    "claude-opus-4-8": ("anthropic", "claude-opus-4.8"),
    "claude-opus-4.7": ("anthropic", "claude-opus-4.7"),
    "claude-opus-4-7": ("anthropic", "claude-opus-4.7"),
    "claude-sonnet-4": ("anthropic", "claude-sonnet-4"),
    "claude-sonnet-4.6": ("anthropic", "claude-sonnet-4.6"),
    "claude-sonnet-4-6": ("anthropic", "claude-sonnet-4.6"),
    "gpt-5.6-sol": ("openai", "gpt-5.6-sol"),
    "openai/gpt-5.6-sol": ("openai", "gpt-5.6-sol"),
    "openai/gpt-5.5": ("openai", "gpt-5.5"),
    "gpt-5.5": ("openai", "gpt-5.5"),
    "gpt-4o": ("openai", "gpt-4o"),
    "gpt-4o-mini": ("openai", "gpt-4o-mini"),
    "gemini-pro": ("google", "gemini-pro"),
    "deepseek-v4-pro": ("deepseek", "deepseek-v4-pro"),
    "deepseek-v3": ("deepseek", "deepseek-v3"),
}

# Default models when none specified
DEFAULT_MODELS = ["claude-opus-5", "gpt-4o", "gemini-pro"]


def estimate_debate_cost(
    num_agents: int = 3,
    num_rounds: int = 9,
    model_types: list[str] | None = None,
) -> dict[str, Any]:
    """Estimate the cost of a debate.

    Args:
        num_agents: Number of participating agents.
        num_rounds: Number of debate rounds.
        model_types: List of model names. If fewer than num_agents,
                     models are assigned round-robin.

    Returns:
        Cost estimation dict with total, per-model breakdown, and assumptions.
    """
    if model_types is None or len(model_types) == 0:
        model_types = DEFAULT_MODELS[:num_agents]

    # Assign models to agents round-robin
    agent_models = []
    for i in range(num_agents):
        agent_models.append(model_types[i % len(model_types)])

    breakdown = []
    total_cost = Decimal("0")

    for model in agent_models:
        provider, model_key = MODEL_PROVIDER_MAP.get(model, ("openrouter", "default"))

        input_tokens = SYSTEM_PROMPT_TOKENS + (AVG_INPUT_TOKENS_PER_ROUND * num_rounds)
        output_tokens = AVG_OUTPUT_TOKENS_PER_ROUND * num_rounds

        cost = calculate_token_cost(provider, model_key, input_tokens, output_tokens)

        # Decompose into input/output cost for the breakdown
        provider_prices = PROVIDER_PRICING.get(provider, PROVIDER_PRICING["openrouter"])
        input_key = model_key if model_key in provider_prices else "default"
        output_key = (
            f"{model_key}-output" if f"{model_key}-output" in provider_prices else "default-output"
        )
        input_price = provider_prices.get(input_key, Decimal("2.00"))
        output_price = provider_prices.get(output_key, Decimal("8.00"))

        input_cost = (Decimal(input_tokens) / Decimal("1000000")) * input_price
        output_cost = (Decimal(output_tokens) / Decimal("1000000")) * output_price

        breakdown.append(
            {
                "model": model,
                "provider": provider,
                "estimated_input_tokens": input_tokens,
                "estimated_output_tokens": output_tokens,
                "input_cost_usd": float(round(input_cost, 6)),
                "output_cost_usd": float(round(output_cost, 6)),
                "subtotal_usd": float(round(cost, 6)),
            }
        )
        total_cost += cost

    return {
        "total_estimated_cost_usd": float(round(total_cost, 4)),
        "breakdown_by_model": breakdown,
        "assumptions": {
            "avg_input_tokens_per_round": AVG_INPUT_TOKENS_PER_ROUND,
            "avg_output_tokens_per_round": AVG_OUTPUT_TOKENS_PER_ROUND,
            "includes_system_prompt": True,
        },
        "num_agents": num_agents,
        "num_rounds": num_rounds,
    }


def handle_estimate_cost(
    num_agents: int = 3,
    num_rounds: int = 9,
    model_types_str: str = "",
) -> HandlerResult:
    """HTTP handler for GET /api/v1/debates/estimate-cost.

    Args:
        num_agents: From query param.
        num_rounds: From query param.
        model_types_str: Comma-separated model types from query param.
    """
    if not 1 <= num_agents <= 8:
        return error_response("num_agents must be between 1 and 8", 400)
    if not 1 <= num_rounds <= 12:
        return error_response("num_rounds must be between 1 and 12", 400)

    model_types: list[str] | None = None
    if model_types_str:
        model_types = [m.strip() for m in model_types_str.split(",") if m.strip()]
        if len(model_types) > 8:
            return error_response("At most 8 model types allowed", 400)

    result = estimate_debate_cost(num_agents, num_rounds, model_types)
    return json_response(result)


__all__ = ["estimate_debate_cost", "handle_estimate_cost"]
