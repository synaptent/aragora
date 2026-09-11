"""Evidence-possibility-control envelopes for agent-facing situation views.

A situation frame separates what is established (evidence envelope) from what
remains materially possible (possibility envelope) from what can be done about
it (control envelope). The load-bearing invariant lives in ``truncate_frame``:

    A high-loss residual cannot disappear because it has a low rank, a low
    posterior, an inconvenient token cost, or because a reranker prefers a
    benign interpretation.

This extends Aragora's dissent-preservation guarantee (ReceiptDissent,
severity-gated dissent) through summarization: budget pressure may drop
low-severity residuals and unavailable affordances, but protected residuals,
blocked affordances, and evidence facts always survive — and when they alone
exceed the budget, the frame is emitted over budget with a truthful
``TruncationReport`` rather than silently thinned.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from aragora.export.decision_receipt import ReceiptDissent
from aragora.reasoning.epistemics import EpistemicTag
from aragora.work.affordances import ActionAffordance, AffordanceDisposition

__all__ = [
    "ControlEnvelope",
    "EvidenceEnvelope",
    "EvidenceFact",
    "PossibilityEnvelope",
    "PossibilityResidual",
    "SituationFrame",
    "TruncationReport",
    "from_receipt_dissents",
    "truncate_frame",
]


@dataclass(slots=True)
class EvidenceFact:
    """A positively established fact with its epistemic tag and references."""

    fact_id: str
    statement: str
    tag: EpistemicTag
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "statement": self.statement,
            "tag": self.tag.to_dict(),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(slots=True)
class PossibilityResidual:
    """An alternative interpretation still consistent with the evidence."""

    residual_id: str
    description: str
    loss_severity: float  # 0.0-1.0: how bad it is if this world is real and ignored
    source: str = ""
    consistent_with_evidence: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "residual_id": self.residual_id,
            "description": self.description,
            "loss_severity": self.loss_severity,
            "source": self.source,
            "consistent_with_evidence": self.consistent_with_evidence,
        }


@dataclass(slots=True)
class EvidenceEnvelope:
    facts: list[EvidenceFact] = field(default_factory=list)
    certified_absences: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": [f.to_dict() for f in self.facts],
            "certified_absences": list(self.certified_absences),
            "assumptions": list(self.assumptions),
        }


@dataclass(slots=True)
class PossibilityEnvelope:
    residuals: list[PossibilityResidual] = field(default_factory=list)
    protected_floor: float = 0.5  # residuals at/above this severity are protected

    def protected(self) -> list[PossibilityResidual]:
        return [r for r in self.residuals if r.loss_severity >= self.protected_floor]

    def to_dict(self) -> dict[str, Any]:
        return {
            "residuals": [r.to_dict() for r in self.residuals],
            "protected_floor": self.protected_floor,
        }


@dataclass(slots=True)
class ControlEnvelope:
    affordances: list[ActionAffordance] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"affordances": [a.to_dict() for a in self.affordances]}


@dataclass(slots=True)
class SituationFrame:
    anchor: dict[str, str]  # repo / commit / branch / cleanliness identity
    evidence: EvidenceEnvelope
    possibility: PossibilityEnvelope
    control: ControlEnvelope
    generated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor": dict(self.anchor),
            "evidence": self.evidence.to_dict(),
            "possibility": self.possibility.to_dict(),
            "control": self.control.to_dict(),
            "generated_at": self.generated_at,
        }


@dataclass(slots=True)
class TruncationReport:
    """Truthful account of what a budget cut actually did."""

    emitted_bytes: int
    budget_bytes: int
    dropped_residuals: int
    dropped_affordances: int
    over_budget: bool
    protected_retained: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "emitted_bytes": self.emitted_bytes,
            "budget_bytes": self.budget_bytes,
            "dropped_residuals": self.dropped_residuals,
            "dropped_affordances": self.dropped_affordances,
            "over_budget": self.over_budget,
            "protected_retained": self.protected_retained,
        }


def from_receipt_dissents(dissents: Iterable[ReceiptDissent]) -> list[PossibilityResidual]:
    """Adapt receipt dissent records into possibility residuals."""
    residuals: list[PossibilityResidual] = []
    for i, d in enumerate(dissents):
        parts = ["; ".join(d.reasons)] if d.reasons else []
        if d.alternative:
            parts.append(f"alternative: {d.alternative}")
        residuals.append(
            PossibilityResidual(
                residual_id=f"dissent:{d.agent}:{i}",
                description=f"[{d.type}] " + " | ".join(parts),
                loss_severity=d.severity,
                source=d.agent,
            )
        )
    return residuals


def _frame_bytes(frame: SituationFrame) -> int:
    return len(json.dumps(frame.to_dict(), separators=(",", ":")).encode("utf-8"))


def truncate_frame(
    frame: SituationFrame, budget_bytes: int
) -> tuple[SituationFrame, TruncationReport]:
    """Cut the frame down toward ``budget_bytes`` without losing protection.

    Drop order: unprotected residuals (lowest severity first), then
    UNAVAILABLE affordances. Protected residuals, all other affordances
    (notably BLOCKED ones), evidence facts, and the anchor are never dropped.
    If the protected core alone exceeds the budget the frame is returned
    over budget with a truthful report — never silently thinned.
    """
    dropped_residuals = 0
    dropped_affordances = 0

    current = frame
    if _frame_bytes(current) > budget_bytes:
        floor = current.possibility.protected_floor
        original_order = list(current.possibility.residuals)
        keep = sorted(original_order, key=lambda r: r.loss_severity)
        while keep and _frame_bytes(current) > budget_bytes and keep[0].loss_severity < floor:
            keep.pop(0)
            dropped_residuals += 1
            current = replace(
                current,
                possibility=replace(current.possibility, residuals=list(keep)),
            )
        if dropped_residuals:
            # Survivors keep the caller's ordering; drop order was only a
            # severity policy, not a presentation change. Same elements mean
            # the same serialized byte count, so mid-loop measurements hold.
            # Keyed on object identity, not residual_id: duplicate ids must
            # not resurrect a dropped residual.
            kept = {id(r) for r in keep}
            current = replace(
                current,
                possibility=replace(
                    current.possibility,
                    residuals=[r for r in original_order if id(r) in kept],
                ),
            )

    if _frame_bytes(current) > budget_bytes:
        affs = list(current.control.affordances)
        removable = [a for a in affs if a.disposition is AffordanceDisposition.UNAVAILABLE]
        while removable and _frame_bytes(current) > budget_bytes:
            victim = removable.pop()
            affs.remove(victim)
            dropped_affordances += 1
            current = replace(current, control=ControlEnvelope(affordances=list(affs)))

    emitted = _frame_bytes(current)
    return current, TruncationReport(
        emitted_bytes=emitted,
        budget_bytes=budget_bytes,
        dropped_residuals=dropped_residuals,
        dropped_affordances=dropped_affordances,
        over_budget=emitted > budget_bytes,
        protected_retained=len(current.possibility.protected()),
    )
