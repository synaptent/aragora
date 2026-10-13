#!/usr/bin/env python3
# ruff: noqa: T201
"""M8 dogfood offline replay: regenerate ODR receipts from stored raw model outputs.

This is the **canonical replay path** for the M8 dogfood receipts.  It does NOT
make any live LLM calls.  Instead it reads the committed raw reviewer outputs
(``raw-reviews/pr-<N>-reviewers.json``) produced during the original live M8 run
and feeds them through the **canonical review-to-receipt collector**
:func:`aragora.swarm.quorum_receipt.collect_outcome_to_decision_receipt` +
:func:`aragora.gauntlet.odr_export.decision_receipt_to_odr` — the same transform
``scripts/emit_pr_receipt.py`` uses to turn a ``CollectOutcome`` into a portable
ODR.

Usage (from the repo root, no venv or PYTHONPATH required — the script
computes the repo root from its own location and adds it to ``sys.path``)::

    python3 docs/case-studies/dogfood/replay_dogfood_receipts.py

This regenerates all 5 ODR receipts in ``docs/case-studies/dogfood/`` and writes
a machine-readable summary to ``dogfood-summary.json``.  Each receipt can then be
verified with ``aragora-verify <receipt>.odr.json`` (expected exit 0).

The script **fails closed** (nonzero exit) if any expected raw-review fixture is
missing or any receipt cannot be produced — no silent partial output.

Design notes
------------
* **No live LLM calls.**  All reviewer text comes from the committed raw-review
  fixtures; spend is zero.
* **Canonical collector.**  Receipts are produced via
  ``collect_outcome_to_decision_receipt`` (not by hand-constructing
  ``DecisionReceipt`` objects), so the quorum/verdict/confidence fields are
  derived by the same code the Action's receipt-emission path uses.
* **No guarded paths touched.**  This script imports the canonical collector and
  ODR exporter but modifies no merge-authority, quorum, settle, or
  receipt-pipeline source code.
* **Repository-relative paths.**  The repo root is computed from this script's
  committed location (``docs/case-studies/dogfood/`` → ``parents[2]``).  All
  paths serialized into ``dogfood-summary.json`` are repository-relative; no
  absolute worker-worktree paths are written into committed artifacts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Resolve the repo root from this script's location (docs/case-studies/dogfood/).
# parents[0] = docs/case-studies, parents[1] = docs, parents[2] = repo root.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]  # docs/case-studies/dogfood -> repo root
sys.path.insert(0, str(REPO_ROOT))

from aragora.gauntlet.odr_export import decision_receipt_to_odr, odr_content_digest
from aragora.swarm.quorum_evidence import CollectOutcome, EvidenceItem
from aragora.swarm.quorum_receipt import collect_outcome_to_decision_receipt

REPO = "synaptent/aragora"

# PR metadata: (number, head_sha, title, tier)
# tier is None (fail-safe Tier 3-4 quorum rule: 2 distinct Western families).
# Head SHAs are the full merged-head SHAs at review time (pinned for
# reproducibility; the subject digest is sha-256 of "repo#pr@head_sha").
PRS = [
    (
        9193,
        "65521e8926752a849b069e6dd16a64fef73bb71e",
        "tests(scripts): harden docs-site fallback mirror guard with source parity",
        None,
    ),
    (
        9062,
        "0a37ec64bde1fca2fbe099780b439b596d940de3",
        "feat(scripts): add OpenRouter fallback for Fable goal cycles",
        None,
    ),
    (
        9030,
        "6fe6ad588f4c2cb3999d60913bd2aa3b0ed2be5b",
        "fix(routing): handle empty LLM domain responses",
        None,
    ),
    (
        9056,
        "d7ed551d0564ffed4c6d3893e938dfa75ce0e573",
        "feat(swarm): wire PR-keyed round budget into A1 reconciler (Tier 4)",
        None,
    ),
    (
        9027,
        "363bde32f58cfb81fab8582a641a0d323d9242c9",
        "fix(scripts): accept operator-context dir in goal-cycle context",
        None,
    ),
]

RAW_DIR = SCRIPT_DIR / "raw-reviews"


def _verdict_to_evidence_verdict(model_verdict: str) -> str:
    """Map the reviewer's parsed verdict to the EvidenceItem verdict string."""
    v = model_verdict.upper().strip()
    if v == "PASS":
        return "pass"
    if v in ("CHANGES_REQUESTED", "CHANGES-REQUESTED"):
        return "changes_requested"
    return "unknown"


def build_outcome(
    pr: int, head_sha: str, title: str, tier: int | None, reviewers: list[dict]
) -> CollectOutcome:
    """Build a CollectOutcome from stored raw reviewer outputs.

    Each reviewer output is mapped to an EvidenceItem with:
    - family: the reviewer's model family key (grok / mistral)
    - body: the reviewer's raw text output
    - would_count: True (the reviewer returned valid, non-empty output)
    - verdict: "pass" or "changes_requested"
    - severity_gated: False (default behavior — all changes_requested count as
      dissenting, matching the non-severity-gated quorum)
    """
    items: list[EvidenceItem] = []
    failures: list[dict] = []
    for r in reviewers:
        if not r.get("ok"):
            failures.append(r)
            continue
        items.append(
            EvidenceItem(
                family=r["family"],
                body=r.get("text", ""),
                would_count=True,
                verdict=_verdict_to_evidence_verdict(r.get("verdict", "UNKNOWN")),
                severity_gated=False,
            )
        )

    supportive = [item.family for item in items if item.supportive]
    dissenting = [item.family for item in items if item.dissenting]

    if supportive and not dissenting:
        action_reason = f"All {len(supportive)} reviewer(s) passed"
    elif supportive and dissenting:
        action_reason = f"{len(dissenting)} reviewer(s) requested changes, {len(supportive)} passed"
    else:
        action_reason = "No reviewers produced a passing verdict"

    return CollectOutcome(
        repo=REPO,
        pr=pr,
        head_sha=head_sha,
        head_committed_at="",
        tier=tier,
        action="post",
        action_reason=action_reason,
        items=items,
        failures=failures,
        posted=[item.family for item in items],
        tiered_gate=False,
    )


def regenerate_receipt(
    pr: int, head_sha: str, title: str, tier: int | None, reviewers: list[dict]
) -> dict:
    """Regenerate one ODR receipt through the canonical collector pipeline."""
    outcome = build_outcome(pr, head_sha, title, tier, reviewers)
    receipt = collect_outcome_to_decision_receipt(outcome)
    # The committed M8 receipts are v0.1 documents; pin the profile so a replay
    # reproduces them now that the library default is v0.2 (release 2.11.0).
    odr = decision_receipt_to_odr(receipt, odr_version="0.1")
    digest = odr_content_digest(odr)

    out_path = SCRIPT_DIR / f"pr-{pr}-receipt.odr.json"
    out_path.write_text(json.dumps(odr, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "pr": pr,
        "head_sha": head_sha,
        "title": title,
        "receipt_path": str(out_path.relative_to(REPO_ROOT)),
        "odr_digest": digest,
        "verdict": odr["claim"]["verdict"],
        "reached": odr["quorum"]["reached"],
        "supportive": odr["quorum"]["supporting_agents"],
        "dissenting": odr["quorum"]["dissent"]["dissenting_agents"]
        if odr["quorum"]["dissent"]["present"]
        else [],
        "confidence": odr["confidence"]["value"],
        "model_families": odr["quorum"]["independence"]["model_families"],
        "distinct_model_families": odr["quorum"]["independence"]["distinct_model_families"],
    }


def main() -> int:
    """Regenerate all 5 receipts, failing closed on any missing input or output.

    Exits nonzero if any expected raw-review fixture is missing, any fixture
    cannot be parsed, or the number of produced receipts does not equal the
    number of expected PRs.  No partial summary is written on failure.
    """
    results: list[dict] = []
    errors: list[str] = []
    for pr, head, title, tier in PRS:
        raw_path = RAW_DIR / f"pr-{pr}-reviewers.json"
        if not raw_path.exists():
            errors.append(f"PR #{pr}: raw reviews not found at {raw_path}")
            print(f"ERROR PR #{pr}: raw reviews not found at {raw_path}")
            continue
        try:
            reviewers = json.loads(raw_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"PR #{pr}: cannot read {raw_path}: {exc}")
            print(f"ERROR PR #{pr}: cannot read {raw_path}: {exc}")
            continue
        result = regenerate_receipt(pr, head, title, tier, reviewers)
        results.append(result)
        print(
            f"PR #{pr}: verdict={result['verdict']} "
            f"supportive={result['supportive']} dissenting={result['dissenting']} "
            f"confidence={result['confidence']} "
            f"families={result['distinct_model_families']} "
            f"digest={result['odr_digest'][:12]}"
        )

    # Fail closed: every expected fixture must be present and every receipt
    # produced.  No silent partial output.
    if errors:
        print(f"\nFAILED: {len(errors)} error(s), {len(results)} receipt(s) produced.")
        for e in errors:
            print(f"  - {e}")
        return 1
    if len(results) != len(PRS):
        print(f"\nFAILED: expected {len(PRS)} receipts, produced {len(results)}.")
        return 1

    summary_path = SCRIPT_DIR / "dogfood-summary.json"
    summary_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nRegenerated {len(results)} receipts via canonical collector.")
    print(f"Summary: {summary_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
