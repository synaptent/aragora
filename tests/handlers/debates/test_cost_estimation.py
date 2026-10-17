"""Tests for debate cost estimation handler (cost_estimation.py).

Tests the cost estimation functions covering:
- estimate_debate_cost() with various parameter combinations
- handle_estimate_cost() HTTP handler with validation
- Default model assignment and round-robin logic
- Provider pricing lookups and fallback behavior
- Boundary conditions, edge cases, and error paths

Covers: success paths, input validation, default handling, round-robin
model assignment, pricing breakdowns, unknown model fallback, handler
query parameter parsing, and error responses.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict[str, Any]:
    """Extract JSON body from a HandlerResult."""
    if result is None:
        return {}
    raw = result.body
    if isinstance(raw, bytes):
        return json.loads(raw.decode())
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _status(result) -> int:
    """Extract status code from a HandlerResult."""
    if result is None:
        return 0
    return result.status_code


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

from aragora.server.handlers.debates.cost_estimation import (
    AVG_INPUT_TOKENS_PER_ROUND,
    AVG_OUTPUT_TOKENS_PER_ROUND,
    DEFAULT_MODELS,
    MODEL_PROVIDER_MAP,
    SYSTEM_PROMPT_TOKENS,
    estimate_debate_cost,
    handle_estimate_cost,
)
from aragora.billing.usage import PROVIDER_PRICING, calculate_token_cost


# ===========================================================================
# Tests for estimate_debate_cost()
# ===========================================================================


class TestEstimateDebateCostDefaults:
    """Tests for estimate_debate_cost with default arguments."""

    def test_default_returns_dict(self):
        """Default call returns a dict with expected top-level keys."""
        result = estimate_debate_cost()
        assert isinstance(result, dict)
        assert "total_estimated_cost_usd" in result
        assert "breakdown_by_model" in result
        assert "assumptions" in result
        assert "num_agents" in result
        assert "num_rounds" in result

    def test_default_num_agents(self):
        """Default num_agents is 3."""
        result = estimate_debate_cost()
        assert result["num_agents"] == 3

    def test_default_num_rounds(self):
        """Default num_rounds is 9."""
        result = estimate_debate_cost()
        assert result["num_rounds"] == 9

    def test_default_breakdown_count(self):
        """Default has 3 breakdown entries (one per agent)."""
        result = estimate_debate_cost()
        assert len(result["breakdown_by_model"]) == 3

    def test_default_models_used(self):
        """Default models match DEFAULT_MODELS[:3]."""
        result = estimate_debate_cost()
        models = [b["model"] for b in result["breakdown_by_model"]]
        assert models == DEFAULT_MODELS[:3]

    def test_default_assumptions(self):
        """Assumptions section contains expected keys and values."""
        result = estimate_debate_cost()
        assumptions = result["assumptions"]
        assert assumptions["avg_input_tokens_per_round"] == AVG_INPUT_TOKENS_PER_ROUND
        assert assumptions["avg_output_tokens_per_round"] == AVG_OUTPUT_TOKENS_PER_ROUND
        assert assumptions["includes_system_prompt"] is True

    def test_total_cost_is_positive(self):
        """Total cost should be a positive number."""
        result = estimate_debate_cost()
        assert result["total_estimated_cost_usd"] > 0

    def test_total_cost_is_float(self):
        """Total cost is serialized as a float."""
        result = estimate_debate_cost()
        assert isinstance(result["total_estimated_cost_usd"], float)


class TestEstimateDebateCostAgentCount:
    """Tests for varying num_agents."""

    def test_single_agent(self):
        """1 agent produces 1 breakdown entry."""
        result = estimate_debate_cost(num_agents=1)
        assert result["num_agents"] == 1
        assert len(result["breakdown_by_model"]) == 1

    def test_two_agents(self):
        """2 agents produces 2 breakdown entries."""
        result = estimate_debate_cost(num_agents=2)
        assert len(result["breakdown_by_model"]) == 2

    def test_eight_agents(self):
        """8 agents produces 8 breakdown entries."""
        result = estimate_debate_cost(num_agents=8)
        assert result["num_agents"] == 8
        assert len(result["breakdown_by_model"]) == 8

    def test_more_agents_costs_more(self):
        """More agents should produce a higher total cost."""
        cost_3 = estimate_debate_cost(num_agents=3)["total_estimated_cost_usd"]
        cost_6 = estimate_debate_cost(num_agents=6)["total_estimated_cost_usd"]
        assert cost_6 > cost_3

    def test_agent_count_zero_default_models(self):
        """Zero agents results in zero cost and empty breakdown."""
        result = estimate_debate_cost(num_agents=0)
        assert result["num_agents"] == 0
        assert len(result["breakdown_by_model"]) == 0
        assert result["total_estimated_cost_usd"] == 0.0


class TestEstimateDebateCostRoundCount:
    """Tests for varying num_rounds."""

    def test_single_round(self):
        """1 round produces expected token estimates."""
        result = estimate_debate_cost(num_agents=1, num_rounds=1)
        entry = result["breakdown_by_model"][0]
        expected_input = SYSTEM_PROMPT_TOKENS + (AVG_INPUT_TOKENS_PER_ROUND * 1)
        expected_output = AVG_OUTPUT_TOKENS_PER_ROUND * 1
        assert entry["estimated_input_tokens"] == expected_input
        assert entry["estimated_output_tokens"] == expected_output

    def test_twelve_rounds(self):
        """12 rounds produces correct token estimates."""
        result = estimate_debate_cost(num_agents=1, num_rounds=12)
        entry = result["breakdown_by_model"][0]
        expected_input = SYSTEM_PROMPT_TOKENS + (AVG_INPUT_TOKENS_PER_ROUND * 12)
        expected_output = AVG_OUTPUT_TOKENS_PER_ROUND * 12
        assert entry["estimated_input_tokens"] == expected_input
        assert entry["estimated_output_tokens"] == expected_output

    def test_more_rounds_costs_more(self):
        """More rounds should increase total cost."""
        cost_3 = estimate_debate_cost(num_rounds=3)["total_estimated_cost_usd"]
        cost_9 = estimate_debate_cost(num_rounds=9)["total_estimated_cost_usd"]
        assert cost_9 > cost_3

    def test_num_rounds_in_result(self):
        """num_rounds is correctly reflected in result."""
        result = estimate_debate_cost(num_rounds=5)
        assert result["num_rounds"] == 5


class TestEstimateDebateCostModelTypes:
    """Tests for explicit model_types parameter."""

    def test_single_model_type(self):
        """Single model type assigned to all agents."""
        result = estimate_debate_cost(num_agents=3, model_types=["gpt-4o"])
        models = [b["model"] for b in result["breakdown_by_model"]]
        assert models == ["gpt-4o", "gpt-4o", "gpt-4o"]

    def test_model_round_robin(self):
        """Models are assigned round-robin when fewer than num_agents."""
        result = estimate_debate_cost(num_agents=5, model_types=["gpt-4o", "claude-sonnet-4"])
        models = [b["model"] for b in result["breakdown_by_model"]]
        assert models == [
            "gpt-4o",
            "claude-sonnet-4",
            "gpt-4o",
            "claude-sonnet-4",
            "gpt-4o",
        ]

    def test_exact_model_count(self):
        """Exact number of models matches agents one-to-one."""
        result = estimate_debate_cost(
            num_agents=3,
            model_types=["gpt-4o", "claude-sonnet-4", "gemini-pro"],
        )
        models = [b["model"] for b in result["breakdown_by_model"]]
        assert models == ["gpt-4o", "claude-sonnet-4", "gemini-pro"]

    def test_more_models_than_agents(self):
        """Excess models are ignored."""
        result = estimate_debate_cost(
            num_agents=2,
            model_types=["gpt-4o", "claude-sonnet-4", "gemini-pro"],
        )
        models = [b["model"] for b in result["breakdown_by_model"]]
        assert models == ["gpt-4o", "claude-sonnet-4"]

    def test_empty_model_list_uses_defaults(self):
        """Empty model list falls back to DEFAULT_MODELS."""
        result = estimate_debate_cost(num_agents=3, model_types=[])
        models = [b["model"] for b in result["breakdown_by_model"]]
        assert models == DEFAULT_MODELS[:3]

    def test_none_model_types_uses_defaults(self):
        """None model_types falls back to DEFAULT_MODELS."""
        result = estimate_debate_cost(num_agents=2, model_types=None)
        models = [b["model"] for b in result["breakdown_by_model"]]
        assert models == DEFAULT_MODELS[:2]


class TestEstimateDebateCostProviderLookup:
    """Tests for provider resolution and pricing."""

    def test_known_model_provider(self):
        """Known model returns correct provider."""
        result = estimate_debate_cost(num_agents=1, model_types=["claude-opus-4"])
        entry = result["breakdown_by_model"][0]
        assert entry["provider"] == "anthropic"

    def test_opus_48_dotted_form_resolves(self):
        """Dotted ``claude-opus-4.8`` must resolve like the hyphen form.

        Regression: the map added the hyphen ``claude-opus-4-8`` but omitted the
        dotted ``claude-opus-4.8``, so dotted cost requests silently fell through
        to the openrouter default — even though dotted ``claude-opus-4.7`` worked.
        """
        assert MODEL_PROVIDER_MAP["claude-opus-4.8"] == ("anthropic", "claude-opus-4.8")
        result = estimate_debate_cost(num_agents=1, model_types=["claude-opus-4.8"])
        entry = result["breakdown_by_model"][0]
        assert entry["provider"] == "anthropic"

    def test_opus_dotted_and_hyphen_forms_agree(self):
        """Dotted and hyphen Opus 4.8 forms resolve to the same provider tuple."""
        assert MODEL_PROVIDER_MAP["claude-opus-4.8"] == MODEL_PROVIDER_MAP["claude-opus-4-8"]
        dotted = estimate_debate_cost(num_agents=1, model_types=["claude-opus-4.8"])
        hyphen = estimate_debate_cost(num_agents=1, model_types=["claude-opus-4-8"])
        assert (
            dotted["breakdown_by_model"][0]["provider"]
            == hyphen["breakdown_by_model"][0]["provider"]
            == "anthropic"
        )

    def test_openai_provider(self):
        """gpt-4o resolves to openai provider."""
        result = estimate_debate_cost(num_agents=1, model_types=["gpt-4o"])
        entry = result["breakdown_by_model"][0]
        assert entry["provider"] == "openai"

    def test_google_provider(self):
        """gemini-pro resolves to google provider."""
        result = estimate_debate_cost(num_agents=1, model_types=["gemini-pro"])
        entry = result["breakdown_by_model"][0]
        assert entry["provider"] == "google"

    def test_deepseek_provider(self):
        """deepseek-v4-pro resolves to deepseek provider."""
        result = estimate_debate_cost(num_agents=1, model_types=["deepseek-v4-pro"])
        entry = result["breakdown_by_model"][0]
        assert entry["provider"] == "deepseek"

    def test_unknown_model_falls_back_to_openrouter(self):
        """Unknown model name falls back to openrouter provider."""
        result = estimate_debate_cost(num_agents=1, model_types=["unknown-model-xyz"])
        entry = result["breakdown_by_model"][0]
        assert entry["provider"] == "openrouter"
        assert entry["model"] == "unknown-model-xyz"

    def test_unknown_model_uses_default_pricing(self):
        """Unknown model uses openrouter default pricing."""
        result = estimate_debate_cost(num_agents=1, num_rounds=1, model_types=["unknown-model-xyz"])
        entry = result["breakdown_by_model"][0]
        # Default openrouter prices: 2.00 input, 8.00 output per 1M tokens
        input_tokens = SYSTEM_PROMPT_TOKENS + AVG_INPUT_TOKENS_PER_ROUND
        output_tokens = AVG_OUTPUT_TOKENS_PER_ROUND
        expected_input_cost = float(
            round((Decimal(input_tokens) / Decimal("1000000")) * Decimal("2.00"), 6)
        )
        expected_output_cost = float(
            round((Decimal(output_tokens) / Decimal("1000000")) * Decimal("8.00"), 6)
        )
        assert entry["input_cost_usd"] == expected_input_cost
        assert entry["output_cost_usd"] == expected_output_cost


class TestEstimateDebateCostBreakdownFields:
    """Tests for breakdown entry fields."""

    def test_breakdown_has_all_required_fields(self):
        """Each breakdown entry has all expected fields."""
        result = estimate_debate_cost(num_agents=1, num_rounds=1)
        entry = result["breakdown_by_model"][0]
        required_fields = {
            "model",
            "provider",
            "estimated_input_tokens",
            "estimated_output_tokens",
            "input_cost_usd",
            "output_cost_usd",
            "subtotal_usd",
        }
        assert required_fields.issubset(entry.keys())

    def test_costs_are_floats(self):
        """All cost fields are floats."""
        result = estimate_debate_cost(num_agents=1, num_rounds=1)
        entry = result["breakdown_by_model"][0]
        assert isinstance(entry["input_cost_usd"], float)
        assert isinstance(entry["output_cost_usd"], float)
        assert isinstance(entry["subtotal_usd"], float)

    def test_tokens_are_ints(self):
        """Token counts are integers."""
        result = estimate_debate_cost(num_agents=1, num_rounds=1)
        entry = result["breakdown_by_model"][0]
        assert isinstance(entry["estimated_input_tokens"], int)
        assert isinstance(entry["estimated_output_tokens"], int)

    def test_subtotal_equals_calculate_token_cost(self):
        """Subtotal matches calculate_token_cost for the same parameters."""
        result = estimate_debate_cost(num_agents=1, num_rounds=1, model_types=["gpt-4o"])
        entry = result["breakdown_by_model"][0]
        input_tokens = SYSTEM_PROMPT_TOKENS + AVG_INPUT_TOKENS_PER_ROUND
        output_tokens = AVG_OUTPUT_TOKENS_PER_ROUND
        expected_cost = calculate_token_cost("openai", "gpt-4o", input_tokens, output_tokens)
        assert entry["subtotal_usd"] == float(round(expected_cost, 6))

    def test_total_equals_sum_of_subtotals(self):
        """Total cost equals the sum of all subtotals."""
        result = estimate_debate_cost(num_agents=3, num_rounds=5)
        subtotal_sum = sum(b["subtotal_usd"] for b in result["breakdown_by_model"])
        # Allow for tiny float rounding differences
        assert abs(result["total_estimated_cost_usd"] - subtotal_sum) < 0.001


class TestEstimateDebateCostTokenCalculation:
    """Tests for token estimation math."""

    def test_input_tokens_formula(self):
        """Input tokens = SYSTEM_PROMPT + rounds * AVG_INPUT_PER_ROUND."""
        for rounds in [1, 3, 9, 12]:
            result = estimate_debate_cost(num_agents=1, num_rounds=rounds)
            entry = result["breakdown_by_model"][0]
            expected = SYSTEM_PROMPT_TOKENS + (AVG_INPUT_TOKENS_PER_ROUND * rounds)
            assert entry["estimated_input_tokens"] == expected, f"Failed for {rounds} rounds"

    def test_output_tokens_formula(self):
        """Output tokens = rounds * AVG_OUTPUT_PER_ROUND."""
        for rounds in [1, 3, 9, 12]:
            result = estimate_debate_cost(num_agents=1, num_rounds=rounds)
            entry = result["breakdown_by_model"][0]
            expected = AVG_OUTPUT_TOKENS_PER_ROUND * rounds
            assert entry["estimated_output_tokens"] == expected, f"Failed for {rounds} rounds"

    def test_all_agents_same_tokens_for_same_model(self):
        """All agents with the same model get identical token estimates."""
        result = estimate_debate_cost(num_agents=4, num_rounds=5, model_types=["gpt-4o"])
        entries = result["breakdown_by_model"]
        for entry in entries:
            assert entry["estimated_input_tokens"] == entries[0]["estimated_input_tokens"]
            assert entry["estimated_output_tokens"] == entries[0]["estimated_output_tokens"]


class TestEstimateDebateCostPricingAccuracy:
    """Tests verifying pricing matches PROVIDER_PRICING."""

    @pytest.mark.parametrize(
        "model,provider,price_key",
        [
            ("claude-opus-4", "anthropic", "claude-opus-4"),
            ("claude-opus-4-8", "anthropic", "claude-opus-4.8"),
            ("claude-opus-4-7", "anthropic", "claude-opus-4.7"),
            ("claude-sonnet-4", "anthropic", "claude-sonnet-4"),
            ("claude-sonnet-4-6", "anthropic", "claude-sonnet-4.6"),
            ("gpt-4o", "openai", "gpt-4o"),
            ("gpt-4o-mini", "openai", "gpt-4o-mini"),
            ("gemini-pro", "google", "gemini-pro"),
            ("deepseek-v4-pro", "deepseek", "deepseek-v4-pro"),
        ],
    )
    def test_known_model_input_cost(self, model, provider, price_key):
        """Input cost matches PROVIDER_PRICING for each known model."""
        result = estimate_debate_cost(num_agents=1, num_rounds=1, model_types=[model])
        entry = result["breakdown_by_model"][0]
        input_tokens = SYSTEM_PROMPT_TOKENS + AVG_INPUT_TOKENS_PER_ROUND
        price = PROVIDER_PRICING[provider][price_key]
        expected = float(round((Decimal(input_tokens) / Decimal("1000000")) * price, 6))
        assert entry["input_cost_usd"] == expected

    @pytest.mark.parametrize(
        "model,provider,price_key",
        [
            ("claude-opus-4", "anthropic", "claude-opus-4"),
            ("claude-opus-4-8", "anthropic", "claude-opus-4.8"),
            ("claude-opus-4-7", "anthropic", "claude-opus-4.7"),
            ("claude-sonnet-4", "anthropic", "claude-sonnet-4"),
            ("claude-sonnet-4-6", "anthropic", "claude-sonnet-4.6"),
            ("gpt-4o", "openai", "gpt-4o"),
            ("gpt-4o-mini", "openai", "gpt-4o-mini"),
            ("gemini-pro", "google", "gemini-pro"),
            ("deepseek-v4-pro", "deepseek", "deepseek-v4-pro"),
        ],
    )
    def test_known_model_output_cost(self, model, provider, price_key):
        """Output cost matches PROVIDER_PRICING for each known model."""
        result = estimate_debate_cost(num_agents=1, num_rounds=1, model_types=[model])
        entry = result["breakdown_by_model"][0]
        output_tokens = AVG_OUTPUT_TOKENS_PER_ROUND
        price = PROVIDER_PRICING[provider][f"{price_key}-output"]
        expected = float(round((Decimal(output_tokens) / Decimal("1000000")) * price, 6))
        assert entry["output_cost_usd"] == expected


class TestEstimateDebateCostModelProviderMap:
    """Tests for MODEL_PROVIDER_MAP completeness."""

    def test_all_default_models_in_map(self):
        """All DEFAULT_MODELS have entries in MODEL_PROVIDER_MAP."""
        for model in DEFAULT_MODELS:
            assert model in MODEL_PROVIDER_MAP, f"{model} missing from MODEL_PROVIDER_MAP"

    def test_model_provider_map_values_are_tuples(self):
        """All values in MODEL_PROVIDER_MAP are (provider, model_key) tuples."""
        for model, value in MODEL_PROVIDER_MAP.items():
            assert isinstance(value, tuple), f"{model}: expected tuple, got {type(value)}"
            assert len(value) == 2, f"{model}: expected 2-tuple, got {len(value)}"

    def test_all_map_providers_in_pricing(self):
        """All providers in MODEL_PROVIDER_MAP exist in PROVIDER_PRICING."""
        for model, (provider, _) in MODEL_PROVIDER_MAP.items():
            assert provider in PROVIDER_PRICING, (
                f"{model}: provider {provider} not in PROVIDER_PRICING"
            )

    def test_default_models_map_to_their_own_provider(self):
        """Each DEFAULT_MODELS entry must resolve to its own real billing
        provider, not the "openrouter" catch-all (frontier-model-refresh,
        2026-09-04 review fix round 1, item 2): claude-fable-5-1 is
        anthropic, gpt-6-astra is openai, gemini-3.1-pro-preview is google.
        """
        expected = {
            "claude-fable-5-1": "anthropic",
            "gpt-6-astra": "openai",
            "gemini-3.1-pro-preview": "google",
        }
        assert set(DEFAULT_MODELS) == set(expected), (
            "DEFAULT_MODELS changed; update this test's expectations"
        )
        for model in DEFAULT_MODELS:
            provider, _ = MODEL_PROVIDER_MAP[model]
            assert provider == expected[model], (
                f"{model}: expected provider {expected[model]!r}, got {provider!r}"
            )
            assert provider != "openrouter", f"{model} incorrectly fell back to openrouter"


class TestEstimateDebateCostDefaultModelsUseCatalogRates:
    """Regression (frontier-model-refresh Task 6): PROVIDER_PRICING used to
    carry no claude-fable-5-1 / gpt-6-astra rows at all, so
    calculate_token_cost() silently fell through to its hardcoded $2/$8
    default bucket for two of the three DEFAULT_MODELS -- underpricing them
    ~6x. The aragora.models.pricing_mirror generator now merges catalog
    rows into PROVIDER_PRICING, so every DEFAULT_MODELS entry must price
    off its own catalog input/output rate.
    """

    def _catalog_subtotal(self, model: str, num_rounds: int) -> float:
        from aragora.models.catalog import CATALOG, by_any_id

        spec = by_any_id(model) or CATALOG[model]
        input_tokens = SYSTEM_PROMPT_TOKENS + AVG_INPUT_TOKENS_PER_ROUND * num_rounds
        output_tokens = AVG_OUTPUT_TOKENS_PER_ROUND * num_rounds
        cost = (Decimal(input_tokens) / Decimal("1000000")) * Decimal(str(spec.input_per_mtok)) + (
            Decimal(output_tokens) / Decimal("1000000")
        ) * Decimal(str(spec.output_per_mtok))
        return float(round(cost, 6))

    def _default_bucket_subtotal(self, num_rounds: int) -> float:
        """The $2/$8 fallback calculate_token_cost() applies when a model
        has no PROVIDER_PRICING row at all -- what every DEFAULT_MODELS
        entry used to silently price at before this table was wired to the
        catalog."""
        input_tokens = SYSTEM_PROMPT_TOKENS + AVG_INPUT_TOKENS_PER_ROUND * num_rounds
        output_tokens = AVG_OUTPUT_TOKENS_PER_ROUND * num_rounds
        cost = (Decimal(input_tokens) / Decimal("1000000")) * Decimal("2.00") + (
            Decimal(output_tokens) / Decimal("1000000")
        ) * Decimal("8.00")
        return float(round(cost, 6))

    def test_default_models_price_off_catalog_rates_not_default_bucket(self):
        """Every DEFAULT_MODELS subtotal must equal catalog-rate arithmetic
        and must differ from the $2/$8 default-bucket result."""
        num_rounds = 9
        result = estimate_debate_cost(
            num_agents=len(DEFAULT_MODELS), num_rounds=num_rounds, model_types=DEFAULT_MODELS
        )
        default_subtotal = self._default_bucket_subtotal(num_rounds)
        breakdown = {entry["model"]: entry for entry in result["breakdown_by_model"]}
        assert set(breakdown) == set(DEFAULT_MODELS)
        for model in DEFAULT_MODELS:
            expected = self._catalog_subtotal(model, num_rounds)
            subtotal = breakdown[model]["subtotal_usd"]
            assert subtotal == expected, (
                f"{model}: subtotal {subtotal} != catalog-rate arithmetic {expected}"
            )
            assert subtotal != default_subtotal, (
                f"{model}: subtotal {subtotal} equals the $2/$8 default-bucket result "
                f"{default_subtotal} -- it fell through to the default rate instead of "
                "the catalog rate"
            )

    def test_fable_5_1_and_astra_use_10_50_arithmetic(self):
        """Fable 5.1 and gpt-6-astra are both $10/$50 per MTok in the
        catalog (frontier-model-refresh) -- pin the exact numbers so a
        future PROVIDER_PRICING regression is caught even if the catalog
        rate itself later changes for one but not the other."""
        num_rounds = 9
        result = estimate_debate_cost(
            num_agents=2,
            num_rounds=num_rounds,
            model_types=["claude-fable-5-1", "gpt-6-astra"],
        )
        input_tokens = SYSTEM_PROMPT_TOKENS + AVG_INPUT_TOKENS_PER_ROUND * num_rounds
        output_tokens = AVG_OUTPUT_TOKENS_PER_ROUND * num_rounds
        expected = float(
            round(
                (Decimal(input_tokens) / Decimal("1000000")) * Decimal("10.00")
                + (Decimal(output_tokens) / Decimal("1000000")) * Decimal("50.00"),
                6,
            )
        )
        for entry in result["breakdown_by_model"]:
            assert entry["subtotal_usd"] == expected


# ===========================================================================
# Tests for handle_estimate_cost()
# ===========================================================================


class TestHandleEstimateCostSuccess:
    """Tests for successful handle_estimate_cost calls."""

    def test_default_call_returns_200(self):
        """Default parameters return 200 status."""
        result = handle_estimate_cost()
        assert _status(result) == 200

    def test_default_call_returns_json(self):
        """Default parameters return valid JSON body."""
        result = handle_estimate_cost()
        body = _body(result)
        assert "total_estimated_cost_usd" in body

    def test_explicit_valid_params(self):
        """Explicit valid params return 200 with correct data."""
        result = handle_estimate_cost(num_agents=4, num_rounds=6)
        assert _status(result) == 200
        body = _body(result)
        assert body["num_agents"] == 4
        assert body["num_rounds"] == 6

    def test_model_types_str_parsed(self):
        """Comma-separated model_types_str is correctly parsed."""
        result = handle_estimate_cost(
            num_agents=2,
            num_rounds=3,
            model_types_str="gpt-4o,claude-sonnet-4",
        )
        assert _status(result) == 200
        body = _body(result)
        models = [b["model"] for b in body["breakdown_by_model"]]
        assert models == ["gpt-4o", "claude-sonnet-4"]

    def test_model_types_with_spaces(self):
        """model_types_str with spaces is trimmed correctly."""
        result = handle_estimate_cost(
            num_agents=2,
            num_rounds=1,
            model_types_str=" gpt-4o , claude-sonnet-4 ",
        )
        assert _status(result) == 200
        body = _body(result)
        models = [b["model"] for b in body["breakdown_by_model"]]
        assert models == ["gpt-4o", "claude-sonnet-4"]

    def test_empty_model_types_str(self):
        """Empty model_types_str uses defaults."""
        result = handle_estimate_cost(num_agents=3, num_rounds=3, model_types_str="")
        assert _status(result) == 200
        body = _body(result)
        models = [b["model"] for b in body["breakdown_by_model"]]
        assert models == DEFAULT_MODELS[:3]


class TestHandleEstimateCostValidation:
    """Tests for input validation in handle_estimate_cost."""

    def test_num_agents_zero_returns_400(self):
        """num_agents=0 returns 400."""
        result = handle_estimate_cost(num_agents=0)
        assert _status(result) == 400
        body = _body(result)
        assert "num_agents" in body.get("error", "")

    def test_num_agents_negative_returns_400(self):
        """Negative num_agents returns 400."""
        result = handle_estimate_cost(num_agents=-1)
        assert _status(result) == 400

    def test_num_agents_nine_returns_400(self):
        """num_agents=9 (above max 8) returns 400."""
        result = handle_estimate_cost(num_agents=9)
        assert _status(result) == 400
        body = _body(result)
        assert "num_agents" in body.get("error", "")

    def test_num_agents_boundary_one(self):
        """num_agents=1 (lower boundary) returns 200."""
        result = handle_estimate_cost(num_agents=1)
        assert _status(result) == 200

    def test_num_agents_boundary_eight(self):
        """num_agents=8 (upper boundary) returns 200."""
        result = handle_estimate_cost(num_agents=8)
        assert _status(result) == 200

    def test_num_rounds_zero_returns_400(self):
        """num_rounds=0 returns 400."""
        result = handle_estimate_cost(num_rounds=0)
        assert _status(result) == 400
        body = _body(result)
        assert "num_rounds" in body.get("error", "")

    def test_num_rounds_negative_returns_400(self):
        """Negative num_rounds returns 400."""
        result = handle_estimate_cost(num_rounds=-5)
        assert _status(result) == 400

    def test_num_rounds_thirteen_returns_400(self):
        """num_rounds=13 (above max 12) returns 400."""
        result = handle_estimate_cost(num_rounds=13)
        assert _status(result) == 400
        body = _body(result)
        assert "num_rounds" in body.get("error", "")

    def test_num_rounds_boundary_one(self):
        """num_rounds=1 (lower boundary) returns 200."""
        result = handle_estimate_cost(num_rounds=1)
        assert _status(result) == 200

    def test_num_rounds_boundary_twelve(self):
        """num_rounds=12 (upper boundary) returns 200."""
        result = handle_estimate_cost(num_rounds=12)
        assert _status(result) == 200

    def test_too_many_model_types_returns_400(self):
        """More than 8 model types returns 400."""
        models = ",".join(["gpt-4o"] * 9)
        result = handle_estimate_cost(model_types_str=models)
        assert _status(result) == 400
        body = _body(result)
        assert "8" in body.get("error", "")

    def test_exactly_eight_model_types_ok(self):
        """Exactly 8 model types is allowed."""
        models = ",".join(["gpt-4o"] * 8)
        result = handle_estimate_cost(num_agents=8, model_types_str=models)
        assert _status(result) == 200

    def test_both_invalid_agents_and_rounds(self):
        """When both are invalid, num_agents is checked first."""
        result = handle_estimate_cost(num_agents=0, num_rounds=0)
        assert _status(result) == 400
        body = _body(result)
        assert "num_agents" in body.get("error", "")

    def test_model_types_str_with_only_commas(self):
        """model_types_str with only commas/spaces produces empty list (uses defaults)."""
        result = handle_estimate_cost(num_agents=2, num_rounds=2, model_types_str=", , , ")
        assert _status(result) == 200
        body = _body(result)
        # Empty after strip -> uses defaults
        models = [b["model"] for b in body["breakdown_by_model"]]
        assert models == DEFAULT_MODELS[:2]


class TestHandleEstimateCostContentType:
    """Tests for response content type."""

    def test_success_content_type_json(self):
        """Success response has application/json content type."""
        result = handle_estimate_cost()
        assert result.content_type == "application/json"

    def test_error_content_type_json(self):
        """Error response has application/json content type."""
        result = handle_estimate_cost(num_agents=0)
        assert result.content_type == "application/json"


class TestEstimateDebateCostCostComparisons:
    """Tests comparing costs across different models and configurations."""

    def test_opus_costs_more_than_sonnet(self):
        """Claude opus should be more expensive than sonnet."""
        opus = estimate_debate_cost(num_agents=1, num_rounds=1, model_types=["claude-opus-4"])
        sonnet = estimate_debate_cost(num_agents=1, num_rounds=1, model_types=["claude-sonnet-4"])
        assert opus["total_estimated_cost_usd"] > sonnet["total_estimated_cost_usd"]

    def test_gpt4o_costs_more_than_mini(self):
        """GPT-4o should be more expensive than GPT-4o-mini."""
        full = estimate_debate_cost(num_agents=1, num_rounds=1, model_types=["gpt-4o"])
        mini = estimate_debate_cost(num_agents=1, num_rounds=1, model_types=["gpt-4o-mini"])
        assert full["total_estimated_cost_usd"] > mini["total_estimated_cost_usd"]

    def test_deepseek_cheaper_than_frontier_models(self):
        """DeepSeek V4 Pro should be cheaper than frontier models."""
        deepseek = estimate_debate_cost(num_agents=1, num_rounds=1, model_types=["deepseek-v4-pro"])
        for model in ["claude-opus-4", "claude-sonnet-4", "gpt-4o", "gemini-pro"]:
            other = estimate_debate_cost(num_agents=1, num_rounds=1, model_types=[model])
            assert deepseek["total_estimated_cost_usd"] <= other["total_estimated_cost_usd"], (
                f"DeepSeek should be <= {model}"
            )

    def test_cost_scales_linearly_with_agents(self):
        """Cost should roughly double when agents double (same model)."""
        cost_2 = estimate_debate_cost(num_agents=2, num_rounds=1, model_types=["gpt-4o"])[
            "total_estimated_cost_usd"
        ]
        cost_4 = estimate_debate_cost(num_agents=4, num_rounds=1, model_types=["gpt-4o"])[
            "total_estimated_cost_usd"
        ]
        assert abs(cost_4 - 2 * cost_2) < 0.0001


class TestEstimateDebateCostEdgeCases:
    """Edge cases and unusual inputs."""

    def test_large_round_count(self):
        """Large round count still produces valid output (no overflow)."""
        result = estimate_debate_cost(num_agents=1, num_rounds=100)
        assert result["total_estimated_cost_usd"] > 0
        assert result["num_rounds"] == 100

    def test_single_agent_single_round_minimal(self):
        """Minimal configuration: 1 agent, 1 round."""
        result = estimate_debate_cost(num_agents=1, num_rounds=1)
        assert len(result["breakdown_by_model"]) == 1
        assert result["total_estimated_cost_usd"] > 0

    def test_model_types_with_duplicates(self):
        """Duplicate models in model_types are preserved."""
        result = estimate_debate_cost(
            num_agents=3,
            model_types=["gpt-4o", "gpt-4o", "gpt-4o"],
        )
        models = [b["model"] for b in result["breakdown_by_model"]]
        assert models == ["gpt-4o", "gpt-4o", "gpt-4o"]

    def test_mixed_known_and_unknown_models(self):
        """Mix of known and unknown models resolves correctly."""
        result = estimate_debate_cost(
            num_agents=3,
            model_types=["gpt-4o", "unknown-llm", "claude-sonnet-4"],
        )
        providers = [b["provider"] for b in result["breakdown_by_model"]]
        assert providers == ["openai", "openrouter", "anthropic"]


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_avg_input_tokens_positive(self):
        assert AVG_INPUT_TOKENS_PER_ROUND > 0

    def test_avg_output_tokens_positive(self):
        assert AVG_OUTPUT_TOKENS_PER_ROUND > 0

    def test_system_prompt_tokens_positive(self):
        assert SYSTEM_PROMPT_TOKENS > 0

    def test_default_models_non_empty(self):
        assert len(DEFAULT_MODELS) > 0

    def test_model_provider_map_non_empty(self):
        assert len(MODEL_PROVIDER_MAP) > 0

    def test_exports(self):
        """__all__ exports the expected symbols."""
        from aragora.server.handlers.debates import cost_estimation

        assert "estimate_debate_cost" in cost_estimation.__all__
        assert "handle_estimate_cost" in cost_estimation.__all__


class TestBreakdownSumsToSubtotal:
    """``input_cost_usd + output_cost_usd`` must equal ``subtotal_usd``.

    Finding O-P2 on #9989: the breakdown re-derived the two halves from the
    flat ``PROVIDER_PRICING`` rows while the subtotal came from the
    tier-aware pricer, so past a model's documented long-context threshold
    the user-facing breakdown contradicted its own total -- 150 rounds of
    ``gpt-6-astra`` reported a 15.01 subtotal against a 9.005 breakdown.
    """

    @staticmethod
    def _assert_identity(result: dict) -> None:
        for row in result["breakdown_by_model"]:
            assert row["input_cost_usd"] + row["output_cost_usd"] == pytest.approx(
                row["subtotal_usd"], abs=1e-6
            ), row

    def test_long_context_tier_breakdown_sums(self):
        """The exact case from the finding: past gpt-6-astra's 272k input
        threshold, where the tiered rate and the flat row diverge."""
        from aragora.server.handlers.debates.cost_estimation import estimate_debate_cost

        result = estimate_debate_cost(num_agents=1, num_rounds=150, model_types=["gpt-6-astra"])
        row = result["breakdown_by_model"][0]
        # The tier really is engaged here -- otherwise this proves nothing.
        flat_input_cost = row["estimated_input_tokens"] / 1_000_000 * 10.0
        assert row["input_cost_usd"] > flat_input_cost
        self._assert_identity(result)

    def test_short_debate_breakdown_sums(self):
        from aragora.server.handlers.debates.cost_estimation import estimate_debate_cost

        self._assert_identity(estimate_debate_cost(num_agents=3, num_rounds=3))

    def test_every_default_model_breakdown_sums(self):
        from aragora.server.handlers.debates.cost_estimation import (
            DEFAULT_MODELS,
            estimate_debate_cost,
        )

        for model in DEFAULT_MODELS:
            for rounds in (1, 9, 150):
                self._assert_identity(
                    estimate_debate_cost(num_agents=1, num_rounds=rounds, model_types=[model])
                )

    def test_unknown_model_breakdown_sums(self):
        """The openrouter/default fallback path holds the identity too."""
        from aragora.server.handlers.debates.cost_estimation import estimate_debate_cost

        self._assert_identity(
            estimate_debate_cost(num_agents=1, num_rounds=9, model_types=["not-a-real-model"])
        )

    def test_total_equals_the_sum_of_the_subtotals(self):
        from aragora.server.handlers.debates.cost_estimation import estimate_debate_cost

        result = estimate_debate_cost(num_agents=3, num_rounds=150)
        assert sum(r["subtotal_usd"] for r in result["breakdown_by_model"]) == pytest.approx(
            result["total_estimated_cost_usd"], abs=1e-3
        )
