"""CLB-013: Canonical golden-path test for the closed-loop backbone.

Covers the full backbone contract chain:
    intake -> spec -> deliberation -> execution -> receipt -> outcome_feedback

Each stage uses only the canonical handoff artifacts from backbone_contracts so
failures point directly to the broken contract stage.
"""

from __future__ import annotations

from types import SimpleNamespace

from aragora.interrogation.crystallizer import CrystallizedSpec, MoSCoWItem
from aragora.interrogation.engine import InterrogationResult, PrioritizedQuestion
from aragora.pipeline.backbone_contracts import (
    DeliberationBundle,
    ExecutionAttemptRecord,
    IntakeBundle,
    OutcomeFeedbackRecord,
    ReceiptEnvelope,
    SpecBundle,
)
from aragora.pipeline.outcome_feedback import PipelineOutcome
from aragora.pipeline.receipt_generator import generate_receipt_envelope
from aragora.prompt_engine.types import PromptIntent, RiskItem, Specification, SpecFile


def test_golden_path_intake_to_outcome() -> None:
    """CLB-013: Full backbone from intake through outcome feedback.

    If this test fails, the assertion message identifies the contract stage.
    """
    # ------------------------------------------------------------------ #
    # Stage 1: Intake                                                      #
    # ------------------------------------------------------------------ #
    intent = PromptIntent(
        raw_prompt="Add offline mode to the mobile app",
        intent_type="feature",
        related_knowledge=[{"source": "km", "id": "doc-mobile-1"}],
    )
    intake = IntakeBundle.from_prompt_intent(
        intent,
        trust_tiers=["operator-authored"],
        taint_flags=[],
        origin_metadata={"entrypoint": "golden_path_test"},
    )
    assert intake.raw_intent == "Add offline mode to the mobile app", (
        "Stage 1 (intake): raw_intent not preserved"
    )
    assert intake.trust_tiers == ["operator-authored"], "Stage 1 (intake): trust_tiers lost"
    assert intake.context_refs == [{"source": "km", "id": "doc-mobile-1"}], (
        "Stage 1 (intake): context_refs lost"
    )

    # ------------------------------------------------------------------ #
    # Stage 2: Spec (prompt engine path)                                   #
    # ------------------------------------------------------------------ #
    spec = Specification(
        title="Offline Mode",
        problem_statement="Users cannot use the app without connectivity.",
        proposed_solution="Cache key data locally and sync on reconnect.",
        success_criteria=["App functions with no network", "Data syncs within 30s on reconnect"],
        file_changes=[
            SpecFile(
                path="mobile/src/offline/cache.ts",
                action="create",
                description="Local cache layer",
            )
        ],
        risks=[
            RiskItem(
                description="Stale data risk",
                likelihood="medium",
                impact="medium",
                mitigation="Timestamp-based invalidation on reconnect.",
            )
        ],
        confidence=0.82,
    )
    spec_bundle = SpecBundle.from_prompt_spec(spec)

    assert spec_bundle.title == "Offline Mode", "Stage 2 (spec): title lost"
    assert spec_bundle.acceptance_criteria, "Stage 2 (spec): acceptance_criteria empty"
    assert spec_bundle.owner_file_scopes == ["mobile/src/offline/cache.ts"], (
        "Stage 2 (spec): file scopes lost"
    )
    assert "constraints" in spec_bundle.missing_required_fields, (
        "Stage 2 (spec): constraints should be missing"
    )
    assert spec_bundle.is_execution_grade is False, (
        "Stage 2 (spec): should not be execution-grade without constraints"
    )

    # ------------------------------------------------------------------ #
    # Stage 3: Deliberation                                                #
    # ------------------------------------------------------------------ #
    debate_result = SimpleNamespace(
        debate_id="debate-gp-001",
        task="Should we add offline mode?",
        final_answer="Yes — cache key read paths, sync on reconnect.",
        confidence=0.88,
        consensus_reached=True,
        consensus_strength="strong",
        consensus_variance=0.3,
        dissenting_views=["Sync conflicts unresolved"],
        participants=["analyst", "critic", "synthesizer"],
        per_agent_similarity={"analyst": 0.9, "critic": 0.75, "synthesizer": 0.93},
        convergence_status="converged",
        debate_cruxes=[{"claim": "conflict resolution strategy", "contested": True}],
        metadata={"pipeline_id": "pipe-gp-001"},
    )
    deliberation = DeliberationBundle.from_debate_result(
        debate_result,
        trust_tier="operator-reviewed",
        taint_flags=[],
    )

    assert deliberation.debate_id == "debate-gp-001", "Stage 3 (deliberation): debate_id lost"
    assert deliberation.quality_verdict == "passed", (
        "Stage 3 (deliberation): expected passed quality verdict"
    )
    assert deliberation.trust_tier == "operator-reviewed", (
        "Stage 3 (deliberation): trust_tier not propagated"
    )
    assert len(deliberation.unresolved_risks) == 1, (
        "Stage 3 (deliberation): cruxes not surfaced as risks"
    )

    # ------------------------------------------------------------------ #
    # Stage 4: Execution                                                   #
    # ------------------------------------------------------------------ #
    outcome = PipelineOutcome(
        pipeline_id="pipe-gp-001",
        run_type="automated",
        domain="mobile",
        spec_completeness=0.85,
        execution_succeeded=True,
        tests_passed=12,
        tests_failed=0,
        files_changed=3,
        total_duration_s=22.5,
    )
    attempt = ExecutionAttemptRecord.from_plan_outcome(
        outcome,
        attempt_id="attempt-gp-001",
        plan_id="plan-gp-001",
        policy_decision={"allowed": True},
        artifacts=["dist/mobile.tar.gz"],
    )

    assert attempt.status == "succeeded", "Stage 4 (execution): status not succeeded"
    assert attempt.tests_passed == 12, "Stage 4 (execution): tests_passed lost"
    assert attempt.plan_id == "plan-gp-001", "Stage 4 (execution): plan_id not preserved"

    # ------------------------------------------------------------------ #
    # Stage 5: Receipt                                                     #
    # ------------------------------------------------------------------ #
    raw_receipt = {
        "receipt_id": "r-gp-001",
        "pipeline_id": "pipe-gp-001",
        "content_hash": "sha256golden",
        "provenance": {
            "ideas": [{"id": "i1", "label": "Offline mode idea"}],
            "goals": [{"id": "g1", "label": "Add offline capability"}],
        },
        "execution": {"status": "completed"},
    }
    envelope = generate_receipt_envelope(
        raw_receipt,
        policy_gate_result={"allowed": True, "source": "golden_path"},
        taint_summary={"tainted": False},
    )

    assert envelope.receipt_id == "r-gp-001", "Stage 5 (receipt): receipt_id lost"
    assert envelope.verdict == "pass", "Stage 5 (receipt): verdict not pass"
    assert len(envelope.provenance_chain) == 2, "Stage 5 (receipt): provenance chain incomplete"

    # ------------------------------------------------------------------ #
    # Stage 6: Outcome feedback → Nomic goal                              #
    # ------------------------------------------------------------------ #
    feedback = OutcomeFeedbackRecord.from_pipeline_outcome(
        outcome,
        receipt_ref=envelope.receipt_id,
    )
    nomic_goal = feedback.to_nomic_goal()

    assert feedback.next_action_recommendation == "promote_or_settle", (
        "Stage 6 (feedback): wrong recommendation"
    )
    assert nomic_goal["module"] == "mobile", (
        "Stage 6 (feedback/nomic): module not derived from domain"
    )
    assert nomic_goal["priority"] == "low", (
        "Stage 6 (feedback/nomic): successful run should be low priority"
    )
    assert "r-gp-001" in nomic_goal["rationale"], (
        "Stage 6 (feedback/nomic): receipt_ref not in rationale"
    )


def test_golden_path_failed_execution_produces_bug_fix_goal() -> None:
    """CLB-013: Failed execution path surfaces bug-fix loop Nomic goal."""
    outcome = PipelineOutcome(
        pipeline_id="pipe-gp-002",
        run_type="automated",
        domain="backend",
        spec_completeness=0.7,
        execution_succeeded=False,
        tests_passed=5,
        tests_failed=3,
        files_changed=2,
        total_duration_s=14.0,
    )
    attempt = ExecutionAttemptRecord.from_plan_outcome(outcome, attempt_id="attempt-gp-002")
    assert attempt.status == "failed", (
        "Stage 4 (execution): failed outcome should set status=failed"
    )

    feedback = OutcomeFeedbackRecord.from_pipeline_outcome(outcome, receipt_ref="r-gp-002")
    nomic_goal = feedback.to_nomic_goal()

    assert feedback.next_action_recommendation == "run_bug_fix_loop", (
        "Stage 6 (feedback): should recommend bug fix"
    )
    assert nomic_goal["priority"] == "high", "Stage 6 (nomic): failed run should be high priority"
    assert (
        "fix" in nomic_goal["description"].lower() or "bug" in nomic_goal["description"].lower()
    ), "Stage 6 (nomic): description should mention fix/bug"


def test_golden_path_interrogation_spec_identifies_missing_fields() -> None:
    """CLB-013: Interrogation path correctly surfaces missing execution-grade fields."""
    crystallized = CrystallizedSpec(
        title="Offline Mode v2",
        problem_statement="Extend offline support to background sync.",
        requirements=[
            MoSCoWItem(description="Background sync worker", priority="must"),
        ],
        success_criteria=["Sync completes within 60s after reconnect"],
        risks=[{"risk": "Battery drain", "mitigation": "Throttle sync to wifi-only"}],
        constraints=["No breaking changes to existing API"],
    )
    result = InterrogationResult(
        original_prompt="Extend offline mode",
        dimensions=["reliability", "performance"],
        research_summary="Current offline support is read-only.",
        prioritized_questions=[
            PrioritizedQuestion(
                question="Should sync be wifi-only by default?",
                why_it_matters="Battery implications.",
                priority_score=0.8,
            )
        ],
        crystallized_spec=crystallized,
    )

    spec_bundle = SpecBundle.from_interrogation_result(result)

    assert spec_bundle.constraints == ["No breaking changes to existing API"], (
        "Stage 2 (spec/interrogation): constraints lost"
    )
    assert "Should sync be wifi-only" in spec_bundle.open_questions[0], (
        "Stage 2 (spec/interrogation): open questions lost"
    )
    assert "owner_file_scopes" in spec_bundle.missing_required_fields, (
        "Stage 2 (spec/interrogation): missing_required_fields should include owner_file_scopes"
    )
