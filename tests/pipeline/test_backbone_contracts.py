from __future__ import annotations

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
from aragora.prompt_engine.spec_validator import ValidationResult, ValidatorRole
from aragora.prompt_engine.types import PromptIntent, RiskItem, Specification, SpecFile


def test_intake_bundle_from_prompt_intent_preserves_core_fields() -> None:
    intent = PromptIntent(
        raw_prompt="Improve onboarding flow",
        intent_type="improvement",
        related_knowledge=[{"source": "km", "id": "doc-1"}],
    )

    bundle = IntakeBundle.from_prompt_intent(
        intent,
        trust_tiers=["operator-authored", "internal-retrieved"],
        taint_flags=["external_note"],
        origin_metadata={"entrypoint": "prompt_engine"},
    )

    assert bundle.raw_intent == "Improve onboarding flow"
    assert bundle.context_refs == [{"source": "km", "id": "doc-1"}]
    assert bundle.trust_tiers == ["operator-authored", "internal-retrieved"]
    assert bundle.taint_flags == ["external_note"]
    assert bundle.origin_metadata["entrypoint"] == "prompt_engine"


def test_spec_bundle_from_prompt_spec_surfaces_missing_execution_fields() -> None:
    spec = Specification(
        title="Onboarding improvements",
        problem_statement="Users drop off too early.",
        proposed_solution="Tighten the onboarding flow and clarify next steps.",
        success_criteria=["Increase activation conversion", "Reduce first-session confusion"],
        file_changes=[
            SpecFile(
                path="aragora/live/src/app/(app)/onboarding/page.tsx",
                action="modify",
                description="Improve onboarding copy",
            )
        ],
        risks=[
            RiskItem(
                description="UX regression",
                likelihood="medium",
                impact="medium",
                mitigation="Keep old copy behind a rollout guard.",
            )
        ],
        confidence=0.72,
    )
    validation = ValidationResult(
        role_results={ValidatorRole.UX_ADVOCATE: {"passed": True, "confidence": 0.9}},
        overall_confidence=0.91,
        passed=True,
    )

    bundle = SpecBundle.from_prompt_spec(spec, validation=validation)

    assert bundle.title == "Onboarding improvements"
    assert bundle.objectives == ["Tighten the onboarding flow and clarify next steps."]
    assert bundle.acceptance_criteria == [
        "Increase activation conversion",
        "Reduce first-session confusion",
    ]
    assert bundle.verification_plan == bundle.acceptance_criteria
    assert bundle.rollback_plan == ["Keep old copy behind a rollout guard."]
    assert bundle.owner_file_scopes == ["aragora/live/src/app/(app)/onboarding/page.tsx"]
    assert bundle.confidence == 0.91
    assert bundle.source_kind == "prompt_engine_spec"
    assert bundle.missing_required_fields == ["constraints"]
    assert bundle.is_execution_grade is False


def test_spec_bundle_from_interrogation_result_preserves_constraints_and_open_questions() -> None:
    crystallized = CrystallizedSpec(
        title="Execution-grade spec",
        problem_statement="Turn a vague request into a concrete implementation plan.",
        requirements=[
            MoSCoWItem(description="Capture owner files", priority="must"),
            MoSCoWItem(description="Define rollback path", priority="must"),
        ],
        success_criteria=["Every generated task has acceptance criteria"],
        risks=[
            {"risk": "Spec drift", "mitigation": "Block execution when required fields are absent"}
        ],
        constraints=["No direct prompt-to-execute path"],
    )
    result = InterrogationResult(
        original_prompt="Make the pipeline safer",
        dimensions=["safety", "execution"],
        research_summary="Current path allows soft degradation.",
        prioritized_questions=[
            PrioritizedQuestion(
                question="Should automated runs fail closed on missing rollback plans?",
                why_it_matters="Execution safety depends on it.",
                priority_score=0.95,
            )
        ],
        crystallized_spec=crystallized,
    )

    bundle = SpecBundle.from_interrogation_result(result)

    assert bundle.title == "Execution-grade spec"
    assert bundle.constraints == ["No direct prompt-to-execute path"]
    assert bundle.acceptance_criteria == ["Every generated task has acceptance criteria"]
    assert bundle.rollback_plan == ["Block execution when required fields are absent"]
    assert bundle.open_questions == ["Should automated runs fail closed on missing rollback plans?"]
    assert bundle.owner_file_scopes == []
    assert "owner_file_scopes" in bundle.missing_required_fields


def test_receipt_envelope_from_pipeline_receipt_flattens_provenance() -> None:
    receipt = {
        "receipt_id": "receipt-123",
        "pipeline_id": "pipe-001",
        "generated_at": "2026-03-06T12:00:00Z",
        "content_hash": "abc123",
        "provenance": {
            "ideas": [{"id": "i1", "label": "Idea"}],
            "goals": [{"id": "g1", "label": "Goal"}],
        },
        "execution": {"status": "completed"},
    }

    envelope = ReceiptEnvelope.from_pipeline_receipt(
        receipt,
        policy_gate_result={"allowed": True},
        taint_summary={"tainted": False},
    )

    assert envelope.receipt_id == "receipt-123"
    assert envelope.artifact_hash == "abc123"
    assert envelope.verdict == "pass"
    assert envelope.policy_gate_result == {"allowed": True}
    assert envelope.taint_summary == {"tainted": False}
    assert envelope.provenance_chain == [
        {"stage": "ideas", "id": "i1", "label": "Idea"},
        {"stage": "goals", "id": "g1", "label": "Goal"},
    ]


def test_deliberation_bundle_from_debate_result_preserves_dissent_and_diversity() -> None:
    from types import SimpleNamespace

    result = SimpleNamespace(
        debate_id="debate-abc",
        task="Should we adopt microservices?",
        final_answer="Prefer a modular monolith for now.",
        confidence=0.78,
        consensus_reached=True,
        consensus_strength="medium",
        consensus_variance=1.3,
        dissenting_views=["Scale concerns are underweighted", "Org readiness not assessed"],
        participants=["analyst", "critic", "synthesizer"],
        per_agent_similarity={"analyst": 0.82, "critic": 0.61, "synthesizer": 0.91},
        convergence_status="converged",
        debate_cruxes=[{"claim": "team size matters", "contested": True}],
        metadata={"source": "pipeline", "pipeline_id": "pipe-001"},
    )

    bundle = DeliberationBundle.from_debate_result(result)

    assert bundle.debate_id == "debate-abc"
    assert bundle.verdict == "Prefer a modular monolith for now."
    assert bundle.confidence == 0.78
    assert bundle.consensus_reached is True
    assert bundle.consensus_strength == "medium"
    assert bundle.dissenting_views == [
        "Scale concerns are underweighted",
        "Org readiness not assessed",
    ]
    assert bundle.participant_count == 3
    assert bundle.diversity_scores == {"analyst": 0.82, "critic": 0.61, "synthesizer": 0.91}
    assert bundle.unresolved_risks == [{"claim": "team size matters", "contested": True}]
    assert bundle.provenance_refs == [{"source": "pipeline", "pipeline_id": "pipe-001"}]


def test_deliberation_bundle_from_debate_result_failed_quality_verdict() -> None:
    from types import SimpleNamespace

    result = SimpleNamespace(
        debate_id="debate-xyz",
        task="Rewrite auth in Rust",
        final_answer="",
        confidence=0.2,
        consensus_reached=False,
        consensus_strength="weak",
        consensus_variance=3.1,
        dissenting_views=["Risk too high", "No rollback plan"],
        participants=["agent-a", "agent-b"],
        per_agent_similarity={},
        convergence_status="diverging",
        debate_cruxes=[],
        metadata={},
    )

    bundle = DeliberationBundle.from_debate_result(result)

    assert bundle.consensus_reached is False
    assert bundle.quality_verdict == "failed"
    assert len(bundle.dissenting_views) == 2
    assert bundle.provenance_refs == []


def test_deliberation_bundle_to_dict_is_serializable() -> None:
    from types import SimpleNamespace

    result = SimpleNamespace(
        debate_id="d1",
        task="t",
        final_answer="a",
        confidence=0.5,
        consensus_reached=True,
        consensus_strength="strong",
        consensus_variance=0.5,
        dissenting_views=[],
        participants=["x"],
        per_agent_similarity={"x": 0.9},
        convergence_status="converged",
        debate_cruxes=[],
        metadata={"foo": "bar"},
    )

    bundle = DeliberationBundle.from_debate_result(result)
    d = bundle.to_dict()

    assert isinstance(d, dict)
    assert d["debate_id"] == "d1"
    assert d["quality_verdict"] == "passed"
    assert "dissenting_views" in d
    assert "unresolved_risks" in d


def test_outcome_feedback_record_from_pipeline_outcome_derives_next_action() -> None:
    outcome = PipelineOutcome(
        pipeline_id="pipe-001",
        run_type="user_project",
        domain="product",
        spec_completeness=0.8,
        execution_succeeded=False,
        tests_passed=3,
        tests_failed=2,
        files_changed=1,
        total_duration_s=42.0,
    )

    record = OutcomeFeedbackRecord.from_pipeline_outcome(
        outcome,
        receipt_ref="receipt-123",
    )

    assert record.receipt_ref == "receipt-123"
    assert record.pipeline_id == "pipe-001"
    assert record.objective_fidelity == outcome.overall_quality_score
    assert record.execution_outcome["tests_failed"] == 2
    assert record.next_action_recommendation == "run_bug_fix_loop"


def test_execution_attempt_record_from_plan_outcome_captures_stable_shape() -> None:
    outcome = PipelineOutcome(
        pipeline_id="pipe-002",
        run_type="automated",
        domain="infrastructure",
        spec_completeness=0.9,
        execution_succeeded=True,
        tests_passed=10,
        tests_failed=0,
        files_changed=3,
        total_duration_s=18.5,
    )

    record = ExecutionAttemptRecord.from_plan_outcome(
        outcome,
        attempt_id="attempt-001",
        plan_id="plan-abc",
        policy_decision={"allowed": True, "reason": "within budget"},
        taint_flags=["external_dependency"],
        artifacts=["dist/output.tar.gz", "reports/test-results.xml"],
        diff_summary="3 files changed, 42 insertions, 5 deletions",
    )

    assert record.attempt_id == "attempt-001"
    assert record.plan_id == "plan-abc"
    assert record.status == "succeeded"
    assert record.tests_passed == 10
    assert record.tests_failed == 0
    assert record.files_changed == 3
    assert record.policy_decision == {"allowed": True, "reason": "within budget"}
    assert record.taint_flags == ["external_dependency"]
    assert record.artifacts == ["dist/output.tar.gz", "reports/test-results.xml"]
    assert record.diff_summary == "3 files changed, 42 insertions, 5 deletions"


def test_execution_attempt_record_from_plan_outcome_failed_sets_status_failed() -> None:
    outcome = PipelineOutcome(
        pipeline_id="pipe-003",
        run_type="automated",
        domain="backend",
        spec_completeness=0.5,
        execution_succeeded=False,
        tests_passed=2,
        tests_failed=5,
        files_changed=1,
        total_duration_s=5.0,
    )

    record = ExecutionAttemptRecord.from_plan_outcome(outcome, attempt_id="attempt-002")

    assert record.status == "failed"
    assert record.tests_failed == 5


def test_generate_receipt_envelope_normalizes_successful_outcome() -> None:
    """CLB-009: Successful outcome produces ReceiptEnvelope with consistent shape."""
    from aragora.pipeline.receipt_generator import generate_receipt_envelope

    receipt = {
        "receipt_id": "r-success-001",
        "pipeline_id": "pipe-abc",
        "content_hash": "sha256abc",
        "provenance": {
            "ideas": [{"id": "i1", "label": "Idea"}],
            "goals": [{"id": "g1", "label": "Goal"}],
        },
        "execution": {"status": "completed"},
    }

    envelope = generate_receipt_envelope(
        receipt,
        policy_gate_result={"allowed": True},
        taint_summary={"tainted": False},
    )

    assert envelope.receipt_id == "r-success-001"
    assert envelope.verdict == "pass"
    assert envelope.policy_gate_result == {"allowed": True}
    assert envelope.taint_summary == {"tainted": False}
    assert len(envelope.provenance_chain) == 2


def test_generate_receipt_envelope_normalizes_blocked_outcome() -> None:
    """CLB-009: Blocked outcome shares the same ReceiptEnvelope shape with verdict=blocked."""
    from aragora.pipeline.receipt_generator import generate_receipt_envelope

    receipt = {
        "receipt_id": "r-blocked-001",
        "pipeline_id": "pipe-xyz",
        "content_hash": "sha256xyz",
        "provenance": {},
        "execution": {"status": "blocked"},
    }

    envelope = generate_receipt_envelope(
        receipt,
        policy_gate_result={"allowed": False, "reason": "budget_exceeded"},
        taint_summary={"tainted": True, "flags": ["external_unverified"]},
        blocked=True,
    )

    assert envelope.verdict == "blocked"
    assert envelope.policy_gate_result["allowed"] is False
    assert envelope.taint_summary["tainted"] is True


def test_generate_receipt_envelope_defaults_empty_dicts_when_missing() -> None:
    """CLB-009: Envelope always has policy_gate_result and taint_summary even if omitted."""
    from aragora.pipeline.receipt_generator import generate_receipt_envelope

    receipt = {
        "receipt_id": "r-min",
        "pipeline_id": "pipe-min",
        "content_hash": "",
        "provenance": {},
        "execution": {"status": "completed"},
    }

    envelope = generate_receipt_envelope(receipt)

    assert envelope.policy_gate_result == {}
    assert envelope.taint_summary == {}
    assert envelope.verdict == "pass"


def test_execution_attempt_record_to_dict_is_serializable() -> None:
    outcome = PipelineOutcome(
        pipeline_id="pipe-004",
        run_type="manual",
        domain="frontend",
        execution_succeeded=True,
        tests_passed=5,
        tests_failed=0,
        files_changed=2,
        total_duration_s=8.0,
    )

    record = ExecutionAttemptRecord.from_plan_outcome(outcome, attempt_id="a3")
    d = record.to_dict()

    assert isinstance(d, dict)
    assert d["attempt_id"] == "a3"
    assert d["status"] == "succeeded"
    assert "policy_decision" in d
    assert "artifacts" in d
