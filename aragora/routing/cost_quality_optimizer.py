"""Cost-quality Pareto optimization for provider selection.

Computes the Pareto frontier across providers and selects the best
provider given a strategy, budget constraint, and quality floor.

Usage:
    optimizer = CostQualityOptimizer(metrics_store)
    best = optimizer.select_provider(SelectionStrategy.BALANCED, budget_remaining=10.0)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from aragora.routing.pricing import with_effective_costs

if TYPE_CHECKING:
    from aragora.routing.provider_metrics import ProviderMetrics, ProviderMetricsStore

logger = logging.getLogger(__name__)

#: Default cache TTL for routing decisions (seconds).
DEFAULT_CACHE_TTL: float = 300.0  # 5 minutes


@dataclass
class _CacheEntry:
    """A cached routing decision with expiry."""

    provider_name: str | None
    expires_at: float


@dataclass
class RoutingCache:
    """TTL-based cache for provider routing decisions.

    Keyed by a tuple of (strategy, budget_remaining, min_quality, frozenset(exclude)).
    """

    ttl: float = DEFAULT_CACHE_TTL
    _entries: dict[tuple, _CacheEntry] = field(default_factory=dict)

    @staticmethod
    def _make_key(
        strategy: str,
        budget_remaining: float | None,
        min_quality: float,
        exclude_providers: frozenset[str] | None,
    ) -> tuple:
        return (strategy, budget_remaining, min_quality, exclude_providers or frozenset())

    def get(
        self,
        strategy: str,
        budget_remaining: float | None,
        min_quality: float,
        exclude_providers: frozenset[str] | None,
    ) -> tuple[bool, str | None]:
        """Return (hit, provider_name). hit=False means cache miss."""
        key = self._make_key(strategy, budget_remaining, min_quality, exclude_providers)
        entry = self._entries.get(key)
        if entry is not None and time.monotonic() < entry.expires_at:
            return True, entry.provider_name
        # Expired or missing — evict stale entry if present
        self._entries.pop(key, None)
        return False, None

    def put(
        self,
        strategy: str,
        budget_remaining: float | None,
        min_quality: float,
        exclude_providers: frozenset[str] | None,
        provider_name: str | None,
    ) -> None:
        key = self._make_key(strategy, budget_remaining, min_quality, exclude_providers)
        self._entries[key] = _CacheEntry(
            provider_name=provider_name,
            expires_at=time.monotonic() + self.ttl,
        )

    def invalidate(self) -> None:
        """Clear all cached entries."""
        self._entries.clear()


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


def filter_candidates(
    providers: list[ProviderMetrics],
    *,
    min_quality: float = 0.0,
    budget_remaining: float | None = None,
    exclude_providers: set[str] | None = None,
) -> list[ProviderMetrics]:
    """Apply selection constraints, returning the actual candidate set.

    This is the exact filter :meth:`CostQualityOptimizer.select_provider`
    chooses among: the quality floor, the total-failure exclusion
    (``failure_rate < 1.0``), caller exclusions, and the budget ceiling.
    """
    candidates = [
        m for m in providers if m.avg_quality_score >= min_quality and m.failure_rate < 1.0
    ]
    if exclude_providers:
        candidates = [m for m in candidates if m.provider_name not in exclude_providers]
    if budget_remaining is not None:
        candidates = [m for m in candidates if m.avg_cost_per_debate <= budget_remaining]
    return candidates


class CostQualityOptimizer:
    """Selects providers using Pareto-optimal cost/quality analysis.

    Args:
        metrics_store: ProviderMetricsStore with recorded debate outcomes.
    """

    def __init__(
        self,
        metrics_store: ProviderMetricsStore,
        cache_ttl: float = DEFAULT_CACHE_TTL,
    ) -> None:
        self._store = metrics_store
        self._cache = RoutingCache(ttl=cache_ttl)

    def _all_metrics_with_real_costs(self) -> list[ProviderMetrics]:
        """Read the store, pricing zero-cost entries via the model catalog.

        Providers whose outcomes were recorded without cost (the default
        ``cost=0.0`` path) previously entered every cost comparison as FREE,
        which let unpriced frontier pins dominate the Pareto frontier. The
        pricing ladder (catalog -> legacy table -> conservative default)
        substitutes a real, nonzero expectation; substituted entries carry
        ``cost_estimated=True`` for downstream audit records.
        """
        return with_effective_costs(list(self._store.get_all_metrics().values()))

    def get_pareto_frontier(self) -> list[ProviderMetrics]:
        """Return the current Pareto frontier across all providers."""
        return pareto_frontier(self._all_metrics_with_real_costs())

    def get_candidates(
        self,
        min_quality: float = 0.0,
        budget_remaining: float | None = None,
        exclude_providers: set[str] | None = None,
    ) -> list[ProviderMetrics]:
        """Return the providers :meth:`select_provider` would choose among.

        Applies the same constraint filter as :meth:`select_provider`
        (via :func:`filter_candidates`) so callers can audit the actual
        post-constraint choice set.
        """
        all_metrics = self._all_metrics_with_real_costs()
        return filter_candidates(
            all_metrics,
            min_quality=min_quality,
            budget_remaining=budget_remaining,
            exclude_providers=exclude_providers,
        )

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
        frozen_exclude = frozenset(exclude_providers) if exclude_providers else None
        hit, cached = self._cache.get(
            strategy.value,
            budget_remaining,
            min_quality,
            frozen_exclude,
        )
        if hit:
            logger.debug("Routing cache hit for strategy=%s", strategy.value)
            return cached

        all_metrics = self._all_metrics_with_real_costs()
        if not all_metrics:
            self._cache.put(strategy.value, budget_remaining, min_quality, frozen_exclude, None)
            return None

        # Filter by constraints
        candidates = filter_candidates(
            all_metrics,
            min_quality=min_quality,
            budget_remaining=budget_remaining,
            exclude_providers=exclude_providers,
        )

        result = self.select_from_candidates(candidates, strategy)
        if result is None:
            return None

        self._cache.put(strategy.value, budget_remaining, min_quality, frozen_exclude, result)
        return result

    def select_from_candidates(
        self,
        candidates: list[ProviderMetrics],
        strategy: SelectionStrategy = SelectionStrategy.BALANCED,
    ) -> str | None:
        """Apply ``strategy`` to an already-filtered candidate list.

        Pure selection: no store read, no cache. Callers that must keep the
        selection consistent with an audited candidate set (e.g. the
        decision-stakes router's rationale) pass the exact list they
        recorded, guaranteeing both come from the same metrics snapshot.
        """
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

    def invalidate_cache(self) -> None:
        """Clear the routing decision cache."""
        self._cache.invalidate()


__all__ = [
    "CostQualityOptimizer",
    "DEFAULT_CACHE_TTL",
    "RoutingCache",
    "SelectionStrategy",
    "filter_candidates",
    "pareto_frontier",
]
