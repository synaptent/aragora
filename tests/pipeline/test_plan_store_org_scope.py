"""PlanStore ownership on create/save and the org-scoped ``*_for_org`` methods."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from aragora.gauntlet.receipt_store import reset_receipt_store
from aragora.pipeline.backbone_contracts import RunLedger
from aragora.pipeline.decision_plan.core import DecisionPlan, PlanStatus
from aragora.pipeline.plan_store import PlanStore

KEYS = {"plans": "id", "plan_executions": "execution_id", "backbone_runs": "run_id"}


@pytest.fixture(autouse=True)
def _reset_receipt_store_fixture() -> Any:
    reset_receipt_store()
    yield
    reset_receipt_store()


# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> PlanStore:
    return PlanStore(
        db_path=str(tmp_path / "plans.db"), org_membership_resolver=lambda _u: frozenset()
    )


def _owned_plan(plan_id: str, org_id: str | None, user_id: str | None = None) -> DecisionPlan:
    return DecisionPlan(
        id=plan_id,
        debate_id=f"debate-{plan_id}",
        task=f"task {plan_id}",
        status=PlanStatus.AWAITING_APPROVAL,
        org_id=org_id,
        created_by=user_id,
    )


def _ownership(store: PlanStore, table: str, record_id: str) -> tuple[Any, Any, Any]:
    conn = sqlite3.connect(store._db_path)
    try:
        return conn.execute(
            f"SELECT org_id, created_by, ownership_source FROM {table} WHERE {KEYS[table]} = ?",
            (record_id,),
        ).fetchone()
    finally:
        conn.close()


def test_create_persists_creator_org(store: PlanStore) -> None:
    store.create(_owned_plan("dp-a", "org-a", "user-a"))
    store.create(_owned_plan("dp-none", None))

    assert _ownership(store, "plans", "dp-a") == ("org-a", "user-a", "created")
    assert _ownership(store, "plans", "dp-none") == (None, None, None)
    loaded = store.get("dp-a")
    assert loaded is not None
    assert (loaded.org_id, loaded.created_by, loaded.ownership_source) == (
        "org-a",
        "user-a",
        "created",
    )


def test_save_never_moves_an_owned_or_unknown_plan(store: PlanStore) -> None:
    store.create(_owned_plan("dp-a", "org-a", "user-a"))
    store.create(_owned_plan("dp-unknown", None))
    conn = sqlite3.connect(store._db_path)
    conn.execute("UPDATE plans SET ownership_source = 'unknown' WHERE id = 'dp-unknown'")
    conn.commit()
    conn.close()

    hijack = store.get("dp-a")
    assert hijack is not None
    hijack.org_id, hijack.created_by = "org-b", "user-b"
    hijack.task = "edited"
    assert store.save(hijack) is True
    claim = _owned_plan("dp-unknown", "org-b", "user-b")
    assert store.save(claim) is True

    assert _ownership(store, "plans", "dp-a") == ("org-a", "user-a", "created")
    assert store.get("dp-a").task == "edited"
    assert _ownership(store, "plans", "dp-unknown") == (None, None, "unknown")


def test_save_assigns_an_unassigned_plan_once(store: PlanStore) -> None:
    store.create(_owned_plan("dp-late", None))

    assert store.save(_owned_plan("dp-late", "org-a", "user-a")) is True
    assert _ownership(store, "plans", "dp-late") == ("org-a", "user-a", "created")

    assert store.save(_owned_plan("dp-late", "org-b", "user-b")) is True
    assert _ownership(store, "plans", "dp-late") == ("org-a", "user-a", "created")


def test_execution_records_and_runs_persist_ownership(store: PlanStore) -> None:
    exec_id = store.create_execution_record(
        plan_id="dp-a", debate_id="debate-a", status="queued", org_id="org-a", created_by="user-a"
    )
    bare_exec = store.create_execution_record(plan_id="dp-a", debate_id="d", status="queued")
    store.create_run(
        RunLedger(run_id="run-a", entrypoint="e", status="plan_ready", plan_id="dp-a"),
        org_id="org-a",
        created_by="user-a",
    )
    store.create_run(RunLedger(run_id="run-bare", entrypoint="e", status="plan_ready"))

    assert _ownership(store, "plan_executions", exec_id) == ("org-a", "user-a", "created")
    assert _ownership(store, "plan_executions", bare_exec) == (None, None, None)
    assert _ownership(store, "backbone_runs", "run-a") == ("org-a", "user-a", "created")
    assert _ownership(store, "backbone_runs", "run-bare") == (None, None, None)
    record = store.get_execution_record(exec_id)
    assert record is not None and record["org_id"] == "org-a"

    assert store.update_run("run-a", status="execution_queued", metadata={"x": 1}) is True
    assert _ownership(store, "backbone_runs", "run-a") == ("org-a", "user-a", "created")


# ---------------------------------------------------------------------------
# Org-scoped queries
# ---------------------------------------------------------------------------


@pytest.fixture
def scoped_store(store: PlanStore) -> PlanStore:
    store.create(_owned_plan("dp-a1", "org-a", "user-a"))
    store.create(_owned_plan("dp-a2", "org-a", "user-a"))
    store.create(_owned_plan("dp-b1", "org-b", "user-b"))
    store.create(_owned_plan("dp-none", None))
    store.create(_owned_plan("dp-unknown", None))
    conn = sqlite3.connect(store._db_path)
    conn.execute("UPDATE plans SET ownership_source = 'unknown' WHERE id = 'dp-unknown'")
    conn.commit()
    conn.close()
    for org, plan_id in (("org-a", "dp-a1"), ("org-b", "dp-b1"), (None, "dp-none")):
        store.create_execution_record(
            execution_id=f"exec-{plan_id}",
            plan_id=plan_id,
            debate_id=f"debate-{plan_id}",
            status="queued",
            org_id=org,
        )
        store.create_run(
            RunLedger(run_id=f"run-{plan_id}", entrypoint="e", status="queued", plan_id=plan_id),
            org_id=org,
        )
    return store


def test_plan_reads_are_limited_to_the_org(scoped_store: PlanStore) -> None:
    assert {p.id for p in scoped_store.list_for_org("org-a")} == {"dp-a1", "dp-a2"}
    assert {p.id for p in scoped_store.list_for_org("org-b")} == {"dp-b1"}
    assert scoped_store.count_for_org("org-a") == 2
    assert scoped_store.count_for_org("org-a", status=PlanStatus.APPROVED) == 0
    assert [p.id for p in scoped_store.list_for_org("org-a", limit=1, offset=1)] != []
    assert scoped_store.list_for_org("org-a", debate_id="debate-dp-b1") == []

    assert scoped_store.get_for_org("dp-a1", "org-a") is not None
    assert scoped_store.get_for_org("dp-a1", "org-b") is None
    for unowned in ("dp-none", "dp-unknown"):
        assert scoped_store.get_for_org(unowned, "org-a") is None
    assert scoped_store.get_for_org("dp-missing", "org-a") is None

    # Unscoped methods keep their behavior for internal callers.
    assert scoped_store.count() == 5


def test_execution_and_run_reads_are_limited_to_the_org(scoped_store: PlanStore) -> None:
    assert scoped_store.get_execution_record_for_org("exec-dp-a1", "org-a") is not None
    assert scoped_store.get_execution_record_for_org("exec-dp-a1", "org-b") is None
    assert scoped_store.get_execution_record_for_org("exec-dp-none", "org-a") is None
    assert [r["execution_id"] for r in scoped_store.list_execution_records_for_org("org-b")] == [
        "exec-dp-b1"
    ]
    assert scoped_store.list_execution_records_for_org("org-a", plan_id="dp-b1") == []

    assert scoped_store.get_run_for_org("run-dp-a1", "org-a") is not None
    assert scoped_store.get_run_for_org("run-dp-a1", "org-b") is None
    assert scoped_store.get_run_for_org("run-dp-none", "org-a") is None
    assert [r.run_id for r in scoped_store.list_runs_for_org("org-a")] == ["run-dp-a1"]
    assert scoped_store.list_runs_for_org("org-b", plan_id="dp-a1") == []


def test_status_updates_require_the_matching_org(scoped_store: PlanStore) -> None:
    claimed = scoped_store.update_status_if_current_for_org(
        "dp-a1",
        "org-b",
        expected_statuses=[PlanStatus.AWAITING_APPROVAL],
        new_status=PlanStatus.APPROVED,
        approved_by="user-b",
    )
    assert claimed is False
    assert scoped_store.update_status_for_org("dp-a1", "org-b", PlanStatus.REJECTED) is False
    assert scoped_store.update_status_for_org("dp-none", "org-a", PlanStatus.REJECTED) is False
    assert scoped_store.update_status_for_org("dp-unknown", "org-a", PlanStatus.REJECTED) is False
    plan = scoped_store.get("dp-a1")
    assert plan is not None and plan.status == PlanStatus.AWAITING_APPROVAL
    assert plan.approval_record is None

    assert scoped_store.update_status_if_current_for_org(
        "dp-a1",
        "org-a",
        expected_statuses=[PlanStatus.AWAITING_APPROVAL],
        new_status=PlanStatus.APPROVED,
        approved_by="user-a",
    )
    assert scoped_store.get("dp-a1").status == PlanStatus.APPROVED
    assert scoped_store.update_status_for_org("dp-a2", "org-a", PlanStatus.REJECTED) is True
    assert scoped_store.get("dp-a2").status == PlanStatus.REJECTED


@pytest.mark.parametrize("org_id", [None, "", "   "])
def test_org_scoped_methods_require_an_org(scoped_store: PlanStore, org_id: Any) -> None:
    calls = [
        lambda: scoped_store.list_for_org(org_id),
        lambda: scoped_store.count_for_org(org_id),
        lambda: scoped_store.get_for_org("dp-none", org_id),
        lambda: scoped_store.update_status_for_org("dp-none", org_id, PlanStatus.REJECTED),
        lambda: scoped_store.update_status_if_current_for_org(
            "dp-none",
            org_id,
            expected_statuses=[PlanStatus.AWAITING_APPROVAL],
            new_status=PlanStatus.APPROVED,
        ),
        lambda: scoped_store.get_execution_record_for_org("exec-dp-none", org_id),
        lambda: scoped_store.list_execution_records_for_org(org_id),
        lambda: scoped_store.get_run_for_org("run-dp-none", org_id),
        lambda: scoped_store.list_runs_for_org(org_id),
    ]
    for call in calls:
        with pytest.raises(ValueError):
            call()
