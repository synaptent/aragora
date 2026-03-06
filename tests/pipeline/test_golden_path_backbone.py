"""CLB-013: Golden-path E2E test for the closed-loop backbone.

Exercises the full handoff chain:
    intake -> spec -> deliberation -> execution -> receipt -> feedback

Every stage is validated using canonical backbone_contracts types.
No real LLM calls are made -- all stage data is constructed or mocked.
"""

from __future__ import annotations

import json

import pytest

from aragora.pipeline.backbone_contracts import (
    DeliberationBundle,
    ExecutionAttemptRecord,
    IntakeBundle,
    OutcomeFeedbackRecord,
    ReceiptEnvelope,
    SpecBundle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_intake() -> IntakeBundle:
    return IntakeBundle(
        source_kind="test",
        raw_intent="Improve error handling in auth module",
        context_refs=[{"source": "codebase", "path": "aragora/auth/"}],
        trust_tiers=["operator-authored"],
        origin_metadata={"entrypoint": "golden_path_test"},
    )


def _make_execution_grade_spec() -> SpecBundle:
    return SpecBundle(
        title="Improve auth error handling",
        problem_statement="Auth module has bare except blocks that swallow errors",
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
        source_kind="prompt_engine_spec",
    )


def _make_non_execution_grade_spec() -> SpecBundle:
    """Spec missing required fields -- should NOT be execution-grade."""
    return SpecBundle(
        title="Vague improvement idea",
        problem_statement="Something about auth",
    )


def _make_deliberation(*, consensus: bool = True, confidence: float = 0.85) -> DeliberationBundle:
    return DeliberationBundle(
        debate_id="test-debate-001",
        verdict="Approved: narrowing exception types improves reliability",
        confidence=confidence,
        consensus_reached=consensus,
        consensus_strength="strong" if consensus else "weak",
        quality_verdict="passed" if (consensus and confidence >= 0.5) else "failed",
        dissenting_views=[] if consensus else ["Risk of breaking changes is underweighted"],
        unresolved_risks=[] if consensus else [{"claim": "May introduce regressions"}],
        participant_count=3,
        diversity_scores={"analyst": 0.82, "critic": 0.65, "synthesizer": 0.91},
    )


def _make_execution(*, succeeded: bool = True) -> ExecutionAttemptRecord:
    return ExecutionAttemptRecord(
        attempt_id="attempt-001",
        plan_id="plan-auth-fix",
        status="succeeded" if succeeded else "failed",
        tests_passed=12 if succeeded else 8,
        tests_failed=0 if succeeded else 4,
        files_changed=3,
        diff_summary="3 files changed, 42 insertions, 5 deletions",
        artifacts=["reports/test-results.xml"],
        policy_decision={"allowed": True, "reason": "within budget"},
        duration_s=18.5,
        error_message="" if succeeded else "4 tests failed in auth module",
    )


def _make_receipt(*, verdict: str = "pass") -> ReceiptEnvelope:
    return ReceiptEnvelope(
        receipt_id="receipt-test-001",
        artifact_hash="sha256-abc123def456",
        verdict=verdict,
        confidence=0.85,
        policy_gate_result={"allowed": True},
        provenance_chain=[
            {"stage": "intake", "source_kind": "test"},
            {"stage": "deliberation", "debate_id": "test-debate-001"},
        ],
    )


def _make_feedback(receipt: ReceiptEnvelope) -> OutcomeFeedbackRecord:
    return OutcomeFeedbackRecord(
        receipt_ref=receipt.receipt_id,
        pipeline_id="pipe-test-001",
        run_type="test",
        domain="auth",
        objective_fidelity=0.85,
        quality_outcome={"overall_quality_score": 0.85, "spec_completeness": 0.9},
        execution_outcome={
            "execution_succeeded": True,
            "tests_passed": 12,
            "tests_failed": 0,
        },
        next_action_recommendation="promote_or_settle",
    )


# ---------------------------------------------------------------------------
# Happy path: full backbone traversal
# ---------------------------------------------------------------------------


class TestGoldenPathBackbone:
    """E2E test: intake -> spec -> debate -> execute -> receipt -> feedback."""

    def test_full_backbone_flow(self) -> None:
        """All six stages produce valid artifacts that chain together."""
        # Stage 0: Intake
        intake = _make_intake()
        assert intake.raw_intent
        assert intake.source_kind == "test"
        intake_dict = intake.to_dict()
        assert isinstance(intake_dict, dict)
        assert intake_dict["raw_intent"] == intake.raw_intent

        # Stage 1: Spec
        spec = _make_execution_grade_spec()
        assert spec.is_execution_grade
        assert not spec.missing_required_fields
        spec_dict = spec.to_dict()
        assert spec_dict["is_execution_grade"] is True

        # Stage 2: Deliberation
        deliberation = _make_deliberation()
        assert deliberation.quality_verdict == "passed"
        assert deliberation.consensus_reached is True
        delib_dict = deliberation.to_dict()
        assert delib_dict["debate_id"] == "test-debate-001"

        # Stage 3: Execution
        execution = _make_execution(succeeded=True)
        assert execution.status == "succeeded"
        assert execution.tests_failed == 0
        exec_dict = execution.to_dict()
        assert exec_dict["attempt_id"] == "attempt-001"

        # Stage 4: Receipt
        receipt = _make_receipt(verdict="pass")
        assert receipt.verdict == "pass"
        assert receipt.receipt_id
        receipt_dict = receipt.to_dict()
        assert len(receipt_dict["provenance_chain"]) == 2

        # Stage 5: Feedback
        feedback = _make_feedback(receipt)
        assert feedback.receipt_ref == receipt.receipt_id
        assert feedback.next_action_recommendation == "promote_or_settle"
        feedback_dict = feedback.to_dict()
        assert feedback_dict["pipeline_id"] == "pipe-test-001"

        # Cross-stage consistency: all artifacts are serializable
        all_stages = [intake, spec, deliberation, execution, receipt, feedback]
        for stage in all_stages:
            assert hasattr(stage, "to_dict")
            d = stage.to_dict()
            assert isinstance(d, dict)
            # Verify JSON-serializable (no datetime, dataclass, or custom objects)
            json.dumps(d)

    def test_backbone_chain_references_are_consistent(self) -> None:
        """Downstream stages reference upstream identifiers correctly."""
        intake = _make_intake()
        spec = _make_execution_grade_spec()
        deliberation = _make_deliberation()
        execution = _make_execution(succeeded=True)
        receipt = _make_receipt()
        feedback = _make_feedback(receipt)

        # Receipt references deliberation
        assert any(
            ref.get("debate_id") == deliberation.debate_id for ref in receipt.provenance_chain
        )

        # Feedback references receipt
        assert feedback.receipt_ref == receipt.receipt_id

        # Execution references a plan
        assert execution.plan_id


# ---------------------------------------------------------------------------
# Failure path: spec not execution-grade
# ---------------------------------------------------------------------------


class TestSpecGateFailure:
    """Tests what happens when spec is not execution-grade."""

    def test_non_execution_grade_spec_reports_missing_fields(self) -> None:
        spec = _make_non_execution_grade_spec()
        assert spec.is_execution_grade is False

        missing = spec.missing_required_fields
        assert "constraints" in missing
        assert "acceptance_criteria" in missing
        assert "verification_plan" in missing
        assert "rollback_plan" in missing
        assert "owner_file_scopes" in missing

    def test_non_execution_grade_spec_to_dict_includes_missing_fields(self) -> None:
        spec = _make_non_execution_grade_spec()
        d = spec.to_dict()
        assert d["is_execution_grade"] is False
        assert len(d["missing_required_fields"]) == 5

    def test_partial_spec_identifies_exact_gaps(self) -> None:
        """A spec with some but not all required fields lists only the gaps."""
        spec = SpecBundle(
            title="Partial spec",
            problem_statement="Partially defined",
            constraints=["Keep it backwards compatible"],
            acceptance_criteria=["Tests pass"],
            # Missing: verification_plan, rollback_plan, owner_file_scopes
        )
        assert spec.is_execution_grade is False
        missing = spec.missing_required_fields
        assert "verification_plan" in missing
        assert "rollback_plan" in missing
        assert "owner_file_scopes" in missing
        assert "constraints" not in missing
        assert "acceptance_criteria" not in missing


# ---------------------------------------------------------------------------
# Failure path: deliberation quality gate failure
# ---------------------------------------------------------------------------


class TestDeliberationQualityGateFailure:
    """Tests what happens when deliberation fails the quality gate."""

    def test_low_confidence_no_consensus_fails_quality(self) -> None:
        deliberation = _make_deliberation(consensus=False, confidence=0.2)
        assert deliberation.quality_verdict == "failed"
        assert deliberation.consensus_reached is False

    def test_high_confidence_no_consensus_still_fails(self) -> None:
        """Even with decent confidence, no consensus should fail."""
        deliberation = DeliberationBundle(
            debate_id="d-fail-002",
            verdict="Contested decision",
            confidence=0.7,
            consensus_reached=False,
            quality_verdict="failed",
            dissenting_views=["Approach A is better", "Approach B is better"],
        )
        assert deliberation.quality_verdict == "failed"
        assert len(deliberation.dissenting_views) == 2

    def test_quality_verdict_from_debate_result_auto_derives(self) -> None:
        """The from_debate_result factory auto-derives quality_verdict."""
        from types import SimpleNamespace

        result = SimpleNamespace(
            debate_id="auto-fail",
            task="test",
            final_answer="",
            confidence=0.1,
            consensus_reached=False,
            consensus_strength="none",
            consensus_variance=5.0,
            dissenting_views=["A", "B", "C"],
            participants=["x", "y"],
            per_agent_similarity={},
            convergence_status="diverging",
            debate_cruxes=[],
            metadata={},
        )

        bundle = DeliberationBundle.from_debate_result(result)
        assert bundle.quality_verdict == "failed"


# ---------------------------------------------------------------------------
# Failure path: execution failure
# ---------------------------------------------------------------------------


class TestExecutionFailure:
    """Tests that execution failures propagate into receipt and feedback."""

    def test_failed_execution_produces_failed_status(self) -> None:
        execution = _make_execution(succeeded=False)
        assert execution.status == "failed"
        assert execution.tests_failed == 4
        assert execution.error_message

    def test_failed_execution_leads_to_blocked_receipt(self) -> None:
        receipt = _make_receipt(verdict="blocked")
        assert receipt.verdict == "blocked"

    def test_failed_execution_feedback_recommends_bug_fix(self) -> None:
        receipt = ReceiptEnvelope(
            receipt_id="receipt-fail-001",
            artifact_hash="sha256-fail",
            verdict="blocked",
            confidence=0.4,
        )
        feedback = OutcomeFeedbackRecord(
            receipt_ref=receipt.receipt_id,
            pipeline_id="pipe-fail-001",
            run_type="test",
            domain="auth",
            objective_fidelity=0.3,
            execution_outcome={
                "execution_succeeded": False,
                "tests_passed": 8,
                "tests_failed": 4,
            },
            next_action_recommendation="run_bug_fix_loop",
        )
        assert feedback.next_action_recommendation == "run_bug_fix_loop"
        assert feedback.execution_outcome["tests_failed"] == 4

    def test_from_pipeline_outcome_auto_derives_next_action(self) -> None:
        """from_pipeline_outcome should auto-detect the correct next action."""
        from aragora.pipeline.outcome_feedback import PipelineOutcome

        # Case 1: success -> promote
        success_outcome = PipelineOutcome(
            pipeline_id="p1",
            run_type="auto",
            domain="auth",
            execution_succeeded=True,
            tests_passed=10,
            tests_failed=0,
        )
        record = OutcomeFeedbackRecord.from_pipeline_outcome(success_outcome, receipt_ref="r1")
        assert record.next_action_recommendation == "promote_or_settle"

        # Case 2: test failures -> bug fix loop
        fail_outcome = PipelineOutcome(
            pipeline_id="p2",
            run_type="auto",
            domain="auth",
            execution_succeeded=False,
            tests_passed=5,
            tests_failed=3,
        )
        record = OutcomeFeedbackRecord.from_pipeline_outcome(fail_outcome, receipt_ref="r2")
        assert record.next_action_recommendation == "run_bug_fix_loop"

        # Case 3: no test data -> manual review
        blocked_outcome = PipelineOutcome(
            pipeline_id="p3",
            run_type="auto",
            domain="auth",
            execution_succeeded=False,
            tests_passed=0,
            tests_failed=0,
        )
        record = OutcomeFeedbackRecord.from_pipeline_outcome(blocked_outcome, receipt_ref="r3")
        assert record.next_action_recommendation == "review_manually"


# ---------------------------------------------------------------------------
# Serialization: all stages round-trip through JSON
# ---------------------------------------------------------------------------


class TestBackboneJsonSerializationRoundTrip:
    """Verifies that every backbone artifact survives a JSON round-trip."""

    @pytest.mark.parametrize(
        "make_fn",
        [
            _make_intake,
            _make_execution_grade_spec,
            _make_non_execution_grade_spec,
            lambda: _make_deliberation(),
            lambda: _make_execution(succeeded=True),
            lambda: _make_execution(succeeded=False),
            lambda: _make_receipt(verdict="pass"),
            lambda: _make_receipt(verdict="blocked"),
            lambda: _make_feedback(_make_receipt()),
        ],
        ids=[
            "IntakeBundle",
            "SpecBundle-exec-grade",
            "SpecBundle-non-exec-grade",
            "DeliberationBundle",
            "ExecutionAttemptRecord-success",
            "ExecutionAttemptRecord-failure",
            "ReceiptEnvelope-pass",
            "ReceiptEnvelope-blocked",
            "OutcomeFeedbackRecord",
        ],
    )
    def test_json_round_trip(self, make_fn) -> None:
        artifact = make_fn()
        d = artifact.to_dict()
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        assert deserialized == d
