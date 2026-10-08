"""Epistemic decay monitor (DIC-20 / #6031).

Evaluates a :class:`~aragora.epistemic.proof_unit.ProofCarryingCodeUnit`
against claim verification results, unresolved crux IDs, and receipt
presence to produce a machine-readable :class:`DecaySignal`.

Reason classes
--------------
failed_claim    — a linked claim failed verification
stale_evidence  — a linked claim is stale
unresolved_crux — a linked crux ID is unresolved
missing_receipt — decision_receipts list is empty
verifier_error  — a claim verification raised an error

Default mode is ``report_only``; the ``decay_policy`` fields on the unit
control escalation to ``repair_required`` or ``fail_closed``.  This module
never mutates state, creates issues, or routes to live dispatch (DIC-21 and
DIC-22 add quarantine and repair on top).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Collection, Iterable

from .claim_verifier import ClaimStatus

if TYPE_CHECKING:
    from .claim_verifier import ClaimResult
    from .constraint_graph import ProofUnitConstraintGraph
    from .proof_unit import ProofCarryingCodeUnit

# Integrity deduction per reason class (summed; clamped to [0, 1]).
_REASON_WEIGHTS: dict[str, float] = {
    "failed_claim": 0.30,
    "stale_evidence": 0.15,
    "unresolved_crux": 0.20,
    "missing_receipt": 0.10,
    "verifier_error": 0.20,
}

_ACTION_RANK = {"report_only": 0, "repair_required": 1, "fail_closed": 2}
_RANK_TO_ACTION = {v: k for k, v in _ACTION_RANK.items()}


def _reject_disabled_world_event_result(result: "ClaimResult") -> None:
    """Fail closed if a world-event result reaches evaluation while disabled."""

    detail = getattr(result, "detail", {}) or {}
    if detail.get("source") != "world_event":
        return

    from .world_event import world_events_enabled

    if not world_events_enabled():
        event_id = detail.get("event_id") or "<unknown>"
        raise RuntimeError(
            "ARAGORA_WORLD_EVENTS_ENABLED is not set; "
            f"world-event claim result {event_id!r} must not propagate to decay evaluation."
        )


@dataclass(frozen=True)
class DecayReason:
    """One reason contributing to integrity deduction."""

    kind: str
    detail: str
    claim_id: str = ""
    crux_id: str = ""

    def to_dict(self) -> dict:
        d: dict = {"kind": self.kind, "detail": self.detail}
        if self.claim_id:
            d["claim_id"] = self.claim_id
        if self.crux_id:
            d["crux_id"] = self.crux_id
        return d


@dataclass
class DecaySignal:
    """Machine-readable decay assessment for one ProofCarryingCodeUnit.

    ``integrity_score`` is 1.0 for a fully healthy unit and 0.0 for
    completely decayed. Each reason deducts from the score; deductions are
    additive and the result is clamped to [0.0, 1.0].

    ``recommended_action`` reflects the most severe policy action triggered
    by any active reason class.  This module never acts on it — action is
    deferred to DIC-21 (quarantine policy).
    """

    code_unit_id: str
    integrity_score: float
    reasons: list[DecayReason] = field(default_factory=list)
    recommended_action: str = "report_only"

    def to_dict(self) -> dict:
        return {
            "code_unit_id": self.code_unit_id,
            "integrity_score": round(self.integrity_score, 4),
            "reasons": [r.to_dict() for r in self.reasons],
            "recommended_action": self.recommended_action,
        }


def evaluate_unit(
    unit: "ProofCarryingCodeUnit",
    claim_results: dict[str, "ClaimResult"] | None = None,
    unresolved_crux_ids: frozenset[str] | None = None,
) -> DecaySignal:
    """Evaluate one ProofCarryingCodeUnit and return a DecaySignal.

    Parameters
    ----------
    unit:
        The code unit to evaluate. Should already have passed ``unit.validate()``.
    claim_results:
        Mapping of ``claim_id → ClaimResult`` from a :class:`ClaimVerifier`
        run.  If omitted, claims with no result are ignored (no deduction).
    unresolved_crux_ids:
        Set of crux IDs currently known to be unresolved.  If omitted, no
        ``unresolved_crux`` reasons are generated.

    Returns
    -------
    :class:`DecaySignal` — report-only, no side effects.
    """
    results: dict[str, "ClaimResult"] = claim_results or {}
    unresolved: frozenset[str] = unresolved_crux_ids or frozenset()

    reasons: list[DecayReason] = []
    deduction = 0.0

    for claim_id in unit.claims:
        result = results.get(claim_id)
        if result is None:
            continue
        _reject_disabled_world_event_result(result)
        if result.status == ClaimStatus.FAIL:
            reasons.append(
                DecayReason(
                    kind="failed_claim",
                    detail=result.message,
                    claim_id=claim_id,
                )
            )
            deduction += _REASON_WEIGHTS["failed_claim"]
        elif result.status == ClaimStatus.STALE:
            reasons.append(
                DecayReason(
                    kind="stale_evidence",
                    detail=result.message,
                    claim_id=claim_id,
                )
            )
            deduction += _REASON_WEIGHTS["stale_evidence"]
        elif result.status == ClaimStatus.ERROR:
            reasons.append(
                DecayReason(
                    kind="verifier_error",
                    detail=result.message,
                    claim_id=claim_id,
                )
            )
            deduction += _REASON_WEIGHTS["verifier_error"]

    for crux_id in unit.linked_crux_ids:
        if crux_id in unresolved:
            reasons.append(
                DecayReason(
                    kind="unresolved_crux",
                    detail=f"Crux {crux_id!r} is unresolved.",
                    crux_id=crux_id,
                )
            )
            deduction += _REASON_WEIGHTS["unresolved_crux"]

    if not unit.decision_receipts:
        reasons.append(
            DecayReason(
                kind="missing_receipt",
                detail="No decision receipts are linked to this code unit.",
            )
        )
        deduction += _REASON_WEIGHTS["missing_receipt"]

    integrity_score = max(0.0, 1.0 - deduction)

    reason_kinds = {r.kind for r in reasons}
    action_rank = 0
    dp = unit.decay_policy
    if "failed_claim" in reason_kinds or "verifier_error" in reason_kinds:
        action_rank = max(action_rank, _ACTION_RANK.get(dp.failed_claim, 0))
    if "stale_evidence" in reason_kinds:
        action_rank = max(action_rank, _ACTION_RANK.get(dp.stale_evidence, 0))
    if "unresolved_crux" in reason_kinds:
        action_rank = max(action_rank, _ACTION_RANK.get(dp.unresolved_crux, 0))

    return DecaySignal(
        code_unit_id=unit.code_unit_id,
        integrity_score=integrity_score,
        reasons=reasons,
        recommended_action=_RANK_TO_ACTION.get(action_rank, "report_only"),
    )


def compute_decay_impact_set(
    graph: "ProofUnitConstraintGraph",
    failing_claim_ids: Collection[str],
    *,
    transitive: bool = False,
    max_depth: int | None = None,
) -> set[str]:
    """Return the set of ``code_unit_id``s impacted by *failing_claim_ids*.

    First live caller of
    :meth:`aragora.epistemic.constraint_graph.ProofUnitConstraintGraph.multi_hop_impact_set`
    (DIC-19, #6838).  Lifts DIC-19 from "scaffolded" to "wired" per the
    audit's classification by giving the constraint graph a real
    decay-pipeline consumer.

    Parameters
    ----------
    graph:
        A :class:`ProofUnitConstraintGraph` over the units in scope.  When
        constructed without ``dependency_edges``, the transitive path is
        identical to the single-hop path — backward-compatible.
    failing_claim_ids:
        The set of claim IDs whose verification has decayed (failed,
        stale, or otherwise unsafe to rely on).
    transitive:
        When ``False`` (default), return only direct claim-owners — the
        same set :func:`evaluate_unit` would generate decay reasons for.
        When ``True``, walk the explicit unit-to-unit dependency edges
        from the graph: if unit A depends on unit B and B's claims fail,
        A is also impacted.
    max_depth:
        Bound on the BFS depth when ``transitive=True``.  ``None``
        (default) is unbounded.  ``max_depth=0`` is equivalent to
        ``transitive=False``.  Ignored when ``transitive=False``.

    Returns
    -------
    A ``set[str]`` of impacted ``code_unit_id``s.  This module does NOT
    mutate the graph, the units, or any quarantine/repair state — that
    decision is deferred to DIC-21/22.

    Notes
    -----
    The graph here is a snapshot — callers reconstruct or persist it
    themselves via :meth:`ProofUnitConstraintGraph.to_dict`.  This
    function is a thin pass-through that establishes the decay-pipeline
    seam; the operator dashboard / repair planner can later call this
    directly with cached graph state without reaching into the constraint
    graph internals.
    """
    if transitive:
        return graph.multi_hop_impact_set(failing_claim_ids, max_depth=max_depth)
    return graph.impact_set(failing_claim_ids)


# ---------------------------------------------------------------------------
# Batch evaluation (DIC-20 / #6031 — batch report path)
# ---------------------------------------------------------------------------


@dataclass
class EpistemicDecayBatchReport:
    """Aggregate result from :func:`evaluate_units`.

    Counts partition ``total``: healthy (score == 1.0 and action != fail_closed),
    degraded (score < 1.0 and action != fail_closed), fail_closed.
    No side effects. The dataclass is always importable; activating the CLI
    monitor is caller-enforced via ``ARAGORA_DECAY_MONITOR_ENABLED``.
    """

    signals: list[DecaySignal] = field(default_factory=list)
    generated_at: str = ""

    @property
    def total(self) -> int:
        return len(self.signals)

    @property
    def healthy_count(self) -> int:
        return sum(
            1
            for s in self.signals
            if s.integrity_score == 1.0 and s.recommended_action != "fail_closed"
        )

    @property
    def degraded_count(self) -> int:
        return sum(
            1
            for s in self.signals
            if s.integrity_score < 1.0 and s.recommended_action != "fail_closed"
        )

    @property
    def fail_closed_count(self) -> int:
        return sum(1 for s in self.signals if s.recommended_action == "fail_closed")

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "total": self.total,
            "healthy_count": self.healthy_count,
            "degraded_count": self.degraded_count,
            "fail_closed_count": self.fail_closed_count,
            "signals": [s.to_dict() for s in self.signals],
        }


def evaluate_units(
    units: "Iterable[ProofCarryingCodeUnit]",
    claim_results: "dict[str, ClaimResult] | None" = None,
    unresolved_crux_ids: "frozenset[str] | None" = None,
    *,
    generated_at: str = "",
) -> EpistemicDecayBatchReport:
    """Batch-evaluate units against shared claim results and crux IDs.

    Returns an :class:`EpistemicDecayBatchReport` — report-only, no side
    effects. ``generated_at`` defaults to current UTC ISO-8601 time.
    """
    from datetime import datetime, timezone

    signals = [
        evaluate_unit(unit, claim_results=claim_results, unresolved_crux_ids=unresolved_crux_ids)
        for unit in units
    ]
    ts = generated_at or datetime.now(timezone.utc).isoformat()
    return EpistemicDecayBatchReport(signals=signals, generated_at=ts)
