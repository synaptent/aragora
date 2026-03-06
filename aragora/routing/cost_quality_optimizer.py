"""Cost-quality Pareto optimization for provider selection.

Computes the Pareto frontier across providers and selects the best
provider given a strategy, budget constraint, and quality floor.

Usage:
    optimizer = CostQualityOptimizer(metrics_store)
    best = optimizer.select_provider(SelectionStrategy.BALANCED, budget_remaining=10.0)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.routing.provider_metrics import ProviderMetrics, ProviderMetricsStore

logger = logging.getLogger(__name__)


class SelectionStrategy(str, Enum):
    """Strategy for selecting a provider."""

    COST_OPTIMIZED = "cost_optimized"
    QUALITY_OPTIMIZED = "quality_optimized"
    BALANCED = "balanced"
    PARETO = "pareto"


def pareto_frontier(providers: list[ProviderMetrics]) -> list[ProviderMetrics]:
    """Compute the Pareto frontier over cost vs quality.

    A provider is Pareto-optimal if no other provider is both cheaper
    (lower avg_cost_per_debate) AND higher quality (higher avg_quality_score).

    Args:
        providers: List of provider metrics to evaluate.

    Returns:
        List of non-dominated providers (the Pareto frontier),
        sorted by ascending cost.
    """
    if not providers:
        return []

    frontier: list[ProviderMetrics] = []
    for candidate in providers:
        dominated = False
        for other in providers:
            if other is candidate:
                continue
            # 'other' dominates 'candidate' if it's at least as good on both
            # dimensions and strictly better on at least one.
            other_cheaper_or_equal = other.avg_cost_per_debate <= candidate.avg_cost_per_debate
            other_better_or_equal_quality = other.avg_quality_score >= candidate.avg_quality_score
            strictly_better = (
                other.avg_cost_per_debate < candidate.avg_cost_per_debate
                or other.avg_quality_score > candidate.avg_quality_score
            )
            if other_cheaper_or_equal and other_better_or_equal_quality and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)

    frontier.sort(key=lambda m: m.avg_cost_per_debate)
    return frontier


class CostQualityOptimizer:
    """Selects providers using Pareto-optimal cost/quality analysis.

    Args:
        metrics_store: ProviderMetricsStore with recorded debate outcomes.
    """

    def __init__(self, metrics_store: ProviderMetricsStore) -> None:
        self._store = metrics_store

    def get_pareto_frontier(self) -> list[ProviderMetrics]:
        """Return the current Pareto frontier across all providers."""
        all_metrics = list(self._store.get_all_metrics().values())
        return pareto_frontier(all_metrics)

    def select_provider(
        self,
        strategy: SelectionStrategy = SelectionStrategy.BALANCED,
        budget_remaining: float | None = None,
        min_quality: float = 0.0,
        exclude_providers: set[str] | None = None,
    ) -> str | None:
        """Select the best provider given constraints.

        Args:
            strategy: Selection strategy to apply.
            budget_remaining: Optional remaining budget in USD.
                Providers whose avg_cost_per_debate exceeds this are excluded.
            min_quality: Minimum acceptable quality score (0-1).
            exclude_providers: Optional set of provider names to exclude.

        Returns:
            Provider name, or None if no provider meets the constraints.
        """
        all_metrics = list(self._store.get_all_metrics().values())
        if not all_metrics:
            return None

        # Filter by constraints
        candidates = [
            m for m in all_metrics if m.avg_quality_score >= min_quality and m.failure_rate < 1.0
        ]

        if exclude_providers:
            candidates = [m for m in candidates if m.provider_name not in exclude_providers]

        if budget_remaining is not None:
            candidates = [m for m in candidates if m.avg_cost_per_debate <= budget_remaining]

        if not candidates:
            return None

        if strategy == SelectionStrategy.COST_OPTIMIZED:
            best = min(candidates, key=lambda m: m.avg_cost_per_debate)
        elif strategy == SelectionStrategy.QUALITY_OPTIMIZED:
            best = max(candidates, key=lambda m: m.avg_quality_score)
        elif strategy == SelectionStrategy.PARETO:
            frontier = pareto_frontier(candidates)
            if not frontier:
                return None
            # Pick the provider with the best balanced score on the frontier
            best = max(
                frontier,
                key=lambda m: m.avg_quality_score - m.avg_cost_per_debate,
            )
        else:
            # BALANCED: score = quality / (cost + epsilon)
            # Avoids division by zero and balances both dimensions.
            epsilon = 0.001
            best = max(
                candidates,
                key=lambda m: m.avg_quality_score / (m.avg_cost_per_debate + epsilon),
            )

        return best.provider_name


__all__ = [
    "CostQualityOptimizer",
    "SelectionStrategy",
    "pareto_frontier",
]
