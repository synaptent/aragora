"""Tests for Smart Provider Routing Phase 1.

Covers:
- ProviderMetrics / ProviderMetricsStore
- Pareto frontier computation
- CostQualityOptimizer provider selection
- ProviderPricing / get_estimated_cost
- ProviderRouter fallback and metrics-based selection
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from aragora.routing.cost_quality_optimizer import (
    CostQualityOptimizer,
    SelectionStrategy,
    pareto_frontier,
)
from aragora.routing.provider_config import (
    PROVIDER_PRICING,
    ProviderPricing,
    get_cheapest_model,
    get_estimated_cost,
    get_models_within_budget,
)
from aragora.routing.provider_metrics import ProviderMetrics, ProviderMetricsStore
from aragora.routing.provider_router import (
    DEFAULT_PROVIDER_ORDER,
    MIN_DEBATES_FOR_METRICS,
    ProviderRouter,
)


# ---------------------------------------------------------------------------
# ProviderMetrics tests
# ---------------------------------------------------------------------------


class TestProviderMetrics:
    """Tests for ProviderMetrics dataclass."""

    def test_to_dict_from_dict_roundtrip(self) -> None:
        metrics = ProviderMetrics(
            provider_name="anthropic",
            total_debates=10,
            total_cost=1.5,
            avg_cost_per_debate=0.15,
            avg_quality_score=0.85,
            consensus_rate=0.7,
            failure_rate=0.1,
            p95_latency_seconds=3.2,
            last_updated="2026-03-06T00:00:00+00:00",
        )
        d = metrics.to_dict()
        restored = ProviderMetrics.from_dict(d)
        assert restored.provider_name == "anthropic"
        assert restored.total_debates == 10
        assert restored.avg_quality_score == pytest.approx(0.85)
        assert restored.p95_latency_seconds == pytest.approx(3.2)

    def test_from_dict_defaults(self) -> None:
        restored = ProviderMetrics.from_dict({"provider_name": "openai"})
        assert restored.total_debates == 0
        assert restored.avg_quality_score == 0.0


# ---------------------------------------------------------------------------
# ProviderMetricsStore tests
# ---------------------------------------------------------------------------


class TestProviderMetricsStore:
    """Tests for ProviderMetricsStore recording and aggregation."""

    def test_record_and_get_metrics(self) -> None:
        store = ProviderMetricsStore()
        store.record_debate_outcome("anthropic", cost=0.10, quality=0.9, latency=2.0)
        store.record_debate_outcome("anthropic", cost=0.20, quality=0.8, latency=3.0)

        m = store.get_metrics("anthropic")
        assert m is not None
        assert m.total_debates == 2
        assert m.total_cost == pytest.approx(0.30)
        assert m.avg_cost_per_debate == pytest.approx(0.15)
        assert m.avg_quality_score == pytest.approx(0.85)

    def test_get_metrics_unknown_provider(self) -> None:
        store = ProviderMetricsStore()
        assert store.get_metrics("nonexistent") is None

    def test_consensus_and_failure_rates(self) -> None:
        store = ProviderMetricsStore()
        store.record_debate_outcome("openai", consensus_reached=True)
        store.record_debate_outcome("openai", consensus_reached=True)
        store.record_debate_outcome("openai", consensus_reached=False, failed=True)

        m = store.get_metrics("openai")
        assert m is not None
        assert m.consensus_rate == pytest.approx(2.0 / 3.0)
        assert m.failure_rate == pytest.approx(1.0 / 3.0)

    def test_get_all_metrics(self) -> None:
        store = ProviderMetricsStore()
        store.record_debate_outcome("anthropic", cost=0.1, quality=0.9)
        store.record_debate_outcome("openai", cost=0.2, quality=0.8)

        all_m = store.get_all_metrics()
        assert "anthropic" in all_m
        assert "openai" in all_m
        assert len(all_m) == 2

    def test_get_top_providers(self) -> None:
        store = ProviderMetricsStore()
        store.record_debate_outcome("cheap", cost=0.01, quality=0.5)
        store.record_debate_outcome("quality", cost=0.50, quality=0.95)
        store.record_debate_outcome("mid", cost=0.10, quality=0.75)

        top_quality = store.get_top_providers("avg_quality_score", n=2)
        assert len(top_quality) == 2
        assert top_quality[0].provider_name == "quality"

        cheapest = store.get_top_providers("avg_cost_per_debate", n=2)
        assert cheapest[0].provider_name == "cheap"

    def test_persistence_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "metrics.json"
            store = ProviderMetricsStore(persist_path=path)
            store.record_debate_outcome("anthropic", cost=0.10, quality=0.9, latency=2.0)
            store.record_debate_outcome("anthropic", cost=0.20, quality=0.8, latency=3.0)

            # Verify file was written
            assert path.exists()
            data = json.loads(path.read_text())
            assert "anthropic" in data

            # Load into new store
            store2 = ProviderMetricsStore(persist_path=path)
            m = store2.get_metrics("anthropic")
            assert m is not None
            assert m.total_debates == 2
            assert m.avg_cost_per_debate == pytest.approx(0.15)

    def test_p95_latency(self) -> None:
        store = ProviderMetricsStore()
        # Record 20 debates with latencies 1..20
        for i in range(1, 21):
            store.record_debate_outcome("test", latency=float(i))

        m = store.get_metrics("test")
        assert m is not None
        # P95 of [1..20]: index = int(20 * 0.95) = 19, clamped to 19 => value 20.0
        assert m.p95_latency_seconds == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Pareto frontier tests
# ---------------------------------------------------------------------------


class TestParetoFrontier:
    """Tests for Pareto frontier computation."""

    def test_empty_input(self) -> None:
        assert pareto_frontier([]) == []

    def test_single_provider(self) -> None:
        m = ProviderMetrics(provider_name="only", avg_cost_per_debate=0.1, avg_quality_score=0.8)
        result = pareto_frontier([m])
        assert len(result) == 1
        assert result[0].provider_name == "only"

    def test_dominated_provider_excluded(self) -> None:
        """A provider that is both more expensive and lower quality is excluded."""
        good = ProviderMetrics(
            provider_name="good", avg_cost_per_debate=0.05, avg_quality_score=0.9
        )
        bad = ProviderMetrics(provider_name="bad", avg_cost_per_debate=0.10, avg_quality_score=0.7)
        result = pareto_frontier([good, bad])
        assert len(result) == 1
        assert result[0].provider_name == "good"

    def test_two_non_dominated_providers(self) -> None:
        """Cheap-low-quality and expensive-high-quality are both on the frontier."""
        cheap = ProviderMetrics(
            provider_name="cheap", avg_cost_per_debate=0.01, avg_quality_score=0.5
        )
        quality = ProviderMetrics(
            provider_name="quality", avg_cost_per_debate=0.20, avg_quality_score=0.95
        )
        result = pareto_frontier([cheap, quality])
        assert len(result) == 2
        names = {m.provider_name for m in result}
        assert names == {"cheap", "quality"}

    def test_three_providers_mixed(self) -> None:
        """Three providers where one is dominated."""
        cheap = ProviderMetrics(
            provider_name="cheap", avg_cost_per_debate=0.02, avg_quality_score=0.6
        )
        mid = ProviderMetrics(provider_name="mid", avg_cost_per_debate=0.10, avg_quality_score=0.7)
        quality = ProviderMetrics(
            provider_name="quality", avg_cost_per_debate=0.15, avg_quality_score=0.95
        )
        result = pareto_frontier([cheap, mid, quality])
        # mid is dominated by quality (quality is higher quality and
        # cheap is cheaper), but mid is NOT dominated by cheap alone
        # since mid has higher quality. And mid is NOT dominated by
        # quality alone since mid is cheaper. So mid is actually
        # non-dominated. Let's verify.
        names = {m.provider_name for m in result}
        # cheap: not dominated (cheapest)
        # mid: is there someone cheaper AND better quality? cheap is cheaper
        #   but worse quality. quality is better quality but more expensive.
        #   So mid is NOT dominated.
        # quality: not dominated (best quality)
        assert names == {"cheap", "mid", "quality"}

    def test_frontier_sorted_by_cost(self) -> None:
        providers = [
            ProviderMetrics(provider_name="b", avg_cost_per_debate=0.20, avg_quality_score=0.9),
            ProviderMetrics(provider_name="a", avg_cost_per_debate=0.05, avg_quality_score=0.6),
        ]
        result = pareto_frontier(providers)
        assert result[0].provider_name == "a"
        assert result[1].provider_name == "b"


# ---------------------------------------------------------------------------
# CostQualityOptimizer tests
# ---------------------------------------------------------------------------


class TestCostQualityOptimizer:
    """Tests for CostQualityOptimizer provider selection."""

    def _make_store(self) -> ProviderMetricsStore:
        store = ProviderMetricsStore()
        # cheap provider: low cost, medium quality
        for _ in range(5):
            store.record_debate_outcome("cheap", cost=0.02, quality=0.60)
        # quality provider: high cost, high quality
        for _ in range(5):
            store.record_debate_outcome("quality", cost=0.30, quality=0.95)
        # balanced provider: medium cost, good quality
        for _ in range(5):
            store.record_debate_outcome("balanced", cost=0.08, quality=0.80)
        # failing provider
        for _ in range(5):
            store.record_debate_outcome("failing", cost=0.05, quality=0.10, failed=True)
        return store

    def test_cost_optimized_selects_cheapest(self) -> None:
        store = self._make_store()
        optimizer = CostQualityOptimizer(store)
        result = optimizer.select_provider(SelectionStrategy.COST_OPTIMIZED)
        assert result == "cheap"

    def test_quality_optimized_selects_best_quality(self) -> None:
        store = self._make_store()
        optimizer = CostQualityOptimizer(store)
        result = optimizer.select_provider(SelectionStrategy.QUALITY_OPTIMIZED)
        assert result == "quality"

    def test_balanced_favors_value(self) -> None:
        store = self._make_store()
        optimizer = CostQualityOptimizer(store)
        result = optimizer.select_provider(SelectionStrategy.BALANCED)
        # balanced or cheap should win (best quality/cost ratio)
        assert result in {"cheap", "balanced"}

    def test_budget_constraint_filters(self) -> None:
        store = self._make_store()
        optimizer = CostQualityOptimizer(store)
        result = optimizer.select_provider(
            SelectionStrategy.QUALITY_OPTIMIZED, budget_remaining=0.05
        )
        # quality provider costs 0.30, should be excluded
        assert result != "quality"

    def test_min_quality_filters(self) -> None:
        store = self._make_store()
        optimizer = CostQualityOptimizer(store)
        result = optimizer.select_provider(SelectionStrategy.COST_OPTIMIZED, min_quality=0.7)
        # cheap provider has 0.60 quality, should be excluded
        assert result in {"balanced", "quality"}

    def test_no_candidates_returns_none(self) -> None:
        store = ProviderMetricsStore()
        optimizer = CostQualityOptimizer(store)
        assert optimizer.select_provider() is None

    def test_pareto_strategy(self) -> None:
        store = self._make_store()
        optimizer = CostQualityOptimizer(store)
        result = optimizer.select_provider(SelectionStrategy.PARETO)
        # Should pick from the Pareto frontier
        assert result is not None
        frontier_names = {m.provider_name for m in optimizer.get_pareto_frontier()}
        assert result in frontier_names

    def test_exclude_providers_filters_candidates(self) -> None:
        store = self._make_store()
        optimizer = CostQualityOptimizer(store)
        result = optimizer.select_provider(
            SelectionStrategy.QUALITY_OPTIMIZED,
            exclude_providers={"quality"},
        )
        assert result in {"balanced", "cheap"}

    def test_get_pareto_frontier(self) -> None:
        store = self._make_store()
        optimizer = CostQualityOptimizer(store)
        frontier = optimizer.get_pareto_frontier()
        assert len(frontier) >= 2
        # failing provider (low quality, not cheapest) should be excluded
        names = {m.provider_name for m in frontier}
        assert "failing" not in names


# ---------------------------------------------------------------------------
# ProviderPricing / get_estimated_cost tests
# ---------------------------------------------------------------------------


class TestProviderPricing:
    """Tests for provider pricing configuration."""

    def test_all_models_have_pricing(self) -> None:
        expected = {
            "claude-opus-4",
            "claude-sonnet-4",
            "gpt-4o",
            "gpt-4o-mini",
            "deepseek-r1",
            "deepseek-chat",
            "mistral-large",
            "gemini-2.0-flash",
        }
        assert expected.issubset(set(PROVIDER_PRICING.keys()))

    def test_pricing_fields(self) -> None:
        p = PROVIDER_PRICING["claude-opus-4"]
        assert p.provider_name == "anthropic"
        assert p.input_cost_per_1k > 0
        assert p.output_cost_per_1k > 0
        assert p.context_window > 0

    def test_get_estimated_cost(self) -> None:
        cost = get_estimated_cost("gpt-4o-mini", input_tokens=1000, output_tokens=1000)
        assert cost > 0
        assert cost < 0.01  # gpt-4o-mini is very cheap

    def test_get_estimated_cost_unknown_provider(self) -> None:
        cost = get_estimated_cost("nonexistent", input_tokens=1000, output_tokens=1000)
        assert cost == 0.0

    def test_get_cheapest_model(self) -> None:
        cheapest = get_cheapest_model()
        assert cheapest in PROVIDER_PRICING

    def test_get_models_within_budget(self) -> None:
        # With a generous budget, should get multiple models
        models = get_models_within_budget(1.0)
        assert len(models) > 0
        # With a tiny budget, may get fewer
        tiny = get_models_within_budget(0.0001)
        assert len(tiny) <= len(models)

    def test_to_dict_from_dict_roundtrip(self) -> None:
        original = PROVIDER_PRICING["claude-sonnet-4"]
        d = original.to_dict()
        restored = ProviderPricing.from_dict(d)
        assert restored == original


# ---------------------------------------------------------------------------
# ProviderRouter tests
# ---------------------------------------------------------------------------


class TestProviderRouter:
    """Tests for ProviderRouter selection logic."""

    def test_round_robin_with_no_data(self) -> None:
        router = ProviderRouter()
        providers = router.select_providers_for_debate(num_agents=3)
        assert len(providers) == 3
        # Should be from DEFAULT_PROVIDER_ORDER
        for p in providers:
            assert p in DEFAULT_PROVIDER_ORDER or p in PROVIDER_PRICING

    def test_round_robin_wraps_around(self) -> None:
        router = ProviderRouter()
        # Request more agents than available providers
        providers = router.select_providers_for_debate(num_agents=20)
        assert len(providers) == 20

    def test_metrics_based_selection_after_sufficient_data(self) -> None:
        router = ProviderRouter()
        # Record enough debates to exceed threshold
        for i in range(MIN_DEBATES_FOR_METRICS + 1):
            router.record_outcome("anthropic", cost=0.10, quality=0.9, latency=2.0)
            router.record_outcome("openai", cost=0.05, quality=0.7, latency=1.5)

        providers = router.select_providers_for_debate(
            num_agents=2, strategy=SelectionStrategy.QUALITY_OPTIMIZED
        )
        assert len(providers) == 2
        # With quality optimization, anthropic should be preferred
        assert "anthropic" in providers
        # Distinct providers should be preferred when alternatives exist
        assert len(set(providers)) == 2

    def test_record_outcome_delegates(self) -> None:
        router = ProviderRouter()
        router.record_outcome("test", cost=0.1, quality=0.8)
        m = router.metrics_store.get_metrics("test")
        assert m is not None
        assert m.total_debates == 1

    def test_get_status(self) -> None:
        router = ProviderRouter()
        status = router.get_status()
        assert status["has_sufficient_data"] is False
        assert status["total_debates_recorded"] == 0
        assert isinstance(status["providers_tracked"], list)
        assert isinstance(status["pareto_frontier"], list)

    def test_budget_constraint_propagated(self) -> None:
        router = ProviderRouter()
        for _ in range(MIN_DEBATES_FOR_METRICS + 1):
            router.record_outcome("expensive", cost=100.0, quality=0.9)
            router.record_outcome("cheap", cost=0.01, quality=0.6)

        # With very tight budget, expensive should be excluded
        providers = router.select_providers_for_debate(num_agents=1, budget=0.05)
        assert len(providers) == 1
        assert providers[0] != "expensive"

    def test_persistence_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "router_metrics.json")
            router = ProviderRouter(persist_path=path)
            router.record_outcome("anthropic", cost=0.1, quality=0.9)

            # Create new router from same path
            router2 = ProviderRouter(persist_path=path)
            m = router2.metrics_store.get_metrics("anthropic")
            assert m is not None
            assert m.total_debates == 1
