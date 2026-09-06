"""Main provider routing entry point.

Combines metrics store, cost/quality optimizer, and pricing config
to select providers for debates.

Usage:
    router = ProviderRouter()
    providers = router.select_providers_for_debate(num_agents=3)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from aragora.agents.credential_validator import CredentialStatus
from aragora.config.model_pins import (
    FABLE_51_DIRECT,
    GEMINI_31_PRO_DIRECT,
    GPT6_ASTRA_DIRECT,
    GROK_46_DIRECT,
    MISTRAL_MEDIUM_DIRECT,
)
from aragora.models import by_any_id
from aragora.models.catalog import CATALOG
from aragora.routing.cost_quality_optimizer import CostQualityOptimizer, SelectionStrategy
from aragora.routing.provider_config import (
    current_pricing_as_of,
    current_pricing_table,
    get_available_models,
)
from aragora.routing.provider_metrics import ProviderMetricsStore

logger = logging.getLogger(__name__)

# DeepSeek has no model_pins constant (it is an OpenRouter-routed family, so
# there is no native-provider pin); read its canonical id straight from the
# catalog rather than hardcoding the literal.
DEEPSEEK_V4_PRO = CATALOG["deepseek-v4-pro-0813"].canonical_id


def _is_under_soak(provider: str, as_of: date) -> bool:
    """True when ``provider`` resolves to a catalog model still under soak.

    Soak gating applies to every selection surface (#9364 rounds 3-8):
    having recorded metrics does not make an under-soak catalog model
    adoptable. Ids unknown to the catalog pass through. ``as_of`` should be
    ``current_pricing_as_of()`` so metrics-path gating and the enumerated
    pricing table agree on one coherent date."""
    spec = by_any_id(provider)
    return spec is not None and spec.is_under_soak(as_of)


# Minimum number of recorded debates before metrics-based selection is used.
MIN_DEBATES_FOR_METRICS = 10

# Default round-robin order when insufficient data is available: the
# cold-start roster. Derived from aragora.config.model_pins (frontier-model-
# refresh, 2026-09-04) rather than hand-written ids, which had drifted to a
# roster that was 100% retired spellings (claude-sonnet-4, gpt-4o,
# mistral-large, gemini-2.0-flash, claude-opus-4) — so a cold-start debate
# could not see the current frontier at all. Canonical ids, because
# _round_robin_selection filters this list by membership in
# provider_config's pricing table, which is keyed by canonical id.
DEFAULT_PROVIDER_ORDER = [
    FABLE_51_DIRECT,
    GPT6_ASTRA_DIRECT,
    GEMINI_31_PRO_DIRECT,
    GROK_46_DIRECT,
    MISTRAL_MEDIUM_DIRECT,
    DEEPSEEK_V4_PRO,
]


@dataclass
class ProviderPathState:
    """Truthful readiness state for one provider path."""

    agent_type: str
    provider: str
    model: str | None
    config_present: bool
    live_ready: bool
    status: str
    available_via: str | None = None
    reason: str | None = None
    detail: str | None = None
    next_action: str | None = None
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_type": self.agent_type,
            "provider": self.provider,
            "model": self.model,
            "config_present": self.config_present,
            "live_ready": self.live_ready,
            "status": self.status,
            "available_via": self.available_via,
            "reason": self.reason,
            "detail": self.detail,
            "next_action": self.next_action,
            "next_actions": list(self.next_actions),
        }


@dataclass
class ProviderPathSummary:
    """Aggregate truth contract for provider-path readiness."""

    status: str
    reason: str
    blocked: bool
    config_present: bool
    live_ready: bool
    requested_provider: str | None
    next_action: str | None = None
    next_actions: list[str] = field(default_factory=list)
    providers: list[ProviderPathState] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "blocked": self.blocked,
            "config_present": self.config_present,
            "live_ready": self.live_ready,
            "requested_provider": self.requested_provider,
            "next_action": self.next_action,
            "next_actions": list(self.next_actions),
            "providers": [provider.to_dict() for provider in self.providers],
        }


def _unique_strings(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        unique.append(text)
        seen.add(text)
    return unique


def _build_blocked_next_steps(
    reason: str,
    *,
    status: CredentialStatus | None = None,
) -> tuple[str, list[str]]:
    if reason == "tls_verification_failed":
        return (
            "Fix local TLS trust configuration and retry the live preflight.",
            [
                "Check the local CA trust store or any corporate TLS interception settings.",
                "Retry quickstart after a provider TLS preflight succeeds.",
            ],
        )
    if reason == "provider_unreachable":
        actions = [
            "Verify outbound network access to the provider endpoint.",
            "Retry quickstart after at least one configured provider responds to preflight.",
        ]
        if status and status.available_via:
            actions.insert(
                0,
                f"Keep {status.available_via} configured; the provider is configured but not currently reachable.",
            )
        return (
            "Verify provider connectivity and retry the live preflight.",
            actions,
        )
    if status and status.next_action:
        return status.next_action, list(status.next_actions)
    return (
        "Set a supported provider credential and retry the live preflight.",
        ["Configure a supported provider API key before requesting live debate mode."],
    )


def summarize_provider_path(
    provider_specs: list[tuple[str, str | None]],
    credential_statuses: dict[str, CredentialStatus],
    *,
    requested_provider: str | None = None,
    verified_live_agents: list[tuple[str, str | None]] | None = None,
    failure_reasons: dict[str, str] | None = None,
    failure_details: dict[str, str | None] | None = None,
) -> ProviderPathSummary:
    """Summarize configured vs verified provider paths into a truthful state."""
    verified_live_agents = verified_live_agents or []
    failure_reasons = failure_reasons or {}
    failure_details = failure_details or {}
    verified_lookup = {agent_type for agent_type, _ in verified_live_agents}

    providers: list[ProviderPathState] = []
    for agent_type, model in provider_specs:
        status = credential_statuses.get(agent_type)
        if agent_type in verified_lookup:
            providers.append(
                ProviderPathState(
                    agent_type=agent_type,
                    provider=agent_type,
                    model=model,
                    config_present=True if status is None else status.config_present,
                    live_ready=True,
                    status="live_ready",
                    available_via=None if status is None else status.available_via,
                    reason="verified_provider_response",
                    detail="First verified provider response succeeded.",
                )
            )
            continue

        if status and status.config_present:
            blocked_reason = failure_reasons.get(agent_type, "provider_unreachable")
            next_action, next_actions = _build_blocked_next_steps(blocked_reason, status=status)
            providers.append(
                ProviderPathState(
                    agent_type=agent_type,
                    provider=agent_type,
                    model=model,
                    config_present=True,
                    live_ready=False,
                    status="blocked",
                    available_via=status.available_via,
                    reason=blocked_reason,
                    detail=failure_details.get(agent_type),
                    next_action=next_action,
                    next_actions=next_actions,
                )
            )
            continue

        missing_status = status or CredentialStatus(
            agent_type=agent_type,
            is_available=False,
            required_vars=[],
            missing_vars=[],
        )
        next_action, next_actions = _build_blocked_next_steps(
            "missing_config", status=missing_status
        )
        providers.append(
            ProviderPathState(
                agent_type=agent_type,
                provider=agent_type,
                model=model,
                config_present=False,
                live_ready=False,
                status="missing_config",
                available_via=missing_status.available_via,
                reason="missing_config",
                next_action=next_action,
                next_actions=next_actions,
            )
        )

    config_present = any(provider.config_present for provider in providers)
    live_ready = any(provider.live_ready for provider in providers)
    if live_ready:
        return ProviderPathSummary(
            status="live_ready",
            reason="verified_provider_response",
            blocked=False,
            config_present=config_present,
            live_ready=True,
            requested_provider=requested_provider,
            providers=providers,
        )

    blocked_providers = [
        provider
        for provider in providers
        if provider.status == ("blocked" if config_present else "missing_config")
    ]
    next_action = next(
        (provider.next_action for provider in blocked_providers if provider.next_action),
        "Set a supported provider credential and retry the live preflight."
        if not config_present
        else "Verify provider connectivity and retry the live preflight.",
    )
    next_actions = _unique_strings(
        [action for provider in blocked_providers for action in provider.next_actions]
    )
    return ProviderPathSummary(
        status="blocked",
        reason="providers_unreachable" if config_present else "missing_config",
        blocked=True,
        config_present=config_present,
        live_ready=False,
        requested_provider=requested_provider,
        next_action=next_action,
        next_actions=next_actions,
        providers=providers,
    )


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

        # Seed the optimizer's exclude set with under-soak catalog models
        # (#9364 round-8): the optimizer itself stays catalog-unaware.
        as_of = current_pricing_as_of()
        excluded: set[str] = {p for p in candidates if _is_under_soak(p, as_of)}
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

    def get_provider_hints(self) -> dict[str, float]:
        """Return a provider_name -> quality_score mapping for TeamSelector integration.

        When sufficient metrics exist, returns normalized quality scores (0-1)
        for each tracked provider.  Falls back to uniform 0.5 hints when data
        is sparse.
        """
        if not self._has_sufficient_data():
            return {}

        all_metrics = self._store.get_all_metrics()
        as_of = current_pricing_as_of()
        return {
            provider: metrics.avg_quality_score
            for provider, metrics in all_metrics.items()
            # No quality boost for under-soak models during team selection.
            if metrics.total_debates > 0 and not _is_under_soak(provider, as_of)
        }

    def select_providers_with_details(
        self,
        num_agents: int = 3,
        budget: float | None = None,
        strategy: SelectionStrategy = SelectionStrategy.BALANCED,
        min_quality: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Select providers with detailed cost/quality information.

        Unlike :meth:`select_providers_for_debate` which returns plain names,
        this method returns dicts containing the provider name, estimated cost,
        and quality score — suitable for budget-aware debate configuration.

        Args:
            num_agents: Number of agents (providers) to select.
            budget: Optional total budget for the debate in USD.
                Providers whose estimated cost exceeds ``budget / num_agents``
                are excluded.
            strategy: Selection strategy.
            min_quality: Minimum acceptable quality score (0-1).

        Returns:
            List of dicts, each with keys:
            - ``provider``: provider/model name
            - ``estimated_cost``: estimated per-debate cost in USD
            - ``quality_score``: quality score (0-1)
        """
        per_agent_budget = budget / num_agents if budget is not None and num_agents > 0 else None

        all_metrics = self._store.get_all_metrics()

        # If we have no metrics, fall back to pricing-based estimates
        if not all_metrics or not self._has_sufficient_data():
            return self._details_from_pricing(num_agents, per_agent_budget)

        # Build candidates filtered by budget and quality; under-soak
        # catalog models are gated against the snapshot's own as-of date.
        as_of = current_pricing_as_of()
        candidates: list[dict[str, Any]] = []
        for provider, metrics in all_metrics.items():
            if _is_under_soak(provider, as_of):
                continue
            if metrics.avg_quality_score < min_quality:
                continue
            if per_agent_budget is not None and metrics.avg_cost_per_debate > per_agent_budget:
                continue
            candidates.append(
                {
                    "provider": provider,
                    "estimated_cost": round(metrics.avg_cost_per_debate, 6),
                    "quality_score": round(metrics.avg_quality_score, 4),
                }
            )

        # Sort by strategy preference
        if strategy == SelectionStrategy.COST_OPTIMIZED:
            candidates.sort(key=lambda c: c["estimated_cost"])
        elif strategy == SelectionStrategy.QUALITY_OPTIMIZED:
            candidates.sort(key=lambda c: c["quality_score"], reverse=True)
        else:
            # Balanced: sort by quality/cost ratio (higher is better)
            candidates.sort(
                key=lambda c: c["quality_score"] / max(c["estimated_cost"], 1e-9),
                reverse=True,
            )

        return candidates[:num_agents]

    def _details_from_pricing(
        self,
        num_agents: int,
        per_agent_budget: float | None,
    ) -> list[dict[str, Any]]:
        """Build provider details from static pricing when no metrics exist.

        Soak-gated explicitly for the same reason as ``_round_robin_selection``:
        the pricing table filters on retirement, so the must-not-adopt rule
        is applied here, at selection.
        """
        results: list[dict[str, Any]] = []
        as_of = current_pricing_as_of()
        for model_key, pricing in current_pricing_table().items():
            if _is_under_soak(model_key, as_of):
                continue
            # Estimate cost per debate using 2K input + 1K output tokens
            estimated_cost = (2000 / 1000.0) * pricing.input_cost_per_1k + (
                1000 / 1000.0
            ) * pricing.output_cost_per_1k
            if per_agent_budget is not None and estimated_cost > per_agent_budget:
                continue
            results.append(
                {
                    "provider": model_key,
                    "estimated_cost": round(estimated_cost, 6),
                    "quality_score": 0.5,  # Unknown quality; neutral default
                }
            )
        results.sort(key=lambda c: c["estimated_cost"])
        return results[:num_agents]

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
        """Select N providers using deterministic round-robin.

        Soak-gated explicitly: the enumerated pricing table is a candidate
        set filtered on RETIREMENT, not soak (frontier-model-refresh final
        review #7), so every SELECTION surface applies the must-not-adopt
        rule itself. This is one of the two no-metrics paths (the other is
        ``_details_from_pricing``); the metrics-driven paths already gate.
        """
        pricing_table = current_pricing_table()
        as_of = current_pricing_as_of()
        available = [
            model
            for model in DEFAULT_PROVIDER_ORDER
            if model in pricing_table and not _is_under_soak(model, as_of)
        ]
        if not available:
            available = [m for m in get_available_models() if not _is_under_soak(m, as_of)]
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
    "ProviderPathState",
    "ProviderPathSummary",
    "summarize_provider_path",
    "get_provider_router",
    "MIN_DEBATES_FOR_METRICS",
    "DEFAULT_PROVIDER_ORDER",
]
