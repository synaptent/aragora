"""Ownership columns and the one-time ownership backfill of plans.db."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from aragora.pipeline.plan_store import PlanStore
from aragora.storage.user_store.sqlite_store import UserStore
from aragora.tenancy.membership import MembershipLookupError, user_org_ids

OWNED_TABLES = {"plans": "id", "plan_executions": "execution_id", "backbone_runs": "run_id"}
OWNERSHIP_COLUMNS = ("org_id", "created_by", "ownership_source")

# plans.db schema as shipped before ownership existed.
LEGACY_SCHEMA = """
CREATE TABLE plans (
    id TEXT PRIMARY KEY, debate_id TEXT NOT NULL, task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created', approval_mode TEXT NOT NULL DEFAULT 'risk_based',
    max_auto_risk TEXT NOT NULL DEFAULT 'low', approved_by TEXT, rejection_reason TEXT,
    budget_json TEXT, approval_record_json TEXT, implementation_profile_json TEXT,
    risk_register_json TEXT, verification_plan_json TEXT, implement_plan_json TEXT,
    metadata_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, approved_at TEXT
);
CREATE TABLE plan_executions (
    execution_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, debate_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL, status TEXT NOT NULL, error_json TEXT, metadata_json TEXT,
    started_at TEXT NOT NULL, completed_at TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE backbone_runs (
    run_id TEXT PRIMARY KEY, entrypoint TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'received',
    intake_bundle_json TEXT, spec_bundle_json TEXT, goal_refs_json TEXT,
    deliberation_bundle_json TEXT, plan_id TEXT, debate_id TEXT, execution_id TEXT,
    receipt_id TEXT, receipt_envelope_json TEXT, feedback_record_json TEXT,
    attestation_json TEXT, taint_flags_json TEXT, metadata_json TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE backbone_run_events (
    event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
    artifact_ref TEXT, details_json TEXT, created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES backbone_runs(run_id) ON DELETE CASCADE
);
"""

TS = "2026-09-01T12:00:00+00:00"


@pytest.fixture
def users(tmp_path: Path) -> dict[str, Any]:
    """A real user store: user_a in org A, user_b in org B, user_orphan in no org."""
    store = UserStore(tmp_path / "users.db")
    ids = {
        name: store.create_user(f"{name}@example.com", "hash", "salt", name=name).id
        for name in ("user_a", "user_b", "user_orphan")
    }
    org_a = store.create_organization("Org A", owner_id=ids["user_a"]).id
    org_b = store.create_organization("Org B", owner_id=ids["user_b"]).id
    return {"store": store, "org_a": org_a, "org_b": org_b, **ids}


def _resolver(user_store: UserStore):
    return lambda user_id: user_org_ids(user_id, user_store)


def _insert(conn: sqlite3.Connection, table: str, **values: Any) -> None:
    columns = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(values.values()))


def _plan(conn: sqlite3.Connection, plan_id: str, metadata: dict[str, Any] | None = None) -> None:
    _insert(
        conn,
        "plans",
        id=plan_id,
        debate_id=f"debate-{plan_id}",
        task=f"task {plan_id}",
        status="awaiting_approval",
        metadata_json=json.dumps(metadata or {}),
        created_at=TS,
        updated_at=TS,
    )


def _execution(conn: sqlite3.Connection, execution_id: str, plan_id: str, metadata: Any) -> None:
    _insert(
        conn,
        "plan_executions",
        execution_id=execution_id,
        plan_id=plan_id,
        debate_id=f"debate-{plan_id}",
        correlation_id=f"corr-{execution_id}",
        status="queued",
        metadata_json=None if metadata is None else json.dumps(metadata),
        started_at=TS,
        updated_at=TS,
    )


def _run(
    conn: sqlite3.Connection,
    run_id: str,
    plan_id: str | None,
    *,
    intake_user: str | None = None,
    metadata_user: str | None = None,
) -> None:
    origin = {"source_surface": "plans_api"}
    if intake_user:
        origin["scheduled_by"] = intake_user
    metadata = {"execution_mode": "workflow"}
    if metadata_user:
        metadata["scheduled_by"] = metadata_user
    _insert(
        conn,
        "backbone_runs",
        run_id=run_id,
        entrypoint="canonical_execution.plans_api",
        status="plan_ready",
        intake_bundle_json=json.dumps({"source_kind": "plans_api", "origin_metadata": origin}),
        goal_refs_json="[]",
        plan_id=plan_id,
        metadata_json=json.dumps(metadata),
        created_at=TS,
        updated_at=TS,
    )
    _insert(
        conn,
        "backbone_run_events",
        event_id=f"evt-{run_id}",
        run_id=run_id,
        stage="intake",
        status="received",
        details_json="{}",
        created_at=TS,
    )


@pytest.fixture
def legacy_db(tmp_path: Path, users: dict[str, Any]) -> str:
    """A pre-ownership plans.db with proven, orphaned, unattributed and conflicting rows."""
    db_path = str(tmp_path / "legacy_plans.db")
    a, b, orphan = users["user_a"], users["user_b"], users["user_orphan"]
    conn = sqlite3.connect(db_path)
    conn.executescript(LEGACY_SCHEMA)
    for plan_id in ("plan-a", "plan-b", "plan-meta", "plan-mixed", "plan-orphan"):
        _plan(conn, plan_id)
    # Request-controlled plan metadata is never treated as proof of ownership.
    _plan(conn, "plan-lonely", {"user_id": a, "owner_id": a})
    conn.execute(
        "UPDATE plans SET metadata_json = ? WHERE id = 'plan-meta'",
        (json.dumps({"backbone_run_id": "run-meta"}),),
    )

    _execution(conn, "exec-proven", "plan-a", {"scheduled_by": a, "execution_mode": "workflow"})
    _execution(conn, "exec-orphan", "plan-orphan", {"scheduled_by": orphan})
    _execution(conn, "exec-ghost", "plan-ghost", {"scheduled_by": "user-not-in-store"})
    _execution(conn, "exec-nouser", "plan-ghost", {"scheduled_by": None})
    _execution(conn, "exec-nometa", "plan-ghost", None)
    _execution(conn, "exec-mixed", "plan-mixed", {"scheduled_by": a})

    _run(conn, "run-proven", "plan-b", intake_user=b, metadata_user=b)
    _run(conn, "run-meta", None, intake_user=a)
    _run(conn, "run-orphan", None, intake_user=orphan)
    _run(conn, "run-nouser", None)
    _run(conn, "run-conflict", None, intake_user=a, metadata_user=b)
    _run(conn, "run-mixed", "plan-mixed", intake_user=b)
    conn.commit()
    conn.close()
    return db_path


EXPECTED = {
    "plan_executions": {
        "exec-proven": ("org_a", "user_a", "backfilled"),
        "exec-mixed": ("org_a", "user_a", "backfilled"),
        "exec-orphan": (None, None, "unknown"),
        "exec-ghost": (None, None, "unknown"),
        "exec-nouser": (None, None, "unknown"),
        "exec-nometa": (None, None, "unknown"),
    },
    "backbone_runs": {
        "run-proven": ("org_b", "user_b", "backfilled"),
        "run-meta": ("org_a", "user_a", "backfilled"),
        "run-mixed": ("org_b", "user_b", "backfilled"),
        "run-orphan": (None, None, "unknown"),
        "run-nouser": (None, None, "unknown"),
        "run-conflict": (None, None, "unknown"),
    },
    "plans": {
        "plan-a": ("org_a", None, "backfilled"),
        "plan-b": ("org_b", None, "backfilled"),
        "plan-meta": ("org_a", None, "backfilled"),
        "plan-mixed": (None, None, "unknown"),
        "plan-orphan": (None, None, "unknown"),
        "plan-lonely": (None, None, "unknown"),
    },
}


def _rows(db_path: str, table: str) -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        key = OWNED_TABLES.get(table, "event_id")
        return {row[key]: dict(row) for row in conn.execute(f"SELECT * FROM {table}")}
    finally:
        conn.close()


def _snapshot(db_path: str) -> dict[str, Any]:
    tables = [*OWNED_TABLES, "backbone_run_events", "_schema_versions"]
    snap: dict[str, Any] = {}
    for table in tables:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            snap[table] = sorted(
                (tuple(row) for row in conn.execute(f"SELECT * FROM {table}")), key=repr
            )
        except sqlite3.OperationalError:
            snap[table] = None
        finally:
            conn.close()
    return snap


def _schema_version(db_path: str) -> int | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT version FROM _schema_versions WHERE module = 'plan_store'"
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _assert_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        for table in OWNED_TABLES:
            columns = {row[1]: row[2] for row in conn.execute(f"PRAGMA table_info({table})")}
            for column in OWNERSHIP_COLUMNS:
                assert columns.get(column) == "TEXT", (table, column)
            indexes = {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}
            assert f"idx_{table}_org_id" in indexes, table
            indexed = [row[2] for row in conn.execute(f"PRAGMA index_info(idx_{table}_org_id)")]
            assert indexed == ["org_id"], table
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_fresh_db_gets_ownership_columns_indexes_and_version(tmp_path: Path) -> None:
    db_path = str(tmp_path / "fresh.db")
    PlanStore(db_path=db_path, org_membership_resolver=lambda _user: frozenset())

    _assert_schema(db_path)
    assert _schema_version(db_path) == 1


def test_legacy_db_gets_ownership_columns_and_indexes(legacy_db: str, users: dict) -> None:
    PlanStore(db_path=legacy_db, org_membership_resolver=_resolver(users["store"]))

    _assert_schema(legacy_db)
    assert _schema_version(legacy_db) == 1


# ---------------------------------------------------------------------------
# Backfill (VAL-OWN-005 / VAL-OWN-006)
# ---------------------------------------------------------------------------


def test_backfill_sets_only_proven_ownership(
    legacy_db: str, users: dict, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="aragora.pipeline.plan_ownership")

    PlanStore(db_path=legacy_db, org_membership_resolver=_resolver(users["store"]))

    for table, expected_rows in EXPECTED.items():
        rows = _rows(legacy_db, table)
        assert set(rows) == set(expected_rows), table
        for record_id, (org_key, user_key, source) in expected_rows.items():
            row = rows[record_id]
            actual = (row["org_id"], row["created_by"], row["ownership_source"])
            expected = (
                users[org_key] if org_key else None,
                users[user_key] if user_key else None,
                source,
            )
            assert actual == expected, (table, record_id)

    messages = [r.getMessage() for r in caplog.records if "ownership backfill" in r.getMessage()]
    assert "plans.db ownership backfill: table=plans backfilled=3 unknown=3" in messages
    assert "plans.db ownership backfill: table=plan_executions backfilled=2 unknown=4" in messages
    assert "plans.db ownership backfill: table=backbone_runs backfilled=3 unknown=3" in messages


def test_backfill_never_changes_non_ownership_columns(legacy_db: str, users: dict) -> None:
    before = {table: _rows(legacy_db, table) for table in [*OWNED_TABLES, "backbone_run_events"]}

    PlanStore(db_path=legacy_db, org_membership_resolver=_resolver(users["store"]))

    for table, rows_before in before.items():
        rows_after = _rows(legacy_db, table)
        assert set(rows_after) == set(rows_before), table
        for record_id, row_before in rows_before.items():
            row_after = {
                k: v for k, v in rows_after[record_id].items() if k not in OWNERSHIP_COLUMNS
            }
            assert row_after == row_before, (table, record_id)


def test_second_schema_setup_changes_nothing(legacy_db: str, users: dict) -> None:
    PlanStore(db_path=legacy_db, org_membership_resolver=_resolver(users["store"]))
    after_first = _snapshot(legacy_db)
    assert _schema_version(legacy_db) == 1

    # A rerun would now prove the orphan's rows; a once-only backfill must not rerun.
    users["store"].add_user_to_org(users["user_orphan"], users["org_a"])
    PlanStore(db_path=legacy_db, org_membership_resolver=_resolver(users["store"]))

    assert _snapshot(legacy_db) == after_first
    assert _schema_version(legacy_db) == 1


def test_backfill_is_deferred_while_the_user_store_is_unavailable(
    legacy_db: str, users: dict
) -> None:
    def unavailable(user_id: str) -> frozenset[str]:
        raise MembershipLookupError("user store offline")

    PlanStore(db_path=legacy_db, org_membership_resolver=unavailable)

    _assert_schema(legacy_db)
    assert _schema_version(legacy_db) is None
    for table in OWNED_TABLES:
        assert all(
            (row["org_id"], row["ownership_source"]) == (None, None)
            for row in _rows(legacy_db, table).values()
        ), table

    PlanStore(db_path=legacy_db, org_membership_resolver=_resolver(users["store"]))
    assert _rows(legacy_db, "plans")["plan-b"]["org_id"] == users["org_b"]
    assert _schema_version(legacy_db) == 1


def test_backfill_is_deferred_while_the_store_places_no_recorded_user_in_an_org(
    legacy_db: str, users: dict, tmp_path: Path
) -> None:
    empty_store = UserStore(tmp_path / "empty_users.db")
    PlanStore(db_path=legacy_db, org_membership_resolver=_resolver(empty_store))

    assert _schema_version(legacy_db) is None
    for table in OWNED_TABLES:
        owners = {(r["org_id"], r["ownership_source"]) for r in _rows(legacy_db, table).values()}
        assert owners == {(None, None)}, table

    PlanStore(db_path=legacy_db, org_membership_resolver=_resolver(users["store"]))
    assert _rows(legacy_db, "plans")["plan-b"]["org_id"] == users["org_b"]
    assert _rows(legacy_db, "plan_executions")["exec-ghost"]["ownership_source"] == "unknown"
    assert _schema_version(legacy_db) == 1


def test_rows_without_a_recorded_user_do_not_defer_the_backfill(tmp_path: Path) -> None:
    db_path = str(tmp_path / "unattributed.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(LEGACY_SCHEMA)
    _run(conn, "run-nouser", None)
    conn.commit()
    conn.close()

    PlanStore(db_path=db_path, org_membership_resolver=lambda _user: frozenset())

    assert _schema_version(db_path) == 1
    assert _rows(db_path, "backbone_runs")["run-nouser"]["ownership_source"] == "unknown"
