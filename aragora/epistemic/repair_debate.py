"""Repair-spec → debate adapter for DIC-22 verified replacement pipeline (#6033).

Bridges a :class:`~aragora.epistemic.repair.RepairSpec` to a lightweight
agent debate and produces a :class:`~aragora.epistemic.crux_receipt.CruxReceipt`.

Invariants:
- Requires ``ARAGORA_REPAIR_PIPELINE_ENABLED`` (inherited from repair.py, default off).
- No live Arena, no queue mutation, no issue creation.
- Callers inject a :class:`RepairDebateAgent` protocol so tests run without
  API keys or network access.
- Output is a receipt-bearing :class:`RepairDebateResult`; no live routing.

Flag gate: ``ARAGORA_REPAIR_PIPELINE_ENABLED`` — same flag as repair.py.
DIC-22 / issue #6033.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from aragora.epistemic.crux_receipt import CruxEntry, CruxReceipt
from aragora.epistemic.repair import RepairSpec, repair_pipeline_enabled


class RepairDebateAgent(Protocol):
    """Minimal agent protocol consumed by :func:`run_repair_debate`.

    Implementations may wrap a real LLM call or return mock data in tests.
    The protocol is deliberately narrow: one ``name`` property and one
    ``evaluate`` method so tests can inject lightweight stubs.
    """

    @property
    def name(self) -> str:
        """Stable identifier for this agent (used in receipt and provenance)."""
        ...

    def evaluate(self, spec: RepairSpec, context: dict[str, Any]) -> dict[str, Any]:
        """Evaluate *spec* and return a dict with keys:

        - ``supports_repair`` (bool) — whether the agent endorses the repair
        - ``crux_candidates`` (list[dict]) — each with ``crux_id``, ``statement``,
          ``load_bearing_score``, ``uncertainty_score``, ``resolution_impact``
        - ``notes`` (str, optional) — free-form rationale

        Missing keys are treated as falsy / empty.
        """
        ...


@dataclass(frozen=True)
class RepairDebateResult:
    """Output of a repair-spec debate.

    ``receipt`` carries the SHA-256-checksummed :class:`CruxReceipt` for
    downstream provenance and audit. ``consensus_reached`` reflects whether
    a majority of agents supported the repair; ``recommended_action`` is the
    bounded string recommendation (never a live routing instruction).
    """

    spec_id: str
    receipt: CruxReceipt
    agent_evaluations: list[dict[str, Any]]
    consensus_reached: bool
    recommended_action: str  # "proceed_with_repair" | "request_human_review"

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "consensus_reached": self.consensus_reached,
            "recommended_action": self.recommended_action,
            "receipt": self.receipt.to_dict(),
            "agent_evaluations": self.agent_evaluations,
        }


def run_repair_debate(
    spec: RepairSpec,
    agents: Sequence[RepairDebateAgent],
    *,
    question_override: str | None = None,
) -> RepairDebateResult:
    """Run a bounded debate over *spec* using *agents* and return a receipted result.

    Requires ``ARAGORA_REPAIR_PIPELINE_ENABLED=1``.  Raises :exc:`RuntimeError`
    otherwise.  Raises :exc:`ValueError` when *agents* is empty.

    No live routing, no queue mutation, no issue creation.  The returned
    :class:`RepairDebateResult` is the sole side-effect; callers decide what
    to do with the receipt.
    """
    if not repair_pipeline_enabled():
        raise RuntimeError(
            "run_repair_debate requires ARAGORA_REPAIR_PIPELINE_ENABLED=1; "
            "set the flag or keep repair_kind='report_only'"
        )
    if not agents:
        raise ValueError("run_repair_debate requires at least one agent")

    question = question_override or (
        f"Is the proposed repair for {spec.code_unit_id!r} (kind={spec.repair_kind!r}) "
        "sound and bounded?"
    )

    context: dict[str, Any] = {
        "code_unit_id": spec.code_unit_id,
        "repair_kind": spec.repair_kind,
        "linked_claims": list(spec.linked_claims),
        "linked_crux_ids": list(spec.linked_crux_ids),
        "validation_commands": list(spec.validation_commands),
    }

    evaluations: list[dict[str, Any]] = []
    for agent in agents:
        ev = dict(agent.evaluate(spec, context))
        ev["agent"] = agent.name
        evaluations.append(ev)

    crux_entries = _collect_crux_entries(spec, evaluations)

    support_count = sum(1 for ev in evaluations if ev.get("supports_repair") is True)
    consensus = support_count > len(evaluations) / 2
    recommended_action = "proceed_with_repair" if consensus else "request_human_review"

    receipt = _build_receipt(spec, question, crux_entries, evaluations, consensus)

    return RepairDebateResult(
        spec_id=spec.spec_id,
        receipt=receipt,
        agent_evaluations=evaluations,
        consensus_reached=consensus,
        recommended_action=recommended_action,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _collect_crux_entries(
    spec: RepairSpec,
    evaluations: list[dict[str, Any]],
) -> list[CruxEntry]:
    """Build the ordered, deduplicated list of :class:`CruxEntry` objects."""
    crux_entries: list[CruxEntry] = []
    entries_by_id: dict[str, CruxEntry] = {}

    for ev in evaluations:
        candidates = ev.get("crux_candidates") or []
        if not isinstance(candidates, list):
            continue
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            cid = str(cand.get("crux_id") or "")
            if not cid:
                continue
            existing = entries_by_id.get(cid)
            if existing is not None:
                if ev["agent"] not in existing.contesting_agents:
                    existing.contesting_agents.append(ev["agent"])
                continue
            entry = CruxEntry(
                crux_id=cid,
                statement=str(cand.get("statement") or ""),
                load_bearing_score=_score_or_default(cand, "load_bearing_score"),
                uncertainty_score=_score_or_default(cand, "uncertainty_score"),
                contesting_agents=[ev["agent"]],
                affected_claims=list(spec.linked_claims),
                resolution_impact=_score_or_default(cand, "resolution_impact"),
            )
            entries_by_id[cid] = entry
            crux_entries.append(entry)

    for crux_id in spec.linked_crux_ids:
        if crux_id in entries_by_id:
            continue
        entry = CruxEntry(
            crux_id=crux_id,
            statement=f"Unresolved crux from decay signal: {crux_id}",
            load_bearing_score=0.7,
            uncertainty_score=0.5,
            contesting_agents=[],
            affected_claims=list(spec.linked_claims),
            resolution_impact=0.5,
        )
        entries_by_id[crux_id] = entry
        crux_entries.append(entry)

    return crux_entries


def _score_or_default(candidate: dict[str, Any], key: str, default: float = 0.5) -> float:
    """Preserve numeric zeroes and bound malformed agent scores to a neutral default."""
    value = candidate.get(key, default)
    if value is None:
        return default
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(score):
        return default
    return min(1.0, max(0.0, score))


def _build_receipt(
    spec: RepairSpec,
    question: str,
    crux_entries: list[CruxEntry],
    evaluations: list[dict[str, Any]],
    consensus: bool,
) -> CruxReceipt:
    """Assemble and checksum the :class:`CruxReceipt`."""
    receipt_id = str(uuid.uuid4())
    debate_id = f"repair-debate-{spec.spec_id}"
    agent_names = [ev["agent"] for ev in evaluations]
    convergence_barrier = 0.0 if consensus else 1.0

    checksum_material = json.dumps(
        {
            "receipt_id": receipt_id,
            "debate_id": debate_id,
            "question": question,
            "cruxes": [c.to_dict() for c in crux_entries],
            "convergence_barrier": round(convergence_barrier, 4),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    checksum = hashlib.sha256(checksum_material.encode("utf-8")).hexdigest()

    return CruxReceipt(
        receipt_id=receipt_id,
        debate_id=debate_id,
        question=question,
        cruxes=crux_entries,
        convergence_barrier=convergence_barrier,
        counterfactuals=[],
        agents=agent_names,
        rounds=1,
        metadata={
            "spec_id": spec.spec_id,
            "code_unit_id": spec.code_unit_id,
            "repair_kind": spec.repair_kind,
            "repair_provenance_hash": spec.provenance_hash,
        },
        checksum=checksum,
    )


__all__ = [
    "RepairDebateAgent",
    "RepairDebateResult",
    "run_repair_debate",
]
