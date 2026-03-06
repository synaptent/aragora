"""Provider pricing configuration and cost estimation.

Contains static pricing data for supported AI model providers
and utility functions for estimating debate costs.

Pricing is per 1M tokens (consistent with aragora.billing.usage).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderPricing:
    """Pricing and capabilities for a single provider/model combination."""

    provider_name: str
    model_name: str
    input_cost_per_1k: float  # USD per 1K input tokens
    output_cost_per_1k: float  # USD per 1K output tokens
    context_window: int  # Maximum context window in tokens
    supports_streaming: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "input_cost_per_1k": self.input_cost_per_1k,
            "output_cost_per_1k": self.output_cost_per_1k,
            "context_window": self.context_window,
            "supports_streaming": self.supports_streaming,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderPricing:
        """Deserialize from dictionary."""
        return cls(
            provider_name=data["provider_name"],
            model_name=data["model_name"],
            input_cost_per_1k=data["input_cost_per_1k"],
            output_cost_per_1k=data["output_cost_per_1k"],
            context_window=data["context_window"],
            supports_streaming=data.get("supports_streaming", True),
        )


# Current pricing as of March 2026, per 1K tokens.
# Source: provider pricing pages. Prices in USD.
PROVIDER_PRICING: dict[str, ProviderPricing] = {
    "claude-opus-4": ProviderPricing(
        provider_name="anthropic",
        model_name="claude-opus-4",
        input_cost_per_1k=0.005,
        output_cost_per_1k=0.025,
        context_window=200_000,
    ),
    "claude-sonnet-4": ProviderPricing(
        provider_name="anthropic",
        model_name="claude-sonnet-4",
        input_cost_per_1k=0.003,
        output_cost_per_1k=0.015,
        context_window=200_000,
    ),
    "gpt-4o": ProviderPricing(
        provider_name="openai",
        model_name="gpt-4o",
        input_cost_per_1k=0.0025,
        output_cost_per_1k=0.010,
        context_window=128_000,
    ),
    "gpt-4o-mini": ProviderPricing(
        provider_name="openai",
        model_name="gpt-4o-mini",
        input_cost_per_1k=0.00015,
        output_cost_per_1k=0.0006,
        context_window=128_000,
    ),
    "deepseek-r1": ProviderPricing(
        provider_name="deepseek",
        model_name="deepseek-r1",
        input_cost_per_1k=0.00028,
        output_cost_per_1k=0.00042,
        context_window=64_000,
    ),
    "deepseek-chat": ProviderPricing(
        provider_name="deepseek",
        model_name="deepseek-chat",
        input_cost_per_1k=0.00028,
        output_cost_per_1k=0.00042,
        context_window=64_000,
    ),
    "mistral-large": ProviderPricing(
        provider_name="mistral",
        model_name="mistral-large",
        input_cost_per_1k=0.002,
        output_cost_per_1k=0.006,
        context_window=128_000,
    ),
    "gemini-2.0-flash": ProviderPricing(
        provider_name="google",
        model_name="gemini-2.0-flash",
        input_cost_per_1k=0.0005,
        output_cost_per_1k=0.003,
        context_window=1_000_000,
        supports_streaming=True,
    ),
}


def get_estimated_cost(
    provider: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate cost for a given provider and token usage.

    Args:
        provider: Model key in PROVIDER_PRICING (e.g. "claude-opus-4").
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD. Returns 0.0 if provider is unknown.
    """
    pricing = PROVIDER_PRICING.get(provider)
    if pricing is None:
        return 0.0

    input_cost = (input_tokens / 1000.0) * pricing.input_cost_per_1k
    output_cost = (output_tokens / 1000.0) * pricing.output_cost_per_1k
    return input_cost + output_cost


def get_available_models() -> list[str]:
    """Return list of all model keys with known pricing."""
    return list(PROVIDER_PRICING.keys())


def get_cheapest_model() -> str:
    """Return the model key with the lowest combined cost per 1K tokens."""
    return min(
        PROVIDER_PRICING,
        key=lambda k: PROVIDER_PRICING[k].input_cost_per_1k
        + PROVIDER_PRICING[k].output_cost_per_1k,
    )


def get_models_within_budget(
    budget_per_debate: float,
    estimated_input_tokens: int = 2000,
    estimated_output_tokens: int = 1000,
) -> list[str]:
    """Return model keys whose estimated cost fits within a per-debate budget.

    Args:
        budget_per_debate: Maximum cost per debate in USD.
        estimated_input_tokens: Expected input tokens per debate.
        estimated_output_tokens: Expected output tokens per debate.

    Returns:
        List of model keys sorted by cost (cheapest first).
    """
    affordable: list[tuple[float, str]] = []
    for model_key, pricing in PROVIDER_PRICING.items():
        cost = get_estimated_cost(model_key, estimated_input_tokens, estimated_output_tokens)
        if cost <= budget_per_debate:
            affordable.append((cost, model_key))
    affordable.sort()
    return [model_key for _, model_key in affordable]


__all__ = [
    "ProviderPricing",
    "PROVIDER_PRICING",
    "get_estimated_cost",
    "get_available_models",
    "get_cheapest_model",
    "get_models_within_budget",
]
