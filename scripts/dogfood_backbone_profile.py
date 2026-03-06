#!/usr/bin/env python3
"""CLB-014: Dogfood profile for the closed-loop backbone.

Runs the full backbone loop in dry-run mode, producing a JSON artifact
for every stage.  Exits 0 when all required stages produce artifacts,
1 otherwise.

Usage:
    python scripts/dogfood_backbone_profile.py --dry-run
    python scripts/dogfood_backbone_profile.py --dry-run --output /tmp/results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure the repo root is on sys.path so we can import aragora
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from aragora.pipeline.backbone_contracts import (
    DeliberationBundle,
    ExecutionAttemptRecord,
    IntakeBundle,
    OutcomeFeedbackRecord,
    ReceiptEnvelope,
    SpecBundle,
)

# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

REQUIRED_STAGES = [
    "intake",
    "spec",
    "deliberation",
    "execution",
    "receipt",
    "feedback",
]


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stage_artifact(stage: str, artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": stage,
        "artifact": artifact,
        "timestamp": _ts(),
    }


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------


def run_intake() -> IntakeBundle:
    return IntakeBundle(
        source_kind="dogfood",
        raw_intent="Improve error handling in auth module",
        context_refs=[{"source": "codebase", "path": "aragora/auth/"}],
        trust_tiers=["operator-authored"],
        origin_metadata={"entrypoint": "dogfood_profile", "run_at": _ts()},
    )


def run_spec(intake: IntakeBundle) -> SpecBundle:
    return SpecBundle(
        title="Improve auth error handling",
        problem_statement=(
            f"Based on intent: {intake.raw_intent!r}. "
            "Auth module has bare except blocks that swallow errors."
        ),
        objectives=["Narrow all exception handlers to specific types"],
        constraints=["Must not break existing tests", "No new dependencies"],
        acceptance_criteria=[
            "All except blocks use specific exception types",
            "No bare except: pass patterns remain",
        ],
        verification_plan=["Run pytest tests/auth/ -v", "Run mypy aragora/auth/"],
        rollback_plan=["Revert commit via git revert"],
        owner_file_scopes=["aragora/auth/"],
        confidence=0.88,
        source_kind="dogfood_profile",
    )


def run_deliberation(spec: SpecBundle) -> DeliberationBundle:
    return DeliberationBundle(
        debate_id="dogfood-debate-001",
        verdict=f"Approved: {spec.title} is well-specified and safe to execute",
        confidence=0.85,
        consensus_reached=True,
        consensus_strength="strong",
        quality_verdict="passed",
        dissenting_views=[],
        unresolved_risks=[],
        participant_count=3,
        diversity_scores={"analyst": 0.82, "critic": 0.65, "synthesizer": 0.91},
        extras={"spec_title": spec.title},
    )


def run_execution(deliberation: DeliberationBundle) -> ExecutionAttemptRecord:
    return ExecutionAttemptRecord(
        attempt_id="dogfood-attempt-001",
        plan_id="dogfood-plan-001",
        status="succeeded",
        tests_passed=12,
        tests_failed=0,
        files_changed=3,
        diff_summary="3 files changed, 42 insertions, 5 deletions",
        artifacts=["reports/test-results.xml"],
        policy_decision={"allowed": True, "reason": "within budget"},
        duration_s=18.5,
        extras={"debate_id": deliberation.debate_id},
    )


def run_receipt(
    execution: ExecutionAttemptRecord,
    deliberation: DeliberationBundle,
) -> ReceiptEnvelope:
    verdict = "pass" if execution.status == "succeeded" else "blocked"
    return ReceiptEnvelope(
        receipt_id="dogfood-receipt-001",
        artifact_hash="sha256-dogfood-abc123",
        verdict=verdict,
        confidence=deliberation.confidence,
        policy_gate_result=execution.policy_decision,
        provenance_chain=[
            {"stage": "intake", "source_kind": "dogfood"},
            {"stage": "deliberation", "debate_id": deliberation.debate_id},
            {"stage": "execution", "attempt_id": execution.attempt_id},
        ],
    )


def run_feedback(
    receipt: ReceiptEnvelope,
    execution: ExecutionAttemptRecord,
) -> OutcomeFeedbackRecord:
    succeeded = execution.status == "succeeded"
    if succeeded:
        next_action = "promote_or_settle"
    elif execution.tests_failed > 0:
        next_action = "run_bug_fix_loop"
    else:
        next_action = "review_manually"

    return OutcomeFeedbackRecord(
        receipt_ref=receipt.receipt_id,
        pipeline_id="dogfood-pipe-001",
        run_type="dogfood",
        domain="auth",
        objective_fidelity=receipt.confidence,
        quality_outcome={"overall_quality_score": receipt.confidence},
        execution_outcome={
            "execution_succeeded": succeeded,
            "tests_passed": execution.tests_passed,
            "tests_failed": execution.tests_failed,
            "files_changed": execution.files_changed,
        },
        next_action_recommendation=next_action,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_profile(*, dry_run: bool = True) -> dict[str, Any]:
    """Run the backbone profile, returning the full results dict."""
    results: dict[str, Any] = {
        "profile": "dogfood_backbone",
        "dry_run": dry_run,
        "started_at": _ts(),
        "stages": [],
        "errors": [],
    }

    try:
        # Stage 1: Intake
        intake = run_intake()
        results["stages"].append(_stage_artifact("intake", intake.to_dict()))

        # Stage 2: Spec
        spec = run_spec(intake)
        if not spec.is_execution_grade:
            results["errors"].append(
                f"Spec is not execution-grade. Missing: {spec.missing_required_fields}"
            )
        results["stages"].append(_stage_artifact("spec", spec.to_dict()))

        # Stage 3: Deliberation
        deliberation = run_deliberation(spec)
        if deliberation.quality_verdict != "passed":
            results["errors"].append(
                f"Deliberation quality gate failed: {deliberation.quality_verdict}"
            )
        results["stages"].append(_stage_artifact("deliberation", deliberation.to_dict()))

        # Stage 4: Execution
        execution = run_execution(deliberation)
        results["stages"].append(_stage_artifact("execution", execution.to_dict()))

        # Stage 5: Receipt
        receipt = run_receipt(execution, deliberation)
        results["stages"].append(_stage_artifact("receipt", receipt.to_dict()))

        # Stage 6: Feedback
        feedback = run_feedback(receipt, execution)
        results["stages"].append(_stage_artifact("feedback", feedback.to_dict()))

    except Exception as exc:
        results["errors"].append(f"Unexpected error: {exc}")

    results["completed_at"] = _ts()

    # Check all required stages were produced
    produced_stages = {s["stage"] for s in results["stages"]}
    missing_stages = [s for s in REQUIRED_STAGES if s not in produced_stages]
    if missing_stages:
        results["errors"].append(f"Missing required stages: {missing_stages}")

    results["success"] = len(results["errors"]) == 0
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the backbone dogfood profile.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run in dry-run mode (no real LLM calls).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="dogfood_backbone_results.json",
        help="Output file path for the results JSON (default: dogfood_backbone_results.json).",
    )
    args = parser.parse_args()

    results = run_profile(dry_run=args.dry_run)

    output_path = Path(args.output)
    output_path.write_text(json.dumps(results, indent=2) + "\n")

    # Summary
    produced = [s["stage"] for s in results["stages"]]
    print(f"Backbone profile complete: {len(produced)}/{len(REQUIRED_STAGES)} stages produced")
    print(f"  Stages: {', '.join(produced)}")
    if results["errors"]:
        print(f"  Errors: {len(results['errors'])}")
        for err in results["errors"]:
            print(f"    - {err}")
    print(f"  Output: {output_path.resolve()}")

    return 0 if results["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
