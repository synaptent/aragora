"""Tests for ExecutionBridge - connects approved plans to workflow execution."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.pipeline.decision_plan.core import (
    ApprovalMode,
    ApprovalRecord,
    BudgetAllocation,
    DecisionPlan,
    PlanStatus,
)
from aragora.pipeline.decision_plan.memory import PlanOutcome
from aragora.pipeline.execution_bridge import (
    ExecutionBridge,
    get_execution_bridge,
    reset_execution_bridge,
)
from aragora.pipeline.plan_store import PlanStore


@pytest.fixture
def store(tmp_path: Path) -> PlanStore:
    """Create a PlanStore with a temp database."""
    return PlanStore(db_path=str(tmp_path / "test_bridge.db"))


@pytest.fixture
def mock_executor() -> MagicMock:
    """Create a mock PlanExecutor."""
    executor = MagicMock()
    executor.execute = AsyncMock(
        return_value=PlanOutcome(
            plan_id="dp-test-001",
            debate_id="debate-abc",
            task="Test task",
            success=True,
            tasks_completed=2,
            tasks_total=2,
            duration_seconds=1.5,
        )
    )
    return executor


@pytest.fixture
def approved_plan() -> DecisionPlan:
    """Create an approved plan ready for execution."""
    plan = DecisionPlan(
        id="dp-test-001",
        debate_id="debate-abc",
        task="Implement rate limiting",
        status=PlanStatus.APPROVED,
        approval_mode=ApprovalMode.ALWAYS,
        approval_record=ApprovalRecord(
            approved=True,
            approver_id="user-42",
        ),
    )
    return plan


@pytest.fixture
def bridge(store: PlanStore, mock_executor: MagicMock) -> ExecutionBridge:
    """Create an ExecutionBridge with test dependencies."""
    return ExecutionBridge(plan_store=store, executor=mock_executor)


class TestExecutionBridgeExecute:
    """Tests for execute_approved_plan."""

    @pytest.mark.asyncio
    async def test_execute_approved_plan(
        self, bridge: ExecutionBridge, store: PlanStore, approved_plan: DecisionPlan
    ) -> None:
        store.create(approved_plan)

        outcome = await bridge.execute_approved_plan(approved_plan.id)

        assert outcome.success is True
        assert outcome.tasks_completed == 2

        # Status should be updated in store
        updated = store.get(approved_plan.id)
        assert updated is not None
        assert updated.status == PlanStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_sets_executing_status(
        self, bridge: ExecutionBridge, store: PlanStore, approved_plan: DecisionPlan
    ) -> None:
        """During execution, plan should transition through EXECUTING."""
        statuses: list[PlanStatus] = []

        original_execute = bridge.executor.execute

        async def capture_status(plan, **kwargs):
            # Capture what status was set before executor runs
            stored = store.get(plan.id)
            if stored:
                statuses.append(stored.status)
            return await original_execute(plan, **kwargs)

        bridge.executor.execute = AsyncMock(side_effect=capture_status)

        store.create(approved_plan)
        await bridge.execute_approved_plan(approved_plan.id)

        # Plan should have been in EXECUTING status when executor was called
        assert PlanStatus.EXECUTING in statuses

    @pytest.mark.asyncio
    async def test_execute_nonexistent_plan_raises(self, bridge: ExecutionBridge) -> None:
        with pytest.raises(ValueError, match="Plan not found"):
            await bridge.execute_approved_plan("does-not-exist")

    @pytest.mark.asyncio
    async def test_execute_rejected_plan_raises(
        self, bridge: ExecutionBridge, store: PlanStore
    ) -> None:
        plan = DecisionPlan(
            id="dp-rejected",
            debate_id="d1",
            task="T1",
            status=PlanStatus.REJECTED,
        )
        store.create(plan)

        with pytest.raises(ValueError, match="rejected"):
            await bridge.execute_approved_plan("dp-rejected")

    @pytest.mark.asyncio
    async def test_execute_already_executing_raises(
        self, bridge: ExecutionBridge, store: PlanStore
    ) -> None:
        plan = DecisionPlan(
            id="dp-running",
            debate_id="d1",
            task="T1",
            status=PlanStatus.EXECUTING,
        )
        store.create(plan)

        with pytest.raises(ValueError, match="already executing"):
            await bridge.execute_approved_plan("dp-running")

    @pytest.mark.asyncio
    async def test_execute_completed_plan_raises(
        self, bridge: ExecutionBridge, store: PlanStore
    ) -> None:
        plan = DecisionPlan(
            id="dp-done",
            debate_id="d1",
            task="T1",
            status=PlanStatus.COMPLETED,
        )
        store.create(plan)

        with pytest.raises(ValueError, match="already been executed"):
            await bridge.execute_approved_plan("dp-done")

    @pytest.mark.asyncio
    async def test_execute_unapproved_plan_raises(
        self, bridge: ExecutionBridge, store: PlanStore
    ) -> None:
        plan = DecisionPlan(
            id="dp-pending",
            debate_id="d1",
            task="T1",
            status=PlanStatus.AWAITING_APPROVAL,
            approval_mode=ApprovalMode.ALWAYS,
        )
        store.create(plan)

        with pytest.raises(ValueError, match="requires approval"):
            await bridge.execute_approved_plan("dp-pending")

    @pytest.mark.asyncio
    async def test_execute_auto_approve_plan(
        self, bridge: ExecutionBridge, store: PlanStore
    ) -> None:
        """Plans with approval_mode=NEVER don't require approval."""
        plan = DecisionPlan(
            id="dp-auto",
            debate_id="d1",
            task="Auto-approved task",
            status=PlanStatus.CREATED,
            approval_mode=ApprovalMode.NEVER,
        )
        store.create(plan)

        outcome = await bridge.execute_approved_plan("dp-auto")
        assert outcome.success is True

    @pytest.mark.asyncio
    async def test_execute_failure_sets_failed_status(
        self, bridge: ExecutionBridge, store: PlanStore, approved_plan: DecisionPlan
    ) -> None:
        bridge.executor.execute = AsyncMock(
            return_value=PlanOutcome(
                plan_id=approved_plan.id,
                debate_id="debate-abc",
                task="Test task",
                success=False,
                error="Step failed",
                tasks_completed=1,
                tasks_total=2,
                duration_seconds=1.0,
            )
        )
        store.create(approved_plan)

        outcome = await bridge.execute_approved_plan(approved_plan.id)

        assert outcome.success is False
        updated = store.get(approved_plan.id)
        assert updated is not None
        assert updated.status == PlanStatus.FAILED

    @pytest.mark.asyncio
    async def test_execute_exception_sets_failed_status(
        self, bridge: ExecutionBridge, store: PlanStore, approved_plan: DecisionPlan
    ) -> None:
        bridge.executor.execute = AsyncMock(side_effect=RuntimeError("Boom"))
        store.create(approved_plan)

        with pytest.raises(RuntimeError, match="Boom"):
            await bridge.execute_approved_plan(approved_plan.id)

        updated = store.get(approved_plan.id)
        assert updated is not None
        assert updated.status == PlanStatus.FAILED

    @pytest.mark.asyncio
    async def test_execute_passes_execution_mode(
        self, bridge: ExecutionBridge, store: PlanStore, approved_plan: DecisionPlan
    ) -> None:
        store.create(approved_plan)

        await bridge.execute_approved_plan(approved_plan.id, execution_mode="hybrid")

        bridge.executor.execute.assert_called_once()
        call_kwargs = bridge.executor.execute.call_args
        assert call_kwargs.kwargs.get("execution_mode") == "hybrid"

    @pytest.mark.asyncio
    async def test_execute_approved_plan_is_claimed_exactly_once(
        self, bridge: ExecutionBridge, store: PlanStore, approved_plan: DecisionPlan
    ) -> None:
        async def _slow_success(plan: DecisionPlan, **kwargs: Any) -> PlanOutcome:
            await asyncio.sleep(0.05)
            return PlanOutcome(
                plan_id=plan.id,
                debate_id=plan.debate_id,
                task=plan.task,
                success=True,
                tasks_completed=1,
                tasks_total=1,
                duration_seconds=0.05,
            )

        bridge.executor.execute = AsyncMock(side_effect=_slow_success)
        store.create(approved_plan)

        first, second = await asyncio.gather(
            bridge.execute_approved_plan(approved_plan.id),
            bridge.execute_approved_plan(approved_plan.id),
            return_exceptions=True,
        )

        outcomes = [item for item in (first, second) if isinstance(item, PlanOutcome)]
        errors = [item for item in (first, second) if isinstance(item, Exception)]

        assert len(outcomes) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)
        assert "already executing" in str(errors[0])
        bridge.executor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execution_records_queryable_by_plan_and_debate(
        self, bridge: ExecutionBridge, store: PlanStore, approved_plan: DecisionPlan
    ) -> None:
        store.create(approved_plan)

        outcome = await bridge.execute_approved_plan(approved_plan.id, execution_mode="workflow")
        assert outcome.success is True

        by_plan = bridge.list_execution_records(plan_id=approved_plan.id)
        by_debate = bridge.list_execution_records(debate_id=approved_plan.debate_id)

        assert len(by_plan) == 1
        assert len(by_debate) == 1
        assert by_plan[0]["execution_id"] == by_debate[0]["execution_id"]
        assert by_plan[0]["plan_id"] == approved_plan.id
        assert by_plan[0]["debate_id"] == approved_plan.debate_id
        assert by_plan[0]["status"] == "succeeded"
        assert by_plan[0]["correlation_id"]

    @pytest.mark.asyncio
    async def test_execution_failure_records_structured_error(
        self, bridge: ExecutionBridge, store: PlanStore, approved_plan: DecisionPlan
    ) -> None:
        bridge.executor.execute = AsyncMock(side_effect=RuntimeError("workflow exploded"))
        store.create(approved_plan)

        with pytest.raises(RuntimeError, match="workflow exploded"):
            await bridge.execute_approved_plan(approved_plan.id, execution_mode="workflow")

        records = bridge.list_execution_records(plan_id=approved_plan.id)
        assert len(records) == 1
        assert records[0]["status"] == "failed"
        assert records[0]["completed_at"] is not None
        assert records[0]["error"]["type"] == "RuntimeError"
        assert records[0]["error"]["message"] == "workflow exploded"


class TestExecutionBridgeSchedule:
    """Tests for schedule_execution (background task)."""

    @pytest.mark.asyncio
    async def test_schedule_execution_fires_background_task(
        self, bridge: ExecutionBridge, store: PlanStore, approved_plan: DecisionPlan
    ) -> None:
        store.create(approved_plan)

        bridge.schedule_execution(approved_plan.id)

        # Give the background task a moment to run
        await asyncio.sleep(0.1)

        bridge.executor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_schedule_execution_logs_error_on_failure(
        self, bridge: ExecutionBridge, store: PlanStore, approved_plan: DecisionPlan
    ) -> None:
        bridge.executor.execute = AsyncMock(side_effect=RuntimeError("Boom"))
        store.create(approved_plan)

        # Should not raise - errors are logged
        bridge.schedule_execution(approved_plan.id)
        await asyncio.sleep(0.1)

    def test_schedule_execution_falls_back_to_thread_without_running_loop(
        self, bridge: ExecutionBridge, store: PlanStore, approved_plan: DecisionPlan
    ) -> None:
        store.create(approved_plan)
        started: dict[str, bool] = {}

        class ImmediateThread:
            def __init__(self, target, name=None, daemon=None):
                self._target = target
                started["daemon"] = bool(daemon)

            def start(self):
                started["started"] = True
                self._target()

        with patch.object(threading, "Thread", ImmediateThread):
            bridge.schedule_execution(approved_plan.id)

        assert started["started"] is True
        assert started["daemon"] is True
        bridge.executor.execute.assert_called_once()
        records = bridge.list_execution_records(plan_id=approved_plan.id)
        assert len(records) == 1
        assert records[0]["status"] == "succeeded"


class TestExecutionBridgeSingleton:
    """Tests for module-level singleton."""

    def test_get_execution_bridge_returns_same_instance(self) -> None:
        reset_execution_bridge()
        b1 = get_execution_bridge()
        b2 = get_execution_bridge()
        assert b1 is b2
        reset_execution_bridge()

    def test_reset_clears_singleton(self) -> None:
        reset_execution_bridge()
        b1 = get_execution_bridge()
        reset_execution_bridge()
        b2 = get_execution_bridge()
        assert b1 is not b2
        reset_execution_bridge()

    def test_lazy_store_initialization(self) -> None:
        reset_execution_bridge()
        bridge = ExecutionBridge()
        # Accessing plan_store should not raise
        store = bridge.plan_store
        assert store is not None
        reset_execution_bridge()

    def test_lazy_executor_initialization(self) -> None:
        reset_execution_bridge()
        bridge = ExecutionBridge()
        executor = bridge.executor
        assert executor is not None
        reset_execution_bridge()
