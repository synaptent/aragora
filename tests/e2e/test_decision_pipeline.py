"""E2E smoke test for the full decision pipeline.

Proves the gold path works end-to-end:
    debate result → plan creation → approval → execution

All external dependencies are mocked (LLM, notifications).
Uses SQLite in a temp directory for persistence.

Runs in CI without external dependencies and completes in under 10 seconds.
"""

from __future__ import annotations

import asyncio
import tempfile
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.core_types import Critique, DebateResult
from aragora.pipeline.decision_plan import (
    ApprovalMode,
    DecisionPlan,
    DecisionPlanFactory,
    PlanOutcome,
    PlanStatus,
)
from aragora.pipeline.risk_register import RiskLevel
from aragora.pipeline.execution_bridge import (
    ExecutionBridge,
    reset_execution_bridge,
)
from aragora.pipeline.plan_store import PlanStore


pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_debate_result(
    *,
    debate_id: str = "debate-e2e-001",
    task: str = "Should we implement rate limiting for the API?",
    confidence: float = 0.85,
    consensus_reached: bool = True,
) -> DebateResult:
    """Build a realistic DebateResult without running an actual debate."""
    return DebateResult(
        debate_id=debate_id,
        task=task,
        final_answer=(
            "1. Implement token-bucket rate limiter in `api/middleware.py`\n"
            "2. Add per-tenant configuration in `config/tenants.yaml`\n"
            "3. Use Redis for distributed counter storage\n"
            "4. Add monitoring dashboard for rate limit hits\n"
        ),
        confidence=confidence,
        consensus_reached=consensus_reached,
        rounds_completed=3,
        messages=[],
        critiques=[
            Critique(
                agent="critic-1",
                target_agent="proposer-1",
                target_content="Use Redis for distributed counter storage",
                issues=["Redis dependency adds operational complexity"],
                suggestions=["Consider SQLite fallback for single-node deploys"],
                severity=6.5,
                reasoning="Redis adds ops burden for single-node deploys",
            ),
        ],
        dissenting_views=["Local in-memory rate limiting may suffice for small deployments"],
        total_cost_usd=0.12,
        metadata={"agents": ["proposer-1", "critic-1", "synthesizer-1"]},
    )


def _make_plan_store(tmp_dir: str) -> PlanStore:
    """Create a PlanStore backed by a temp directory."""
    db_path = os.path.join(tmp_dir, "plans.db")
    return PlanStore(db_path=db_path)


def _mock_plan_outcome(plan: DecisionPlan) -> PlanOutcome:
    """Build a successful PlanOutcome for a given plan."""
    return PlanOutcome(
        plan_id=plan.id,
        debate_id=plan.debate_id,
        task=plan.task,
        success=True,
        tasks_completed=4,
        tasks_total=4,
        duration_seconds=1.2,
    )


# ---------------------------------------------------------------------------
# Happy path: debate → plan → approve → execute
# ---------------------------------------------------------------------------


class TestDecisionPipelineHappyPath:
    """Full gold-path flow with all components wired together."""

    def test_debate_result_to_plan(self):
        """DebateResult produces a valid DecisionPlan via factory."""
        result = _make_debate_result()
        plan = DecisionPlanFactory.from_debate_result(
            result,
            approval_mode=ApprovalMode.ALWAYS,
        )

        assert plan.debate_id == "debate-e2e-001"
        assert plan.task == result.task
        assert plan.status == PlanStatus.AWAITING_APPROVAL
        assert plan.requires_human_approval is True
        # Factory should have extracted implementation tasks from numbered lines
        assert plan.implement_plan is not None
        assert len(plan.implement_plan.tasks) >= 1
        # Risk register should exist
        assert plan.risk_register is not None

    def test_plan_store_roundtrip(self):
        """Plan survives create → get → update_status via SQLite."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)
            result = _make_debate_result()
            plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)

            store.create(plan)
            loaded = store.get(plan.id)
            assert loaded is not None
            assert loaded.id == plan.id
            assert loaded.status == PlanStatus.AWAITING_APPROVAL

            store.update_status(plan.id, PlanStatus.APPROVED, approved_by="user-e2e")
            reloaded = store.get(plan.id)
            assert reloaded is not None
            assert reloaded.status == PlanStatus.APPROVED

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """debate result → factory → store → approve → execute → verify status."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)

            # Step 1: Create debate result
            result = _make_debate_result()

            # Step 2: Factory creates plan
            plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)
            assert plan.status == PlanStatus.AWAITING_APPROVAL

            # Step 3: Persist
            store.create(plan)

            # Step 4: Approve
            plan.approve("e2e-approver")
            store.update_status(plan.id, PlanStatus.APPROVED, approved_by="e2e-approver")

            verified = store.get(plan.id)
            assert verified is not None
            assert verified.status == PlanStatus.APPROVED

            # Step 5: Execute via bridge with mocked executor
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = _mock_plan_outcome(plan)

            bridge = ExecutionBridge(plan_store=store, executor=mock_executor)
            outcome = await bridge.execute_approved_plan(plan.id)

            assert outcome.success is True
            assert outcome.tasks_completed == 4
            assert outcome.plan_id == plan.id

            # Step 6: Verify final status persisted
            final = store.get(plan.id)
            assert final is not None
            assert final.status == PlanStatus.COMPLETED

            # Executor was called with the plan
            mock_executor.execute.assert_called_once()
            call_args = mock_executor.execute.call_args
            assert call_args[0][0].id == plan.id

    @pytest.mark.asyncio
    async def test_full_pipeline_with_notifications_mocked(self):
        """Same flow but verify notification fire-and-forget calls."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)
            result = _make_debate_result()
            plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)
            store.create(plan)

            # Mock the notification module (doesn't exist yet)
            mock_notify_created = AsyncMock()
            mock_notify_approved = AsyncMock()
            mock_notify_exec_started = AsyncMock()

            notifications_mock = MagicMock()
            notifications_mock.notify_plan_created = mock_notify_created
            notifications_mock.notify_plan_approved = mock_notify_approved
            notifications_mock.notify_execution_started = mock_notify_exec_started

            with patch.dict(
                "sys.modules",
                {"aragora.pipeline.notifications": notifications_mock},
            ):
                from aragora.server.handlers.plans import _fire_plan_notification

                # Fire notification for plan creation
                _fire_plan_notification("created", plan, org_id="org-e2e")
                # Give event loop a tick
                await asyncio.sleep(0.05)

                # Approve
                plan.approve("notifier-tester")
                store.update_status(plan.id, PlanStatus.APPROVED, approved_by="notifier-tester")
                _fire_plan_notification(
                    "approved", plan, org_id="org-e2e", approved_by="notifier-tester"
                )
                await asyncio.sleep(0.05)

                # Execute
                mock_executor = AsyncMock()
                mock_executor.execute.return_value = _mock_plan_outcome(plan)
                bridge = ExecutionBridge(plan_store=store, executor=mock_executor)
                outcome = await bridge.execute_approved_plan(plan.id)

                _fire_plan_notification("execution_started", plan, org_id="org-e2e")
                await asyncio.sleep(0.05)

            assert outcome.success is True

            # Notifications were fired (async, best-effort) for the acting org
            mock_notify_created.assert_called_once()
            mock_notify_approved.assert_called_once()
            mock_notify_exec_started.assert_called_once()
            assert mock_notify_created.call_args.kwargs["org_id"] == "org-e2e"
            assert mock_notify_approved.call_args.kwargs["org_id"] == "org-e2e"


# ---------------------------------------------------------------------------
# Auto-approve path (low risk, ApprovalMode.NEVER)
# ---------------------------------------------------------------------------


class TestAutoApprovePath:
    """Plans with approval_mode=NEVER skip the approval step."""

    def test_auto_approved_plan(self):
        """Plan with NEVER approval mode starts as APPROVED."""
        result = _make_debate_result(confidence=0.95, consensus_reached=True)
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.NEVER)
        assert plan.status == PlanStatus.APPROVED
        assert plan.requires_human_approval is False

    @pytest.mark.asyncio
    async def test_auto_approve_execute(self):
        """Auto-approved plan can be executed immediately."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)
            result = _make_debate_result()
            plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.NEVER)
            store.create(plan)

            mock_executor = AsyncMock()
            mock_executor.execute.return_value = _mock_plan_outcome(plan)
            bridge = ExecutionBridge(plan_store=store, executor=mock_executor)

            outcome = await bridge.execute_approved_plan(plan.id)
            assert outcome.success is True
            assert store.get(plan.id).status == PlanStatus.COMPLETED


# ---------------------------------------------------------------------------
# Rejection path
# ---------------------------------------------------------------------------


class TestRejectionPath:
    """Plans that are rejected cannot be executed."""

    def test_reject_plan(self):
        """Rejecting a plan sets status and records the reason."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)
            result = _make_debate_result()
            plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)
            store.create(plan)

            plan.reject("reviewer-1", reason="Too risky for production")
            store.update_status(
                plan.id,
                PlanStatus.REJECTED,
                approved_by="reviewer-1",
                rejection_reason="Too risky for production",
            )

            loaded = store.get(plan.id)
            assert loaded is not None
            assert loaded.status == PlanStatus.REJECTED

    @pytest.mark.asyncio
    async def test_execute_rejected_plan_fails(self):
        """Attempting to execute a rejected plan raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)
            result = _make_debate_result()
            plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)
            store.create(plan)

            store.update_status(plan.id, PlanStatus.REJECTED, rejection_reason="No")

            bridge = ExecutionBridge(plan_store=store, executor=AsyncMock())
            with pytest.raises(ValueError, match="rejected"):
                await bridge.execute_approved_plan(plan.id)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    """Guard rails: nonexistent, double-execute, unapproved."""

    @pytest.mark.asyncio
    async def test_execute_nonexistent_plan(self):
        """Executing a plan that doesn't exist raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)
            bridge = ExecutionBridge(plan_store=store, executor=AsyncMock())

            with pytest.raises(ValueError, match="not found"):
                await bridge.execute_approved_plan("nonexistent-id")

    @pytest.mark.asyncio
    async def test_execute_unapproved_plan(self):
        """Executing an unapproved plan raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)
            result = _make_debate_result()
            plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.ALWAYS)
            store.create(plan)

            bridge = ExecutionBridge(plan_store=store, executor=AsyncMock())
            with pytest.raises(ValueError, match="requires approval"):
                await bridge.execute_approved_plan(plan.id)

    @pytest.mark.asyncio
    async def test_double_execute_fails(self):
        """Executing an already-completed plan raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)
            result = _make_debate_result()
            plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.NEVER)
            store.create(plan)

            mock_executor = AsyncMock()
            mock_executor.execute.return_value = _mock_plan_outcome(plan)
            bridge = ExecutionBridge(plan_store=store, executor=mock_executor)

            # First execution succeeds
            outcome = await bridge.execute_approved_plan(plan.id)
            assert outcome.success is True

            # Second execution fails
            with pytest.raises(ValueError, match="already been executed"):
                await bridge.execute_approved_plan(plan.id)

    @pytest.mark.asyncio
    async def test_execution_failure_sets_failed_status(self):
        """When executor raises, plan status becomes FAILED."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)
            result = _make_debate_result()
            plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.NEVER)
            store.create(plan)

            mock_executor = AsyncMock()
            mock_executor.execute.side_effect = RuntimeError("Workflow engine crashed")
            bridge = ExecutionBridge(plan_store=store, executor=mock_executor)

            with pytest.raises(RuntimeError, match="Workflow engine crashed"):
                await bridge.execute_approved_plan(plan.id)

            failed_plan = store.get(plan.id)
            assert failed_plan is not None
            assert failed_plan.status == PlanStatus.FAILED


# ---------------------------------------------------------------------------
# Risk-based approval
# ---------------------------------------------------------------------------


class TestRiskBasedApproval:
    """RISK_BASED approval mode routes based on debate confidence."""

    def test_high_confidence_auto_approves(self):
        """High-confidence consensus auto-approves in RISK_BASED mode."""
        result = _make_debate_result(confidence=0.95, consensus_reached=True)
        plan = DecisionPlanFactory.from_debate_result(
            result,
            approval_mode=ApprovalMode.RISK_BASED,
            max_auto_risk=RiskLevel.MEDIUM,
        )
        # High confidence, consensus reached, only medium dissent risk → auto-approved
        assert plan.status == PlanStatus.APPROVED

    def test_low_confidence_requires_approval(self):
        """Low-confidence result requires human approval in RISK_BASED mode."""
        result = _make_debate_result(confidence=0.4, consensus_reached=False)
        plan = DecisionPlanFactory.from_debate_result(result, approval_mode=ApprovalMode.RISK_BASED)
        # Low confidence + no consensus → risks → requires approval
        assert plan.status == PlanStatus.AWAITING_APPROVAL
        assert plan.requires_human_approval is True


# ---------------------------------------------------------------------------
# Plan listing and filtering
# ---------------------------------------------------------------------------


class TestPlanListing:
    """PlanStore list and count operations."""

    def test_list_by_status(self):
        """Can filter plans by status."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)

            # Create two plans: one awaiting, one approved
            r1 = _make_debate_result(debate_id="debate-list-1")
            p1 = DecisionPlanFactory.from_debate_result(r1, approval_mode=ApprovalMode.ALWAYS)
            store.create(p1)

            r2 = _make_debate_result(debate_id="debate-list-2")
            p2 = DecisionPlanFactory.from_debate_result(r2, approval_mode=ApprovalMode.NEVER)
            store.create(p2)

            awaiting = store.list(status=PlanStatus.AWAITING_APPROVAL)
            approved = store.list(status=PlanStatus.APPROVED)

            assert len(awaiting) == 1
            assert awaiting[0].id == p1.id
            assert len(approved) == 1
            assert approved[0].id == p2.id

    def test_count_plans(self):
        """Count returns correct totals."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_plan_store(tmp)

            for i in range(3):
                r = _make_debate_result(debate_id=f"debate-count-{i}")
                p = DecisionPlanFactory.from_debate_result(r, approval_mode=ApprovalMode.ALWAYS)
                store.create(p)

            assert store.count() == 3
            assert store.count(status=PlanStatus.AWAITING_APPROVAL) == 3
            assert store.count(status=PlanStatus.APPROVED) == 0
