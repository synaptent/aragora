"""DIC-17: follow-up-issue proposals from load-bearing cruxes and failed claims.

This module is the bridge between the AGT-01 CruxSet output and the
AGT-05 failed-claim output on one side, and the swarm's boss-ready
queue on the other. It **proposes** follow-up issues — it does not
file them. Filing is an explicit separate step gated on both
``ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED`` and whatever queue-governance
the caller enforces.

Acceptance shape per docs/plans/EPISTEMIC_CI_AND_CRUX_ENGINE.md
§DIC-17:

- one failure (crux or losing claim) creates AT MOST one bounded
  proposal — the caller is responsible for dedup via ``source_key``
- generated proposals DO NOT receive ``boss-ready`` unless the
  current tranche permits them (we always emit without that label;
  the proof-first reconciler in scripts/reconcile_proof_first_queue.py
  will strip it if anything else ever adds it)
- no broad restock behavior — a proposal is a single targeted issue
  with specific body text linking back to the originating crux/claim
- test coverage for queue-governance constraints

The module is shape-only. It imports :class:`Crux` and :class:`CruxSet`
from :mod:`aragora.reasoning.cruxset`, and :class:`StakeableClaim`,
:class:`ResolvedClaim`, :class:`ReputationDelta` from
:mod:`aragora.reputation.types` (lazy-imported to avoid pulling those
modules just to construct a proposal shape).
"""

from __future__ import annotations

from collections.abc import Iterable

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.epistemic.coherence import CoherenceIssue
    from aragora.epistemic.repair import RepairSpec
    from aragora.reasoning.cruxset import Crux, CruxSet
    from aragora.reputation.types import (
        ReputationDelta,
        ResolvedClaim,
        StakeableClaim,
    )

# DIC-17 default thresholds
DEFAULT_CRUX_LOAD_BEARING_THRESHOLD = 0.6
DEFAULT_DELTA_LOSS_THRESHOLD = -10.0
MAX_BODY_STATEMENT_CHARS = 800


_BOSS_READY_LABEL = "boss-ready"


def _is_boss_ready_label(label: object) -> bool:
    """True when *label* spells ``boss-ready`` under any case or surrounding whitespace.

    The queue-governance invariant is about the label GitHub would apply, and
    GitHub label matching is case-insensitive, so ``"Boss-Ready"`` or
    ``" boss-ready "`` must be treated exactly like the canonical spelling.
    """
    return str(label).strip().casefold() == _BOSS_READY_LABEL


def _without_boss_ready(labels: Iterable[str]) -> tuple[str, ...]:
    """Return *labels* sorted, with every ``boss-ready`` variant removed."""
    return tuple(sorted(label for label in labels if not _is_boss_ready_label(label)))


@dataclass(frozen=True)
class FollowupProposal:
    """A proposed bounded follow-up issue.

    - ``source_kind``: ``"crux"``, ``"failed_claim"``, or ``"coherence_issue"``
    - ``source_key``: stable dedup key; callers should skip proposals
      whose source_key they have already filed
    - ``labels``: intentionally excludes ``boss-ready`` by default;
      the proof-first reconciler strips it anyway if it is added by
      mistake
    - ``rationale``: short human-readable reason for the proposal
    - ``provenance``: machine-readable links back to the originating
      artifact (cruxset_id, crux_id, claim_id, resolution_id)
    """

    source_kind: str
    source_key: str
    title: str
    body: str
    labels: tuple[str, ...]
    rationale: str
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_kind not in {"crux", "failed_claim", "coherence_issue", "repair_spec"}:
            raise ValueError(f"unsupported source_kind: {self.source_kind!r}")
        if not str(self.source_key).strip():
            raise ValueError("source_key must be non-empty")
        if not str(self.title).strip():
            raise ValueError("title must be non-empty")
        if not str(self.body).strip():
            raise ValueError("body must be non-empty")
        if any(_is_boss_ready_label(label) for label in self.labels):
            raise ValueError(
                "follow-up proposals must NOT carry boss-ready label (queue-governance invariant)"
            )

    def to_gh_create_args(self, *, repo: str) -> list[str]:
        """Return the gh-CLI arguments that would file this proposal.

        Intended for callers that choose to file. This method does NOT
        invoke gh itself — it returns the args as a list so callers
        have full control over whether/when to file.
        """
        args = ["issue", "create", "--repo", repo, "--title", self.title, "--body", self.body]
        for label in self.labels:
            args.extend(["--label", label])
        return args


# ---------------------------------------------------------------------------
# Crux → proposal
# ---------------------------------------------------------------------------


def _source_key(prefix: str, identifier: str) -> str:
    material = f"{prefix}|{identifier}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _truncate(text: str, limit: int = MAX_BODY_STATEMENT_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def propose_followup_for_crux(
    crux: "Crux",
    *,
    cruxset_id: str = "",
    question: str = "",
    load_bearing_threshold: float = DEFAULT_CRUX_LOAD_BEARING_THRESHOLD,
    extra_labels: tuple[str, ...] = (),
) -> FollowupProposal | None:
    """Propose exactly one bounded follow-up issue for a single crux, or None.

    Returns ``None`` when ``crux.load_bearing_score`` is below
    ``load_bearing_threshold`` — not all cruxes merit a bounded
    follow-up issue; only the load-bearing ones.
    """
    if not (0.0 <= load_bearing_threshold <= 1.0):
        raise ValueError("load_bearing_threshold must be in [0, 1]")
    if crux.load_bearing_score < load_bearing_threshold:
        return None

    statement = _truncate(str(crux.statement))
    title = f"[DIC-17] Resolve load-bearing crux: {statement[:80]}".strip()
    if len(title) > 140:
        title = title[:139] + "…"

    body_lines = [
        "## Goal",
        "Resolve a load-bearing crux surfaced by the Arena debate path.",
        "",
        "## Crux",
        f"- statement: {statement}",
        f"- load_bearing_score: {crux.load_bearing_score:.3f}",
    ]
    if crux.counterfactual:
        body_lines.extend(
            [
                "",
                "## Counterfactual",
                crux.counterfactual.strip(),
            ]
        )
    if crux.evidence_gaps:
        body_lines.extend(["\n## Evidence gaps"])
        body_lines.extend(f"- {gap.strip()}" for gap in crux.evidence_gaps if gap.strip())
    if crux.candidate_verifier:
        body_lines.extend(
            [
                "",
                "## Candidate verifier",
                crux.candidate_verifier.strip(),
            ]
        )
    body_lines.extend(
        [
            "",
            "## Provenance",
            "- source: DIC-17 crux follow-up bridge",
            f"- crux_id: {crux.crux_id}",
            f"- cruxset_id: {cruxset_id or '(n/a)'}",
            f"- question: {_truncate(question, 200) or '(n/a)'}",
            "",
            "## Queue policy",
            "This issue is a DIC-17 proposal. It MUST NOT carry `boss-ready` unless the "
            "current tranche in `docs/status/NEXT_STEPS_CANONICAL.md` explicitly permits "
            "it. The proof-first reconciler in `scripts/reconcile_proof_first_queue.py` "
            "will strip the label if it is added outside the permitted lane.",
        ]
    )

    labels = _without_boss_ready({"epistemic", "crux", *extra_labels})
    source_key = _source_key("crux", f"{cruxset_id}|{crux.crux_id}" if cruxset_id else crux.crux_id)

    return FollowupProposal(
        source_kind="crux",
        source_key=source_key,
        title=title,
        body="\n".join(body_lines),
        labels=labels,
        rationale=(
            f"load_bearing_score={crux.load_bearing_score:.3f} >= {load_bearing_threshold:.3f}"
        ),
        provenance={
            "crux_id": crux.crux_id,
            "cruxset_id": cruxset_id,
            "load_bearing_score": round(crux.load_bearing_score, 6),
        },
    )


def propose_followup_for_cruxset(
    cruxset: "CruxSet",
    *,
    top_k: int = 1,
    load_bearing_threshold: float = DEFAULT_CRUX_LOAD_BEARING_THRESHOLD,
    extra_labels: tuple[str, ...] = (),
) -> list[FollowupProposal]:
    """Propose up to ``top_k`` bounded follow-ups for the top cruxes in a set.

    Cruxes in a :class:`CruxSet` are already sorted by
    ``load_bearing_score`` descending; this function walks the first
    ``top_k`` and emits a proposal for each that clears the threshold.
    """
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    out: list[FollowupProposal] = []
    for crux in cruxset.cruxes[:top_k]:
        proposal = propose_followup_for_crux(
            crux,
            cruxset_id=cruxset.cruxset_id,
            question=cruxset.question,
            load_bearing_threshold=load_bearing_threshold,
            extra_labels=extra_labels,
        )
        if proposal is not None:
            out.append(proposal)
    return out


# ---------------------------------------------------------------------------
# Failed claim → proposal
# ---------------------------------------------------------------------------


def propose_followup_for_failed_claim(
    claim: "StakeableClaim",
    resolved: "ResolvedClaim",
    delta: "ReputationDelta",
    *,
    delta_loss_threshold: float = DEFAULT_DELTA_LOSS_THRESHOLD,
    extra_labels: tuple[str, ...] = (),
) -> FollowupProposal | None:
    """Propose exactly one bounded follow-up issue for a failed claim, or None.

    Returns ``None`` unless:
    - ``resolved.outcome`` is ``"yes"`` or ``"no"`` (inconclusive /
      invalid outcomes do not merit follow-up)
    - ``delta.delta <= delta_loss_threshold`` (only sharp losses
      trigger a follow-up; small miscalibrations do not)

    The proposal captures the claim, resolution, delta, and scoring
    rule so an operator can decide whether to turn it into actionable
    work or mark it as a known-hard domain.
    """
    if resolved.outcome not in {"yes", "no"}:
        return None
    if delta.delta > delta_loss_threshold:
        return None

    title = f"[DIC-17] Investigate high-loss prediction: {claim.agent_id}/{claim.domain}"
    if len(title) > 140:
        title = title[:139] + "…"

    body_lines = [
        "## Goal",
        "Investigate a sharply-losing prediction from the AGT-05 settlement flow.",
        "",
        "## Claim",
        f"- agent_id: {claim.agent_id}",
        f"- domain: {claim.domain}",
        f"- statement: {_truncate(claim.statement)}",
        f"- position: {claim.position}",
    ]
    if claim.predicted_probability is not None:
        body_lines.append(f"- predicted_probability: {claim.predicted_probability:.3f}")
    body_lines.extend(
        [
            f"- stake_units: {claim.stake_units}",
            f"- resolution_source: {claim.resolution_source}",
            f"- resolution_id: {claim.resolution_id}",
            "",
            "## Resolution",
            f"- outcome: {resolved.outcome}",
            f"- resolved_at: {resolved.resolved_at}",
            f"- source: {resolved.resolution_source}",
            "",
            "## Settlement",
            f"- scoring_rule: {delta.scoring_rule}",
            f"- delta: {delta.delta:+.3f} (threshold: <= {delta_loss_threshold:+.1f})",
            f"- delta_id: {delta.delta_id}",
            "",
            "## Provenance",
            "- source: DIC-17 failed-claim follow-up bridge",
            f"- claim_id: {claim.claim_id}",
            "",
            "## Queue policy",
            "This issue is a DIC-17 proposal. It MUST NOT carry `boss-ready` unless the "
            "current tranche in `docs/status/NEXT_STEPS_CANONICAL.md` explicitly permits "
            "it. The proof-first reconciler in `scripts/reconcile_proof_first_queue.py` "
            "will strip the label if it is added outside the permitted lane.",
        ]
    )

    labels = _without_boss_ready({"epistemic", "failed-claim", *extra_labels})
    source_key = _source_key("failed_claim", delta.delta_id)

    return FollowupProposal(
        source_kind="failed_claim",
        source_key=source_key,
        title=title,
        body="\n".join(body_lines),
        labels=labels,
        rationale=(
            f"delta={delta.delta:+.3f} <= {delta_loss_threshold:+.1f} "
            f"(agent {claim.agent_id} in {claim.domain})"
        ),
        provenance={
            "claim_id": claim.claim_id,
            "resolution_id": claim.resolution_id,
            "delta_id": delta.delta_id,
            "agent_id": claim.agent_id,
            "domain": claim.domain,
            "delta": round(delta.delta, 6),
        },
    )


# ---------------------------------------------------------------------------
# Coherence issue → proposal  (DIC-26 → DIC-17 bridge)
# ---------------------------------------------------------------------------


def propose_followup_for_coherence_issue(
    issue: "CoherenceIssue",
    *,
    source_context: str = "",
    extra_labels: tuple[str, ...] = (),
) -> FollowupProposal | None:
    """Propose exactly one bounded follow-up issue for a CoherenceIssue, or None.

    Returns ``None`` for ``severity="warning"`` issues — warning-level
    incoherence (mild confidence rot, single-evidence conflicts) does
    not automatically merit actionable queue work. Only ``severity="error"``
    (hard contradictions, deep confidence rot) produces a proposal.

    This implements the DIC-26 acceptance criterion: "Output flows
    through DIC-17 bridge only when explicitly enabled" — this function
    is the bridge side; the caller controls whether to invoke it.

    The ``boss-ready`` label is always excluded; the proof-first
    reconciler will strip it if ever added externally.
    """
    if issue.severity != "error":
        return None

    kind_slug = {
        "contradiction": "contradiction",
        "evidence_conflict": "evidence-conflict",
        "confidence_rot": "confidence-rot",
    }.get(issue.kind.value, issue.kind.value)

    belief_ids_excerpt = ", ".join(str(b) for b in list(issue.belief_ids)[:3])
    if len(issue.belief_ids) > 3:
        belief_ids_excerpt += f" (+{len(issue.belief_ids) - 3})"

    title = f"[DIC-26] Resolve coherence {issue.kind.value}: [{belief_ids_excerpt[:55]}]"
    if len(title) > 140:
        title = title[:139] + "…"

    body_lines = [
        "## Goal",
        f"Resolve a {issue.kind.value} surfaced by the DIC-26 Belief Coherence Monitor.",
        "",
        "## Incoherence",
        f"- kind: {issue.kind.value}",
        f"- severity: {issue.severity}",
        f"- belief_ids: {', '.join(str(b) for b in issue.belief_ids)}",
        "",
        "## Detail",
        _truncate(issue.detail),
    ]
    if source_context:
        body_lines.extend(["", "## Source context", _truncate(source_context, 200)])
    body_lines.extend(
        [
            "",
            "## Provenance",
            "- source: DIC-26 coherence-monitor → DIC-17 follow-up bridge",
            "",
            "## Queue policy",
            "This issue is a DIC-17 proposal. It MUST NOT carry `boss-ready` unless the "
            "current tranche in `docs/status/NEXT_STEPS_CANONICAL.md` explicitly permits "
            "it. The proof-first reconciler in `scripts/reconcile_proof_first_queue.py` "
            "will strip the label if it is added outside the permitted lane.",
        ]
    )

    labels = _without_boss_ready({"epistemic", "coherence", kind_slug, *extra_labels})
    # Dedup key: stable hash of belief_ids (sorted) + kind so the same
    # incoherence produces the same source_key regardless of scan order.
    dedup_material = "|".join(sorted(str(b) for b in issue.belief_ids)) + f"|{issue.kind.value}"
    source_key = _source_key("coherence_issue", dedup_material)

    return FollowupProposal(
        source_kind="coherence_issue",
        source_key=source_key,
        title=title,
        body="\n".join(body_lines),
        labels=labels,
        rationale=f"severity={issue.severity!r} {issue.kind.value} across {len(issue.belief_ids)} belief(s)",
        provenance={
            "kind": issue.kind.value,
            "severity": issue.severity,
            "belief_ids": list(issue.belief_ids),
        },
    )


# ---------------------------------------------------------------------------
# RepairSpec → proposal  (DIC-22 → DIC-17 bridge)
# ---------------------------------------------------------------------------


def propose_followup_for_repair_spec(
    spec: "RepairSpec",
    *,
    extra_labels: tuple[str, ...] = (),
) -> FollowupProposal | None:
    """Propose exactly one bounded follow-up issue for a RepairSpec, or None.

    Returns ``None`` for ``repair_kind='report_only'`` specs — advisory
    report-only artifacts are self-contained and do not require a queued
    follow-up issue.  ``'shadow_candidate'`` and ``'pr_candidate'`` specs
    indicate work that should be tracked and therefore do produce proposals.

    This implements the DIC-22 → DIC-17 bridge: a verified repair candidate
    that has been validated by ``propose_repair()`` becomes a bounded,
    queue-governance-compliant follow-up proposal.

    The ``boss-ready`` label is always excluded.  The proof-first reconciler
    strips it regardless; callers must not add it.
    """
    if spec.repair_kind == "report_only":
        return None

    title = f"[DIC-22] Review repair candidate: {spec.code_unit_id} ({spec.repair_kind})"
    if len(title) > 140:
        title = title[:139] + "…"

    body_lines = [
        "## Goal",
        "Review and approve a bounded repair candidate produced by the DIC-22 "
        "verified-replacement pipeline for a decayed proof-carrying code unit.",
        "",
        "## Repair spec",
        f"- spec_id: {spec.spec_id}",
        f"- code_unit_id: {spec.code_unit_id}",
        f"- repair_kind: {spec.repair_kind}",
        f"- integrity_score: {spec.decay_signal.integrity_score:.3f}",
        f"- created_at: {spec.created_at}",
    ]
    if spec.linked_claims:
        body_lines.extend(["", "## Linked claims"])
        body_lines.extend(f"- {c}" for c in spec.linked_claims)
    if spec.linked_crux_ids:
        body_lines.extend(["", "## Linked cruxes"])
        body_lines.extend(f"- {c}" for c in spec.linked_crux_ids)
    if spec.validation_commands:
        body_lines.extend(["", "## Validation commands"])
        body_lines.extend(f"- `{cmd}`" for cmd in spec.validation_commands)
    if spec.proposed_patch:
        body_lines.extend(
            [
                "",
                "## Proposed patch",
                _truncate(spec.proposed_patch, MAX_BODY_STATEMENT_CHARS),
            ]
        )
    body_lines.extend(
        [
            "",
            "## Provenance",
            "- source: DIC-22 repair pipeline → DIC-17 follow-up bridge",
            f"- spec_id: {spec.spec_id}",
            f"- provenance_hash: {spec.provenance_hash or '(report_only — no hash)'}",
            "",
            "## Queue policy",
            "This issue is a DIC-17 proposal. It MUST NOT carry `boss-ready` unless the "
            "current tranche in `docs/status/NEXT_STEPS_CANONICAL.md` explicitly permits "
            "it. The proof-first reconciler in `scripts/reconcile_proof_first_queue.py` "
            "will strip the label if it is added outside the permitted lane.",
        ]
    )

    labels = _without_boss_ready({"epistemic", "repair-required", spec.repair_kind, *extra_labels})
    source_key = _source_key("repair_spec", spec.spec_id)

    return FollowupProposal(
        source_kind="repair_spec",
        source_key=source_key,
        title=title,
        body="\n".join(body_lines),
        labels=labels,
        rationale=(
            f"repair_kind={spec.repair_kind!r} for {spec.code_unit_id} "
            f"(integrity={spec.decay_signal.integrity_score:.3f})"
        ),
        provenance={
            "spec_id": spec.spec_id,
            "code_unit_id": spec.code_unit_id,
            "repair_kind": spec.repair_kind,
            "provenance_hash": spec.provenance_hash,
            "linked_claims": list(spec.linked_claims),
            "linked_crux_ids": list(spec.linked_crux_ids),
        },
    )


__all__ = [
    "DEFAULT_CRUX_LOAD_BEARING_THRESHOLD",
    "DEFAULT_DELTA_LOSS_THRESHOLD",
    "FollowupProposal",
    "MAX_BODY_STATEMENT_CHARS",
    "propose_followup_for_coherence_issue",
    "propose_followup_for_crux",
    "propose_followup_for_cruxset",
    "propose_followup_for_failed_claim",
    "propose_followup_for_repair_spec",
]
