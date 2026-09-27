"""Tests for decision-stakes routing (aragora.routing.decision_stakes_router)."""

from __future__ import annotations

from aragora.routing.cost_quality_optimizer import CostQualityOptimizer, SelectionStrategy
from aragora.routing.decision_stakes_router import (
    COST_EFFICIENT,
    FRONTIER,
    DecisionStakesRouter,
    RoutingRationale,
    policy_for_tier,
)
from aragora.routing.provider_metrics import ProviderMetrics


class _Store:
    """Minimal ProviderMetricsStore stand-in: the optimizer only reads metrics."""

    def __init__(self, metrics: list[ProviderMetrics]) -> None:
        self._m = {m.provider_name: m for m in metrics}

    def get_all_metrics(self) -> dict[str, ProviderMetrics]:
        return dict(self._m)


_METRICS = {
    "cheap": ProviderMetrics(
        provider_name="cheap",
        avg_cost_per_debate=0.01,
        avg_quality_score=0.40,
        failure_rate=0.0,
    ),
    "mid": ProviderMetrics(
        provider_name="mid",
        avg_cost_per_debate=0.10,
        avg_quality_score=0.75,
        failure_rate=0.0,
    ),
    "frontier": ProviderMetrics(
        provider_name="frontier",
        avg_cost_per_debate=1.00,
        avg_quality_score=0.95,
        failure_rate=0.0,
    ),
}


def _optimizer(*providers: str) -> CostQualityOptimizer:
    names = providers or tuple(_METRICS)
    return CostQualityOptimizer(_Store([_METRICS[n] for n in names]))


def test_policy_for_tier_classes() -> None:
    assert policy_for_tier(0).tier_class == COST_EFFICIENT
    assert policy_for_tier(2).tier_class == COST_EFFICIENT
    assert policy_for_tier(3).tier_class == FRONTIER
    assert policy_for_tier(4).tier_class == FRONTIER


def test_policy_for_tier_clamps_out_of_range() -> None:
    assert policy_for_tier(-5).tier_class == policy_for_tier(0).tier_class
    assert policy_for_tier(99) == policy_for_tier(4)


def test_min_quality_rises_with_stakes() -> None:
    qualities = [policy_for_tier(t).min_quality for t in range(5)]
    assert qualities == sorted(qualities)
    assert qualities[0] <= qualities[4]
    assert qualities != [qualities[0]] * 5  # actually rises


def test_low_tier_routes_to_cost_efficient_model() -> None:
    rationale = DecisionStakesRouter(_optimizer()).route(0)
    assert rationale.selected_provider == "cheap"
    assert rationale.tier_class == COST_EFFICIENT
    assert rationale.strategy == SelectionStrategy.COST_OPTIMIZED.value


def test_high_tier_escalates_to_frontier_model() -> None:
    rationale = DecisionStakesRouter(_optimizer()).route(4)
    assert rationale.selected_provider == "frontier"
    assert rationale.tier_class == FRONTIER
    assert rationale.strategy == SelectionStrategy.QUALITY_OPTIMIZED.value


def test_min_quality_floor_excludes_low_quality_at_high_tier() -> None:
    # Tier 4 requires min_quality 0.8; without "frontier" in the store,
    # nothing qualifies — and the reason blames the policy, not exclusions.
    rationale = DecisionStakesRouter(_optimizer("cheap", "mid")).route(4)
    assert rationale.selected_provider is None
    assert "no provider satisfied" in rationale.selection_reason
    assert "min_quality=0.8" in rationale.selection_reason
    assert rationale.excluded_providers == []
    assert rationale.models_considered == []  # nothing survived the floor


def test_exclusions_are_recorded_in_rationale() -> None:
    # Tier 4's floor (0.8) is met only by "frontier" (0.95); excluding it is
    # a caller constraint, and the audit record must say so — not blame the
    # policy alone.
    rationale = DecisionStakesRouter(_optimizer()).route(4, exclude_providers={"frontier"})
    assert rationale.selected_provider is None
    assert rationale.excluded_providers == ["frontier"]
    assert "excluded=['frontier']" in rationale.selection_reason
    assert "frontier" not in {m["provider"] for m in rationale.models_considered}


def test_exclusions_recorded_on_success_path_too() -> None:
    rationale = DecisionStakesRouter(_optimizer()).route(0, exclude_providers={"cheap"})
    assert rationale.selected_provider == "mid"  # cheapest remaining
    assert rationale.excluded_providers == ["cheap"]
    assert "excluded=['cheap']" in rationale.selection_reason
    assert "cheap" not in {m["provider"] for m in rationale.models_considered}


def test_no_exclusions_yields_empty_recorded_list() -> None:
    rationale = DecisionStakesRouter(_optimizer()).route(0)
    assert rationale.excluded_providers == []
    assert "excluded" not in rationale.selection_reason


def test_models_considered_is_the_post_constraint_candidate_set() -> None:
    # Tier 2 has min_quality 0.5 → "cheap" (0.40) was never in the choice set.
    rationale = DecisionStakesRouter(_optimizer()).route(2)
    assert {m["provider"] for m in rationale.models_considered} == {"mid", "frontier"}
    for entry in rationale.models_considered:
        assert {"provider", "avg_cost_per_debate", "avg_quality_score", "failure_rate"} <= set(
            entry
        )
    # The unconstrained Pareto frontier is still recorded, distinctly named.
    assert {m["provider"] for m in rationale.frontier_before_constraints} == {
        "cheap",
        "mid",
        "frontier",
    }


def test_models_considered_excludes_over_budget_providers() -> None:
    # Budget 0.05 rules out mid (0.10) and frontier (1.00).
    rationale = DecisionStakesRouter(_optimizer()).route(0, budget_remaining=0.05)
    assert {m["provider"] for m in rationale.models_considered} == {"cheap"}


def test_selected_provider_is_always_in_models_considered() -> None:
    for tier in range(5):
        rationale = DecisionStakesRouter(_optimizer()).route(tier)
        assert rationale.selected_provider in {m["provider"] for m in rationale.models_considered}


def test_out_of_range_tier_records_effective_and_requested_tier() -> None:
    rationale = DecisionStakesRouter(_optimizer()).route(99)
    assert rationale.decision_tier == 4  # the tier whose policy was applied
    assert rationale.requested_tier == 99  # the raw caller value
    assert rationale.tier_class == FRONTIER
    assert "tier 4" in rationale.selection_reason

    low = DecisionStakesRouter(_optimizer()).route(-3)
    assert low.decision_tier == 0
    assert low.requested_tier == -3


def test_in_range_tier_requested_equals_effective() -> None:
    rationale = DecisionStakesRouter(_optimizer()).route(3)
    assert rationale.decision_tier == 3
    assert rationale.requested_tier == 3


def test_budget_constraint_is_recorded_and_applied() -> None:
    # Budget 0.05 excludes mid (0.10) and frontier (1.00); only "cheap" remains.
    rationale = DecisionStakesRouter(_optimizer()).route(0, budget_remaining=0.05)
    assert rationale.budget_remaining == 0.05
    assert rationale.selected_provider == "cheap"


def test_to_dict_is_receipt_routing_block_shaped() -> None:
    import json

    rationale = DecisionStakesRouter(_optimizer()).route(3)
    payload = rationale.to_dict()
    # Canonical routing-rationale schema family (shared with auto_evidence_cycle).
    assert payload["record_type"] == "routing_rationale"
    assert payload["schema"] == "aragora.routing_rationale/v1"
    assert payload["status"] == "present"
    assert payload["selector"] == "decision_stakes_pareto"
    assert payload["pareto_optimizer_consulted"] is True
    assert payload["decision_tier"] == 3
    assert payload["requested_tier"] == 3
    assert payload["tier_class"] == FRONTIER
    assert "selection_reason" in payload
    assert payload["excluded_providers"] == []
    assert "models_considered" in payload
    assert "frontier_before_constraints" in payload
    # Cost stays honestly absent (metrics expectation, not observed spend).
    assert payload["cost"]["recorded"] is False
    assert payload["cost"]["total_usd"] is None
    json.dumps(payload)  # must be JSON-serializable for the receipt


def test_rationale_makes_no_unenforced_escalation_claim() -> None:
    # Tier 3-4 policy raises the quality floor and prefers quality-optimized
    # selection, but applies no frontier-model-family constraint — any
    # provider clearing the floor can be selected. The receipt must not
    # carry an outcome-shaped "escalated_to_frontier" claim the router
    # doesn't enforce; the applied policy class is already recorded
    # truthfully as tier_class.
    payload = DecisionStakesRouter(_optimizer()).route(4).to_dict()
    assert "escalated_to_frontier" not in payload
    assert payload["tier_class"] == FRONTIER


def test_empty_metrics_store_yields_no_selection_not_crash() -> None:
    router = DecisionStakesRouter(CostQualityOptimizer(_Store([])))
    rationale = router.route(1)
    assert isinstance(rationale, RoutingRationale)
    assert rationale.selected_provider is None
    assert rationale.models_considered == []


def test_broken_metrics_store_yields_recorded_no_selection_not_crash() -> None:
    class _BrokenStore:
        def get_all_metrics(self) -> dict[str, ProviderMetrics]:
            raise RuntimeError("metrics backend down")

    router = DecisionStakesRouter(CostQualityOptimizer(_BrokenStore()))
    rationale = router.route(2)
    assert rationale.selected_provider is None
    assert rationale.models_considered == []
    assert rationale.frontier_before_constraints == []
    assert "metrics unavailable" in rationale.selection_reason


def test_store_flaking_mid_route_yields_recorded_no_selection_not_crash() -> None:
    # get_pareto_frontier and get_candidates each do their own fresh
    # get_all_metrics read. A transient failure that hits only a later read
    # (e.g. a network-backed store) must still produce the honest
    # no-selection rationale, not escape route().
    class _FlakyStore(_Store):
        def __init__(self, metrics: list[ProviderMetrics], succeed_reads: int) -> None:
            super().__init__(metrics)
            self._reads_left = succeed_reads

        def get_all_metrics(self) -> dict[str, ProviderMetrics]:
            if self._reads_left <= 0:
                raise OSError("metrics backend connection reset")
            self._reads_left -= 1
            return super().get_all_metrics()

    store = _FlakyStore(list(_METRICS.values()), succeed_reads=1)
    router = DecisionStakesRouter(CostQualityOptimizer(store))
    rationale = router.route(2)
    assert rationale.selected_provider is None
    assert "metrics unavailable" in rationale.selection_reason


def test_selection_is_made_from_the_recorded_candidate_snapshot() -> None:
    # The audit rationale must never claim the selection was made from a
    # candidate set it wasn't: if the store's metrics change between the
    # get_candidates read and selection, the selection must still come from
    # the recorded models_considered snapshot, not a fresh read.
    class _MutatingStore(_Store):
        def __init__(self) -> None:
            super().__init__([_METRICS["cheap"], _METRICS["mid"]])
            self._reads = 0

        def get_all_metrics(self) -> dict[str, ProviderMetrics]:
            self._reads += 1
            if self._reads >= 3:  # any read after the recorded snapshot
                return {
                    "newcheap": ProviderMetrics(
                        provider_name="newcheap",
                        avg_cost_per_debate=0.001,
                        avg_quality_score=0.9,
                        failure_rate=0.0,
                    )
                }
            return super().get_all_metrics()

    rationale = DecisionStakesRouter(CostQualityOptimizer(_MutatingStore())).route(0)
    considered = {m["provider"] for m in rationale.models_considered}
    assert rationale.selected_provider in considered
    assert rationale.selected_provider == "cheap"  # tier 0 = cost-optimized


def test_stale_optimizer_cache_cannot_leak_into_the_rationale() -> None:
    # A prior select_provider call caches its result; route() must not
    # return that cached selection against a freshly-recorded candidate set
    # from a newer snapshot.
    store = _Store([_METRICS["cheap"], _METRICS["mid"]])
    optimizer = CostQualityOptimizer(store)
    # Warm the cache with the same constraint key tier 0 uses.
    assert optimizer.select_provider(strategy=SelectionStrategy.COST_OPTIMIZED) == "cheap"
    # Metrics move on: "cheap" disappears from the store.
    store._m = {"mid": _METRICS["mid"], "frontier": _METRICS["frontier"]}

    rationale = DecisionStakesRouter(optimizer).route(0)
    considered = {m["provider"] for m in rationale.models_considered}
    assert considered == {"mid", "frontier"}
    assert rationale.selected_provider in considered
    assert rationale.selected_provider == "mid"  # cheapest in the recorded snapshot
