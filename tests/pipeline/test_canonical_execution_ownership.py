"""Ownership of queued plan executions: persisted owner and the pre-run re-check."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.gauntlet.receipt_store import reset_receipt_store
from aragora.pipeline.canonical_execution import (
    build_decision_plan_from_orchestration,
    execute_queued_plan,
    queue_plan_execution,
)
from aragora.pipeline.decision_plan import PlanStatus
from aragora.pipeline.decision_integrity_utils import (
    ensure_decision_plan_backbone_run,
    execute_decision_plan_with_backbone,
)
from aragora.pipeline.execution_ownership import (
    EXECUTION_MEMBERSHIP_UNVERIFIED,
    EXECUTION_ORG_MISMATCH,
    EXECUTION_SCHEDULER_NOT_MEMBER,
    ExecutionNotAuthorizedError,
)
from aragora.pipeline.plan_store import PlanStore

ORG_A = "org-a"
ORG_B = "org-b"
USER_A = "user-a"


class _UserStore:
    """Minimal user store: ``memberships`` maps user id -> org id."""

    def __init__(self, memberships: dict[str, str], *, fail: bool = False) -> None:
        self.memberships = memberships
        self.fail = fail

    def get_user_by_id(self, user_id: str) -> Any:
        if self.fail:
            raise ConnectionError("user store down")
        org_id = self.memberships.get(user_id)
        return SimpleNamespace(id=user_id, org_id=org_id) if user_id in self.memberships else None

    def get_organization_by_id(self, org_id: str) -> Any:
        return SimpleNamespace(id=org_id)


@pytest.fixture
def store(tmp_path: Path) -> PlanStore:
    return PlanStore(db_path=str(tmp_path / "canonical_ownership.db"))


@pytest.fixture(autouse=True)
def _patch_runtime(monkeypatch: pytest.MonkeyPatch, store: PlanStore) -> Any:
    monkeypatch.setattr("aragora.pipeline.plan_store.get_plan_store", lambda: store)
    monkeypatch.setattr("aragora.pipeline.executor.store_plan", lambda plan: None)
    reset_receipt_store()
    yield
    reset_receipt_store()


@pytest.fixture
def user_store(monkeypatch: pytest.MonkeyPatch) -> _UserStore:
    users = _UserStore({USER_A: ORG_A})
    monkeypatch.setattr("aragora.tenancy.membership._registered_user_store", users)
    return users


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fake = MagicMock()
    fake.execute_approved_plan = AsyncMock(
        return_value=SimpleNamespace(success=True, receipt_id=None)
    )
    fake.get_execution_record.return_value = {"status": "succeeded"}
    monkeypatch.setattr("aragora.pipeline.execution_bridge.get_execution_bridge", lambda: fake)
    return fake


def _auth(org_id: str | None = ORG_A, user_id: str = USER_A) -> SimpleNamespace:
    return SimpleNamespace(user_id=user_id, org_id=org_id)


def _build_plan() -> Any:
    plan, _tasks = build_decision_plan_from_orchestration(
        subject_id="pipe-own",
        subject_label="Pipeline pipe-own",
        nodes=[{"id": "task-1", "label": "Build cache", "data": {"orch_type": "agent_task"}}],
        edges=[],
        source_surface="canvas_pipeline",
        execution_mode="workflow",
    )
    return plan


def _set_plan_owner(store: PlanStore, plan_id: str, org_id: str | None, source: str) -> None:
    conn = sqlite3.connect(store._db_path)
    try:
        conn.execute(
            "UPDATE plans SET org_id = ?, ownership_source = ? WHERE id = ?",
            (org_id, source, plan_id),
        )
        conn.commit()
    finally:
        conn.close()


class TestQueuePersistsOwner:
    def test_queue_persists_org_and_creator_on_execution_and_run(self, store: PlanStore) -> None:
        plan = _build_plan()

        launch = queue_plan_execution(plan, auth_context=_auth(), execution_mode="workflow")

        record = store.get_execution_record(launch["execution_id"])
        assert record is not None
        assert (record["org_id"], record["created_by"], record["ownership_source"]) == (
            ORG_A,
            USER_A,
            "created",
        )
        assert store.get_run_for_org(launch["run_id"], ORG_A) is not None
        assert store.list_runs_for_org(ORG_B) == []
        stored = store.get_for_org(plan.id, ORG_A)
        assert stored is not None
        assert (stored.org_id, stored.created_by, stored.ownership_source) == (
            ORG_A,
            USER_A,
            "created",
        )

    def test_explicit_owner_overrides_auth_context(self, store: PlanStore) -> None:
        plan = _build_plan()

        launch = queue_plan_execution(plan, org_id=ORG_A, created_by=USER_A)

        record = store.get_execution_record(launch["execution_id"])
        assert record is not None
        assert (record["org_id"], record["created_by"]) == (ORG_A, USER_A)

    def test_queue_without_org_leaves_records_unowned(self, store: PlanStore) -> None:
        plan = _build_plan()

        launch = queue_plan_execution(plan, auth_context=SimpleNamespace(user_id="svc"))

        record = store.get_execution_record(launch["execution_id"])
        assert record is not None
        assert record["org_id"] is None
        assert store.list_runs_for_org(ORG_A) == []

    def test_queue_org_mismatch_refuses_other_org_plan_without_writes(
        self, store: PlanStore
    ) -> None:
        plan = _build_plan()
        plan.org_id, plan.created_by = ORG_A, USER_A
        store.create(plan)
        before = store.get(plan.id)

        with pytest.raises(ExecutionNotAuthorizedError) as excinfo:
            queue_plan_execution(plan, auth_context=_auth(ORG_B, "user-b"))

        assert excinfo.value.code == EXECUTION_ORG_MISMATCH
        assert store.list_execution_records(plan_id=plan.id) == []
        assert store.list_runs(plan_id=plan.id) == []
        after = store.get(plan.id)
        assert after is not None and before is not None
        assert (after.org_id, after.status) == (before.org_id, before.status)

    def test_queue_org_mismatch_refuses_unknown_owner_plan(self, store: PlanStore) -> None:
        plan = _build_plan()
        store.create(plan)
        _set_plan_owner(store, plan.id, None, "unknown")

        with pytest.raises(ExecutionNotAuthorizedError):
            queue_plan_execution(plan, auth_context=_auth())

        assert store.list_execution_records(plan_id=plan.id) == []

    def test_decision_backbone_run_carries_scheduler_org(self, store: PlanStore) -> None:
        plan = _build_plan()

        run_id = ensure_decision_plan_backbone_run(
            plan, auth_context=_auth(), source_surface="decision_plans", source_id="d-1"
        )

        assert store.get_run_for_org(run_id, ORG_A) is not None
        assert store.get_run_for_org(run_id, ORG_B) is None


class TestExecuteQueuedPlanRecheck:
    @pytest.mark.asyncio
    async def test_execute_queued_plan_org_mismatch_refuses(
        self, store: PlanStore, user_store: _UserStore, bridge: MagicMock
    ) -> None:
        plan = _build_plan()
        launch = queue_plan_execution(plan, auth_context=_auth())
        _set_plan_owner(store, plan.id, ORG_B, "created")
        status_before = store.get(plan.id).status

        with pytest.raises(ExecutionNotAuthorizedError) as excinfo:
            await execute_queued_plan(
                plan,
                execution_id=launch["execution_id"],
                correlation_id=launch["correlation_id"],
                auth_context=_auth(),
            )

        assert excinfo.value.code == EXECUTION_ORG_MISMATCH
        bridge.execute_approved_plan.assert_not_called()
        record = store.get_execution_record(launch["execution_id"])
        assert record is not None
        assert record["status"] == "failed"
        assert record["error"]["code"] == EXECUTION_ORG_MISMATCH
        assert store.get(plan.id).status == status_before
        assert store.get(plan.id).status not in (PlanStatus.EXECUTING, PlanStatus.COMPLETED)
        run = store.get_run(launch["run_id"])
        assert run is not None and run.status == "execution_failed"

    @pytest.mark.asyncio
    async def test_execute_queued_plan_not_member_refuses(
        self, store: PlanStore, user_store: _UserStore, bridge: MagicMock
    ) -> None:
        plan = _build_plan()
        launch = queue_plan_execution(plan, auth_context=_auth())
        user_store.memberships[USER_A] = "org-elsewhere"
        status_before = store.get(plan.id).status

        with pytest.raises(ExecutionNotAuthorizedError) as excinfo:
            await execute_queued_plan(
                plan,
                execution_id=launch["execution_id"],
                correlation_id=launch["correlation_id"],
                auth_context=_auth(),
            )

        assert excinfo.value.code == EXECUTION_SCHEDULER_NOT_MEMBER
        bridge.execute_approved_plan.assert_not_called()
        record = store.get_execution_record(launch["execution_id"])
        assert record is not None
        assert record["status"] == "failed"
        assert record["error"]["code"] == EXECUTION_SCHEDULER_NOT_MEMBER
        assert store.get(plan.id).status == status_before

    @pytest.mark.asyncio
    async def test_execute_queued_plan_not_member_when_user_removed(
        self, store: PlanStore, user_store: _UserStore, bridge: MagicMock
    ) -> None:
        plan = _build_plan()
        launch = queue_plan_execution(plan, auth_context=_auth())
        del user_store.memberships[USER_A]

        with pytest.raises(ExecutionNotAuthorizedError):
            await execute_queued_plan(
                plan,
                execution_id=launch["execution_id"],
                correlation_id=launch["correlation_id"],
            )

        bridge.execute_approved_plan.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_queued_plan_not_member_unverifiable_store_refuses(
        self, store: PlanStore, user_store: _UserStore, bridge: MagicMock
    ) -> None:
        plan = _build_plan()
        launch = queue_plan_execution(plan, auth_context=_auth())
        user_store.fail = True

        with pytest.raises(ExecutionNotAuthorizedError) as excinfo:
            await execute_queued_plan(
                plan,
                execution_id=launch["execution_id"],
                correlation_id=launch["correlation_id"],
            )

        assert excinfo.value.code == EXECUTION_MEMBERSHIP_UNVERIFIED
        bridge.execute_approved_plan.assert_not_called()
        record = store.get_execution_record(launch["execution_id"])
        assert record is not None and record["status"] == "failed"

    @pytest.mark.asyncio
    async def test_org_mismatch_or_not_member_control_current_member_executes(
        self, store: PlanStore, user_store: _UserStore, bridge: MagicMock
    ) -> None:
        plan = _build_plan()
        launch = queue_plan_execution(plan, auth_context=_auth())

        outcome, record, _receipt = await execute_queued_plan(
            plan,
            execution_id=launch["execution_id"],
            correlation_id=launch["correlation_id"],
            auth_context=_auth(),
        )

        bridge.execute_approved_plan.assert_awaited_once()
        assert outcome.success is True
        assert record == {"status": "succeeded"}
        stored_record = store.get_execution_record(launch["execution_id"])
        assert stored_record is not None and stored_record["status"] == "queued"

    @pytest.mark.asyncio
    async def test_org_mismatch_control_unowned_legacy_execution_runs(
        self, store: PlanStore, bridge: MagicMock
    ) -> None:
        plan = _build_plan()
        launch = queue_plan_execution(plan)

        await execute_queued_plan(
            plan,
            execution_id=launch["execution_id"],
            correlation_id=launch["correlation_id"],
        )

        bridge.execute_approved_plan.assert_awaited_once()


class TestExecuteDecisionPlanWithBackboneRecheck:
    @pytest.mark.asyncio
    async def test_backbone_execute_not_member_refuses(
        self,
        store: PlanStore,
        user_store: _UserStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plan = _build_plan()
        user_store.memberships[USER_A] = "org-elsewhere"
        executed = AsyncMock()
        monkeypatch.setattr(
            "aragora.pipeline.execution_bridge.ExecutionBridge.execute_approved_plan", executed
        )

        with pytest.raises(ExecutionNotAuthorizedError) as excinfo:
            await execute_decision_plan_with_backbone(
                plan, executor=MagicMock(), auth_context=_auth(), execution_mode="workflow"
            )

        assert excinfo.value.code == EXECUTION_SCHEDULER_NOT_MEMBER
        executed.assert_not_called()
        records = store.list_execution_records(plan_id=plan.id)
        assert [(r["status"], r["org_id"]) for r in records] == [("failed", ORG_A)]

    @pytest.mark.asyncio
    async def test_backbone_execute_org_mismatch_control_member_executes(
        self,
        store: PlanStore,
        user_store: _UserStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plan = _build_plan()
        executed = AsyncMock(return_value=SimpleNamespace(success=True))
        monkeypatch.setattr(
            "aragora.pipeline.execution_bridge.ExecutionBridge.execute_approved_plan", executed
        )

        launch, outcome = await execute_decision_plan_with_backbone(
            plan, executor=MagicMock(), auth_context=_auth(), execution_mode="workflow"
        )

        executed.assert_awaited_once()
        assert outcome.success is True
        record = store.get_execution_record(launch["execution_id"])
        assert record is not None
        assert (record["org_id"], record["created_by"]) == (ORG_A, USER_A)
