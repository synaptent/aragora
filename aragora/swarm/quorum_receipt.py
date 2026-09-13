"""Bridge: a merge-quorum PR-review outcome -> a portable DecisionReceipt.

This is the M2 core. It turns a :class:`CollectOutcome` — the result of a
heterogeneous-model PR review produced by ``aragora/swarm/quorum_evidence.py`` —
into a gauntlet :class:`DecisionReceipt`, so the review can be exported to a
portable Open Decision Receipt (``aragora/gauntlet/odr_export.py``) and verified
independently by ``aragora-verify``.

Design rules (mirroring the emitter's "never fabricate" contract):

- **Pure and side-effect-free.** It copies fields off the outcome; it makes no
  network calls and mutates nothing. The Action / settlement layer decides what
  to do with the receipt.
- **No invented clearance.** The verdict and quorum reflect only posted,
  supportive evidence when no reviewer dissent is present. Prepared evidence
  must remain merge-blocking in the portable receipt.
- **Internally consistent quorum.** Posted supporting and dissenting families
  are carried into ``consensus_proof``; ``odr_export`` records all reviewers as
  participants, so the verifier's quorum-consistency check holds
  (supporting/dissenting agents are always a subset of participants).
- **Family is the disclosed axis.** Each evidence item's model *family* is
  recorded as its participant provider, so ODR independence (distinct model
  families) is disclosed rather than guessed.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from aragora.cli.commands.review_queue_comment_verdicts import extract_finding_lines
from aragora.gauntlet.receipt_models import (
    AgentResponseRecord,
    ConsensusProof,
    DecisionReceipt,
)
from aragora.swarm.quorum_evidence import (
    FAMILY_PROVIDERS,
    CollectOutcome,
    collect_outcome_from_dict,
    tier_quorum_rule,
)

__all__ = ["collect_outcome_to_decision_receipt"]


def _odr_content(outcome: CollectOutcome, raw: dict[str, Any]) -> dict[str, Any]:
    rule = tier_quorum_rule(outcome.tier, tiered_gate=outcome.tiered_gate)
    verdicts, findings = [], []
    for item in outcome.items:
        if not item.family.strip():
            continue
        rows: list[dict[str, Any]] = [
            {
                "issuer": item.family,
                "severity": line[1:3],
                "blocking": line[1:3] in ("P0", "P1"),
                "text": line[4:].strip(),
            }
            for line in extract_finding_lines(item.body)
        ]
        findings.extend(rows)
        verdicts.append(
            {
                "issuer": item.family,
                "verdict": item.verdict,
                "model_family": FAMILY_PROVIDERS.get(item.family, item.family),
                "model_id": "undisclosed",
                "head_sha": outcome.head_sha,
                "counted": item.would_count,
                "grounded": item.grounded,
                "blocking": item.dissenting,
            }
        )
    observations = [
        {"kind": "failure", "family": failure.family, "detail": failure.error or ""}
        for failure in outcome.failures
    ]
    observations.extend(
        {"kind": "timeout", "family": family, "detail": "reviewer exceeded collection deadline"}
        for family in raw.get("timed_out_families", outcome.timed_out_families)
    )
    dissent: dict[str, Any] = {
        "findings": findings,
        "blocking": any(f["blocking"] for f in findings),
    }
    if findings:
        dissent["severity_max"] = min(f["severity"] for f in findings)
    content: dict[str, Any] = {
        "verdicts": verdicts,
        "dissent": dissent,
        "observations": observations,
        "rule": {
            "required_signals": rule.required_signals,
            "requires_western_frontier": rule.requires_western_frontier,
            "western_only_counted": rule.western_only_counted,
            "counted_families": sorted(rule.counted_families(outcome.counting_families)),
        },
        "mechanism": {
            "type": "merge-quorum",
            "policy_version": raw["policy_version"],
            "tier": outcome.tier,
            "tiered_gate": outcome.tiered_gate,
            "action": outcome.action,
            "action_reason": outcome.action_reason,
        },
    }
    if outcome.items and len({item.severity_gated for item in outcome.items}) == 1:
        content["mechanism"]["severity_gated"] = outcome.items[0].severity_gated
    if outcome.adjudication is not None:
        adjudication = deepcopy(outcome.adjudication)
        if "verdict" in adjudication:
            adjudication["verdict"] = adjudication["verdict"].removeprefix("adjudicated_")
        policy = dict(adjudication.get("policy", {}))
        for key in ("groundedness_bar", "advisory_severity_policy"):
            if key in adjudication:
                policy[key] = adjudication.pop(key)
        content["adjudication"] = {"status": "present", **adjudication, "policy": policy}
    return content


def collect_outcome_to_decision_receipt(
    outcome: CollectOutcome | dict[str, Any],
) -> DecisionReceipt:
    """Map a merge-quorum :class:`CollectOutcome` onto a :class:`DecisionReceipt`.

    The returned receipt is ready for ``decision_receipt_to_odr`` and carries the
    PR's provenance (repo, number, head SHA, tier) under ``settlement_metadata``.
    """
    raw = outcome if isinstance(outcome, dict) else outcome.to_dict()
    if isinstance(outcome, dict):
        outcome = collect_outcome_from_dict(outcome)
    raw = {**outcome.to_dict(), **raw}
    supportive = list(outcome.supportive_families)
    dissenting = list(outcome.dissenting_families)
    counting = list(outcome.counting_families)
    posted = {str(family).strip() for family in outcome.posted if str(family).strip()}
    posted_supportive = [family for family in supportive if family in posted]
    posted_quorum = bool(posted) and tier_quorum_rule(
        outcome.tier,
        tiered_gate=outcome.tiered_gate,
    ).is_satisfied_by(posted_supportive)
    reached = outcome.action == "post" and posted_quorum and not dissenting

    confidence = (len(supportive) / len(counting)) if counting else 0.0
    verdict = "PASS" if reached else "CHANGES_REQUESTED"

    head = (outcome.head_sha or "").strip()
    input_hash = hashlib.sha256(f"{outcome.repo}#{outcome.pr}@{head}".encode()).hexdigest()

    agent_responses = [
        AgentResponseRecord(
            agent=item.family,
            response=item.body,
            provider=FAMILY_PROVIDERS.get(item.family, item.family),
        )
        for item in outcome.items
        if (item.family or "").strip()
    ]

    dissenting_views = [f"{item.family}: {item.body}" for item in outcome.items if item.dissenting]

    return DecisionReceipt(
        receipt_id=f"pr-{outcome.pr}-{head[:12]}" if head else f"pr-{outcome.pr}",
        gauntlet_id=f"merge-quorum/{outcome.repo}#{outcome.pr}",
        timestamp=outcome.head_committed_at or "",
        input_summary=f"Merge {outcome.repo}#{outcome.pr} @ {head[:12]}",
        input_hash=input_hash,
        risk_summary={
            "counting": len(counting),
            "supportive": len(supportive),
            "dissenting": len(dissenting),
            "total": len(outcome.items),
        },
        attacks_attempted=0,
        attacks_successful=0,
        probes_run=0,
        vulnerabilities_found=0,
        verdict=verdict,
        confidence=confidence,
        robustness_score=confidence,
        verdict_reasoning=outcome.action_reason,
        dissenting_views=dissenting_views,
        consensus_proof=ConsensusProof(
            reached=reached,
            confidence=confidence,
            supporting_agents=posted_supportive,
            dissenting_agents=dissenting,
            method="merge-quorum",
        ),
        agent_responses=agent_responses,
        settlement_metadata={
            "repo": outcome.repo,
            "pr": outcome.pr,
            "head_sha": head,
            "tier": outcome.tier,
            "action": outcome.action,
            "tiered_gate": outcome.tiered_gate,
            **({"base_sha": raw["base_sha"]} if "base_sha" in raw else {}),
            "odr": _odr_content(outcome, raw),
        },
    )
