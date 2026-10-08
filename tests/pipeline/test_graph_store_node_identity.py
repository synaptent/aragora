"""Node identity in GraphStore is ``(graph_id, id)``.

The same node id (``raw-idea-0``, ``fractal-0``, ...) in two graphs names two
different nodes; writing one graph never moves, replaces or deletes the nodes
of another. Stores created before node identity was per graph keep their old
``nodes`` table (its schema is never changed) and get their rows copied once
into ``graph_nodes``. Deleting or rewriting a copied graph's nodes also deletes
that graph's rows from the old table, as writes did before the copy.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aragora.canvas.stages import PipelineStage
from aragora.pipeline.graph_store import GraphStore
from aragora.pipeline.universal_node import UniversalGraph, UniversalNode


def _node(node_id: str, label: str, **extra) -> UniversalNode:
    return UniversalNode(
        id=node_id,
        stage=extra.pop("stage", PipelineStage.IDEAS),
        node_subtype="concept",
        label=label,
        **extra,
    )


def _graph(graph_id: str, *nodes: UniversalNode) -> UniversalGraph:
    graph = UniversalGraph(id=graph_id, name=graph_id)
    for node in nodes:
        graph.nodes[node.id] = node
    return graph


@pytest.fixture
def store(tmp_path: Path) -> GraphStore:
    return GraphStore(db_path=str(tmp_path / "pipeline_graphs.db"))


def _labels(store: GraphStore, graph_id: str) -> dict[str, str]:
    graph = store.get(graph_id)
    assert graph is not None
    return {node_id: node.label for node_id, node in graph.nodes.items()}


class TestPerGraphNodes:
    def test_two_orgs_keep_their_own_node_with_the_same_id(self, store: GraphStore) -> None:
        store.create(_graph("ugraph-a", _node("raw-idea-0", "A secret idea")), org_id="org-a")
        store.create(_graph("ugraph-b", _node("raw-idea-0", "B idea")), org_id="org-b")

        assert _labels(store, "ugraph-a") == {"raw-idea-0": "A secret idea"}
        assert _labels(store, "ugraph-b") == {"raw-idea-0": "B idea"}
        assert [n.label for n in store.query_nodes("ugraph-a")] == ["A secret idea"]

    def test_two_pipelines_of_one_org_do_not_overwrite_each_other(self, store: GraphStore) -> None:
        first = _graph("ugraph-1", _node("raw-idea-0", "first"), _node("raw-idea-1", "first two"))
        second = _graph("ugraph-2", _node("raw-idea-0", "second"))
        store.create(first, org_id="org-a")
        store.create(second, org_id="org-a")

        assert _labels(store, "ugraph-1") == {"raw-idea-0": "first", "raw-idea-1": "first two"}
        assert _labels(store, "ugraph-2") == {"raw-idea-0": "second"}
        counts = {g["id"]: g["node_count"] for g in store.list(org_id="org-a")}
        assert counts == {"ugraph-1": 2, "ugraph-2": 1}

    def test_update_and_delete_touch_only_their_own_graph(self, store: GraphStore) -> None:
        store.create(_graph("g-a", _node("n-1", "A")), org_id="org-a")
        store.create(_graph("g-b", _node("n-1", "B")), org_id="org-b")

        graph_b = store.get("g-b")
        graph_b.nodes.clear()
        store.update(graph_b)
        assert _labels(store, "g-a") == {"n-1": "A"}

        store.create(_graph("g-b", _node("n-1", "B again")), org_id="org-b")
        assert store.delete("g-b") is True
        assert _labels(store, "g-a") == {"n-1": "A"}
        assert store.get("g-b") is None

    def test_add_and_remove_node_with_an_id_another_graph_uses(self, store: GraphStore) -> None:
        store.create(_graph("g-a"), org_id="org-a")
        store.create(_graph("g-b"), org_id="org-b")
        store.add_node("g-a", _node("n-shared", "A"))

        store.add_node("g-b", _node("n-shared", "B"))
        assert store.node_graph_ids("n-shared") == ["g-a", "g-b"]
        assert _labels(store, "g-a") == {"n-shared": "A"}
        assert _labels(store, "g-b") == {"n-shared": "B"}

        store.remove_node("g-b", "n-shared")
        assert store.node_graph_ids("n-shared") == ["g-a"]
        assert _labels(store, "g-a") == {"n-shared": "A"}
        assert store.node_graph_ids("n-missing") == []

    def test_provenance_stays_inside_the_graph(self, store: GraphStore) -> None:
        store.create(
            _graph("g-a", _node("root", "A root"), _node("leaf", "A leaf", parent_ids=["root"])),
            org_id="org-a",
        )
        store.create(_graph("g-b", _node("root", "B root")), org_id="org-b")

        chain = store.get_provenance_chain("g-a", "leaf")
        downstream = store.get_downstream_chain("g-a", "root")

        assert [n.label for n in chain] == ["A leaf", "A root"]
        assert [n.label for n in downstream] == ["A root", "A leaf"]


# ---------------------------------------------------------------------------
# One-time copy from the old ``nodes`` table
# ---------------------------------------------------------------------------

_OLD_SCHEMA = """
    CREATE TABLE graphs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        owner_id TEXT,
        workspace_id TEXT,
        edges_json TEXT DEFAULT '[]',
        transitions_json TEXT DEFAULT '[]',
        metadata_json TEXT DEFAULT '{}',
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        org_id TEXT,
        created_by TEXT,
        ownership_source TEXT
    );
    CREATE TABLE nodes (
        id TEXT PRIMARY KEY,
        graph_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        node_subtype TEXT NOT NULL,
        label TEXT NOT NULL,
        description TEXT DEFAULT '',
        position_x REAL DEFAULT 0,
        position_y REAL DEFAULT 0,
        width REAL DEFAULT 200,
        height REAL DEFAULT 100,
        content_hash TEXT NOT NULL,
        previous_hash TEXT,
        parent_ids_json TEXT DEFAULT '[]',
        source_stage TEXT,
        status TEXT DEFAULT 'active',
        {execution_status}
        confidence REAL DEFAULT 0,
        data_json TEXT DEFAULT '{}',
        style_json TEXT DEFAULT '{}',
        metadata_json TEXT DEFAULT '{}',
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        FOREIGN KEY (graph_id) REFERENCES graphs(id)
    );
    CREATE INDEX idx_nodes_graph_stage ON nodes(graph_id, stage);
    CREATE INDEX idx_nodes_subtype ON nodes(node_subtype);
    CREATE INDEX idx_nodes_content_hash ON nodes(content_hash);
"""

_OLD_NODES = [
    # id, graph_id, stage, subtype, label, content_hash, parent_ids_json, data_json
    ("raw-idea-0", "g-old-a", "ideas", "concept", "A legacy idea", "h0", "[]", '{"k": 1}'),
    ("goal-1", "g-old-a", "goals", "goal", "A legacy goal", "h1", '["raw-idea-0"]', "{}"),
    ("raw-idea-1", "g-old-b", "ideas", "concept", "B legacy idea", "h2", "[]", "{}"),
]


def _old_db(path: Path, *, with_execution_status: bool = True) -> None:
    conn = sqlite3.connect(path)
    column = "execution_status TEXT," if with_execution_status else ""
    conn.executescript(_OLD_SCHEMA.replace("{execution_status}", column))
    conn.executemany(
        "INSERT INTO graphs (id, name, created_at, updated_at, org_id, created_by,"
        " ownership_source) VALUES (?, ?, 1, 2, ?, ?, 'created')",
        [("g-old-a", "Old A", "org-a", "user-a"), ("g-old-b", "Old B", "org-b", "user-b")],
    )
    for node_id, graph_id, stage, subtype, label, digest, parents, data in _OLD_NODES:
        conn.execute(
            "INSERT INTO nodes (id, graph_id, stage, node_subtype, label, content_hash,"
            " parent_ids_json, data_json, position_x, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 7.5, 10, 20)",
            (node_id, graph_id, stage, subtype, label, digest, parents, data),
        )
    conn.commit()
    conn.close()


def _old_table_state(path: Path) -> tuple:
    conn = sqlite3.connect(path)
    try:
        schema = conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE tbl_name = 'nodes' ORDER BY name"
        ).fetchall()
        rows = conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()
        return schema, rows
    finally:
        conn.close()


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()


def _new_rows(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT graph_id, id, label FROM graph_nodes ORDER BY graph_id, id"
        ).fetchall()
    finally:
        conn.close()


class TestOldSchemaCopy:
    @pytest.mark.parametrize("with_execution_status", [True, False])
    def test_existing_nodes_survive_the_copy_unchanged(
        self, tmp_path: Path, with_execution_status: bool
    ) -> None:
        db_path = tmp_path / "old.db"
        _old_db(db_path, with_execution_status=with_execution_status)
        old_state = _old_table_state(db_path)

        store = GraphStore(db_path=str(db_path))

        graph_a = store.get("g-old-a")
        assert graph_a is not None
        assert {n.id: n.label for n in graph_a.nodes.values()} == {
            "raw-idea-0": "A legacy idea",
            "goal-1": "A legacy goal",
        }
        idea = graph_a.nodes["raw-idea-0"]
        assert (idea.content_hash, idea.position_x, idea.data, idea.created_at) == (
            "h0",
            7.5,
            {"k": 1},
            10,
        )
        assert idea.execution_status is None
        assert graph_a.nodes["goal-1"].parent_ids == ["raw-idea-0"]
        assert _labels(store, "g-old-b") == {"raw-idea-1": "B legacy idea"}
        assert store.get_owner_org("g-old-a") == "org-a"
        assert _old_table_state(db_path) == old_state

    def test_copy_runs_once_and_never_changes_the_old_schema(self, tmp_path: Path) -> None:
        db_path = tmp_path / "old.db"
        _old_db(db_path)
        old_schema, _ = _old_table_state(db_path)
        tables_before = _tables(db_path)

        store = GraphStore(db_path=str(db_path))
        copied = _new_rows(db_path)
        GraphStore(db_path=str(db_path))
        assert _new_rows(db_path) == copied

        # Later writes are not undone by reopening the store.
        graph_a = store.get("g-old-a")
        del graph_a.nodes["goal-1"]
        store.update(graph_a)
        store.create(_graph("g-new", _node("raw-idea-0", "new idea")), org_id="org-b")
        assert store.delete("g-old-b") is True
        GraphStore(db_path=str(db_path))

        assert _new_rows(db_path) == [
            ("g-new", "raw-idea-0", "new idea"),
            ("g-old-a", "raw-idea-0", "A legacy idea"),
        ]
        assert _old_table_state(db_path) == (old_schema, [])
        assert tables_before <= _tables(db_path)

    def test_new_table_is_keyed_by_graph_and_id_with_the_old_indexes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "old.db"
        _old_db(db_path)
        GraphStore(db_path=str(db_path))

        conn = sqlite3.connect(db_path)
        try:
            key = sorted(
                (row[5], row[1]) for row in conn.execute("PRAGMA table_info(graph_nodes)") if row[5]
            )
            indexed = {
                tuple(col[2] for col in conn.execute(f"PRAGMA index_info({row[1]})"))
                for row in conn.execute("PRAGMA index_list(graph_nodes)")
            }
        finally:
            conn.close()

        assert key == [(1, "graph_id"), (2, "id")]
        assert {("graph_id", "stage"), ("node_subtype",), ("content_hash",)} <= indexed

    def test_fresh_store_has_no_old_nodes_table(self, store: GraphStore) -> None:
        assert "graph_nodes" in _tables(Path(store._db_path))
        assert "nodes" not in _tables(Path(store._db_path))


def _old_rows_of(path: Path, graph_id: str) -> list[tuple]:
    return [row for row in _old_table_state(path)[1] if row[1] == graph_id]


def _add_orphan_row(path: Path) -> None:
    """An old row whose graph is gone; the copy skips it."""
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO nodes (id, graph_id, stage, node_subtype, label, content_hash,"
        " created_at, updated_at) VALUES ('orphan-0', 'g-gone', 'ideas', 'concept',"
        " 'Orphan idea', 'h9', 1, 2)"
    )
    conn.commit()
    conn.close()


class TestOldTableRows:
    """Writes that drop a copied graph's nodes drop the same rows from the old table."""

    @pytest.fixture
    def old_store(self, tmp_path: Path) -> tuple[GraphStore, Path, list]:
        db_path = tmp_path / "old.db"
        _old_db(db_path)
        _add_orphan_row(db_path)
        schema, _ = _old_table_state(db_path)
        return GraphStore(db_path=str(db_path)), db_path, schema

    def test_delete_removes_that_graphs_old_rows_only(self, old_store) -> None:
        store, db_path, schema = old_store
        b_rows = _old_rows_of(db_path, "g-old-b")
        orphan_rows = _old_rows_of(db_path, "g-gone")

        assert store.delete("g-old-a") is True

        assert store.get("g-old-a") is None
        assert _old_rows_of(db_path, "g-old-a") == []
        assert _old_rows_of(db_path, "g-old-b") == b_rows
        assert _old_rows_of(db_path, "g-gone") == orphan_rows
        assert _old_table_state(db_path)[0] == schema
        assert _labels(store, "g-old-b") == {"raw-idea-1": "B legacy idea"}

    def test_update_removes_that_graphs_old_rows_only(self, old_store) -> None:
        store, db_path, schema = old_store
        b_rows = _old_rows_of(db_path, "g-old-b")
        graph_a = store.get("g-old-a")
        graph_a.nodes["raw-idea-0"].label = "A edited idea"

        store.update(graph_a)

        assert _old_rows_of(db_path, "g-old-a") == []
        assert _old_rows_of(db_path, "g-old-b") == b_rows
        assert _old_table_state(db_path)[0] == schema
        assert _labels(store, "g-old-a") == {
            "raw-idea-0": "A edited idea",
            "goal-1": "A legacy goal",
        }

    def test_create_over_a_graph_removes_its_old_rows_only(self, old_store) -> None:
        store, db_path, _ = old_store
        b_rows = _old_rows_of(db_path, "g-old-b")

        store.create(_graph("g-old-a", _node("raw-idea-0", "A replaced idea")), org_id="org-a")

        assert _old_rows_of(db_path, "g-old-a") == []
        assert _old_rows_of(db_path, "g-old-b") == b_rows
        assert _labels(store, "g-old-a") == {"raw-idea-0": "A replaced idea"}

    def test_remove_and_replace_node_drop_only_that_graphs_old_row(self, old_store) -> None:
        store, db_path, schema = old_store
        b_rows = _old_rows_of(db_path, "g-old-b")
        a_goal = [row for row in _old_rows_of(db_path, "g-old-a") if row[0] == "goal-1"]

        # goal-1's old row belongs to g-old-a; writing goal-1 in g-old-b leaves it.
        store.add_node("g-old-b", _node("goal-1", "B goal"))
        store.remove_node("g-old-b", "goal-1")
        assert [row for row in _old_rows_of(db_path, "g-old-a") if row[0] == "goal-1"] == a_goal

        store.remove_node("g-old-a", "goal-1")
        store.add_node("g-old-a", _node("raw-idea-0", "A replaced idea"))

        assert _old_rows_of(db_path, "g-old-a") == []
        assert _old_rows_of(db_path, "g-old-b") == b_rows
        assert _old_table_state(db_path)[0] == schema
        assert _labels(store, "g-old-a") == {"raw-idea-0": "A replaced idea"}
        assert _labels(store, "g-old-b") == {"raw-idea-1": "B legacy idea"}

    def test_delete_keeps_foreign_keys_on_and_is_one_transaction(self, old_store) -> None:
        store, db_path, _ = old_store
        old_state = _old_table_state(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE fk_probe (graph_id TEXT NOT NULL REFERENCES graphs(id))")
        conn.execute("INSERT INTO fk_probe VALUES ('g-old-a')")
        conn.commit()
        conn.close()

        with pytest.raises(sqlite3.IntegrityError):
            store.delete("g-old-a")

        assert _old_table_state(db_path) == old_state
        assert _labels(store, "g-old-a") == {
            "raw-idea-0": "A legacy idea",
            "goal-1": "A legacy goal",
        }
