"""Receipt ownership columns, the one-time ownership backfill and org-scoped reads.

Covers ``aragora.storage.receipt_ownership``, the ownership parts of
``aragora.storage.receipt_store.ReceiptStore`` and the server-side
``aragora.server.receipt_link_resolver``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from aragora.server.receipt_link_resolver import (
    ServerReceiptLinkResolver,
    install_receipt_link_resolver,
)
from aragora.storage.receipt_ownership import (
    OWNERSHIP_BACKFILLED,
    OWNERSHIP_CREATED,
    OWNERSHIP_UNKNOWN,
    SCHEMA_MODULE,
    SCHEMA_VERSION,
    ReceiptLinkLookupError,
    get_receipt_link_resolver,
    migrate_receipt_ownership,
    receipt_links,
    register_receipt_link_resolver,
)
from aragora.storage.receipt_store import ReceiptStore

ORG_A = "org-a"
ORG_B = "org-b"

# The receipts table as it was before the ownership columns existed.
_LEGACY_RECEIPTS_DDL = """
CREATE TABLE receipts (
    receipt_id TEXT PRIMARY KEY,
    gauntlet_id TEXT NOT NULL UNIQUE,
    debate_id TEXT,
    created_at REAL NOT NULL,
    expires_at REAL,
    verdict TEXT NOT NULL,
    confidence REAL NOT NULL,
    risk_level TEXT NOT NULL,
    risk_score REAL NOT NULL DEFAULT 0.0,
    checksum TEXT NOT NULL,
    signature TEXT,
    signature_algorithm TEXT,
    signature_key_id TEXT,
    signed_at REAL,
    timestamp_token TEXT,
    timestamp_tsa_url TEXT,
    timestamp_at REAL,
    legal_hold INTEGER DEFAULT 0,
    legal_hold_reason TEXT,
    legal_hold_placed_by TEXT,
    legal_hold_placed_at REAL,
    legal_hold_matter_id TEXT,
    audit_trail_id TEXT,
    data_json TEXT NOT NULL
)
"""


class FakeResolver:
    """Link resolver backed by dicts; ``fail`` makes every lookup raise."""

    def __init__(
        self,
        debates: dict[str, str | None] | None = None,
        plans: dict[str, str | None] | None = None,
        fail: bool = False,
    ) -> None:
        self.debates = debates or {}
        self.plans = plans or {}
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def debate_org_id(self, debate_id: str) -> str | None:
        self.calls.append(("debate", debate_id))
        if self.fail:
            raise ReceiptLinkLookupError("debate store down")
        return self.debates.get(debate_id)

    def plan_org_id(self, plan_id: str) -> str | None:
        self.calls.append(("plan", plan_id))
        if self.fail:
            raise ReceiptLinkLookupError("plan store down")
        return self.plans.get(plan_id)


@pytest.fixture(autouse=True)
def _no_registered_resolver():
    previous = get_receipt_link_resolver()
    register_receipt_link_resolver(None)
    yield
    register_receipt_link_resolver(previous)


def _receipt(receipt_id: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "receipt_id": receipt_id,
        "gauntlet_id": f"g-{receipt_id}",
        "timestamp": 1_750_000_000.0,
        "verdict": "APPROVED",
        "confidence": 0.8,
        "risk_level": "LOW",
        "risk_score": 0.1,
        "checksum": f"sum-{receipt_id}",
        "statement": f"statement {receipt_id}",
    }
    payload.update(extra)
    return payload


def _store(path: Path) -> ReceiptStore:
    return ReceiptStore(db_path=path, file_receipt_dirs=[])


def _legacy_db(path: Path, rows: list[tuple[str, str | None, dict[str, Any]]]) -> None:
    """Create a pre-ownership receipts table holding ``(receipt_id, debate_id, data)`` rows."""
    conn = sqlite3.connect(path)
    conn.execute(_LEGACY_RECEIPTS_DDL)
    for index, (receipt_id, debate_id, data) in enumerate(rows):
        conn.execute(
            "INSERT INTO receipts (receipt_id, gauntlet_id, debate_id, created_at, verdict,"
            " confidence, risk_level, checksum, data_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                receipt_id,
                f"g-{receipt_id}",
                debate_id,
                1_750_000_000.0 + index,
                "APPROVED",
                0.8,
                "LOW",
                f"sum-{receipt_id}",
                json.dumps({"receipt_id": receipt_id, **data}),
            ),
        )
    conn.commit()
    conn.close()


def _dump(path: Path) -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = {row["receipt_id"]: dict(row) for row in conn.execute("SELECT * FROM receipts")}
    conn.close()
    return rows


def _owner(path: Path, receipt_id: str) -> tuple[Any, Any, Any]:
    row = _dump(path)[receipt_id]
    return row["org_id"], row["created_by"], row["ownership_source"]


def _schema_version(path: Path) -> int | None:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT version FROM _schema_versions WHERE module = ?", (SCHEMA_MODULE,)
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()
    return row[0] if row else None


LEGACY_ROWS: list[tuple[str, str | None, dict[str, Any]]] = [
    ("r-debate-a", "d-a", {}),
    ("r-payload-debate-b", None, {"debate_id": "d-b"}),
    ("r-config-plan-a", None, {"config_used": {"plan_id": "p-a"}}),
    ("r-agreeing-links", "d-a", {"plan_id": "p-a"}),
    ("r-conflicting-links", "d-a", {"plan_id": "p-b"}),
    ("r-unowned-debate", "d-unowned", {}),
    ("r-missing-debate", "d-missing", {}),
    ("r-unlinked", None, {}),
]
RESOLVER_DATA = {
    "debates": {"d-a": ORG_A, "d-b": ORG_B, "d-unowned": None},
    "plans": {"p-a": ORG_A, "p-b": ORG_B},
}
EXPECTED_BACKFILL = {
    "r-debate-a": (ORG_A, None, OWNERSHIP_BACKFILLED),
    "r-payload-debate-b": (ORG_B, None, OWNERSHIP_BACKFILLED),
    "r-config-plan-a": (ORG_A, None, OWNERSHIP_BACKFILLED),
    "r-agreeing-links": (ORG_A, None, OWNERSHIP_BACKFILLED),
    "r-conflicting-links": (None, None, OWNERSHIP_UNKNOWN),
    "r-unowned-debate": (None, None, OWNERSHIP_UNKNOWN),
    "r-missing-debate": (None, None, OWNERSHIP_UNKNOWN),
    "r-unlinked": (None, None, OWNERSHIP_UNKNOWN),
}


class TestSchema:
    def test_fresh_sqlite_table_has_ownership_columns_and_org_index(self, tmp_path):
        path = tmp_path / "receipts.db"
        _store(path)
        conn = sqlite3.connect(path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(receipts)")}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(receipts)")}
        conn.close()
        assert {"org_id", "created_by", "ownership_source"} <= columns
        assert "idx_receipts_org" in indexes

    def test_legacy_sqlite_table_gains_the_columns_without_touching_rows(self, tmp_path):
        path = tmp_path / "receipts.db"
        _legacy_db(path, LEGACY_ROWS)
        before = _dump(path)

        _store(path)
        after = _dump(path)

        assert set(after) == set(before)
        for receipt_id, row in after.items():
            assert (row["org_id"], row["created_by"], row["ownership_source"]) == (None,) * 3
            assert {k: v for k, v in row.items() if k in before[receipt_id]} == before[receipt_id]

    def test_reopening_a_migrated_table_is_harmless(self, tmp_path):
        path = tmp_path / "receipts.db"
        _legacy_db(path, LEGACY_ROWS)
        _store(path)
        _store(path)
        assert len(_dump(path)) == len(LEGACY_ROWS)

    def test_postgres_ddl_declares_and_migrates_the_columns(self):
        create = ReceiptStore.SCHEMA_STATEMENTS_POSTGRESQL[0]
        for column in ("org_id TEXT", "created_by TEXT", "ownership_source TEXT"):
            assert column in create
            assert (
                f"ALTER TABLE receipts ADD COLUMN IF NOT EXISTS {column}"
                in ReceiptStore.MIGRATION_STATEMENTS_POSTGRESQL
            )
        assert (
            "CREATE INDEX IF NOT EXISTS idx_receipts_org ON receipts(org_id)"
            in ReceiptStore.SCHEMA_STATEMENTS_POSTGRESQL
        )


class TestBackfill:
    def test_backfill_proves_owners_through_linked_debates_and_plans(self, tmp_path):
        path = tmp_path / "receipts.db"
        _legacy_db(path, LEGACY_ROWS)
        before = _dump(path)
        register_receipt_link_resolver(FakeResolver(**RESOLVER_DATA))

        _store(path)

        after = _dump(path)
        assert {rid: _owner(path, rid) for rid in after} == EXPECTED_BACKFILL
        ownership = {"org_id", "created_by", "ownership_source"}
        for receipt_id, row in after.items():
            unchanged = {k: v for k, v in row.items() if k not in ownership}
            assert unchanged == before[receipt_id]
        assert _schema_version(path) == SCHEMA_VERSION

    def test_backfill_runs_once(self, tmp_path):
        path = tmp_path / "receipts.db"
        _legacy_db(path, LEGACY_ROWS)
        resolver = FakeResolver(**RESOLVER_DATA)
        register_receipt_link_resolver(resolver)
        store = _store(path)
        first = _dump(path)
        resolver.calls.clear()

        assert store.migrate_ownership() is False
        _store(path)

        assert _dump(path) == first
        assert resolver.calls == []

    def test_receipts_saved_after_the_backfill_stay_unassigned(self, tmp_path):
        path = tmp_path / "receipts.db"
        register_receipt_link_resolver(FakeResolver(**RESOLVER_DATA))
        store = _store(path)
        store.save(_receipt("r-late", debate_id="d-a"))

        assert store.migrate_ownership() is False
        assert _owner(path, "r-late") == (None, None, None)

    def test_backfill_is_deferred_until_a_resolver_is_registered(self, tmp_path):
        path = tmp_path / "receipts.db"
        _legacy_db(path, LEGACY_ROWS)

        store = _store(path)
        assert store.migrate_ownership() is False
        assert _schema_version(path) is None
        assert all(_owner(path, rid) == (None, None, None) for rid in EXPECTED_BACKFILL)

        register_receipt_link_resolver(FakeResolver(**RESOLVER_DATA))
        assert store.migrate_ownership() is True
        assert {rid: _owner(path, rid) for rid in EXPECTED_BACKFILL} == EXPECTED_BACKFILL

    def test_failed_lookup_writes_nothing_and_retries_later(self, tmp_path):
        path = tmp_path / "receipts.db"
        _legacy_db(path, LEGACY_ROWS)
        register_receipt_link_resolver(FakeResolver(fail=True))

        store = _store(path)
        assert _schema_version(path) is None
        assert all(_owner(path, rid) == (None, None, None) for rid in EXPECTED_BACKFILL)

        register_receipt_link_resolver(FakeResolver(**RESOLVER_DATA))
        assert store.migrate_ownership() is True
        assert _owner(path, "r-debate-a") == (ORG_A, None, OWNERSHIP_BACKFILLED)

    def test_backfill_leaves_created_receipts_alone(self, tmp_path):
        path = tmp_path / "receipts.db"
        store = _store(path)
        store.save(_receipt("r-created", debate_id="d-b"), org_id=ORG_A, created_by="user-1")
        store.save(_receipt("r-plain", debate_id="d-b"))

        register_receipt_link_resolver(FakeResolver(**RESOLVER_DATA))
        assert store.migrate_ownership() is True

        assert _owner(path, "r-created") == (ORG_A, "user-1", OWNERSHIP_CREATED)
        assert _owner(path, "r-plain") == (ORG_B, None, OWNERSHIP_BACKFILLED)

    def test_postgres_records_the_version_with_an_upsert(self):
        class RecordingBackend:
            def __init__(self) -> None:
                self.writes: list[str] = []

            def execute_write(self, sql: str, params: tuple = ()) -> None:
                self.writes.append(" ".join(sql.split()))

            def fetch_one(self, sql: str, params: tuple = ()) -> None:
                return None

            def fetch_all(self, sql: str, params: tuple = ()) -> list:
                return []

            def executemany(self, sql: str, rows: list) -> None:
                raise AssertionError("no rows to update")

        backend = RecordingBackend()
        assert migrate_receipt_ownership(backend, "postgresql", FakeResolver()) is True
        assert any(
            w.startswith("INSERT INTO _schema_versions") and "ON CONFLICT (module)" in w
            for w in backend.writes
        )


class TestReceiptLinks:
    def test_links_come_from_column_payload_and_config(self):
        data = json.dumps(
            {"debate_id": "d-2", "plan_id": "p-1", "config_used": {"debate_id": "d-1"}}
        )
        assert receipt_links("d-1", data) == (["d-1", "d-2"], ["p-1"])

    @pytest.mark.parametrize("data", [None, "", "not json", "[]", {"config_used": "x"}])
    def test_malformed_payloads_link_nothing(self, data):
        assert receipt_links(None, data) == ([], [])


class TestSaveOwnership:
    def test_save_for_an_org_records_a_created_owner(self, tmp_path):
        path = tmp_path / "receipts.db"
        store = _store(path)
        store.save(_receipt("r1"), org_id=ORG_A, created_by="user-a")
        assert _owner(path, "r1") == (ORG_A, "user-a", OWNERSHIP_CREATED)
        assert store.get("r1").org_id == ORG_A

    def test_save_without_an_org_leaves_the_receipt_unassigned(self, tmp_path):
        path = tmp_path / "receipts.db"
        store = _store(path)
        store.save(_receipt("r1"), created_by="user-a")
        assert _owner(path, "r1") == (None, None, None)

    def test_resave_never_moves_or_clears_an_owner(self, tmp_path):
        path = tmp_path / "receipts.db"
        store = _store(path)
        store.save(_receipt("r1"), org_id=ORG_A, created_by="user-a")
        store.save(_receipt("r1", verdict="REJECTED"))
        store.save(_receipt("r1"), org_id=ORG_B, created_by="user-b")
        assert _owner(path, "r1") == (ORG_A, "user-a", OWNERSHIP_CREATED)

    def test_resave_assigns_a_never_assigned_receipt(self, tmp_path):
        path = tmp_path / "receipts.db"
        store = _store(path)
        store.save(_receipt("r1"))
        store.save(_receipt("r1"), org_id=ORG_B, created_by="user-b")
        assert _owner(path, "r1") == (ORG_B, "user-b", OWNERSHIP_CREATED)


class TestOrgScopedReads:
    @pytest.fixture
    def store(self, tmp_path) -> ReceiptStore:
        store = _store(tmp_path / "receipts.db")
        store.save(_receipt("a1", user_id="u1"), org_id=ORG_A, created_by="u1")
        store.save(_receipt("a2", verdict="REJECTED"), org_id=ORG_A)
        store.save(_receipt("b1", user_id="u1"), org_id=ORG_B, created_by="u1")
        store.save(_receipt("unowned", user_id="u1"))
        return store

    def test_get_for_org_returns_only_owned_receipts(self, store):
        assert store.get_for_org("a1", ORG_A).receipt_id == "a1"
        assert store.get_for_org("b1", ORG_A) is None
        assert store.get_for_org("unowned", ORG_A) is None
        assert store.get_by_gauntlet_for_org("g-a1", ORG_A).receipt_id == "a1"
        assert store.get_by_gauntlet_for_org("g-b1", ORG_A) is None

    def test_list_count_and_search_exclude_other_orgs(self, store):
        assert {r.receipt_id for r in store.list_for_org(ORG_A, limit=50)} == {"a1", "a2"}
        assert store.count_for_org(ORG_A) == 2
        assert store.count_for_org(ORG_B) == 1
        assert {r.receipt_id for r in store.search_for_org(ORG_A, "statement")} == {"a1", "a2"}
        assert store.search_count_for_org(ORG_A, "statement") == 2

    def test_stats_retention_and_dsar_cover_only_the_org(self, store):
        assert store.stats_for_org(ORG_A)["total"] == 2
        retention = store.retention_status_for_org(ORG_A)
        assert retention["total_receipts"] == 2
        receipts, total = store.get_by_user_for_org(ORG_A, "u1")
        assert (total, [r.receipt_id for r in receipts]) == (1, ["a1"])

    def test_verification_does_not_see_other_orgs(self, store):
        assert store.verify_integrity("b1", org_id=ORG_A)["error"] == "Receipt not found"
        assert store.verify_signature("b1", org_id=ORG_A).error == "Receipt not found"
        results, summary = store.verify_batch(["a1", "b1", "unowned"], org_id=ORG_A)
        assert [r.error for r in results][1:] == ["Receipt not found", "Receipt not found"]
        assert summary["total"] == 3

    @pytest.mark.parametrize("org_id", ["", "  ", None])
    def test_scoped_reads_refuse_a_blank_org(self, store, org_id):
        with pytest.raises(ValueError):
            store.get_for_org("a1", org_id)
        with pytest.raises(ValueError):
            store.list_for_org(org_id)


class TestServerReceiptLinkResolver:
    def test_debate_and_plan_orgs_come_from_their_stores(self):
        class Debates:
            def get_org_id(self, debate_id):
                return {"d-a": ORG_A}.get(debate_id)

        class Plan:
            org_id = ORG_B

        class Plans:
            def get(self, plan_id):
                return Plan() if plan_id == "p-b" else None

        resolver = ServerReceiptLinkResolver(Debates(), lambda: Plans())
        assert resolver.debate_org_id("d-a") == ORG_A
        assert resolver.debate_org_id("d-x") is None
        assert resolver.plan_org_id("p-b") == ORG_B
        assert resolver.plan_org_id("p-x") is None

    def test_unavailable_or_failing_stores_raise_lookup_errors(self):
        class BrokenDebates:
            def get_org_id(self, debate_id):
                raise sqlite3.OperationalError("locked")

        def broken_plans():
            raise RuntimeError("plan store down")

        with pytest.raises(ReceiptLinkLookupError):
            ServerReceiptLinkResolver(None).debate_org_id("d-a")
        with pytest.raises(ReceiptLinkLookupError):
            ServerReceiptLinkResolver(BrokenDebates()).debate_org_id("d-a")
        with pytest.raises(ReceiptLinkLookupError):
            ServerReceiptLinkResolver(None, broken_plans).plan_org_id("p-a")

    def test_install_registers_the_resolver_and_runs_the_backfill(self, tmp_path, monkeypatch):
        path = tmp_path / "receipts.db"
        _legacy_db(path, [("r1", "d-a", {})])
        store = _store(path)
        monkeypatch.setattr("aragora.storage.receipt_store.get_receipt_store", lambda: store)

        class Debates:
            def get_org_id(self, debate_id):
                return ORG_A

        assert install_receipt_link_resolver(Debates()) is True
        assert isinstance(get_receipt_link_resolver(), ServerReceiptLinkResolver)
        assert _owner(path, "r1") == (ORG_A, None, OWNERSHIP_BACKFILLED)


def test_each_linked_record_is_looked_up_once(tmp_path):
    """However many receipts link a debate or plan, it is resolved a single time."""
    path = tmp_path / "receipts.db"
    _legacy_db(path, [(f"r{i}", "d-a", {"plan_id": "p-a"}) for i in range(50)])
    resolver = FakeResolver(**RESOLVER_DATA)
    register_receipt_link_resolver(resolver)
    _store(path)
    assert sorted(resolver.calls) == [("debate", "d-a"), ("plan", "p-a")]
