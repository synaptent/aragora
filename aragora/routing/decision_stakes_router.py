"""Decision-stakes model routing — route by decision tier, record *why*.

Per-prompt routing (OpenRouter auto-router, Martian, Not Diamond, native lab
routers) is commoditizing. The defensible layer, and the one that belongs in a
decision receipt, is **decision-stakes routing**: choose models by the *stakes
of the decision* (its merge-gate tier) and make "why was this model trusted
with this decision" an auditable artifact.

Policy (issue #8233): low-stakes bounded lane / evidence work (Tier 0-2) routes
cost-first with low quality floors; strategic synthesis and Tier 3-4 settlement
juries route quality-first with high quality floors (0.7/0.8). The frontier
preference is enforced through those floors and the quality-optimized strategy,
NOT through a frontier-model-family allowlist — any provider whose measured
quality clears the floor is eligible. Selection within a tier is delegated to
the existing Pareto cost/quality optimizer (``cost_quality_optimizer``), driven
by the live ELO/calibration data already collected per provider; a hard
frontier-family constraint would need a provider→family registry and is
deliberately out of scope here.

This module is the routing *policy + rationale* core. The :class:`RoutingRationale`
it emits is the shape destined for the ODR receipt's ``routing`` block once that
block is un-reserved (spec §4.8 reserves it in v0.1); wiring it into the
emitter, and the cost-per-settled-PR instrument, are separate follow-ups.
Related to the ODR epic (#8223): the routing decision is decision-semantics.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from aragora.routing.cost_quality_optimizer import SelectionStrategy

if TYPE_CHECKING:
    from aragora.routing.cost_quality_optimizer import CostQualityOptimizer

__all__ = [
    "TierClass",
    "RoutingPolicy",
    "RoutingRationale",
    "DecisionStakesRouter",
    "TIER_POLICY",
    "policy_for_tier",
    "ROUTING_RATIONALE_SCHEMA",
]

COST_EFFICIENT = "cost_efficient"
FRONTIER = "frontier"
TierClass = str  # COST_EFFICIENT | FRONTIER

# Canonical routing-rationale record family, shared with the evidence-collection
# variant written by ``scripts/auto_evidence_cycle.py``. That variant records a
# *static-configuration* family selection with ``pareto_optimizer_consulted:
# False`` ("the Pareto optimizer is not wired into this path yet"). This router
# IS that wiring for execution routing, so its record reuses the same schema and
# flips the flag to ``True``.
ROUTING_RATIONALE_SCHEMA = "aragora.routing_rationale/v1"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutingPolicy:
    """The routing policy applied at one decision tier."""

    tier_class: TierClass
    strategy: SelectionStrategy
    min_quality: float


# Tier 0-2: cost-efficient (bounded lane / evidence work, damped by exact-head
# gates + quorum). Tier 3-4: frontier (strategic synthesis / human-risk
# settlement juries). min_quality rises with stakes.
TIER_POLICY: dict[int, RoutingPolicy] = {
    0: RoutingPolicy(COST_EFFICIENT, SelectionStrategy.COST_OPTIMIZED, 0.0),
    1: RoutingPolicy(COST_EFFICIENT, SelectionStrategy.COST_OPTIMIZED, 0.3),
    2: RoutingPolicy(COST_EFFICIENT, SelectionStrategy.BALANCED, 0.5),
    3: RoutingPolicy(FRONTIER, SelectionStrategy.QUALITY_OPTIMIZED, 0.7),
    4: RoutingPolicy(FRONTIER, SelectionStrategy.QUALITY_OPTIMIZED, 0.8),
}

_MAX_TIER = max(TIER_POLICY)


def _clamp_tier(decision_tier: int) -> int:
    """Clamp ``decision_tier`` into the known policy range."""
    if decision_tier < 0:
        return 0
    if decision_tier > _MAX_TIER:
        return _MAX_TIER
    return decision_tier


def policy_for_tier(decision_tier: int) -> RoutingPolicy:
    """Return the :class:`RoutingPolicy` for ``decision_tier`` (clamped to 0-4)."""
    return TIER_POLICY[_clamp_tier(decision_tier)]


@dataclass
class RoutingRationale:
    """The auditable record of a decision-stakes routing choice.

    This is the artifact no generic per-prompt router produces: it binds the
    selected model to the *stakes* of the decision and the cost/quality inputs
    that justified it. ``to_dict()`` is the payload shape for the ODR receipt
    ``routing`` block.

    Field semantics (audit-critical):

    - ``decision_tier`` is the *effective* tier whose policy was applied —
      out-of-range requests are clamped; the raw caller value is preserved in
      ``requested_tier`` so ``route(99)`` never emits ``decision_tier: 99``
      while silently applying Tier-4 policy.
    - ``models_considered`` is the *post-constraint* candidate set — the
      providers that survived the tier's quality floor, the caller's budget,
      and caller exclusions, i.e. the set the choice was actually made among.
      The unconstrained Pareto frontier is recorded separately (and named
      distinctly) as ``frontier_before_constraints`` for context.
    - ``excluded_providers`` records caller-requested exclusions so an
      exclusion-caused non-selection is never misattributed to the policy.
    """

    decision_tier: int
    tier_class: TierClass
    strategy: str
    min_quality: float
    selected_provider: str | None
    selection_reason: str
    requested_tier: int | None = None
    excluded_providers: list[str] = field(default_factory=list)
    models_considered: list[dict[str, Any]] = field(default_factory=list)
    frontier_before_constraints: list[dict[str, Any]] = field(default_factory=list)
    budget_remaining: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Emit the ``aragora.routing_rationale/v1`` record for this choice.

        Same schema family as the evidence-collection record
        (``scripts/auto_evidence_cycle.py``); ``selector`` and
        ``pareto_optimizer_consulted`` mark this as the execution-routing
        variant where the Pareto optimizer *is* consulted. Cost stays
        ``recorded: false`` — per-provider ``avg_cost_per_debate`` (in
        ``models_considered``) is an expectation from metrics, not observed
        spend, and is never reported as recorded cost.
        """
        return {
            "record_type": "routing_rationale",
            "schema": ROUTING_RATIONALE_SCHEMA,
            "status": "present",
            "selector": "decision_stakes_pareto",
            "pareto_optimizer_consulted": True,
            **asdict(self),
            "cost": {
                "recorded": False,
                "total_usd": None,
                "absent_reason": (
                    "per-provider avg_cost_per_debate is an expectation from "
                    "metrics, not observed spend; recorded as absent"
                ),
            },
        }


class DecisionStakesRouter:
    """Routes by decision tier and records the rationale.

    Wraps a :class:`~aragora.routing.cost_quality_optimizer.CostQualityOptimizer`
    (which carries the live per-provider cost/quality/calibration metrics) and
    applies the tier policy on top.
    """

    def __init__(self, optimizer: CostQualityOptimizer) -> None:
        self._optimizer = optimizer

    def route(
        self,
        decision_tier: int,
        *,
        budget_remaining: float | None = None,
        exclude_providers: set[str] | None = None,
    ) -> RoutingRationale:
        """Select a provider for a decision of ``decision_tier`` and record why.

        Out-of-range tiers are clamped for policy selection; the rationale
        records the clamped tier it actually applied as ``decision_tier`` and
        the raw caller value as ``requested_tier``.
        """
        effective_tier = _clamp_tier(decision_tier)
        policy = TIER_POLICY[effective_tier]
        excluded = sorted(exclude_providers) if exclude_providers else []

        # The audit record needs two sets: the unconstrained Pareto frontier
        # (context: the non-dominated cost/quality options that existed) and
        # the actual candidate set after the tier's quality floor, the
        # caller's budget, and caller exclusions — the set the choice is
        # made among. Selection applies the policy strategy to that exact
        # recorded list (no second store read, no cache), so the rationale
        # can never claim a candidate set the choice wasn't made from.
        try:
            frontier = self._optimizer.get_pareto_frontier()
            candidates = self._optimizer.get_candidates(
                min_quality=policy.min_quality,
                budget_remaining=budget_remaining,
                exclude_providers=exclude_providers,
            )
            selected = self._optimizer.select_from_candidates(candidates, policy.strategy)
            metrics_available = True
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as e:
            # Never let metric gaps break routing — record empty sets and no
            # selection, with the rationale naming the metrics gap.
            logger.warning("provider metrics unavailable; routing without selection: %s", e)
            frontier = []
            candidates = []
            selected = None
            metrics_available = False

        constraints = (
            f"strategy={policy.strategy.value}, min_quality={policy.min_quality}"
            + (f", budget={budget_remaining}" if budget_remaining is not None else "")
            + (f", excluded={excluded}" if excluded else "")
        )
        if not metrics_available:
            reason = (
                f"provider metrics unavailable; no selection for tier-{effective_tier} "
                f"{policy.tier_class} policy ({constraints})"
            )
        elif selected is None:
            reason = (
                f"no provider satisfied tier-{effective_tier} {policy.tier_class} policy "
                f"and caller constraints ({constraints})"
            )
        else:
            reason = (
                f"tier {effective_tier} ({policy.tier_class}) selects '{selected}' ({constraints})"
            )

        def _describe(metrics: list[Any]) -> list[dict[str, Any]]:
            # ``cost_source`` is audit-critical: providers whose outcomes were
            # recorded without spend get a catalog-priced expectation from the
            # pricing ladder (never $0), and the rationale must not present
            # that estimate as observed spend.
            return [
                {
                    "provider": m.provider_name,
                    "avg_cost_per_debate": m.avg_cost_per_debate,
                    "avg_quality_score": m.avg_quality_score,
                    "failure_rate": m.failure_rate,
                    "cost_source": (
                        "estimated_from_pricing"
                        if getattr(m, "cost_estimated", False)
                        else "observed"
                    ),
                }
                for m in metrics
            ]

        return RoutingRationale(
            decision_tier=effective_tier,
            tier_class=policy.tier_class,
            strategy=policy.strategy.value,
            min_quality=policy.min_quality,
            selected_provider=selected,
            selection_reason=reason,
            requested_tier=decision_tier,
            excluded_providers=excluded,
            models_considered=_describe(candidates),
            frontier_before_constraints=_describe(frontier),
            budget_remaining=budget_remaining,
        )
