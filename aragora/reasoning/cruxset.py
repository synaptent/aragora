"""CruxSet contract — the load-bearing-disagreement output of the debate path.

This module defines the AGT-01 / DIC-15 contract that the existing
:class:`aragora.reasoning.crux_detector.CruxDetector` will emit on the
production debate path once the AGT-* upper-layer gate opens. The shape
mirrors the spec in ``docs/plans/EPISTEMIC_CI_AND_CRUX_ENGINE.md`` and
``docs/plans/AGENT_CIVILIZATION_SUBSTRATE.md`` so the AGT-05 reputation
flow has a concrete structure to wire against.

A CruxSet is a signed, content-addressed bundle that captures, for a
specific question:

- the candidate decision (when one was reached)
- the 3-5 load-bearing disagreements that would flip the decision if
  resolved differently (the cruxes themselves)
- the evidence gaps surfacing each crux
- the counterfactual hooks that quantify why each crux is load-bearing
- the verifier candidates that could later resolve each crux

The bundle is designed to be ingestable by AGT-05 as a
``StakeableClaim`` of domain ``crux_resolution``, and by AGT-04 / AGT-03
as the source of agent positions on contested questions.

This module is contract-only: it does not run debates, does not invoke
:class:`CruxDetector`, and does not emit anything by itself. The
flag-gated emitter that ties the two together lives in
:mod:`aragora.reasoning.cruxset_emission`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable

CRUXSET_SCHEMA_VERSION = "1.0"


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class CruxPosition:
    """One side of a crux — a position taken by one or more agents."""

    side: str
    agents: tuple[str, ...] = field(default_factory=tuple)
    rationale: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "agents": list(self.agents),
            "rationale": self.rationale,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CruxPosition":
        return cls(
            side=str(data["side"]),
            agents=tuple(str(a) for a in (data.get("agents") or [])),
            rationale=str(data.get("rationale") or ""),
        )


@dataclass(frozen=True)
class Crux:
    """A single load-bearing disagreement.

    Field shape matches the EPISTEMIC_CI_AND_CRUX_ENGINE.md spec for a
    crux:

    - ``crux_id``: stable identifier for the crux within its CruxSet
    - ``statement``: the claim or assumption that is load-bearing
    - ``positions``: the agent positions on this crux (typically 2)
    - ``load_bearing_score``: counterfactual-validated impact in [0, 1]
    - ``evidence_gaps``: machine-readable list of missing evidence items
    - ``counterfactual``: short note explaining why flipping this crux
      would change the decision
    - ``candidate_verifier``: pointer to a verifier or doc that could
      later resolve this crux (free-form for now; AGT-05 will tighten)
    """

    crux_id: str
    statement: str
    positions: tuple[CruxPosition, ...]
    load_bearing_score: float
    evidence_gaps: tuple[str, ...] = field(default_factory=tuple)
    counterfactual: str = ""
    candidate_verifier: str = ""

    def __post_init__(self) -> None:
        if not (0.0 <= self.load_bearing_score <= 1.0):
            raise ValueError("load_bearing_score must be in [0, 1]")
        if not str(self.crux_id).strip():
            raise ValueError("crux_id must be non-empty")
        if not str(self.statement).strip():
            raise ValueError("statement must be non-empty")

    def to_json(self) -> dict[str, Any]:
        return {
            "crux_id": self.crux_id,
            "statement": self.statement,
            "positions": [p.to_json() for p in self.positions],
            "load_bearing_score": round(self.load_bearing_score, 6),
            "evidence_gaps": list(self.evidence_gaps),
            "counterfactual": self.counterfactual,
            "candidate_verifier": self.candidate_verifier,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Crux":
        return cls(
            crux_id=str(data["crux_id"]),
            statement=str(data["statement"]),
            positions=tuple(CruxPosition.from_json(p) for p in (data.get("positions") or [])),
            load_bearing_score=float(data["load_bearing_score"]),
            evidence_gaps=tuple(str(g) for g in (data.get("evidence_gaps") or [])),
            counterfactual=str(data.get("counterfactual") or ""),
            candidate_verifier=str(data.get("candidate_verifier") or ""),
        )


@dataclass(frozen=True)
class CruxSet:
    """A signed bundle of cruxes for one question.

    ``cruxset_id`` is content-addressed from the question text and the
    ranked crux list so identical analyses deduplicate. ``checksum``
    is the SHA-256 of the canonical JSON serialization, used to verify
    that a stored or transmitted CruxSet has not been tampered with.

    ``decision`` is the candidate decision the debate reached (when one
    was reached); for crux-finder mode debates, ``decision`` may be
    None when the explicit goal is to surface disagreement rather than
    converge.
    """

    cruxset_id: str
    schema_version: str
    question: str
    decision: str | None
    cruxes: tuple[Crux, ...]
    evidence_gaps: tuple[str, ...]
    counterfactual_notes: tuple[str, ...]
    verifier_candidates: tuple[str, ...]
    receipt_id: str
    provenance: dict[str, Any]
    created_at: str
    checksum: str

    @classmethod
    def build(
        cls,
        *,
        question: str,
        cruxes: Iterable[Crux],
        decision: str | None = None,
        evidence_gaps: Iterable[str] = (),
        counterfactual_notes: Iterable[str] = (),
        verifier_candidates: Iterable[str] = (),
        receipt_id: str = "",
        provenance: dict[str, Any] | None = None,
        created_at: str | None = None,
        schema_version: str | None = None,
    ) -> "CruxSet":
        """Build a CruxSet, computing ``cruxset_id`` and ``checksum``.

        ``schema_version`` defaults to :data:`CRUXSET_SCHEMA_VERSION`. Pass the
        original value when *rebuilding* an existing set (e.g. enrichment) so a
        deserialized older- or future-version set is not silently restamped with
        the current version — ``from_dict`` preserves what it read, and a rebuild
        must not quietly disagree with it.
        """
        question_str = (question or "").strip()
        if not question_str:
            raise ValueError("question must be non-empty")

        cruxes_tuple = tuple(cruxes)
        if len(cruxes_tuple) == 0:
            raise ValueError("CruxSet requires at least one crux")
        # Sort by load_bearing_score desc; ties broken by crux_id asc for determinism
        cruxes_sorted = tuple(
            sorted(
                cruxes_tuple,
                key=lambda c: (-c.load_bearing_score, c.crux_id),
            )
        )

        cruxset_id = _build_cruxset_id(question_str, cruxes_sorted)
        provenance_dict = dict(provenance or {})
        timestamp = created_at or _utc_now_iso()

        # Build a draft and then compute the checksum over its canonical form.
        draft = cls(
            cruxset_id=cruxset_id,
            schema_version=schema_version or CRUXSET_SCHEMA_VERSION,
            question=question_str,
            decision=decision,
            cruxes=cruxes_sorted,
            evidence_gaps=tuple(str(g).strip() for g in evidence_gaps if str(g).strip()),
            counterfactual_notes=tuple(
                str(n).strip() for n in counterfactual_notes if str(n).strip()
            ),
            verifier_candidates=tuple(
                str(v).strip() for v in verifier_candidates if str(v).strip()
            ),
            receipt_id=str(receipt_id or ""),
            provenance=provenance_dict,
            created_at=timestamp,
            checksum="",
        )
        return draft._with_checksum()

    def _with_checksum(self) -> "CruxSet":
        canonical = self._canonical_payload()
        digest = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return CruxSet(
            cruxset_id=self.cruxset_id,
            schema_version=self.schema_version,
            question=self.question,
            decision=self.decision,
            cruxes=self.cruxes,
            evidence_gaps=self.evidence_gaps,
            counterfactual_notes=self.counterfactual_notes,
            verifier_candidates=self.verifier_candidates,
            receipt_id=self.receipt_id,
            provenance=self.provenance,
            created_at=self.created_at,
            checksum=digest,
        )

    def _canonical_payload(self) -> dict[str, Any]:
        return {
            "cruxset_id": self.cruxset_id,
            "schema_version": self.schema_version,
            "question": self.question,
            "decision": self.decision,
            "cruxes": [c.to_json() for c in self.cruxes],
            "evidence_gaps": list(self.evidence_gaps),
            "counterfactual_notes": list(self.counterfactual_notes),
            "verifier_candidates": list(self.verifier_candidates),
            "receipt_id": self.receipt_id,
            "provenance": self.provenance,
            "created_at": self.created_at,
        }

    def verify_checksum(self) -> bool:
        """Recompute the checksum and compare to the stored value."""
        recomputed = (
            CruxSet(
                cruxset_id=self.cruxset_id,
                schema_version=self.schema_version,
                question=self.question,
                decision=self.decision,
                cruxes=self.cruxes,
                evidence_gaps=self.evidence_gaps,
                counterfactual_notes=self.counterfactual_notes,
                verifier_candidates=self.verifier_candidates,
                receipt_id=self.receipt_id,
                provenance=self.provenance,
                created_at=self.created_at,
                checksum="",
            )
            ._with_checksum()
            .checksum
        )
        return recomputed == self.checksum

    def to_json(self) -> dict[str, Any]:
        payload = self._canonical_payload()
        payload["checksum"] = self.checksum
        return payload

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CruxSet":
        return cls(
            cruxset_id=str(data["cruxset_id"]),
            schema_version=str(data.get("schema_version") or CRUXSET_SCHEMA_VERSION),
            question=str(data["question"]),
            decision=(None if data.get("decision") is None else str(data["decision"])),
            cruxes=tuple(Crux.from_json(c) for c in (data.get("cruxes") or [])),
            evidence_gaps=tuple(str(g) for g in (data.get("evidence_gaps") or [])),
            counterfactual_notes=tuple(str(n) for n in (data.get("counterfactual_notes") or [])),
            verifier_candidates=tuple(str(v) for v in (data.get("verifier_candidates") or [])),
            receipt_id=str(data.get("receipt_id") or ""),
            provenance=dict(data.get("provenance") or {}),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            checksum=str(data.get("checksum") or ""),
        )


def _build_cruxset_id(question: str, cruxes: tuple[Crux, ...]) -> str:
    material = json.dumps(
        {
            "question": question,
            "cruxes": [c.crux_id for c in cruxes],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"crxset_{digest}"


def build_cruxset_from_analysis(
    *,
    question: str,
    analysis_payload: dict[str, Any],
    decision: str | None = None,
    receipt_id: str = "",
    provenance: dict[str, Any] | None = None,
    max_cruxes: int = 5,
    counterfactuals_by_claim_id: dict[str, str] | None = None,
) -> CruxSet:
    """Convert a :class:`CruxAnalysisResult` payload into a CruxSet.

    The input is the dict returned by ``CruxAnalysisResult.to_dict()``
    (defined in :mod:`aragora.reasoning.crux_detector`). This function
    is the seam between the existing analysis output and the new
    contract: it does NOT call :class:`CruxDetector` itself, so it is
    safe to use in tests with mocked analysis payloads.

    Cruxes are ranked by ``crux_score`` (which the analyser already
    composes from influence × disagreement × uncertainty × centrality
    × resolution_impact). The first ``max_cruxes`` are taken; the
    ``load_bearing_score`` is the analyser's ``crux_score``.

    ``counterfactuals_by_claim_id`` is the DIC-15 counterfactual hook: a
    mapping from ``claim_id`` to a human-readable counterfactual string
    computed by the crux-finder validation pass (see
    :func:`~aragora.reasoning.cruxset_emission.maybe_emit_cruxset_from_finder_result`).
    When supplied, it overrides the default ``resolution_impact`` text so
    the AGT-05 reputation flow and downstream consumers see the richer
    condition/outcome text rather than the bare numeric score.
    """
    raw_cruxes = list(analysis_payload.get("cruxes") or [])
    if not raw_cruxes:
        raise ValueError("analysis_payload contains no cruxes; cannot build CruxSet")

    cf_map: dict[str, str] = counterfactuals_by_claim_id or {}

    cruxes: list[Crux] = []
    for entry in raw_cruxes[:max_cruxes]:
        if not isinstance(entry, dict):
            continue
        # Annotated variable-length: mypy otherwise infers tuple[CruxPosition]
        # from this single-element literal and rejects the append below.
        positions: tuple[CruxPosition, ...] = (
            CruxPosition(
                side="for",
                agents=(str(entry.get("author") or ""),),
                rationale="proposing agent",
            ),
        )
        contesting = entry.get("contesting_agents") or []
        if contesting:
            positions = positions + (
                CruxPosition(
                    side="against",
                    agents=tuple(str(a) for a in contesting),
                    rationale="contesting agents",
                ),
            )
        claim_id = str(entry.get("claim_id") or "")
        # DIC-15 hook: prefer the validation-pass counterfactual when available.
        if claim_id in cf_map:
            counterfactual_text = cf_map[claim_id]
        elif entry.get("resolution_impact") is not None:
            counterfactual_text = (
                f"Resolution impact {round(float(entry.get('resolution_impact') or 0.0), 4)}"
            )
        else:
            counterfactual_text = ""
        cruxes.append(
            Crux(
                crux_id=claim_id,
                statement=str(entry.get("statement") or ""),
                positions=positions,
                load_bearing_score=float(entry.get("crux_score") or 0.0),
                evidence_gaps=tuple(),
                counterfactual=counterfactual_text,
                candidate_verifier="",
            )
        )

    counterfactual_notes = (
        f"avg_uncertainty={round(float(analysis_payload.get('average_uncertainty') or 0.0), 4)}",
        f"convergence_barrier={round(float(analysis_payload.get('convergence_barrier') or 0.0), 4)}",
    )

    return CruxSet.build(
        question=question,
        cruxes=cruxes,
        decision=decision,
        evidence_gaps=(),
        counterfactual_notes=counterfactual_notes,
        verifier_candidates=tuple(
            str(c) for c in (analysis_payload.get("recommended_focus") or [])
        ),
        receipt_id=receipt_id,
        provenance=dict(provenance or {}),
    )


__all__ = [
    "CRUXSET_SCHEMA_VERSION",
    "Crux",
    "CruxPosition",
    "CruxSet",
    "build_cruxset_from_analysis",
]
