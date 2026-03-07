"""Tests for PlanStore - SQLite-backed DecisionPlan persistence."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from aragora.gauntlet.receipt_store import ReceiptState, get_receipt_store, reset_receipt_store
from aragora.pipeline.decision_plan.core import (
    ApprovalMode,
    BudgetAllocation,
    DecisionPlan,
    ImplementationProfile,
    PlanStatus,
)
from aragora.pipeline.risk_register import Risk, RiskCategory, RiskLevel, RiskRegister
from aragora.pipeline.plan_store import PlanStore
from aragora.pipeline.verification_plan import (
    CasePriority,
    VerificationCase,
    VerificationPlan,
    VerificationType,
)
from aragora.implement.types import ImplementPlan, ImplementTask


@pytest.fixture
def store(tmp_path: Path) -> PlanStore:
    """Create a PlanStore with a temp database."""
    db_path = str(tmp_path / "test_plans.db")
    return PlanStore(db_path=db_path)


@pytest.fixture(autouse=True)
def _reset_receipt_store_fixture() -> None:
    reset_receipt_store()
    yield
    reset_receipt_store()


@pytest.fixture
def sample_plan() -> DecisionPlan:
    """Create a sample DecisionPlan for testing."""
    return DecisionPlan(
        id="dp-test-001",
        debate_id="debate-abc",
        task="Implement rate limiting for API endpoints",
        status=PlanStatus.AWAITING_APPROVAL,
        approval_mode=ApprovalMode.RISK_BASED,
        budget=BudgetAllocation(limit_usd=10.0, estimated_usd=5.0, spent_usd=1.0),
        metadata={"priority": "high", "action_items": [{"description": "Add rate limiter"}]},
    )


class TestPlanStoreCreate:
    """Tests for plan creation."""

    def test_create_and_get(self, store: PlanStore, sample_plan: DecisionPlan) -> None:
        store.create(sample_plan)
        retrieved = store.get(sample_plan.id)

        assert retrieved is not None
        assert retrieved.id == sample_plan.id
        assert retrieved.debate_id == "debate-abc"
        assert retrieved.task == "Implement rate limiting for API endpoints"
        assert retrieved.status == PlanStatus.AWAITING_APPROVAL
        assert retrieved.approval_mode == ApprovalMode.RISK_BASED

    def test_create_preserves_budget(self, store: PlanStore, sample_plan: DecisionPlan) -> None:
        store.create(sample_plan)
        retrieved = store.get(sample_plan.id)

        assert retrieved is not None
        assert retrieved.budget.limit_usd == 10.0
        assert retrieved.budget.estimated_usd == 5.0
        assert retrieved.budget.spent_usd == 1.0

    def test_create_preserves_metadata(self, store: PlanStore, sample_plan: DecisionPlan) -> None:
        store.create(sample_plan)
        retrieved = store.get(sample_plan.id)

        assert retrieved is not None
        assert retrieved.metadata["priority"] == "high"
        assert len(retrieved.metadata["action_items"]) == 1

    def test_create_persists_pre_execution_receipt(
        self, store: PlanStore, sample_plan: DecisionPlan
    ) -> None:
        store.create(sample_plan)
        retrieved = store.get(sample_plan.id)

        assert retrieved is not None
        receipt_meta = retrieved.metadata["decision_receipt"]
        receipt_id = receipt_meta["receipt_id"]
        stored = get_receipt_store().get(receipt_id)

        assert receipt_id
        assert receipt_meta["state"] == ReceiptState.CREATED.value
        assert stored is not None
        assert stored.state == ReceiptState.CREATED

    def test_create_preserves_max_auto_risk(self, store: PlanStore) -> None:
        plan = DecisionPlan(
            id="dp-risk-roundtrip",
            debate_id="debate-risk",
            task="Risk persistence test",
            max_auto_risk=RiskLevel.MEDIUM,
        )
        store.create(plan)
        retrieved = store.get(plan.id)

        assert retrieved is not None
        assert retrieved.max_auto_risk == RiskLevel.MEDIUM

    def test_create_preserves_implementation_profile(self, store: PlanStore) -> None:
        plan = DecisionPlan(
            id="dp-profile-roundtrip",
            debate_id="debate-profile",
            task="Profile persistence test",
            implementation_profile=ImplementationProfile(
                execution_mode="workflow",
                channel_targets=["slack:#eng", "teams:ops"],
                thread_id="thread-123",
                thread_id_by_platform={"slack": "abc", "teams": "xyz"},
            ),
        )
        store.create(plan)
        retrieved = store.get(plan.id)

        assert retrieved is not None
        assert retrieved.implementation_profile is not None
        assert retrieved.implementation_profile.execution_mode == "workflow"
        assert retrieved.implementation_profile.channel_targets == ["slack:#eng", "teams:ops"]
        assert retrieved.implementation_profile.thread_id == "thread-123"
        assert retrieved.implementation_profile.thread_id_by_platform == {
            "slack": "abc",
            "teams": "xyz",
        }

    def test_create_preserves_plan_artifacts(self, store: PlanStore) -> None:
        plan = DecisionPlan(
            id="dp-artifacts-roundtrip",
            debate_id="debate-artifacts",
            task="Artifact persistence test",
            risk_register=RiskRegister(
                debate_id="debate-artifacts",
                risks=[
                    Risk(
                        id="risk-1",
                        title="Regression risk",
                        description="Regression risk",
                        level=RiskLevel.MEDIUM,
                        category=RiskCategory.TECHNICAL,
                        source="test",
                    )
                ],
            ),
            verification_plan=VerificationPlan(
                debate_id="debate-artifacts",
                title="Verify artifacts",
                description="Artifact verification plan",
                test_cases=[
                    VerificationCase(
                        id="case-1",
                        title="Verify something",
                        description="Confirm artifact persistence",
                        test_type=VerificationType.INTEGRATION,
                        priority=CasePriority.P1,
                    )
                ],
            ),
            implement_plan=ImplementPlan(
                design_hash="abc123",
                tasks=[
                    ImplementTask(
                        id="task-1",
                        description="Modify file",
                        files=["aragora/pipeline/example.py"],
                        complexity="moderate",
                    )
                ],
            ),
        )
        store.create(plan)
        retrieved = store.get(plan.id)

        assert retrieved is not None
        assert retrieved.risk_register is not None
        assert retrieved.risk_register.risks[0].title == "Regression risk"
        assert retrieved.verification_plan is not None
        assert retrieved.verification_plan.test_cases[0].title == "Verify something"
        assert retrieved.implement_plan is not None
        assert retrieved.implement_plan.tasks[0].files == ["aragora/pipeline/example.py"]

    def test_get_nonexistent_returns_none(self, store: PlanStore) -> None:
        assert store.get("does-not-exist") is None


class TestPlanStoreList:
    """Tests for listing plans."""

    def test_list_all(self, store: PlanStore) -> None:
        for i in range(5):
            plan = DecisionPlan(
                id=f"dp-list-{i}",
                debate_id=f"debate-{i}",
                task=f"Task {i}",
                status=PlanStatus.AWAITING_APPROVAL,
            )
            store.create(plan)

        plans = store.list()
        assert len(plans) == 5

    def test_list_filter_by_status(self, store: PlanStore) -> None:
        store.create(
            DecisionPlan(
                id="dp-approved",
                debate_id="d1",
                task="T1",
                status=PlanStatus.APPROVED,
            )
        )
        store.create(
            DecisionPlan(
                id="dp-pending",
                debate_id="d2",
                task="T2",
                status=PlanStatus.AWAITING_APPROVAL,
            )
        )

        approved = store.list(status=PlanStatus.APPROVED)
        assert len(approved) == 1
        assert approved[0].id == "dp-approved"

        pending = store.list(status=PlanStatus.AWAITING_APPROVAL)
        assert len(pending) == 1
        assert pending[0].id == "dp-pending"

    def test_list_filter_by_debate_id(self, store: PlanStore) -> None:
        store.create(DecisionPlan(id="dp-a", debate_id="debate-x", task="T1"))
        store.create(DecisionPlan(id="dp-b", debate_id="debate-x", task="T2"))
        store.create(DecisionPlan(id="dp-c", debate_id="debate-y", task="T3"))

        plans = store.list(debate_id="debate-x")
        assert len(plans) == 2
        assert all(p.debate_id == "debate-x" for p in plans)

    def test_list_with_limit_and_offset(self, store: PlanStore) -> None:
        for i in range(10):
            store.create(DecisionPlan(id=f"dp-page-{i}", debate_id="d", task=f"T{i}"))

        page1 = store.list(limit=3, offset=0)
        assert len(page1) == 3

        page2 = store.list(limit=3, offset=3)
        assert len(page2) == 3

        # IDs should not overlap
        ids1 = {p.id for p in page1}
        ids2 = {p.id for p in page2}
        assert ids1.isdisjoint(ids2)

    def test_count(self, store: PlanStore) -> None:
        store.create(
            DecisionPlan(id="dp-c1", debate_id="d1", task="T1", status=PlanStatus.APPROVED)
        )
        store.create(
            DecisionPlan(id="dp-c2", debate_id="d1", task="T2", status=PlanStatus.APPROVED)
        )
        store.create(
            DecisionPlan(id="dp-c3", debate_id="d2", task="T3", status=PlanStatus.REJECTED)
        )

        assert store.count() == 3
        assert store.count(status=PlanStatus.APPROVED) == 2
        assert store.count(debate_id="d1") == 2
        assert store.count(debate_id="d1", status=PlanStatus.APPROVED) == 2
        assert store.count(debate_id="d2", status=PlanStatus.APPROVED) == 0


class TestPlanStoreUpdate:
    """Tests for plan status updates."""

    def test_update_status_approve(self, store: PlanStore, sample_plan: DecisionPlan) -> None:
        store.create(sample_plan)
        result = store.update_status(sample_plan.id, PlanStatus.APPROVED, approved_by="user-42")

        assert result is True
        plan = store.get(sample_plan.id)
        assert plan is not None
        assert plan.status == PlanStatus.APPROVED
        assert plan.approval_record is not None
        assert plan.approval_record.approved is True
        assert plan.approval_record.approver_id == "user-42"
        receipt_id = plan.metadata["decision_receipt"]["receipt_id"]
        stored = get_receipt_store().get(receipt_id)
        assert stored is not None
        assert stored.state == ReceiptState.APPROVED

    def test_update_status_reject(self, store: PlanStore, sample_plan: DecisionPlan) -> None:
        store.create(sample_plan)
        result = store.update_status(
            sample_plan.id,
            PlanStatus.REJECTED,
            approved_by="user-99",
            rejection_reason="Too risky",
        )

        assert result is True
        plan = store.get(sample_plan.id)
        assert plan is not None
        assert plan.status == PlanStatus.REJECTED
        assert plan.approval_record is not None
        assert plan.approval_record.approved is False
        assert plan.approval_record.reason == "Too risky"
        receipt_id = plan.metadata["decision_receipt"]["receipt_id"]
        stored = get_receipt_store().get(receipt_id)
        assert stored is not None
        assert stored.state == ReceiptState.EXPIRED

    def test_update_status_completed_marks_receipt_executed(
        self, store: PlanStore, sample_plan: DecisionPlan
    ) -> None:
        sample_plan.status = PlanStatus.APPROVED
        store.create(sample_plan)
        result = store.update_status(sample_plan.id, PlanStatus.COMPLETED)

        assert result is True
        plan = store.get(sample_plan.id)
        assert plan is not None
        receipt_id = plan.metadata["decision_receipt"]["receipt_id"]
        stored = get_receipt_store().get(receipt_id)
        assert stored is not None
        assert stored.state == ReceiptState.EXECUTED

    def test_update_nonexistent_returns_false(self, store: PlanStore) -> None:
        result = store.update_status("ghost", PlanStatus.APPROVED)
        assert result is False


class TestPlanStoreDelete:
    """Tests for plan deletion."""

    def test_delete_existing(self, store: PlanStore, sample_plan: DecisionPlan) -> None:
        store.create(sample_plan)
        assert store.delete(sample_plan.id) is True
        assert store.get(sample_plan.id) is None

    def test_delete_nonexistent(self, store: PlanStore) -> None:
        assert store.delete("ghost") is False


class TestPlanStoreCombinedFilters:
    """Tests combining multiple filters."""

    def test_filter_by_status_and_debate(self, store: PlanStore) -> None:
        store.create(DecisionPlan(id="dp-1", debate_id="dA", task="T", status=PlanStatus.APPROVED))
        store.create(DecisionPlan(id="dp-2", debate_id="dA", task="T", status=PlanStatus.REJECTED))
        store.create(DecisionPlan(id="dp-3", debate_id="dB", task="T", status=PlanStatus.APPROVED))

        result = store.list(debate_id="dA", status=PlanStatus.APPROVED)
        assert len(result) == 1
        assert result[0].id == "dp-1"


class TestPlanStoreExecutionClaims:
    """Tests for atomic execution claim semantics."""

    def test_update_status_if_current_claims_once(self, store: PlanStore) -> None:
        plan = DecisionPlan(
            id="dp-claim-1",
            debate_id="debate-claim",
            task="Claim me once",
            status=PlanStatus.APPROVED,
        )
        store.create(plan)

        first = store.update_status_if_current(
            plan.id,
            expected_statuses=[PlanStatus.APPROVED],
            new_status=PlanStatus.EXECUTING,
        )
        second = store.update_status_if_current(
            plan.id,
            expected_statuses=[PlanStatus.APPROVED],
            new_status=PlanStatus.EXECUTING,
        )

        assert first is True
        assert second is False
        updated = store.get(plan.id)
        assert updated is not None
        assert updated.status == PlanStatus.EXECUTING


class TestPlanStoreExecutionRecords:
    """Tests for persistent execution record storage."""

    def test_execution_record_roundtrip_and_filters(self, store: PlanStore) -> None:
        store.create(DecisionPlan(id="dp-exec-1", debate_id="debate-x", task="T1"))
        store.create(DecisionPlan(id="dp-exec-2", debate_id="debate-y", task="T2"))

        exec_id_1 = store.create_execution_record(
            plan_id="dp-exec-1",
            debate_id="debate-x",
            status="running",
            correlation_id="corr-1",
            metadata={"execution_mode": "workflow"},
        )
        exec_id_2 = store.create_execution_record(
            plan_id="dp-exec-2",
            debate_id="debate-y",
            status="queued",
            correlation_id="corr-2",
        )

        updated = store.update_execution_record(
            exec_id_1,
            status="failed",
            error={"type": "RuntimeError", "message": "boom"},
            metadata={"terminal_state": "failed"},
        )
        assert updated is True

        record = store.get_execution_record(exec_id_1)
        assert record is not None
        assert record["execution_id"] == exec_id_1
        assert record["plan_id"] == "dp-exec-1"
        assert record["debate_id"] == "debate-x"
        assert record["status"] == "failed"
        assert record["error"]["type"] == "RuntimeError"
        assert record["completed_at"] is not None

        by_plan = store.list_execution_records(plan_id="dp-exec-1")
        by_debate = store.list_execution_records(debate_id="debate-y")
        by_status = store.list_execution_records(status="queued")

        assert len(by_plan) == 1
        assert by_plan[0]["execution_id"] == exec_id_1
        assert len(by_debate) == 1
        assert by_debate[0]["execution_id"] == exec_id_2
        assert len(by_status) == 1
        assert by_status[0]["execution_id"] == exec_id_2
