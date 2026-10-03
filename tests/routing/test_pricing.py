"""Tests for catalog-backed routing pricing (aragora.routing.pricing).

Covers the fallback ladder (canonical catalog -> legacy table -> conservative
nonzero default), the never-$0 guarantee for frontier pins, and the wiring
into the Pareto optimizer and the decision-stakes router's rationale.

The canonical catalog (``aragora.models``, PR #9355) is now a hard dependency
of this tree: ``aragora.routing.provider_config`` imports it at module load
(catalog projection, #9364), and ``_use_no_catalog`` below uses the real
``by_any_id`` to strip projected rows. The patchable resolver seam is still
used to simulate fake- and no-catalog worlds for the fallback-ladder tests;
``test_real_catalog_when_available`` runs unconditionally against the real
catalog.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from aragora.routing import pricing
from aragora.routing.cost_quality_optimizer import CostQualityOptimizer, SelectionStrategy
from aragora.routing.decision_stakes_router import DecisionStakesRouter
from aragora.routing.pricing import (
    PRICING_SOURCE_CATALOG,
    PRICING_SOURCE_DEFAULT,
    PRICING_SOURCE_LEGACY_TABLE,
    ResolvedPricing,
    effective_cost_per_debate,
    estimate_model_cost_usd,
    is_frontier_family,
    resolve_model_pricing,
    with_effective_costs,
)
from aragora.routing.provider_config import PROVIDER_PRICING
from aragora.routing.provider_metrics import ProviderMetrics, ProviderMetricsStore


@dataclass(frozen=True)
class _FakeSpec:
    """Duck-typed stand-in for aragora.models.ModelSpec pricing fields."""

    input_per_mtok: float
    output_per_mtok: float


_FAKE_CATALOG = {
    "claude-fable-5": _FakeSpec(input_per_mtok=10.00, output_per_mtok=50.00),
    "gpt-5.6-sol": _FakeSpec(input_per_mtok=5.00, output_per_mtok=30.00),
}


@pytest.fixture(autouse=True)
def _fresh_pricing_state(monkeypatch: pytest.MonkeyPatch):
    """Isolate the cached catalog resolver and the warn-once set per test."""
    monkeypatch.setattr(pricing, "_by_any_id", pricing._UNSET)
    monkeypatch.setattr(pricing, "_warned_defaults", set())
    yield


def _use_fake_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pricing, "_by_any_id", _FAKE_CATALOG.get)


def _use_no_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pricing, "_by_any_id", None)
    # The catalog projection (#9364) bakes catalog rows into PROVIDER_PRICING
    # at import time. A no-catalog world has no projected rows either, so
    # restrict the rung-2 legacy table to its hand-maintained rows.
    from aragora.models import by_any_id as _real_by_any_id

    monkeypatch.setattr(
        pricing,
        "PROVIDER_PRICING",
        {k: v for k, v in pricing.PROVIDER_PRICING.items() if _real_by_any_id(k) is None},
    )


# ---------------------------------------------------------------------------
# Rung 1: canonical catalog
# ---------------------------------------------------------------------------


class TestCatalogRung:
    def test_known_catalog_model_resolves_nonzero_real_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_fake_catalog(monkeypatch)
        resolved = resolve_model_pricing("claude-fable-5")
        assert resolved.source == PRICING_SOURCE_CATALOG
        assert resolved.input_per_mtok == pytest.approx(10.00)
        assert resolved.output_per_mtok == pytest.approx(50.00)
        # 1M input + 1M output at $10/$50 per MTok = $60
        assert resolved.estimate_cost_usd(1_000_000, 1_000_000) == pytest.approx(60.0)

    def test_catalog_takes_precedence_over_legacy_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Legacy table has claude-opus-4; give the catalog a diverging price
        # and verify the catalog wins.
        monkeypatch.setattr(
            pricing,
            "_by_any_id",
            {"claude-opus-4": _FakeSpec(input_per_mtok=6.00, output_per_mtok=27.00)}.get,
        )
        resolved = resolve_model_pricing("claude-opus-4")
        assert resolved.source == PRICING_SOURCE_CATALOG
        assert resolved.input_per_mtok == pytest.approx(6.00)

    def test_real_catalog_when_available(self) -> None:
        """Against the real aragora.models (a hard dependency since #9364)."""
        import aragora.models as models

        for canonical_id, spec in models.CATALOG.items():
            resolved = resolve_model_pricing(canonical_id)
            assert resolved.source == PRICING_SOURCE_CATALOG
            assert resolved.input_per_mtok == pytest.approx(spec.input_per_mtok)
            assert resolved.output_per_mtok == pytest.approx(spec.output_per_mtok)
            assert resolved.estimate_debate_cost_usd() > 0.0


# ---------------------------------------------------------------------------
# Rung 2: legacy table
# ---------------------------------------------------------------------------


class TestLegacyTableRung:
    def test_legacy_model_falls_back_to_table(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_no_catalog(monkeypatch)
        resolved = resolve_model_pricing("claude-opus-4")
        table = PROVIDER_PRICING["claude-opus-4"]
        assert resolved.source == PRICING_SOURCE_LEGACY_TABLE
        assert resolved.input_per_1k == pytest.approx(table.input_cost_per_1k)
        assert resolved.output_per_1k == pytest.approx(table.output_cost_per_1k)
        assert resolved.estimate_debate_cost_usd() > 0.0

    def test_catalog_miss_falls_through_to_table(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_fake_catalog(monkeypatch)  # fake catalog has no gpt-4o-mini
        resolved = resolve_model_pricing("gpt-4o-mini")
        assert resolved.source == PRICING_SOURCE_LEGACY_TABLE


# ---------------------------------------------------------------------------
# Rung 3: conservative default (never $0)
# ---------------------------------------------------------------------------


class TestConservativeDefaultRung:
    def test_unknown_model_falls_back_with_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _use_no_catalog(monkeypatch)
        with caplog.at_level(logging.WARNING, logger="aragora.routing.pricing"):
            resolved = resolve_model_pricing("totally-unknown-model")
        assert resolved.source == PRICING_SOURCE_DEFAULT
        assert resolved.input_per_mtok > 0.0
        assert resolved.output_per_mtok > 0.0
        assert any("totally-unknown-model" in r.message for r in caplog.records)

    def test_default_warning_logged_once_per_model(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _use_no_catalog(monkeypatch)
        with caplog.at_level(logging.WARNING, logger="aragora.routing.pricing"):
            resolve_model_pricing("totally-unknown-model")
            resolve_model_pricing("totally-unknown-model")
        warnings = [r for r in caplog.records if "totally-unknown-model" in r.message]
        assert len(warnings) == 1

    @pytest.mark.parametrize(
        "frontier_pin",
        ["claude-fable-5", "gpt-5.6-sol", "grok-4.5", "gemini-3.0-pro", "openai/gpt-6"],
    )
    def test_frontier_pin_never_scores_zero(
        self, monkeypatch: pytest.MonkeyPatch, frontier_pin: str
    ) -> None:
        """The July-9 bug: frontier pins unknown to the stale table cost $0."""
        _use_no_catalog(monkeypatch)
        assert is_frontier_family(frontier_pin)
        resolved = resolve_model_pricing(frontier_pin)
        assert resolved.input_per_mtok >= pricing.DEFAULT_FRONTIER_INPUT_PER_MTOK
        assert resolved.output_per_mtok >= pricing.DEFAULT_FRONTIER_OUTPUT_PER_MTOK
        assert estimate_model_cost_usd(frontier_pin, 2000, 1000) > 0.0

    def test_frontier_default_exceeds_unknown_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_no_catalog(monkeypatch)
        frontier = resolve_model_pricing("claude-fable-5")
        unknown = resolve_model_pricing("mystery-model-9000")
        assert frontier.estimate_debate_cost_usd() > unknown.estimate_debate_cost_usd()
        assert unknown.estimate_debate_cost_usd() > 0.0


# ---------------------------------------------------------------------------
# Metrics normalization (effective costs)
# ---------------------------------------------------------------------------


class TestEffectiveCosts:
    def test_observed_cost_passes_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_no_catalog(monkeypatch)
        m = ProviderMetrics(provider_name="claude-fable-5", avg_cost_per_debate=0.42)
        assert effective_cost_per_debate(m) == pytest.approx(0.42)
        (out,) = with_effective_costs([m])
        assert out is m
        assert out.cost_estimated is False

    def test_zero_cost_is_replaced_by_priced_estimate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_fake_catalog(monkeypatch)
        m = ProviderMetrics(
            provider_name="claude-fable-5",
            avg_cost_per_debate=0.0,
            avg_quality_score=0.9,
        )
        (out,) = with_effective_costs([m])
        # 2K input at $10/MTok + 1K output at $50/MTok = 0.02 + 0.05
        assert out.avg_cost_per_debate == pytest.approx(0.07)
        assert out.cost_estimated is True
        # Original entry is not mutated.
        assert m.avg_cost_per_debate == 0.0


# ---------------------------------------------------------------------------
# Pareto optimizer wiring
# ---------------------------------------------------------------------------


def _store_with_free_frontier_pin() -> ProviderMetricsStore:
    """A store where a frontier pin was recorded with the default cost=0.0.

    Before the catalog wiring, 'claude-fable-5' entered every cost comparison
    at $0 and dominated cost-optimized selection.
    """
    store = ProviderMetricsStore()
    for _ in range(5):
        store.record_debate_outcome("claude-fable-5", cost=0.0, quality=0.90)
        store.record_debate_outcome("deepseek-chat", cost=0.005, quality=0.60)
    return store


class TestOptimizerWiring:
    def test_frontier_pin_never_enters_frontier_at_zero_cost(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_no_catalog(monkeypatch)
        optimizer = CostQualityOptimizer(_store_with_free_frontier_pin())
        for m in optimizer.get_pareto_frontier():
            assert m.avg_cost_per_debate > 0.0

    def test_cost_optimized_does_not_pick_unpriced_frontier_pin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_no_catalog(monkeypatch)
        optimizer = CostQualityOptimizer(_store_with_free_frontier_pin())
        selected = optimizer.select_provider(SelectionStrategy.COST_OPTIMIZED)
        assert selected == "deepseek-chat"

    def test_candidates_carry_estimated_cost_marker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_no_catalog(monkeypatch)
        optimizer = CostQualityOptimizer(_store_with_free_frontier_pin())
        by_name = {m.provider_name: m for m in optimizer.get_candidates()}
        assert by_name["claude-fable-5"].avg_cost_per_debate > 0.0
        assert by_name["claude-fable-5"].cost_estimated is True
        assert by_name["deepseek-chat"].cost_estimated is False

    def test_budget_excludes_estimated_frontier_cost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_no_catalog(monkeypatch)
        optimizer = CostQualityOptimizer(_store_with_free_frontier_pin())
        # Frontier default estimate is 0.035/debate; a 0.01 budget excludes it
        # (previously it passed every budget at $0).
        candidates = optimizer.get_candidates(budget_remaining=0.01)
        assert {m.provider_name for m in candidates} == {"deepseek-chat"}


# ---------------------------------------------------------------------------
# Decision-stakes router rationale wiring
# ---------------------------------------------------------------------------


class TestDecisionStakesWiring:
    def test_rationale_records_real_cost_and_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_no_catalog(monkeypatch)
        router = DecisionStakesRouter(CostQualityOptimizer(_store_with_free_frontier_pin()))
        rationale = router.route(2)

        considered = {m["provider"]: m for m in rationale.models_considered}
        assert considered["claude-fable-5"]["avg_cost_per_debate"] > 0.0
        assert considered["claude-fable-5"]["cost_source"] == "estimated_from_pricing"
        assert considered["deepseek-chat"]["cost_source"] == "observed"

    def test_rationale_frontier_context_has_no_zero_costs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_no_catalog(monkeypatch)
        router = DecisionStakesRouter(CostQualityOptimizer(_store_with_free_frontier_pin()))
        rationale = router.route(4)
        for entry in rationale.frontier_before_constraints:
            assert entry["avg_cost_per_debate"] > 0.0

    def test_receipt_payload_keeps_cost_unrecorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Estimates feed the tradeoff; the receipt must not claim spend."""
        _use_no_catalog(monkeypatch)
        router = DecisionStakesRouter(CostQualityOptimizer(_store_with_free_frontier_pin()))
        payload = router.route(3).to_dict()
        assert payload["cost"]["recorded"] is False


# ---------------------------------------------------------------------------
# ResolvedPricing unit conversion
# ---------------------------------------------------------------------------


def test_resolved_pricing_unit_accessors() -> None:
    resolved = ResolvedPricing(
        model_id="x", input_per_mtok=10.0, output_per_mtok=50.0, source=PRICING_SOURCE_CATALOG
    )
    assert resolved.input_per_1k == pytest.approx(0.010)
    assert resolved.output_per_1k == pytest.approx(0.050)
    assert resolved.estimate_cost_usd(2000, 1000) == pytest.approx(0.07)
