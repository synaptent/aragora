"""Org scoping for the fact store: v1 -> v2 migration, quarantine and the scoped view."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

import aragora.knowledge.fact_store as fact_store_module
from aragora.knowledge import FactFilters, FactRelationType, FactStore, InMemoryFactStore
from aragora.knowledge.fact_store import ScopedFactStore

LEGACY_STATEMENT = "The vendor contract renews every March"

# FactStore keyword search joins a contentless FTS5 table whose fact_id reads
# back as NULL, so a non-empty SQLite query matches nothing. An empty query
# takes the org-filtered list_facts path on both backends.
ALL = ""


def _v1_hash(statement: str) -> str:
    normalized = " ".join(statement.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def _make_v1_db(path, *, with_org_column: bool = False) -> None:
    """Write a knowledge.db the way the v1 store left it, with two legacy facts and a relation."""
    conn = sqlite3.connect(path)
    conn.executescript(FactStore.INITIAL_SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(facts)")}
    assert "org_id" not in columns
    if with_org_column:
        conn.execute("ALTER TABLE facts ADD COLUMN org_id TEXT")
    conn.execute(
        "CREATE TABLE _schema_versions (module TEXT PRIMARY KEY, version INTEGER NOT NULL, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO _schema_versions (module, version) VALUES ('fact_store', 1)")
    for fact_id, statement in (("fact_legacy1", LEGACY_STATEMENT), ("fact_legacy2", "Legacy two")):
        conn.execute(
            "INSERT INTO facts (id, statement, statement_hash, confidence, workspace_id, "
            "validation_status, created_at, updated_at) VALUES (?, ?, ?, 0.9, 'default', "
            "'unverified', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            (fact_id, statement, _v1_hash(statement)),
        )
        conn.execute(
            "INSERT INTO facts_fts (fact_id, statement, topics) VALUES (?, ?, '')",
            (fact_id, statement),
        )
    conn.execute(
        "INSERT INTO fact_relations (id, source_fact_id, target_fact_id, relation_type, created_at) "
        "VALUES ('rel_legacy', 'fact_legacy1', 'fact_legacy2', 'contradicts', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()


def _schema_state(path) -> tuple[int, set[str], set[str]]:
    conn = sqlite3.connect(path)
    try:
        version = conn.execute(
            "SELECT version FROM _schema_versions WHERE module = 'fact_store'"
        ).fetchone()[0]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(facts)")}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(facts)")}
    finally:
        conn.close()
    return version, columns, indexes


class TestMigration:
    def test_v1_file_migrates_with_null_org_and_indexes(self, tmp_path):
        db = tmp_path / "knowledge.db"
        _make_v1_db(db)

        store = FactStore(db_path=db)

        version, columns, indexes = _schema_state(db)
        assert version == 2
        assert "org_id" in columns
        assert {"idx_facts_org_workspace", "idx_facts_org_scope_hash"} <= indexes
        legacy = store.get_fact("fact_legacy1")
        assert legacy is not None and legacy.org_id is None
        assert len(store.list_facts()) == 2
        assert "org_id" not in legacy.to_dict()

    def test_second_open_is_a_noop(self, tmp_path, monkeypatch):
        db = tmp_path / "knowledge.db"
        _make_v1_db(db)
        FactStore(db_path=db)

        def _fail(conn):
            raise AssertionError("migration ran on an already-migrated file")

        monkeypatch.setattr(fact_store_module, "_add_org_scope", _fail)
        store = FactStore(db_path=db)

        assert _schema_state(db)[0] == 2
        assert {f.id for f in store.list_facts()} == {"fact_legacy1", "fact_legacy2"}

    def test_interrupted_migration_completes(self, tmp_path):
        db = tmp_path / "knowledge.db"
        _make_v1_db(db, with_org_column=True)

        FactStore(db_path=db)

        version, columns, indexes = _schema_state(db)
        assert version == 2 and "org_id" in columns
        assert {"idx_facts_org_workspace", "idx_facts_org_scope_hash"} <= indexes

    def test_already_v2_file_keeps_scoped_rows(self, tmp_path):
        db = tmp_path / "knowledge.db"
        created = ScopedFactStore(FactStore(db_path=db), "org_a").add_fact("Owned", "default")

        reopened = ScopedFactStore(FactStore(db_path=db), "org_a")

        assert _schema_state(db)[0] == 2
        assert reopened.get_fact(created.id) is not None


class TestQuarantine:
    @pytest.fixture
    def legacy_store(self, tmp_path):
        db = tmp_path / "knowledge.db"
        _make_v1_db(db)
        return FactStore(db_path=db)

    def test_legacy_rows_invisible_to_scoped_callers(self, legacy_store):
        scoped = ScopedFactStore(legacy_store, "org_a")

        assert scoped.get_fact("fact_legacy1") is None
        assert scoped.list_facts() == []
        assert scoped.query_facts("vendor") == []
        assert scoped.query_facts(ALL) == []
        assert scoped.get_contradictions("fact_legacy1") == []
        assert scoped.get_relations("fact_legacy1") == []
        assert scoped.update_fact("fact_legacy1", confidence=0.1) is None
        assert scoped.delete_fact("fact_legacy1") is False
        assert (
            scoped.add_relation("fact_legacy1", "fact_legacy2", FactRelationType.SUPPORTS) is None
        )
        stats = scoped.get_statistics()
        assert stats["total_facts"] == 0 and stats["total_relations"] == 0
        assert legacy_store.get_fact("fact_legacy1").confidence == 0.9
        assert len(legacy_store.query_facts(ALL)) == 2
        assert len(legacy_store.get_relations("fact_legacy1")) == 1

    def test_scoped_dedup_never_matches_a_legacy_row(self, legacy_store):
        created = ScopedFactStore(legacy_store, "org_a").add_fact(LEGACY_STATEMENT, "default")

        assert created.id != "fact_legacy1"
        assert created.org_id == "org_a"

    def test_assign_org_claims_only_unassigned_rows(self, legacy_store):
        owned_b = ScopedFactStore(legacy_store, "org_b").add_fact("Org B fact", "default")

        assert legacy_store.assign_org("org_a", fact_ids=[]) == 0
        assert legacy_store.assign_org("org_a", workspace_id="other") == 0
        assert legacy_store.assign_org("org_a", fact_ids=["fact_legacy1", owned_b.id]) == 1
        assert legacy_store.assign_org("org_a", workspace_id="default") == 1

        scoped_a = ScopedFactStore(legacy_store, "org_a")
        assert {f.id for f in scoped_a.list_facts()} == {"fact_legacy1", "fact_legacy2"}
        assert [r.id for r in scoped_a.get_relations("fact_legacy1")] == ["rel_legacy"]
        assert legacy_store.get_fact(owned_b.id).org_id == "org_b"
        with pytest.raises(ValueError):
            legacy_store.assign_org("")


@pytest.fixture(params=["sqlite", "memory"])
def store(request, tmp_path):
    if request.param == "sqlite":
        return FactStore(db_path=tmp_path / "knowledge.db")
    return InMemoryFactStore()


class TestScopedView:
    def test_requires_a_non_empty_org(self, store):
        for bad in ("", "   ", None):
            with pytest.raises(ValueError):
                ScopedFactStore(store, bad)  # type: ignore[arg-type]

    def test_rejects_a_different_org(self, store):
        scoped = ScopedFactStore(store, "org_a")

        with pytest.raises(ValueError):
            scoped.add_fact("Statement", "default", org_id="org_b")
        with pytest.raises(ValueError):
            scoped.list_facts(FactFilters(org_id="org_b"))
        assert scoped.list_facts(FactFilters(org_id="org_a")) == []

    def test_reads_never_cross_orgs(self, store):
        scoped_a = ScopedFactStore(store, "org_a")
        scoped_b = ScopedFactStore(store, "org_b")
        own = scoped_a.add_fact("Alpha pricing is tiered", "default", topics=["pricing"])
        foreign = scoped_b.add_fact("Alpha pricing is flat", "default", topics=["pricing"])
        unassigned = store.add_fact("Alpha pricing is secret", "default")

        assert own.org_id == "org_a" and store.get_fact(own.id).org_id == "org_a"
        assert unassigned.org_id is None
        assert "org_id" not in own.to_dict()
        assert scoped_a.get_fact(foreign.id) is None
        assert scoped_a.get_fact(unassigned.id) is None
        assert [f.id for f in scoped_a.list_facts()] == [own.id]
        assert [f.id for f in scoped_a.query_facts(ALL)] == [own.id]
        assert {f.id for f in scoped_a.query_facts("pricing")} <= {own.id}
        assert [f.id for f in scoped_a.list_facts(FactFilters(workspace_id="default"))] == [own.id]
        assert len(store.list_facts()) == 3

    def test_writes_never_cross_orgs(self, store):
        scoped_a = ScopedFactStore(store, "org_a")
        own = scoped_a.add_fact("Own fact", "default")
        foreign = ScopedFactStore(store, "org_b").add_fact("Foreign fact", "default")

        assert scoped_a.update_fact(foreign.id, confidence=0.99) is None
        assert scoped_a.delete_fact(foreign.id) is False
        assert store.get_fact(foreign.id).confidence == 0.5
        with pytest.raises(ValueError):
            scoped_a.update_fact(own.id, superseded_by=foreign.id)
        with pytest.raises(ValueError):
            scoped_a.update_fact(own.id, superseded_by="fact_missing")
        newer = scoped_a.add_fact("Newer own fact", "default")
        assert scoped_a.update_fact(own.id, superseded_by=newer.id).superseded_by == newer.id
        assert scoped_a.update_fact(newer.id, confidence=0.8).confidence == 0.8
        assert scoped_a.delete_fact(newer.id) is True

    def test_dedup_is_scoped_to_org_and_workspace(self, store):
        scoped_a = ScopedFactStore(store, "org_a")
        foreign = ScopedFactStore(store, "org_b").add_fact("Shared statement", "default")
        unassigned = store.add_fact("Shared statement", "default")

        first = scoped_a.add_fact("Shared statement", "default")
        again = scoped_a.add_fact("  shared   STATEMENT ", "default")
        other_workspace = scoped_a.add_fact("Shared statement", "ws_other")

        assert first.id not in (foreign.id, unassigned.id)
        assert again.id == first.id
        assert other_workspace.id != first.id
        assert store.add_fact("Shared statement", "default").id == unassigned.id

    def test_dedup_keeps_the_oldest_duplicate(self, store):
        scoped = ScopedFactStore(store, "org_a")
        fact_a = scoped.add_fact("Repeated claim", "default")
        fact_b = scoped.add_fact("Repeated claim", "default", deduplicate=False)

        assert fact_b.id != fact_a.id
        assert scoped.add_fact("Repeated claim", "default").id == fact_a.id
        assert scoped.delete_fact(fact_a.id) is True
        assert scoped.add_fact("Repeated claim", "default").id == fact_b.id

    def test_relations_are_scoped_at_both_ends(self, store):
        scoped_a = ScopedFactStore(store, "org_a")
        own_1 = scoped_a.add_fact("Own one", "default")
        own_2 = scoped_a.add_fact("Own two", "default")
        foreign = ScopedFactStore(store, "org_b").add_fact("Foreign", "default")

        assert scoped_a.add_relation(own_1.id, foreign.id, FactRelationType.SUPPORTS) is None
        assert scoped_a.add_relation(foreign.id, own_1.id, FactRelationType.SUPPORTS) is None
        store.add_relation(own_1.id, foreign.id, FactRelationType.CONTRADICTS)
        own_rel = scoped_a.add_relation(own_1.id, own_2.id, FactRelationType.CONTRADICTS)

        assert own_rel is not None
        assert [r.id for r in scoped_a.get_relations(own_1.id)] == [own_rel.id]
        assert [f.id for f in scoped_a.get_contradictions(own_1.id)] == [own_2.id]
        assert ScopedFactStore(store, "org_b").get_relations(foreign.id) == []
        assert ScopedFactStore(store, "org_b").get_contradictions(foreign.id) == []
        assert len(store.get_relations(own_1.id)) == 2

    def test_statistics_are_scoped(self, store):
        scoped_a = ScopedFactStore(store, "org_a")
        own_1 = scoped_a.add_fact("Own one", "default", confidence=0.4)
        own_2 = scoped_a.add_fact("Own two", "ws_two", confidence=0.8)
        foreign = ScopedFactStore(store, "org_b").add_fact("Foreign", "default", confidence=0.1)
        store.add_fact("Unassigned", "default")
        scoped_a.add_relation(own_1.id, own_2.id, FactRelationType.SUPPORTS)
        store.add_relation(own_1.id, foreign.id, FactRelationType.SUPPORTS)

        stats = scoped_a.get_statistics()
        assert stats["total_facts"] == 2
        assert stats["average_confidence"] == pytest.approx(0.6)
        assert stats["total_relations"] == 1
        in_workspace = scoped_a.get_statistics("default")
        assert in_workspace["total_facts"] == 1 and in_workspace["total_relations"] == 0
        assert store.get_statistics()["total_facts"] == 4
        assert store.get_statistics()["total_relations"] == 2

    def test_assign_org_parity(self, store):
        unassigned = store.add_fact("Legacy claim", "default")
        scoped = ScopedFactStore(store, "org_a")
        newer = scoped.add_fact("Legacy claim", "default")

        assert store.assign_org("org_a", fact_ids=[unassigned.id]) == 1
        assert store.assign_org("org_a", fact_ids=[unassigned.id]) == 0
        assert scoped.add_fact("Legacy claim", "default").id == unassigned.id
        assert {f.id for f in scoped.list_facts()} == {unassigned.id, newer.id}
        assert store.add_fact("Legacy claim", "default").id not in (unassigned.id, newer.id)
