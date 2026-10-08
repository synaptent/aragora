"""Ownership columns of PipelineResultStore: stamping, preservation, migration, org lists."""

from __future__ import annotations

import sqlite3

import pytest

from aragora.storage.pipeline_store import PipelineResultStore


def _result(**stage_status: str) -> dict:
    return {"stage_status": stage_status or {"ideas": "complete"}}


@pytest.fixture
def store(tmp_path) -> PipelineResultStore:
    return PipelineResultStore(str(tmp_path / "pipeline_results.db"))


def _owner_row(store: PipelineResultStore, pipeline_id: str) -> tuple:
    conn = sqlite3.connect(store.db_path)
    try:
        return conn.execute(
            "SELECT org_id, created_by, ownership_source FROM pipeline_results WHERE id = ?",
            (pipeline_id,),
        ).fetchone()
    finally:
        conn.close()


def test_save_records_owner_on_insert(store: PipelineResultStore) -> None:
    store.save("pipe-a", _result(), org_id="org-a", created_by="user-a")

    assert _owner_row(store, "pipe-a") == ("org-a", "user-a", "created")
    assert store.get_owner_org("pipe-a") == "org-a"


def test_resave_keeps_owner_and_cannot_move_it(store: PipelineResultStore) -> None:
    store.save("pipe-a", _result(), org_id="org-a", created_by="user-a")
    store.save("pipe-a", _result(goals="complete"))
    store.save("pipe-a", _result(actions="complete"), org_id="org-b", created_by="user-b")

    assert _owner_row(store, "pipe-a") == ("org-a", "user-a", "created")
    assert store.get("pipe-a")["stage_status"] == {"actions": "complete"}


def test_save_without_org_leaves_owner_unknown(store: PipelineResultStore) -> None:
    store.save("pipe-x", _result())

    assert _owner_row(store, "pipe-x") == (None, None, None)
    assert store.get_owner_org("pipe-x") is None


def test_owner_of_missing_pipeline_is_none(store: PipelineResultStore) -> None:
    assert store.get_owner_org("pipe-missing") is None


def test_owner_lookup_after_reads_that_change_the_row_factory(store: PipelineResultStore) -> None:
    store.save("pipe-a", _result(), org_id="org-a")
    store.get("pipe-a")
    store.list_pipelines()

    assert store.get_owner_org("pipe-a") == "org-a"


def test_list_for_org_returns_only_that_org(store: PipelineResultStore) -> None:
    store.save("pipe-a1", _result(), org_id="org-a", created_by="user-a")
    store.save("pipe-a2", _result(), org_id="org-a", created_by="user-a")
    store.save("pipe-b1", _result(), org_id="org-b", created_by="user-b")
    store.save("pipe-null", _result())

    assert {p["id"] for p in store.list_for_org("org-a")} == {"pipe-a1", "pipe-a2"}
    assert {p["id"] for p in store.list_for_org("org-b")} == {"pipe-b1"}
    assert store.list_for_org("") == []
    assert len(store.list_pipelines(limit=10)) == 4


def test_list_for_org_honours_status_and_limit(store: PipelineResultStore) -> None:
    store.save("pipe-a1", _result(ideas="complete"), org_id="org-a")
    store.save("pipe-a2", _result(ideas="pending"), org_id="org-a")

    assert [p["id"] for p in store.list_for_org("org-a", status="complete")] == ["pipe-a1"]
    assert len(store.list_for_org("org-a", limit=1)) == 1


def test_save_for_org_creates_a_missing_row_for_that_org(store: PipelineResultStore) -> None:
    assert store.save_for_org("pipe-new", _result(), org_id="org-b", created_by="user-b") is True

    assert _owner_row(store, "pipe-new") == ("org-b", "user-b", "created")
    assert store.get("pipe-new")["stage_status"] == {"ideas": "complete"}


def test_save_for_org_updates_only_the_owners_row(store: PipelineResultStore) -> None:
    store.save("pipe-a", _result(), org_id="org-a", created_by="user-a")

    assert store.save_for_org("pipe-a", _result(goals="complete"), "org-a", "user-a2") is True
    assert store.get("pipe-a")["stage_status"] == {"goals": "complete"}
    assert _owner_row(store, "pipe-a") == ("org-a", "user-a", "created")

    assert store.save_for_org("pipe-a", _result(actions="complete"), "org-b", "user-b") is False
    assert store.get("pipe-a")["stage_status"] == {"goals": "complete"}
    assert _owner_row(store, "pipe-a") == ("org-a", "user-a", "created")


def test_save_for_org_never_writes_an_unowned_row(store: PipelineResultStore) -> None:
    store.save("pipe-x", _result())

    assert store.save_for_org("pipe-x", _result(goals="complete"), "org-a", "user-a") is False
    assert store.get("pipe-x")["stage_status"] == {"ideas": "complete"}
    assert _owner_row(store, "pipe-x") == (None, None, None)


def test_save_for_org_needs_an_org(store: PipelineResultStore) -> None:
    assert store.save_for_org("pipe-new", _result(), "", None) is False
    assert store.get("pipe-new") is None


def test_migration_marks_existing_rows_unknown(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(PipelineResultStore.INITIAL_SCHEMA)
    conn.execute(
        "CREATE TABLE _schema_versions (module TEXT PRIMARY KEY, version INTEGER NOT NULL,"
        " updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO _schema_versions (module, version) VALUES ('pipeline_results', 2)")
    conn.execute(
        "INSERT INTO pipeline_results (id, status, created_at, updated_at)"
        " VALUES ('pipe-legacy', 'complete', 1.0, 1.0)"
    )
    conn.commit()
    conn.close()

    PipelineResultStore(str(db_path))
    store = PipelineResultStore(str(db_path))

    assert _owner_row(store, "pipe-legacy") == (None, None, "unknown")
    assert store.get_owner_org("pipe-legacy") is None
    assert store.list_for_org("org-a") == []
    assert store.get("pipe-legacy")["status"] == "complete"

    store.save("pipe-legacy", _result(), org_id="org-a", created_by="user-a")
    assert _owner_row(store, "pipe-legacy") == (None, None, "unknown")
