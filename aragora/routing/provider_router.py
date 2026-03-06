"""Main provider routing entry point.

Combines metrics store, cost/quality optimizer, and pricing config
to select providers for debates.

Usage:
    router = ProviderRouter()
    providers = router.select_providers_for_debate(num_agents=3)
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.routing.cost_quality_optimizer import CostQualityOptimizer, SelectionStrategy
from aragora.routing.provider_config import PROVIDER_PRICING, get_available_models
from aragora.routing.provider_metrics import ProviderMetricsStore

logger = logging.getLogger(__name__)

# Minimum number of recorded debates before metrics-based selection is used.
MIN_DEBATES_FOR_METRICS = 10

# Default round-robin order when insufficient data is available.
DEFAULT_PROVIDER_ORDER = [
    "claude-sonnet-4",
    "gpt-4o",
    "deepseek-r1",
    "mistral-large",
    "gemini-2.0-flash",
    "gpt-4o-mini",
    "deepseek-chat",
    "claude-opus-4",
]


class ProviderRouter:
    """Route debate agent assignments to optimal providers.

    Uses recorded metrics when available (>= MIN_DEBATES_FOR_METRICS),
    falling back to a deterministic round-robin when data is sparse.

    Args:
        metrics_store: Optional pre-configured ProviderMetricsStore.
            A new in-memory store is created if not provided.
        persist_path: Optional path for metrics persistence (ignored if
            metrics_store is provided).
    """

    def __init__(
        self,
        metrics_store: ProviderMetricsStore | None = None,
        persist_path: str | None = None,
    ) -> None:
        self._store = metrics_store or ProviderMetricsStore(persist_path=persist_path)
        self._optimizer = CostQualityOptimizer(self._store)

    @property
    def metrics_store(self) -> ProviderMetricsStore:
        """Access the underlying metrics store."""
        return self._store

    @property
    def optimizer(self) -> CostQualityOptimizer:
        """Access the cost/quality optimizer."""
        return self._optimizer

    def select_providers_for_debate(
        self,
        num_agents: int = 3,
        strategy: SelectionStrategy = SelectionStrategy.BALANCED,
        budget: float | None = None,
        min_quality: float = 0.0,
    ) -> list[str]:
        """Select providers for a multi-agent debate.

        Args:
            num_agents: Number of agents (providers) to select.
            strategy: Selection strategy.
            budget: Optional total budget for the debate in USD.
                Divided across agents for per-agent budget constraint.
            min_quality: Minimum acceptable quality score (0-1).

        Returns:
            List of provider/model names to use.
        """
        if not self._has_sufficient_data():
            logger.info(
                "Insufficient metrics data (<%d debates), using round-robin",
                MIN_DEBATES_FOR_METRICS,
            )
            return self._round_robin_selection(num_agents)

        per_agent_budget = budget / num_agents if budget else None

        selected: list[str] = []
        all_metrics = self._store.get_all_metrics()

        # Build candidate pool from metrics
        candidates = list(all_metrics.keys())
        if not candidates:
            return self._round_robin_selection(num_agents)

        excluded: set[str] = set()
        for _ in range(num_agents):
            provider = self._optimizer.select_provider(
                strategy=strategy,
                budget_remaining=per_agent_budget,
                min_quality=min_quality,
                exclude_providers=excluded,
            )
            if provider is None:
                break

            selected.append(provider)
            excluded.add(provider)

            # Relax the remaining budget slightly after each pick so later
            # selections still reflect the original budget pressure.
            if per_agent_budget is not None and provider in all_metrics:
                cost = all_metrics[provider].avg_cost_per_debate
                per_agent_budget = max(0.0, per_agent_budget - cost * 0.1)

        # Pad with round-robin if we couldn't fill all slots
        if len(selected) < num_agents:
            fallbacks = self._round_robin_selection(num_agents - len(selected))
            for fb in fallbacks:
                if fb not in selected:
                    selected.append(fb)
                if len(selected) >= num_agents:
                    break

        return selected[:num_agents]

    def record_outcome(
        self,
        provider: str,
        *,
        cost: float = 0.0,
        quality: float = 0.0,
        latency: float = 0.0,
        consensus_reached: bool = False,
        failed: bool = False,
    ) -> None:
        """Convenience method to record a debate outcome.

        Delegates to the underlying ProviderMetricsStore.
        """
        self._store.record_debate_outcome(
            provider,
            cost=cost,
            quality=quality,
            latency=latency,
            consensus_reached=consensus_reached,
            failed=failed,
        )

    def get_status(self) -> dict[str, Any]:
        """Return current router status for diagnostics."""
        all_metrics = self._store.get_all_metrics()
        total_debates = sum(m.total_debates for m in all_metrics.values())
        return {
            "has_sufficient_data": self._has_sufficient_data(),
            "total_debates_recorded": total_debates,
            "min_debates_threshold": MIN_DEBATES_FOR_METRICS,
            "providers_tracked": list(all_metrics.keys()),
            "pareto_frontier": [m.provider_name for m in self._optimizer.get_pareto_frontier()],
        }

    def _has_sufficient_data(self) -> bool:
        """Check if we have enough data for metrics-based selection."""
        all_metrics = self._store.get_all_metrics()
        total_debates = sum(m.total_debates for m in all_metrics.values())
        return total_debates >= MIN_DEBATES_FOR_METRICS

    def _round_robin_selection(self, n: int) -> list[str]:
        """Select N providers using deterministic round-robin."""
        available = [model for model in DEFAULT_PROVIDER_ORDER if model in PROVIDER_PRICING]
        if not available:
            available = get_available_models()
        if not available:
            return []

        selected: list[str] = []
        for i in range(n):
            selected.append(available[i % len(available)])
        return selected


# Module-level singleton for convenience
_router: ProviderRouter | None = None


def get_provider_router(persist_path: str | None = None) -> ProviderRouter:
    """Get or create the global ProviderRouter instance.

    Args:
        persist_path: Optional path for metrics persistence.
            Only used when creating a new instance.
    """
    global _router
    if _router is None:
        _router = ProviderRouter(persist_path=persist_path)
    return _router


__all__ = [
    "ProviderRouter",
    "get_provider_router",
    "MIN_DEBATES_FOR_METRICS",
    "DEFAULT_PROVIDER_ORDER",
]
