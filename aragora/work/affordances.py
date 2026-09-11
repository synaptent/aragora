"""Action affordances: explicit next-move records with gates before ranking.

Replaces opaque universal scores in agent-facing views. Every candidate next
move carries its own cost vector, risk tier, preconditions, invalidators, and
expected terminal proof. Hard authority/safety gates (halt, capabilities,
live blockers) are applied BEFORE ranking, and ranking returns a nondominated
Pareto frontier rather than a single winner, so tradeoffs stay visible.

``wait/watch`` is itself an affordance (with wake predicates, deadline,
fallback, and cancellation semantics) so "the right move is to wait" competes
explicitly with acting.

Prior art: ``aragora.routing.decision_stakes_router`` records an unconstrained
Pareto frontier for model routing; this module applies the same philosophy to
work selection. Additive: does not modify ``aragora.work.models``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from aragora.reasoning.epistemics import (
    EpistemicTag,
    KnowledgeState,
    ProvenanceClass,
    reconcile,
)
from aragora.work.models import WorkRecommendation

__all__ = [
    "ActionAffordance",
    "AffordanceDisposition",
    "CostVector",
    "WaitSpec",
    "apply_hard_gates",
    "from_work_recommendation",
    "pareto_frontier",
]


class AffordanceDisposition(str, Enum):
    """Control-envelope classification of a candidate action."""

    ROBUST = "robust"  # safe under every live interpretation
    CONDITIONAL = "conditional"  # safe only in named worlds / predicates
    INFORMATION_GATHERING = "information_gathering"  # read-only probe
    WAIT_WATCH = "wait_watch"  # deliberate wait with wake conditions
    BLOCKED = "blocked"  # a live authority forbids it right now
    UNAVAILABLE = "unavailable"  # missing capability or approval


_ACTIONABLE = frozenset(
    {
        AffordanceDisposition.ROBUST,
        AffordanceDisposition.CONDITIONAL,
        AffordanceDisposition.INFORMATION_GATHERING,
        AffordanceDisposition.WAIT_WATCH,
    }
)

# Dispositions exempt from the halt gate: they observe, never mutate.
_HALT_EXEMPT = frozenset(
    {AffordanceDisposition.WAIT_WATCH, AffordanceDisposition.INFORMATION_GATHERING}
)

# Already-downgraded dispositions: terminal for the halt gate (re-gating
# gated output must not re-fire halt against a lost intrinsic disposition).
_NON_ACTIONABLE = frozenset({AffordanceDisposition.BLOCKED, AffordanceDisposition.UNAVAILABLE})


@dataclass(slots=True)
class CostVector:
    """Multi-axis cost; axes are minimized independently by the frontier."""

    tokens: int = 0
    seconds: float = 0.0
    money_usd: float = 0.0
    human_attention: int = 0  # 0 none, 1 notify, 2 approval required

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "seconds": self.seconds,
            "money_usd": self.money_usd,
            "human_attention": self.human_attention,
        }


@dataclass(slots=True)
class WaitSpec:
    """Semantics that make waiting a first-class, cancellable action."""

    wake_predicates: list[str]
    deadline_epoch: float | None
    expected_evidence: list[str]
    fallback_affordance_id: str | None
    owner: str
    cancellation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "wake_predicates": list(self.wake_predicates),
            "deadline_epoch": self.deadline_epoch,
            "expected_evidence": list(self.expected_evidence),
            "fallback_affordance_id": self.fallback_affordance_id,
            "owner": self.owner,
            "cancellation": self.cancellation,
        }


@dataclass(slots=True)
class ActionAffordance:
    """One candidate next move with everything needed to judge it."""

    affordance_id: str
    target: str
    operation: str
    reason_available: str
    disposition: AffordanceDisposition
    expected_gain: str
    expected_value: float
    cost: CostVector
    risk_tier: int  # 0-4 per the operating contract
    reversibility: str  # "reversible" | "compensable" | "irreversible"
    required_capabilities: list[str]
    required_approvals: list[str]
    preconditions: list[str]
    invalidators: list[str]
    alternatives: list[str]
    expected_terminal_proof: str
    epistemics: EpistemicTag | None = None
    wait: WaitSpec | None = None
    blocked_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "affordance_id": self.affordance_id,
            "target": self.target,
            "operation": self.operation,
            "reason_available": self.reason_available,
            "disposition": self.disposition.value,
            "expected_gain": self.expected_gain,
            "expected_value": self.expected_value,
            "cost": self.cost.to_dict(),
            "risk_tier": self.risk_tier,
            "reversibility": self.reversibility,
            "required_capabilities": list(self.required_capabilities),
            "required_approvals": list(self.required_approvals),
            "preconditions": list(self.preconditions),
            "invalidators": list(self.invalidators),
            "alternatives": list(self.alternatives),
            "expected_terminal_proof": self.expected_terminal_proof,
            "epistemics": self.epistemics.to_dict() if self.epistemics else None,
            "wait": self.wait.to_dict() if self.wait else None,
            "blocked_by": list(self.blocked_by),
        }


def _merged_reasons(cand: ActionAffordance, new_reasons: Iterable[str]) -> list[str]:
    """Pre-existing ``blocked_by`` first, then new gate reasons, deduplicated.

    Order-preserving dedup makes gating idempotent: re-gating already-gated
    output never duplicates a reason.
    """
    return list(dict.fromkeys([*cand.blocked_by, *new_reasons]))


def apply_hard_gates(
    candidates: Sequence[ActionAffordance],
    *,
    halted: bool = False,
    capabilities_held: frozenset[str] = frozenset(),
    approvals_granted: frozenset[str] = frozenset(),
    live_blockers: Mapping[str, Sequence[str]] | None = None,
) -> list[ActionAffordance]:
    """Downgrade dispositions per live authority BEFORE any ranking happens.

    Never removes items: a blocked action stays visible as blocked, which is
    the point — the agent sees what it cannot do and why. Inputs are not
    mutated; downgraded copies are returned, with pre-existing ``blocked_by``
    entries preserved first and all reasons order-preserving-deduplicated, so
    gating is idempotent: re-gating already-gated output changes nothing.

    Precedence: a live-authority prohibition (a live blocker, or halt on an
    actionable non-exempt candidate) downgrades to BLOCKED and dominates a
    capability/approval lack — BLOCKED survives situation-frame truncation,
    so a live blocker can never be silently dropped under budget pressure —
    while a pure lack of required capabilities or approvals downgrades to
    UNAVAILABLE (approvals are a hard gate, not advice). Already-non-
    actionable candidates are terminal for the halt gate and pass through
    unchanged unless a live blocker names them, which (re)classifies them
    BLOCKED. A live blocker downgrades a still-actionable candidate even when
    its reason string is already recorded in ``blocked_by`` — a recorded
    reason is not the same as an applied downgrade. Gates only ever
    downgrade: re-gating with a relaxed gate (e.g. after a halt lifts) never
    recovers a candidate — recompute affordances from their original source
    to recover. Diagnostics are consequently path-dependent: gates applied
    across successive passes may record fewer ``blocked_by`` reasons than one
    combined pass (a terminal candidate skips later halt marking), though the
    non-actionable classification itself is identical either way.
    """
    blockers_by_id = dict(live_blockers or {})
    gated: list[ActionAffordance] = []
    for cand in candidates:
        live_reasons: list[str] = list(blockers_by_id.get(cand.affordance_id, ()))
        missing = [c for c in cand.required_capabilities if c not in capabilities_held]
        unapproved = [a for a in cand.required_approvals if a not in approvals_granted]
        non_actionable = cand.disposition in _NON_ACTIONABLE
        halt_applies = halted and not non_actionable and cand.disposition not in _HALT_EXEMPT
        prohibitions = [*live_reasons, *(["halt"] if halt_applies else [])]
        lacks = [
            *(f"missing capability: {c}" for c in missing),
            *(f"missing approval: {a}" for a in unapproved),
        ]
        if prohibitions:
            gated.append(
                replace(
                    cand,
                    disposition=AffordanceDisposition.BLOCKED,
                    blocked_by=_merged_reasons(cand, [*prohibitions, *lacks]),
                )
            )
        elif non_actionable:
            gated.append(cand)
        elif lacks:
            gated.append(
                replace(
                    cand,
                    disposition=AffordanceDisposition.UNAVAILABLE,
                    blocked_by=_merged_reasons(cand, lacks),
                )
            )
        else:
            gated.append(cand)
    return gated


def _frontier_key(a: ActionAffordance) -> tuple[float, float, float, float, float, float]:
    """All-minimized objective tuple (value negated so higher value is better)."""
    return (
        -a.expected_value,
        float(a.cost.tokens),
        a.cost.seconds,
        a.cost.money_usd,
        float(a.risk_tier),
        float(a.cost.human_attention),
    )


def _dominates(a: ActionAffordance, b: ActionAffordance) -> bool:
    ka, kb = _frontier_key(a), _frontier_key(b)
    return all(x <= y for x, y in zip(ka, kb)) and ka != kb


def pareto_frontier(candidates: Sequence[ActionAffordance]) -> list[ActionAffordance]:
    """Nondominated actionable candidates; blocked/unavailable never rank."""
    actionable = [c for c in candidates if c.disposition in _ACTIONABLE]
    return [c for c in actionable if not any(_dominates(o, c) for o in actionable)]


def from_work_recommendation(
    rec: WorkRecommendation,
    *,
    live_blockers: Sequence[str] = (),
) -> ActionAffordance:
    """Adapt an existing WorkRecommendation into an explicit affordance.

    The recommendation's own view of actionability (DERIVED authority) is
    reconciled against live blockers (OBSERVED authority): a clean rec that a
    live authority contradicts becomes CONFLICTED, never silently 'ready'.

    WorkRecommendation carries no cost or risk data, so adapter-produced
    affordances default to a zero CostVector and risk_tier 0; among such
    candidates alone the frontier degenerates to highest ``score.total``.
    Callers with real cost/risk estimates should set them on the result for
    the frontier's tradeoff axes to bite.
    """
    claimed_tag = EpistemicTag(
        state=KnowledgeState.ESTIMATED,
        provenance=ProvenanceClass.DERIVED,
        basis=[f"work:rec:{rec.item_id}"],
    )
    rec_actionable = not rec.blockers
    if live_blockers:
        live_tag = EpistemicTag(
            state=KnowledgeState.KNOWN,
            provenance=ProvenanceClass.OBSERVED,
            basis=[f"live:{b}" for b in live_blockers],
        )
        _, tag = reconcile(rec_actionable, claimed_tag, False, live_tag)
    else:
        tag = claimed_tag

    blocked = list(dict.fromkeys([*rec.blockers, *live_blockers]))
    return ActionAffordance(
        affordance_id=f"work:{rec.item_id}",
        target=rec.item_id,
        operation=rec.action,
        reason_available="; ".join(rec.rationale) or "recommended by work broker",
        disposition=AffordanceDisposition.BLOCKED if blocked else AffordanceDisposition.CONDITIONAL,
        expected_gain=f"{rec.classification} ({rec.priority})",
        expected_value=rec.score.total,
        cost=CostVector(),
        risk_tier=0,
        reversibility="reversible",
        required_capabilities=[],
        required_approvals=[],
        preconditions=[],
        invalidators=list(live_blockers),
        alternatives=[],
        expected_terminal_proof="work item transitions per its acceptance criteria",
        epistemics=tag,
        blocked_by=blocked,
    )
