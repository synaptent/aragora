"""Catalog-backed model pricing for routing decisions.

The Pareto cost/quality optimizer and the decision-stakes router reason about
``avg_cost_per_debate``. Historically that number came from two stale sources:

1. Outcomes recorded with the default ``cost=0.0`` (several call sites record
   consensus/quality only), which made every such provider look FREE.
2. The legacy ``PROVIDER_PRICING`` table in ``provider_config.py``, which
   predates the July-2026 frontier models entirely — ``get_estimated_cost``
   returns ``0.0`` for any model it does not know, so every frontier pin
   (claude-fable-5, gpt-5.6-sol, grok-4.5, ...) scored $0 and corrupted the
   cost/quality tradeoff.

This module resolves real prices through a fallback ladder:

1. **Canonical model catalog** (``aragora.models``, PR #9355) via
   ``by_any_id()`` — USD per 1M tokens, drift-enforced against the live
   OpenRouter snapshot. The import is guarded so this module works whether or
   not phase 1 of the catalog has landed.
2. **Legacy table** (``provider_config.PROVIDER_PRICING``) for rows the
   catalog does not (yet) enforce.
3. **Conservative nonzero default** with a logged warning — a known-frontier
   family never resolves to $0.

Prices in :class:`ResolvedPricing` are USD per 1M tokens (the catalog's
convention); per-1K accessors are provided for legacy-table interop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable

# From-import holds the snapshot current at import time (published snapshots
# are never mutated — stale-but-never-corrupt). Freshness is immaterial for
# this rung-2 point lookup: rung 1 (catalog resolution) precedes it for every
# cataloged id, and this rung never iterates the dict.
from aragora.routing.provider_config import PROVIDER_PRICING

if TYPE_CHECKING:
    from aragora.routing.provider_metrics import ProviderMetrics

logger = logging.getLogger(__name__)

__all__ = [
    "PRICING_SOURCE_CATALOG",
    "PRICING_SOURCE_DEFAULT",
    "PRICING_SOURCE_LEGACY_TABLE",
    "ResolvedPricing",
    "effective_cost_per_debate",
    "estimate_model_cost_usd",
    "is_frontier_family",
    "resolve_model_pricing",
    "with_effective_costs",
]

#: Where a resolved price came from (recorded in routing rationale audits).
PRICING_SOURCE_CATALOG = "catalog"
PRICING_SOURCE_LEGACY_TABLE = "legacy_table"
PRICING_SOURCE_DEFAULT = "conservative_default"

#: Model-id / provider-name prefixes treated as frontier families. A model in
#: one of these families must NEVER price at $0: an unknown frontier pin gets
#: the conservative frontier default below instead.
FRONTIER_FAMILY_PREFIXES: tuple[str, ...] = (
    "anthropic",
    "claude",
    "gemini",
    "google",
    "gpt",
    "grok",
    "o1",
    "o3",
    "o4",
    "openai",
    "x-ai",
    "xai",
)

# Conservative defaults, USD per 1M tokens. The frontier default is pinned to
# the cheapest frontier-tier price in the catalog capture (claude-opus-5 /
# gpt-5.6 at $5/$25-30) so an unpriced frontier pin is assumed expensive,
# never free. The unknown default is a mid-tier assumption.
DEFAULT_FRONTIER_INPUT_PER_MTOK = 5.00
DEFAULT_FRONTIER_OUTPUT_PER_MTOK = 25.00
DEFAULT_UNKNOWN_INPUT_PER_MTOK = 1.00
DEFAULT_UNKNOWN_OUTPUT_PER_MTOK = 4.00

#: Token estimate used to price one debate when no observed spend exists.
#: Matches the 2K-input/1K-output convention already used by
#: ``ProviderRouter._details_from_pricing``.
ESTIMATED_INPUT_TOKENS_PER_DEBATE = 2000
ESTIMATED_OUTPUT_TOKENS_PER_DEBATE = 1000


@dataclass(frozen=True)
class ResolvedPricing:
    """A model's resolved input/output prices and where they came from."""

    model_id: str
    input_per_mtok: float
    output_per_mtok: float
    source: str  # one of the PRICING_SOURCE_* constants

    @property
    def input_per_1k(self) -> float:
        """USD per 1K input tokens (legacy-table convention)."""
        return self.input_per_mtok / 1000.0

    @property
    def output_per_1k(self) -> float:
        """USD per 1K output tokens (legacy-table convention)."""
        return self.output_per_mtok / 1000.0

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD for a given token usage."""
        return (input_tokens / 1_000_000.0) * self.input_per_mtok + (
            output_tokens / 1_000_000.0
        ) * self.output_per_mtok

    def estimate_debate_cost_usd(self) -> float:
        """Estimate the cost of one debate turn at the standard token budget."""
        return self.estimate_cost_usd(
            ESTIMATED_INPUT_TOKENS_PER_DEBATE,
            ESTIMATED_OUTPUT_TOKENS_PER_DEBATE,
        )


_UNSET = object()
# Cached catalog resolver: _UNSET until first use, then either the catalog's
# by_any_id or None when aragora.models is unavailable (pre-#9355 checkouts).
# Tests patch this attribute directly to simulate either state.
_by_any_id: Callable[[str], Any] | None | object = _UNSET

# Model ids we already warned about falling to the conservative default, so a
# hot routing loop does not spam the log.
_warned_defaults: set[str] = set()


def _catalog_resolver() -> Callable[[str], Any] | None:
    """Return the canonical catalog's ``by_any_id``, or None if unavailable.

    Import-guarded: the canonical catalog ships in PR #9355 (``aragora.models``);
    until it lands (or on trees without it) the ladder skips straight to the
    legacy table.
    """
    global _by_any_id
    if _by_any_id is _UNSET:
        try:
            from aragora.models import by_any_id as _resolver
        except ImportError:
            logger.debug(
                "canonical model catalog (aragora.models) unavailable; "
                "pricing falls back to the legacy table"
            )
            _by_any_id = None
        else:
            _by_any_id = _resolver
    return _by_any_id  # type: ignore[return-value]


def is_frontier_family(model_id: str) -> bool:
    """True when ``model_id`` names a known frontier model family."""
    normalized = str(model_id).strip().lower()
    return normalized.startswith(FRONTIER_FAMILY_PREFIXES)


def resolve_model_pricing(model_id: str) -> ResolvedPricing:
    """Resolve real input/output prices for ``model_id``.

    Ladder: canonical catalog -> legacy table -> conservative nonzero default
    (with a once-per-model logged warning). Never returns $0/$0 — a routing
    layer that believes a model is free will always mis-rank it.
    """
    model_id = str(model_id).strip()

    resolver = _catalog_resolver()
    if resolver is not None:
        spec = resolver(model_id)
        if spec is not None:
            return ResolvedPricing(
                model_id=model_id,
                input_per_mtok=float(spec.input_per_mtok),
                output_per_mtok=float(spec.output_per_mtok),
                source=PRICING_SOURCE_CATALOG,
            )

    legacy = PROVIDER_PRICING.get(model_id)
    if legacy is not None:
        return ResolvedPricing(
            model_id=model_id,
            input_per_mtok=legacy.input_cost_per_1k * 1000.0,
            output_per_mtok=legacy.output_cost_per_1k * 1000.0,
            source=PRICING_SOURCE_LEGACY_TABLE,
        )

    if is_frontier_family(model_id):
        input_per_mtok = DEFAULT_FRONTIER_INPUT_PER_MTOK
        output_per_mtok = DEFAULT_FRONTIER_OUTPUT_PER_MTOK
        family = "frontier-family"
    else:
        input_per_mtok = DEFAULT_UNKNOWN_INPUT_PER_MTOK
        output_per_mtok = DEFAULT_UNKNOWN_OUTPUT_PER_MTOK
        family = "unknown"

    if model_id not in _warned_defaults:
        _warned_defaults.add(model_id)
        logger.warning(
            "no catalog or legacy pricing for %s model '%s'; using conservative "
            "default $%.2f/$%.2f per MTok (never $0)",
            family,
            model_id,
            input_per_mtok,
            output_per_mtok,
        )

    return ResolvedPricing(
        model_id=model_id,
        input_per_mtok=input_per_mtok,
        output_per_mtok=output_per_mtok,
        source=PRICING_SOURCE_DEFAULT,
    )


def estimate_model_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a model and token usage via the pricing ladder.

    Unlike the legacy ``provider_config.get_estimated_cost`` (which returns
    ``0.0`` for unknown models), this never prices a model at $0.
    """
    return resolve_model_pricing(model_id).estimate_cost_usd(input_tokens, output_tokens)


def effective_cost_per_debate(metrics: ProviderMetrics) -> float:
    """Observed avg cost per debate, or a priced estimate when none exists.

    Several outcome-recording call sites record consensus/quality with the
    default ``cost=0.0``; treating that as a real $0 price is exactly the bug
    that let frontier pins dominate cost-optimized routing.
    """
    if metrics.avg_cost_per_debate > 0.0:
        return metrics.avg_cost_per_debate
    return resolve_model_pricing(metrics.provider_name).estimate_debate_cost_usd()


def with_effective_costs(metrics: list[ProviderMetrics]) -> list[ProviderMetrics]:
    """Return metrics with zero observed costs replaced by priced estimates.

    Entries with observed spend pass through unchanged. Entries with no
    observed spend (``avg_cost_per_debate <= 0``) are copied with the pricing
    ladder's per-debate estimate and ``cost_estimated=True`` so downstream
    audit records (decision-stakes rationale) can distinguish observed spend
    from a catalog expectation.
    """
    normalized: list[ProviderMetrics] = []
    for m in metrics:
        if m.avg_cost_per_debate > 0.0:
            normalized.append(m)
        else:
            normalized.append(
                replace(
                    m,
                    avg_cost_per_debate=effective_cost_per_debate(m),
                    cost_estimated=True,
                )
            )
    return normalized
