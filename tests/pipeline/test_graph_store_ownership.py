"""Ownership columns of GraphStore: stamping, preservation, migration, org lists, node ids."""

from __future__ import annotations

import sqlite3

import pytest

from aragora.canvas.stages import PipelineStage
from aragora.pipeline.graph_store import GraphStore
from aragora.pipeline.universal_node import UniversalGraph, UniversalNode


def _graph(graph_id: str, name: str = "G") -> UniversalGraph:
    return UniversalGraph(id=graph_id, name=name)


def _node(node_id: str) -> UniversalNode:
    return UniversalNode(
        id=node_id, stage=PipelineStage.IDEAS, node_subtype="concept", label=node_id
    )


@pytest.fixture
def store(tmp_path) -> GraphStore:
    return GraphStore(db_path=str(tmp_path / "pipeline_graphs.db"))


def _owner_row(store: GraphStore, graph_id: str) -> tuple:
    conn = sqlite3.connect(store._db_path)
    try:
        return conn.execute(
            "SELECT org_id, created_by, ownership_source FROM graphs WHERE id = ?", (graph_id,)
        ).fetchone()
    finally:
        conn.close()


def test_create_records_owner(store: GraphStore) -> None:
    store.create(_graph("g-a"), org_id="org-a", created_by="user-a")

    assert _owner_row(store, "g-a") == ("org-a", "user-a", "created")
    assert store.get_owner_org("g-a") == "org-a"


def test_update_and_recreate_keep_owner(store: GraphStore) -> None:
    store.create(_graph("g-a"), org_id="org-a", created_by="user-a")
    graph = store.get("g-a")
    graph.name = "Renamed"
    store.update(graph)
    store.create(_graph("g-a", "Replaced"), org_id="org-b", created_by="user-b")

    assert _owner_row(store, "g-a") == ("org-a", "user-a", "created")
    assert store.get("g-a").name == "Replaced"


def test_graph_without_org_has_no_owner(store: GraphStore) -> None:
    store.create(_graph("g-x"))

    assert store.get_owner_org("g-x") is None
    assert store.get_owner_org("g-missing") is None


def test_list_filters_by_org(store: GraphStore) -> None:
    store.create(_graph("g-a"), org_id="org-a")
    store.create(_graph("g-b"), org_id="org-b")
    store.create(_graph("g-x"))

    assert [g["id"] for g in store.list(org_id="org-a")] == ["g-a"]
    assert [g["id"] for g in store.list(org_id="org-b")] == ["g-b"]
    assert {g["id"] for g in store.list()} == {"g-a", "g-b", "g-x"}


def test_add_node_refuses_a_node_id_of_another_graph(store: GraphStore) -> None:
    store.create(_graph("g-a"), org_id="org-a")
    store.create(_graph("g-b"), org_id="org-b")
    store.add_node("g-a", _node("n-shared"))

    with pytest.raises(ValueError):
        store.add_node("g-b", _node("n-shared"))

    assert store.node_graph_id("n-shared") == "g-a"
    assert "n-shared" in store.get("g-a").nodes
    store.add_node("g-a", _node("n-shared"))


def test_existing_graphs_are_marked_unknown(tmp_path) -> None:
    db_path = tmp_path / "legacy_graphs.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE graphs (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, owner_id TEXT, workspace_id TEXT,
            edges_json TEXT DEFAULT '[]', transitions_json TEXT DEFAULT '[]',
            metadata_json TEXT DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        INSERT INTO graphs (id, name, created_at, updated_at) VALUES ('g-legacy', 'L', 1, 1);
        """
    )
    conn.commit()
    conn.close()

    store = GraphStore(db_path=str(db_path))
    GraphStore(db_path=str(db_path))

    assert _owner_row(store, "g-legacy") == (None, None, "unknown")
    assert store.get_owner_org("g-legacy") is None
    assert store.list(org_id="org-a") == []
    assert store.get("g-legacy").name == "L"
