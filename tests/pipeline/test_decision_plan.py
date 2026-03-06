"""
Tests for aragora.pipeline.decision_plan -- the gold path bridge.

Covers:
- DecisionPlanFactory.from_debate_result (end-to-end creation)
- Risk register generation from DebateResult
- Verification plan generation from DebateResult
- Implementation plan extraction from final answer
- Budget tracking and limits
- Approval logic (risk-based, confidence-based, always, never)
- Workflow generation with risk-aware routing
- Status lifecycle
- Serialization round-trip
"""

from __future__ import annotations

import pytest

from aragora.core_types import Critique, DebateResult, Vote
from aragora.pipeline.decision_plan import (
    ApprovalMode,
    ApprovalRecord,
    BudgetAllocation,
    DecisionPlan,
    DecisionPlanFactory,
    ImplementationProfile,
    PlanOutcome,
    PlanStatus,
    record_plan_outcome,
)
from aragora.pipeline.risk_register import RiskLevel
from aragora.prompt_engine.spec_validator import ValidationResult, ValidatorRole
from aragora.prompt_engine.types import RiskItem, Specification, SpecFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(**overrides) -> DebateResult:
    """Create a DebateResult with sensible defaults."""
    defaults = {
        "debate_id": "test-debate-001",
        "task": "Design a rate limiter for our API",
        "final_answer": (
            "1. Implement token bucket algorithm in `rate_limiter.py`\n"
            "2. Add Redis backend for distributed counting\n"
            "3. Create middleware wrapper for Flask routes\n"
            "4. Add configuration for per-endpoint limits"
        ),
        "confidence": 0.85,
        "consensus_reached": True,
        "rounds_used": 3,
        "participants": ["claude", "gpt4", "gemini"],
        "total_cost_usd": 0.05,
    }
    defaults.update(overrides)
    return DebateResult(**defaults)


def _make_result_with_critiques() -> DebateResult:
    """Create a DebateResult with high-severity critiques."""
    return _make_result(
        critiques=[
            Critique(
                agent="gpt4",
                target_agent="claude",
                target_content="token bucket",
                issues=[
                    "No handling of burst traffic patterns",
                    "Redis single point of failure risk",
                ],
                suggestions=["Add sliding window fallback", "Add Redis Sentinel"],
                severity=8.0,
                reasoning="Reliability concerns",
            ),
            Critique(
                agent="gemini",
                target_agent="claude",
                target_content="middleware",
                issues=["Missing rate limit bypass for health checks"],
                suggestions=["Add whitelist for internal endpoints"],
                severity=5.0,
                reasoning="Operational concerns",
            ),
        ],
        dissenting_views=["Consider sliding window instead of token bucket"],
        debate_cruxes=[{"claim": "Token bucket is the best algorithm", "sensitivity": 0.7}],
    )


# ---------------------------------------------------------------------------
# DecisionPlanFactory.from_debate_result
# ---------------------------------------------------------------------------


class TestDecisionPlanFactory:
    """Tests for the factory that creates DecisionPlan from DebateResult."""

    def test_basic_creation(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)

        assert plan.debate_id == "test-debate-001"
        assert plan.task == "Design a rate limiter for our API"
        assert plan.debate_result is result
        assert plan.risk_register is not None
        assert plan.verification_plan is not None
        assert plan.implement_plan is not None

    def test_implementation_tasks_extracted(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)

        tasks = plan.implement_plan.tasks
        assert len(tasks) >= 3
        assert any("token bucket" in t.description.lower() for t in tasks)
        assert any("redis" in t.description.lower() for t in tasks)

    def test_verification_plan_generated(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)

        cases = plan.verification_plan.test_cases
        # Should have at least smoke + regression
        assert len(cases) >= 2
        # Should have a smoke test
        assert any(c.id == "smoke-1" for c in cases)
        # Should have a regression test
        assert any(c.id == "regression-1" for c in cases)

    def test_risks_from_critiques(self):
        result = _make_result_with_critiques()
        plan = DecisionPlanFactory.from_debate_result(result)

        risks = plan.risk_register.risks
        # Should have risks from high-severity critiques
        critique_risks = [r for r in risks if r.source.startswith("critique:")]
        assert len(critique_risks) >= 1
        # Should have risks from dissenting views
        dissent_risks = [r for r in risks if r.source == "dissent_analysis"]
        assert len(dissent_risks) >= 1
        # Should have risks from cruxes
        crux_risks = [r for r in risks if r.source == "belief_network"]
        assert len(crux_risks) >= 1

    def test_low_confidence_risk(self):
        result = _make_result(confidence=0.4)
        plan = DecisionPlanFactory.from_debate_result(result)

        conf_risks = [r for r in plan.risk_register.risks if "confidence" in r.title.lower()]
        assert len(conf_risks) == 1
        assert conf_risks[0].level == RiskLevel.HIGH  # <0.5 = HIGH

    def test_no_consensus_risk(self):
        result = _make_result(consensus_reached=False)
        plan = DecisionPlanFactory.from_debate_result(result)

        no_cons_risks = [r for r in plan.risk_register.risks if "no consensus" in r.title.lower()]
        assert len(no_cons_risks) == 1
        assert no_cons_risks[0].level == RiskLevel.HIGH

    def test_budget_from_debate_cost(self):
        result = _make_result(total_cost_usd=0.15)
        plan = DecisionPlanFactory.from_debate_result(result, budget_limit_usd=5.0)

        assert plan.budget.limit_usd == 5.0
        assert plan.budget.debate_cost_usd == 0.15
        assert plan.budget.spent_usd == 0.15
        assert plan.budget.remaining_usd == pytest.approx(4.85)
        assert not plan.budget.over_budget

    def test_fallback_single_task(self):
        """When no structured steps found, should create a single fallback task."""
        result = _make_result(final_answer="Just a plain paragraph with no numbered steps.")
        plan = DecisionPlanFactory.from_debate_result(result)

        assert len(plan.implement_plan.tasks) == 1
        assert plan.implement_plan.tasks[0].complexity == "complex"

    def test_validate_execution_grade_specification_fail_closed(self):
        spec = Specification(
            title="Incomplete spec",
            problem_statement="Problem",
            proposed_solution="Solution",
            success_criteria=["Criterion"],
        )

        with pytest.raises(ValueError, match="execution-grade"):
            DecisionPlanFactory.validate_execution_grade_specification(spec, fail_closed=True)

    def test_from_debate_result_blocks_incomplete_spec_for_never_mode(self):
        spec = Specification(
            title="Incomplete spec",
            problem_statement="Problem",
            proposed_solution="Solution",
            success_criteria=["Criterion"],
        )

        with pytest.raises(ValueError, match="owner_file_scopes"):
            DecisionPlanFactory.from_debate_result(
                _make_result(),
                approval_mode=ApprovalMode.NEVER,
                specification=spec,
            )

    def test_from_debate_result_records_missing_spec_fields_for_manual_lane(self):
        spec = Specification(
            title="Incomplete spec",
            problem_statement="Problem",
            proposed_solution="Solution",
            success_criteria=["Criterion"],
        )

        plan = DecisionPlanFactory.from_debate_result(
            _make_result(),
            approval_mode=ApprovalMode.ALWAYS,
            specification=spec,
        )

        assert "spec_bundle" in plan.metadata
        assert sorted(plan.metadata["spec_bundle_missing_fields"]) == [
            "constraints",
            "owner_file_scopes",
            "rollback_plan",
        ]

    def test_from_debate_result_accepts_execution_grade_spec_in_auto_lane(self):
        spec = Specification(
            title="Execution-grade spec",
            problem_statement="Problem",
            proposed_solution="Solution",
            success_criteria=["Criterion"],
            file_changes=[
                SpecFile(path="aragora/pipeline/example.py", action="modify", description="Change")
            ],
            risks=[
                RiskItem(
                    description="Regression risk",
                    likelihood="medium",
                    impact="medium",
                    mitigation="Use staged rollback",
                )
            ],
        )
        spec.constraints = ["Keep existing API contract stable"]
        validation = ValidationResult(
            role_results={ValidatorRole.DEVILS_ADVOCATE: {"passed": True, "confidence": 0.9}},
            overall_confidence=0.9,
            passed=True,
        )

        plan = DecisionPlanFactory.from_debate_result(
            _make_result(),
            approval_mode=ApprovalMode.NEVER,
            specification=spec,
            validation_result=validation,
        )

        assert plan.metadata["spec_bundle"]["title"] == "Execution-grade spec"
        assert "spec_bundle_missing_fields" not in plan.metadata

    def test_from_debate_result_stores_deliberation_bundle_in_metadata(self):
        result = _make_result(
            consensus_reached=True,
            confidence=0.82,
            dissenting_views=["Dissenter view A"],
        )

        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)

        db = plan.metadata.get("deliberation_bundle", {})
        assert db.get("debate_id") == "test-debate-001"
        assert db.get("quality_verdict") == "passed"
        assert db.get("consensus_reached") is True
        assert db.get("confidence") == pytest.approx(0.82)
        assert "Dissenter view A" in db.get("dissenting_views", [])

    def test_from_debate_result_halts_automated_planning_on_failed_quality(self):
        result = _make_result(
            consensus_reached=False,
            confidence=0.15,
        )

        with pytest.raises(ValueError, match="quality verdict"):
            DecisionPlanFactory.from_debate_result(
                result,
                approval_mode=ApprovalMode.NEVER,
            )

    def test_from_debate_result_allows_manual_lane_on_failed_quality(self):
        result = _make_result(
            consensus_reached=False,
            confidence=0.15,
        )

        # ALWAYS approval mode should not raise even on failed quality
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)
        db = plan.metadata.get("deliberation_bundle", {})
        assert db.get("quality_verdict") == "failed"

    def test_from_debate_result_accepts_explicit_deliberation_bundle(self):
        from aragora.pipeline.backbone_contracts import DeliberationBundle

        result = _make_result(consensus_reached=True, confidence=0.9)
        bundle = DeliberationBundle(
            debate_id="custom-debate",
            verdict="Custom verdict",
            confidence=0.9,
            consensus_reached=True,
            quality_verdict="passed",
        )

        plan = DecisionPlanFactory.from_debate_result(
            result,
            approval_mode=ApprovalMode.ALWAYS,
            deliberation_bundle=bundle,
        )

        db = plan.metadata.get("deliberation_bundle", {})
        assert db.get("debate_id") == "custom-debate"
        assert db.get("verdict") == "Custom verdict"


# ---------------------------------------------------------------------------
# Approval Logic
# ---------------------------------------------------------------------------


class TestApprovalLogic:
    """Tests for the approval determination and recording."""

    def test_risk_based_requires_approval_on_high_risk(self):
        result = _make_result(consensus_reached=False)  # Triggers HIGH risk
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.RISK_BASED)
        assert plan.requires_human_approval is True

    def test_risk_based_no_approval_on_low_risk(self):
        result = _make_result(confidence=0.95)  # High confidence, no critiques
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.RISK_BASED)
        # Only dissent/crux risks at MEDIUM, highest is MEDIUM
        # max_auto_risk defaults to LOW, so MEDIUM > LOW → requires approval
        # But if we raise max_auto_risk to MEDIUM:
        plan.max_auto_risk = RiskLevel.MEDIUM
        # Now it should not require approval since no risks above MEDIUM
        assert plan.requires_human_approval is False

    def test_always_mode(self):
        result = _make_result(confidence=0.99)
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)
        assert plan.requires_human_approval is True

    def test_never_mode(self):
        # consensus_reached=True with adequate confidence → quality_verdict="passed", gate passes
        result = _make_result(consensus_reached=True, confidence=0.85)
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.NEVER)
        assert plan.requires_human_approval is False

    def test_confidence_based_low_confidence(self):
        result = _make_result(confidence=0.6)
        plan = DecisionPlanFactory.from_debate_result(
            result, approval_mode=ApprovalMode.CONFIDENCE_BASED
        )
        assert plan.requires_human_approval is True

    def test_confidence_based_high_confidence(self):
        result = _make_result(confidence=0.9)
        plan = DecisionPlanFactory.from_debate_result(
            result, approval_mode=ApprovalMode.CONFIDENCE_BASED
        )
        assert plan.requires_human_approval is False

    def test_approve_advances_status(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)
        plan.status = PlanStatus.AWAITING_APPROVAL

        plan.approve("user-123", reason="Looks good")

        assert plan.status == PlanStatus.APPROVED
        assert plan.is_approved is True
        assert plan.approval_record.approver_id == "user-123"
        assert plan.approval_record.reason == "Looks good"

    def test_reject_advances_status(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)

        plan.reject("user-456", reason="Too risky")

        assert plan.status == PlanStatus.REJECTED
        assert plan.is_approved is False
        assert plan.approval_record.approved is False


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class TestBudgetAllocation:
    """Tests for BudgetAllocation tracking."""

    def test_unlimited_budget(self):
        budget = BudgetAllocation()
        assert budget.remaining_usd is None
        assert not budget.over_budget

    def test_budget_tracking(self):
        budget = BudgetAllocation(limit_usd=10.0, spent_usd=7.5)
        assert budget.remaining_usd == pytest.approx(2.5)
        assert not budget.over_budget

    def test_over_budget(self):
        budget = BudgetAllocation(limit_usd=1.0, spent_usd=1.5)
        assert budget.remaining_usd == 0.0
        assert budget.over_budget

    def test_to_dict(self):
        budget = BudgetAllocation(
            limit_usd=5.0,
            spent_usd=2.0,
            debate_cost_usd=0.5,
            implementation_cost_usd=1.0,
            verification_cost_usd=0.5,
        )
        d = budget.to_dict()
        assert d["limit_usd"] == 5.0
        assert d["remaining_usd"] == pytest.approx(3.0)
        assert d["over_budget"] is False


# ---------------------------------------------------------------------------
# Workflow Generation
# ---------------------------------------------------------------------------


class TestWorkflowGeneration:
    """Tests for to_workflow_definition()."""

    def test_basic_workflow_structure(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)
        workflow = plan.to_workflow_definition()

        assert workflow.id == f"wf-{plan.id}"
        assert len(workflow.steps) >= 3  # At least: impl tasks + verify + memory
        assert len(workflow.transitions) >= 2

        # Check step types
        step_types = [s.step_type for s in workflow.steps]
        assert "memory_write" in step_types  # Feedback loop

    def test_approval_checkpoint_when_required(self):
        result = _make_result(consensus_reached=False)
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)
        workflow = plan.to_workflow_definition()

        # First step should be human checkpoint
        assert workflow.steps[0].step_type == "human_checkpoint"
        assert "Approval" in workflow.steps[0].name

    def test_no_approval_checkpoint_when_auto(self):
        result = _make_result(confidence=0.95)
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.NEVER)
        workflow = plan.to_workflow_definition()

        # First step should NOT be human checkpoint
        assert workflow.steps[0].step_type != "human_checkpoint"

    def test_workflow_has_verification_step(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)
        workflow = plan.to_workflow_definition()

        verify_steps = [s for s in workflow.steps if s.name == "Run Verification"]
        assert len(verify_steps) == 1

    def test_workflow_has_memory_writeback(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)
        workflow = plan.to_workflow_definition()

        memory_steps = [s for s in workflow.steps if s.step_type == "memory_write"]
        assert len(memory_steps) == 1
        assert memory_steps[0].config["debate_id"] == "test-debate-001"

    def test_workflow_metadata_includes_context(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)
        workflow = plan.to_workflow_definition()

        assert workflow.metadata["debate_id"] == "test-debate-001"
        assert workflow.metadata["debate_confidence"] == 0.85

    def test_workflow_includes_openclaw_actions(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(
            result,
            metadata={
                "openclaw_actions": [
                    {
                        "action_type": "shell",
                        "command": "ls -la",
                        "description": "List workspace files",
                    }
                ],
                "openclaw_session": {"workspace_id": "/workspace/project"},
            },
        )
        workflow = plan.to_workflow_definition()

        step_types = [s.step_type for s in workflow.steps]
        assert "openclaw_session" in step_types
        assert "openclaw_action" in step_types

        action_steps = [s for s in workflow.steps if s.step_type == "openclaw_action"]
        assert action_steps, "Expected at least one OpenClaw action step"
        assert action_steps[0].config.get("session_id", "").startswith("{step.")

    def test_workflow_maps_computer_use_actions(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(
            result,
            metadata={
                "computer_use_actions": [
                    {"action": "click", "coordinate": [12, 34], "description": "Click button"}
                ]
            },
        )
        workflow = plan.to_workflow_definition()

        action_steps = [s for s in workflow.steps if s.step_type == "openclaw_action"]
        assert action_steps
        assert action_steps[0].config.get("action_type") == "mouse"

    def test_workflow_validates(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)
        workflow = plan.to_workflow_definition()

        is_valid, errors = workflow.validate()
        assert is_valid, f"Workflow validation failed: {errors}"


# ---------------------------------------------------------------------------
# Risk Assessment Properties
# ---------------------------------------------------------------------------


class TestRiskAssessment:
    """Tests for risk properties on DecisionPlan."""

    def test_no_risks_gives_low(self):
        plan = DecisionPlan()
        assert plan.highest_risk_level == RiskLevel.LOW
        assert not plan.has_critical_risks

    def test_critical_risks_detected(self):
        result = _make_result(consensus_reached=False)  # HIGH risk
        plan = DecisionPlanFactory.from_debate_result(result)
        # No consensus gives HIGH, not CRITICAL
        assert plan.highest_risk_level == RiskLevel.HIGH


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    """Tests for to_dict()."""

    def test_to_dict_includes_all_fields(self):
        result = _make_result_with_critiques()
        plan = DecisionPlanFactory.from_debate_result(result, budget_limit_usd=10.0)
        d = plan.to_dict()

        assert d["debate_id"] == "test-debate-001"
        assert d["status"] == "awaiting_approval"
        assert d["budget"]["limit_usd"] == 10.0
        assert d["risk_register"] is not None
        assert d["verification_plan"] is not None
        assert d["implement_plan"] is not None
        assert "has_critical_risks" in d
        assert "requires_human_approval" in d

    def test_summary_output(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)
        summary = plan.summary()

        assert "Decision Plan" in summary
        assert "rate limiter" in summary.lower()
        assert "85%" in summary


# ---------------------------------------------------------------------------
# ImplementationProfile
# ---------------------------------------------------------------------------


class TestImplementationProfile:
    """Tests for ImplementationProfile parsing and wiring."""

    def test_profile_from_dict_normalizes_lists(self):
        profile = ImplementationProfile.from_dict(
            {
                "execution_mode": "fabric",
                "implementers": "claude, codex",
                "fabric_models": ["claude", "codex"],
                "channel_targets": "slack:#eng,teams:abc",
                "thread_id_by_platform": {"slack": "t-1"},
            }
        )

        assert profile.execution_mode == "fabric"
        assert profile.implementers == ["claude", "codex"]
        assert profile.fabric_models == ["claude", "codex"]
        assert profile.channel_targets == ["slack:#eng", "teams:abc"]
        assert profile.thread_id_by_platform == {"slack": "t-1"}

    def test_plan_parses_profile_from_metadata(self):
        plan = DecisionPlan(metadata={"implementation": {"implementers": "claude"}})
        assert plan.implementation_profile is not None
        assert plan.implementation_profile.implementers == ["claude"]

    def test_plan_to_dict_includes_profile(self):
        profile = ImplementationProfile(execution_mode="fabric", implementers=["claude"])
        plan = DecisionPlan(implementation_profile=profile)
        payload = plan.to_dict()
        assert payload["implementation_profile"]["execution_mode"] == "fabric"


# ---------------------------------------------------------------------------
# Status Lifecycle
# ---------------------------------------------------------------------------


class TestStatusLifecycle:
    """Tests for plan status transitions."""

    def test_initial_status_awaiting_approval(self):
        result = _make_result(consensus_reached=False)
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)
        assert plan.status == PlanStatus.AWAITING_APPROVAL

    def test_initial_status_approved_when_auto(self):
        result = _make_result(confidence=0.95)
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.NEVER)
        assert plan.status == PlanStatus.APPROVED

    def test_execution_tracking(self):
        from datetime import datetime

        plan = DecisionPlan(status=PlanStatus.APPROVED)
        plan.status = PlanStatus.EXECUTING
        plan.execution_started_at = datetime.now()

        assert plan.status == PlanStatus.EXECUTING
        assert plan.execution_started_at is not None

    def test_completion_tracking(self):
        from datetime import datetime

        plan = DecisionPlan(status=PlanStatus.EXECUTING)
        plan.status = PlanStatus.COMPLETED
        plan.execution_completed_at = datetime.now()
        plan.memory_written = True

        assert plan.status == PlanStatus.COMPLETED
        assert plan.memory_written is True


# ---------------------------------------------------------------------------
# PlanOutcome
# ---------------------------------------------------------------------------


class TestPlanOutcome:
    """Tests for PlanOutcome data structure."""

    def test_completion_rate(self):
        outcome = PlanOutcome(
            plan_id="dp-1",
            debate_id="d-1",
            task="test",
            success=True,
            tasks_completed=3,
            tasks_total=4,
        )
        assert outcome.completion_rate == pytest.approx(0.75)

    def test_verification_rate(self):
        outcome = PlanOutcome(
            plan_id="dp-1",
            debate_id="d-1",
            task="test",
            success=True,
            verification_passed=5,
            verification_total=6,
        )
        assert outcome.verification_rate == pytest.approx(5 / 6)

    def test_zero_division(self):
        outcome = PlanOutcome(plan_id="dp-1", debate_id="d-1", task="test", success=False)
        assert outcome.completion_rate == 0.0
        assert outcome.verification_rate == 0.0

    def test_to_memory_content(self):
        outcome = PlanOutcome(
            plan_id="dp-1",
            debate_id="d-1",
            task="Design rate limiter",
            success=True,
            tasks_completed=3,
            tasks_total=3,
            verification_passed=5,
            verification_total=6,
            total_cost_usd=0.12,
            lessons=["Token bucket works well for API rate limiting"],
        )
        content = outcome.to_memory_content()

        assert "SUCCESS" in content
        assert "Design rate limiter" in content
        assert "3/3 tasks" in content
        assert "5/6 cases" in content
        assert "Token bucket" in content

    def test_to_dict(self):
        outcome = PlanOutcome(
            plan_id="dp-1",
            debate_id="d-1",
            task="test",
            success=True,
            tasks_completed=2,
            tasks_total=3,
        )
        d = outcome.to_dict()
        assert d["success"] is True
        assert d["completion_rate"] == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# Memory Feedback Loop
# ---------------------------------------------------------------------------


class TestRecordPlanOutcome:
    """Tests for record_plan_outcome (the feedback loop)."""

    @pytest.mark.asyncio
    async def test_updates_plan_status_on_success(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)
        plan.status = PlanStatus.EXECUTING

        outcome = PlanOutcome(
            plan_id=plan.id,
            debate_id=plan.debate_id,
            task=plan.task,
            success=True,
            tasks_completed=3,
            tasks_total=3,
            total_cost_usd=0.25,
        )

        results = await record_plan_outcome(plan, outcome)

        assert plan.status == PlanStatus.COMPLETED
        assert plan.execution_completed_at is not None
        assert plan.budget.spent_usd == 0.25
        assert plan.memory_written is True
        assert results["errors"] == []

    @pytest.mark.asyncio
    async def test_updates_plan_status_on_failure(self):
        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)
        plan.status = PlanStatus.EXECUTING

        outcome = PlanOutcome(
            plan_id=plan.id,
            debate_id=plan.debate_id,
            task=plan.task,
            success=False,
            error="Redis connection failed",
        )

        await record_plan_outcome(plan, outcome)

        assert plan.status == PlanStatus.FAILED
        assert plan.execution_error == "Redis connection failed"

    @pytest.mark.asyncio
    async def test_writes_to_continuum_memory(self):
        from unittest.mock import AsyncMock, MagicMock

        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)

        mock_memory = AsyncMock()
        mock_entry = MagicMock()
        mock_entry.id = "mem-123"
        mock_memory.store.return_value = mock_entry

        outcome = PlanOutcome(
            plan_id=plan.id,
            debate_id=plan.debate_id,
            task=plan.task,
            success=True,
            tasks_completed=3,
            tasks_total=3,
            verification_passed=5,
            verification_total=6,
        )

        results = await record_plan_outcome(plan, outcome, continuum_memory=mock_memory)

        assert results["continuum_id"] == "mem-123"
        mock_memory.store.assert_awaited_once()
        call_kwargs = mock_memory.store.call_args[1]
        assert call_kwargs["key"] == f"plan_outcome:{plan.id}"
        # Success with good verification rate → base importance 0.6
        assert call_kwargs["importance"] == 0.6
        assert "plan_outcome" in call_kwargs["metadata"]["type"]

    @pytest.mark.asyncio
    async def test_failure_gets_higher_importance(self):
        from unittest.mock import AsyncMock, MagicMock

        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)

        mock_memory = AsyncMock()
        mock_entry = MagicMock()
        mock_entry.id = "mem-456"
        mock_memory.store.return_value = mock_entry

        outcome = PlanOutcome(
            plan_id=plan.id,
            debate_id=plan.debate_id,
            task=plan.task,
            success=False,
            error="Tests failed",
            verification_passed=3,
            verification_total=6,
        )

        await record_plan_outcome(plan, outcome, continuum_memory=mock_memory)

        call_kwargs = mock_memory.store.call_args[1]
        # Failure with ok verification → base importance 0.8
        assert call_kwargs["importance"] == 0.8

    @pytest.mark.asyncio
    async def test_writes_to_knowledge_mound(self):
        from unittest.mock import AsyncMock

        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)

        mock_mound = AsyncMock()
        mock_mound.store_knowledge.return_value = "km-789"

        outcome = PlanOutcome(
            plan_id=plan.id,
            debate_id=plan.debate_id,
            task=plan.task,
            success=True,
            verification_passed=5,
            verification_total=6,
        )

        results = await record_plan_outcome(plan, outcome, knowledge_mound=mock_mound)

        assert results["mound_id"] == "km-789"
        mock_mound.store_knowledge.assert_awaited_once()
        call_kwargs = mock_mound.store_knowledge.call_args[1]
        assert call_kwargs["source"] == "decision_plan"
        assert call_kwargs["confidence"] == pytest.approx(5 / 6)

    @pytest.mark.asyncio
    async def test_handles_memory_errors_gracefully(self):
        from unittest.mock import AsyncMock

        result = _make_result()
        plan = DecisionPlanFactory.from_debate_result(result)

        mock_memory = AsyncMock()
        mock_memory.store.side_effect = RuntimeError("Connection refused")

        outcome = PlanOutcome(
            plan_id=plan.id,
            debate_id=plan.debate_id,
            task=plan.task,
            success=True,
        )

        results = await record_plan_outcome(plan, outcome, continuum_memory=mock_memory)

        # Should not raise, but record the error
        assert len(results["errors"]) == 1
        assert "Connection refused" in results["errors"][0]
        assert plan.memory_written is False
