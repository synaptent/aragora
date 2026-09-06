"""
Debate Cost Estimation Handler.

Provides a pre-creation cost estimate based on agent count, round count,
and model selection. Uses PROVIDER_PRICING from the billing module.
"""

import logging
from decimal import Decimal
from typing import Any

from aragora.billing.usage import PROVIDER_PRICING, calculate_token_cost
from aragora.config.model_pins import FABLE_51_DIRECT, GEMINI_31_PRO_DIRECT, GPT6_ASTRA_DIRECT
from aragora.models.catalog import CATALOG, ModelSpec
from aragora.server.handlers.base import HandlerResult, error_response, json_response

logger = logging.getLogger(__name__)

# Average token estimates per round per agent (based on historical data)
AVG_INPUT_TOKENS_PER_ROUND = 2000  # system prompt + context + prior messages
AVG_OUTPUT_TOKENS_PER_ROUND = 800  # agent response
SYSTEM_PROMPT_TOKENS = 500  # one-time system prompt overhead per agent

# Legacy hand-maintained model -> (provider, model_key) rows. Kept verbatim
# (not regenerated from the catalog) so callers/receipts already pinning
# these exact spellings keep resolving to the exact provider/model_key pair
# they always have -- several of these model_key spellings (e.g.
# "claude-opus-4.8", "gpt-4o", "gemini-pro") are the real keys billing's
# PROVIDER_PRICING tables index on, which the catalog's canonical ids don't
# always match (frontier-model-refresh, 2026-09-04: Task 6 handles
# migrating PROVIDER_PRICING itself; this table is not touched here).
_LEGACY_MODEL_PROVIDER_MAP: dict[str, tuple[str, str]] = {
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


def _pricing_provider(spec: ModelSpec) -> str:
    """Billing provider label for a catalog row: the same billing provider
    the legacy rows above used for that FAMILY, not necessarily the
    catalog's own ``provider`` field.

    ``ModelSpec.provider`` records how a row is *reached* (e.g.
    deepseek-v4-pro-0813's ``provider`` is "openrouter" because that is its
    only modeled transport), which is not always the same thing as which
    billing family it belongs to -- the legacy "deepseek-v4-pro" row above
    was always billed as "deepseek", and deepseek-v4-pro-0813 is the same
    family. So this keys off ``spec.family`` (the pretraining-lineage
    grouping) instead: when the family itself names a PROVIDER_PRICING
    bucket, use it; otherwise fall back to "openrouter", which has a
    documented default-rate bucket.

    Every family a catalog row carries now names a real bucket:
    ``aragora.models.pricing_mirror._bucketed`` emits each row under its
    family as well as its provider (2026-09-05 merge-gate fix wave, finding
    O-P2c on #9989). Before that, the family bucket existed only for the
    families the LEGACY hand-written table happened to name, so
    ``deepseek-v4-pro-0813`` resolved to the "deepseek" bucket and then
    silently fell back to the $2/$8 default because the catalog rate had
    been emitted under "openrouter" instead. The "openrouter" fallback
    below is retained for a row with no ``family`` at all.
    """
    return spec.family if spec.family in PROVIDER_PRICING else "openrouter"


# Model -> (provider, model_key) mapping for cost lookup. Built from every
# catalog spelling (canonical/direct/openrouter/alias) so any current or
# legacy/retired model resolves to a real provider, then the legacy rows
# above are layered on top unchanged so old receipts still resolve exactly
# as they always have (frontier-model-refresh, 2026-09-04).
MODEL_PROVIDER_MAP: dict[str, tuple[str, str]] = {
    **{
        spelling: (_pricing_provider(spec), spec.canonical_id)
        for spec in CATALOG.values()
        for spelling in spec.all_ids()
    },
    **_LEGACY_MODEL_PROVIDER_MAP,
}

# Default models when none specified.
DEFAULT_MODELS = [FABLE_51_DIRECT, GPT6_ASTRA_DIRECT, GEMINI_31_PRO_DIRECT]


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

        # Decompose into input/output cost for the breakdown. The two halves
        # MUST sum to the subtotal, so both come from the same tier-aware
        # pricer the subtotal did. Reading the flat PROVIDER_PRICING rows
        # directly ignored the long-context tier: a 150-round debate on
        # gpt-6-astra (past its 272k threshold) reported subtotal 15.01
        # against an input+output of 9.005 -- a user-facing breakdown that
        # contradicted its own total (finding O-P2 on #9989). Deriving the
        # output half by subtraction makes the identity hold by construction
        # for every model, tiered or flat, exactly as the wave-3 fix to
        # aragora/server/fastapi/routes/costs.py does.
        input_cost = calculate_token_cost(provider, model_key, input_tokens, 0)
        output_cost = cost - input_cost

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
