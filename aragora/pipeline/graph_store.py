"""
SQLite-backed persistent store for UniversalGraph objects.

Follows the PlanStore pattern: WAL mode, per-method connections,
separate tables for graphs and nodes, edges stored as JSON in the
graph row.

Usage:
    store = GraphStore()
    store.create(graph)
    graph = store.get(graph_id)
    store.add_node(graph_id, node)
    chain = store.get_provenance_chain(graph_id, node_id)

Each graph row carries ``org_id``, ``created_by`` and ``ownership_source``.
The owner is written when the graph is first inserted and never changed by a
later write of the same id. Graphs stored before these columns existed are
marked ``unknown`` with a NULL ``org_id``; a NULL ``org_id`` is visible to no
org.
"""

from __future__ import annotations

import builtins
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from aragora.canvas.stages import PipelineStage
from aragora.pipeline.universal_node import (
    UniversalEdge,
    UniversalGraph,
    UniversalNode,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR = os.environ.get("ARAGORA_DATA_DIR", str(Path.home() / ".aragora"))
_DEFAULT_DB_PATH = os.path.join(_DEFAULT_DB_DIR, "pipeline_graphs.db")
_STAGE_SORT_ORDER: dict[PipelineStage, int] = {
    PipelineStage.IDEAS: 0,
    PipelineStage.PRINCIPLES: 1,
    PipelineStage.GOALS: 2,
    PipelineStage.ACTIONS: 3,
    PipelineStage.ORCHESTRATION: 4,
}

OWNERSHIP_CREATED = "created"
OWNERSHIP_UNKNOWN = "unknown"


def _get_db_path() -> str:
    """Resolve the graph store database path."""
    try:
        from aragora.config import resolve_db_path

        return resolve_db_path("pipeline_graphs.db")
    except ImportError:
        return _DEFAULT_DB_PATH


class GraphStore:
    """SQLite-backed store for UniversalGraph objects.

    Thread-safe via WAL mode. Each method creates its own connection.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _get_db_path()
        self._ensure_dir()
        self._ensure_tables()

    def _ensure_dir(self) -> None:
        parent = Path(self._db_path).parent
        parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS graphs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id TEXT,
                    workspace_id TEXT,
                    edges_json TEXT DEFAULT '[]',
                    transitions_json TEXT DEFAULT '[]',
                    metadata_json TEXT DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS nodes (
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
                    execution_status TEXT,
                    confidence REAL DEFAULT 0,
                    data_json TEXT DEFAULT '{}',
                    style_json TEXT DEFAULT '{}',
                    metadata_json TEXT DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (graph_id) REFERENCES graphs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_nodes_graph_stage
                    ON nodes(graph_id, stage);
                CREATE INDEX IF NOT EXISTS idx_nodes_subtype
                    ON nodes(node_subtype);
                CREATE INDEX IF NOT EXISTS idx_nodes_content_hash
                    ON nodes(content_hash);
            """)
            node_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(nodes)").fetchall()
            }
            if "execution_status" not in node_columns:
                conn.execute("ALTER TABLE nodes ADD COLUMN execution_status TEXT")
            graph_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(graphs)").fetchall()
            }
            if "ownership_source" not in graph_columns:
                for column in ("org_id", "created_by", "ownership_source"):
                    if column not in graph_columns:
                        conn.execute(f"ALTER TABLE graphs ADD COLUMN {column} TEXT")
                conn.execute(
                    "UPDATE graphs SET ownership_source = ? WHERE org_id IS NULL",
                    (OWNERSHIP_UNKNOWN,),
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_graphs_org_updated ON graphs(org_id, updated_at)"
            )
            conn.commit()
        finally:
            conn.close()

    # -- CRUD ---------------------------------------------------------------

    def create(
        self,
        graph: UniversalGraph,
        *,
        org_id: str | None = None,
        created_by: str | None = None,
    ) -> str:
        """Insert or replace a graph snapshot. Returns graph ID.

        ``org_id`` and ``created_by`` are recorded only when the graph is first
        inserted; replacing an existing graph keeps its owner.
        """
        conn = self._connect()
        try:
            self._upsert_graph(conn, graph, org_id=org_id, created_by=created_by)
            conn.execute("DELETE FROM nodes WHERE graph_id = ?", (graph.id,))
            for node in graph.nodes.values():
                self._insert_node(conn, graph.id, node)
            conn.commit()
            logger.info("Created graph %s with %d nodes", graph.id, len(graph.nodes))
            return graph.id
        finally:
            conn.close()

    def get(self, graph_id: str) -> UniversalGraph | None:
        """Retrieve a graph by ID, including all nodes."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM graphs WHERE id = ?", (graph_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_graph(conn, row)
        finally:
            conn.close()

    def get_owner_org(self, graph_id: str) -> str | None:
        """The org that owns the graph, or None if it is missing or has no owner."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT org_id FROM graphs WHERE id = ?", (graph_id,)).fetchone()
        finally:
            conn.close()
        if row is None or not isinstance(row["org_id"], str) or not row["org_id"]:
            return None
        return str(row["org_id"])

    def node_graph_id(self, node_id: str) -> str | None:
        """The id of the graph that holds ``node_id``, or None if no graph does."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT graph_id FROM nodes WHERE id = ?", (node_id,)).fetchone()
        finally:
            conn.close()
        return str(row["graph_id"]) if row is not None else None

    def get_dag_snapshot(self, graph_id: str) -> Any | None:
        """Retrieve a normalized DAG snapshot for visualization."""
        graph = self.get(graph_id)
        if graph is None:
            return None
        return graph.to_dag_snapshot()

    def list(
        self,
        owner_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 50,
        *,
        org_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List graph summaries (without loading all nodes).

        ``org_id`` limits the list to graphs owned by that org.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if org_id is not None:
            clauses.append("g.org_id = ?")
            params.append(org_id)
        if owner_id is not None:
            clauses.append("owner_id = ?")
            params.append(owner_id)
        if workspace_id is not None:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"""SELECT g.id, g.name, g.owner_id, g.workspace_id,
                           g.created_at, g.updated_at,
                           COUNT(n.id) AS node_count
                    FROM graphs g
                    LEFT JOIN nodes n ON n.graph_id = g.id
                    {where}
                    GROUP BY g.id
                    ORDER BY g.updated_at DESC
                    LIMIT ?"""  # noqa: S608 -- internal query construction
        params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "owner_id": r["owner_id"],
                    "workspace_id": r["workspace_id"],
                    "node_count": r["node_count"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def update(self, graph: UniversalGraph) -> None:
        """Persist a full graph snapshot, including node mutations."""
        conn = self._connect()
        try:
            self._upsert_graph(conn, graph)
            conn.execute("DELETE FROM nodes WHERE graph_id = ?", (graph.id,))
            for node in graph.nodes.values():
                self._insert_node(conn, graph.id, node)
            conn.commit()
        finally:
            conn.close()

    def delete(self, graph_id: str) -> bool:
        """Delete a graph and all its nodes. Returns True if found."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM nodes WHERE graph_id = ?", (graph_id,))
            cursor = conn.execute("DELETE FROM graphs WHERE id = ?", (graph_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # -- Node operations ----------------------------------------------------

    def add_node(self, graph_id: str, node: UniversalNode) -> None:
        """Add a single node to an existing graph.

        Raises ValueError when ``node.id`` already belongs to another graph:
        node ids are unique across graphs, so writing it would move that node.
        """
        conn = self._connect()
        try:
            row = conn.execute("SELECT graph_id FROM nodes WHERE id = ?", (node.id,)).fetchone()
            if row is not None and row["graph_id"] != graph_id:
                raise ValueError("Node id is already in use")
            self._insert_node(conn, graph_id, node)
            conn.commit()
        finally:
            conn.close()

    def remove_node(self, graph_id: str, node_id: str) -> None:
        """Remove a node from a graph (also cleans edges referencing it)."""
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM nodes WHERE id = ? AND graph_id = ?",
                (node_id, graph_id),
            )
            # Clean edges from the graph's edges_json
            row = conn.execute("SELECT edges_json FROM graphs WHERE id = ?", (graph_id,)).fetchone()
            if row and row["edges_json"]:
                edges = json.loads(row["edges_json"])
                edges = [
                    e
                    for e in edges
                    if e.get("source_id") != node_id and e.get("target_id") != node_id
                ]
                conn.execute(
                    "UPDATE graphs SET edges_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(edges), __import__("time").time(), graph_id),
                )
            conn.commit()
        finally:
            conn.close()

    def query_nodes(
        self,
        graph_id: str,
        stage: PipelineStage | None = None,
        subtype: str | None = None,
    ) -> builtins.list[UniversalNode]:
        """Query nodes in a graph with optional filters."""
        clauses = ["graph_id = ?"]
        params: list[Any] = [graph_id]
        if stage is not None:
            clauses.append("stage = ?")
            params.append(stage.value)
        if subtype is not None:
            clauses.append("node_subtype = ?")
            params.append(subtype)

        where = " AND ".join(clauses)
        conn = self._connect()
        try:
            rows = conn.execute(f"SELECT * FROM nodes WHERE {where}", params).fetchall()  # noqa: S608 -- internal query construction
            return [self._row_to_node(r) for r in rows]
        finally:
            conn.close()

    def get_provenance_chain(self, graph_id: str, node_id: str) -> builtins.list[UniversalNode]:
        """Walk parent_ids recursively to build a provenance chain."""
        conn = self._connect()
        try:
            # Load all nodes for this graph into memory for traversal
            rows = conn.execute("SELECT * FROM nodes WHERE graph_id = ?", (graph_id,)).fetchall()
            node_map: dict[str, UniversalNode] = {}
            for r in rows:
                n = self._row_to_node(r)
                node_map[n.id] = n

            # Walk the chain
            visited: set[str] = set()
            chain: list[UniversalNode] = []
            self._walk_chain(node_id, node_map, visited, chain)
            return chain
        finally:
            conn.close()

    def get_downstream_chain(self, graph_id: str, node_id: str) -> builtins.list[UniversalNode]:
        """Walk child relationships recursively to build a downstream chain."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM nodes WHERE graph_id = ?", (graph_id,)).fetchall()
            node_map: dict[str, UniversalNode] = {}
            for row in rows:
                node = self._row_to_node(row)
                node_map[node.id] = node

            visited: set[str] = set()
            chain: list[UniversalNode] = []
            self._walk_downstream_chain(node_id, node_map, visited, chain)
            return chain
        finally:
            conn.close()

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _upsert_graph(
        conn: sqlite3.Connection,
        graph: UniversalGraph,
        *,
        org_id: str | None = None,
        created_by: str | None = None,
    ) -> None:
        owner_org = org_id if isinstance(org_id, str) and org_id else None
        conn.execute(
            """
            INSERT INTO graphs
                (id, name, owner_id, workspace_id, edges_json,
                 transitions_json, metadata_json, created_at, updated_at,
                 org_id, created_by, ownership_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                owner_id=excluded.owner_id,
                workspace_id=excluded.workspace_id,
                edges_json=excluded.edges_json,
                transitions_json=excluded.transitions_json,
                metadata_json=excluded.metadata_json,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at
            """,
            (
                graph.id,
                graph.name,
                graph.owner_id,
                graph.workspace_id,
                json.dumps([e.to_dict() for e in graph.edges.values()]),
                json.dumps([t.to_dict() for t in graph.transitions]),
                json.dumps(graph.metadata),
                graph.created_at,
                graph.updated_at,
                owner_org,
                created_by if owner_org else None,
                OWNERSHIP_CREATED if owner_org else None,
            ),
        )

    def _insert_node(self, conn: sqlite3.Connection, graph_id: str, node: UniversalNode) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO nodes
               (id, graph_id, stage, node_subtype, label, description,
                position_x, position_y, width, height,
                content_hash, previous_hash, parent_ids_json, source_stage,
                status, execution_status, confidence, data_json, style_json, metadata_json,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                node.id,
                graph_id,
                node.stage.value,
                node.node_subtype,
                node.label,
                node.description,
                node.position_x,
                node.position_y,
                node.width,
                node.height,
                node.content_hash,
                node.previous_hash,
                json.dumps(node.parent_ids),
                node.source_stage.value if node.source_stage else None,
                node.status,
                node.execution_status,
                node.confidence,
                json.dumps(node.data),
                json.dumps(node.style),
                json.dumps(node.metadata),
                node.created_at,
                node.updated_at,
            ),
        )

    def _row_to_graph(self, conn: sqlite3.Connection, row: sqlite3.Row) -> UniversalGraph:
        graph = UniversalGraph(
            id=row["id"],
            name=row["name"],
            owner_id=row["owner_id"],
            workspace_id=row["workspace_id"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

        # Load edges
        for ed in json.loads(row["edges_json"] or "[]"):
            edge = UniversalEdge.from_dict(ed)
            graph.edges[edge.id] = edge

        # Load transitions
        for td in json.loads(row["transitions_json"] or "[]"):
            from aragora.canvas.stages import ProvenanceLink, StageTransition

            graph.transitions.append(
                StageTransition(
                    id=td["id"],
                    from_stage=PipelineStage(td["from_stage"]),
                    to_stage=PipelineStage(td["to_stage"]),
                    provenance=[
                        ProvenanceLink(
                            source_node_id=p["source_node_id"],
                            source_stage=PipelineStage(p["source_stage"]),
                            target_node_id=p["target_node_id"],
                            target_stage=PipelineStage(p["target_stage"]),
                            content_hash=p["content_hash"],
                            timestamp=p.get("timestamp", 0),
                            method=p.get("method", ""),
                        )
                        for p in td.get("provenance", [])
                    ],
                    status=td.get("status", "pending"),
                    confidence=td.get("confidence", 0),
                    ai_rationale=td.get("ai_rationale", ""),
                    human_notes=td.get("human_notes", ""),
                    created_at=td.get("created_at", 0),
                    reviewed_at=td.get("reviewed_at"),
                )
            )

        # Load nodes
        node_rows = conn.execute("SELECT * FROM nodes WHERE graph_id = ?", (graph.id,)).fetchall()
        for nr in node_rows:
            node = self._row_to_node(nr)
            graph.nodes[node.id] = node

        return graph

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> UniversalNode:
        source_stage_raw = row["source_stage"]
        return UniversalNode(
            id=row["id"],
            stage=PipelineStage(row["stage"]),
            node_subtype=row["node_subtype"],
            label=row["label"],
            description=row["description"] or "",
            position_x=row["position_x"],
            position_y=row["position_y"],
            width=row["width"],
            height=row["height"],
            content_hash=row["content_hash"],
            previous_hash=row["previous_hash"],
            parent_ids=json.loads(row["parent_ids_json"] or "[]"),
            source_stage=PipelineStage(source_stage_raw) if source_stage_raw else None,
            status=row["status"],
            execution_status=row["execution_status"],
            confidence=row["confidence"],
            data=json.loads(row["data_json"] or "{}"),
            style=json.loads(row["style_json"] or "{}"),
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _walk_chain(
        node_id: str,
        node_map: dict[str, UniversalNode],
        visited: set[str],
        chain: builtins.list[UniversalNode],
    ) -> None:
        if node_id in visited or node_id not in node_map:
            return
        visited.add(node_id)
        node = node_map[node_id]
        chain.append(node)
        for parent_id in node.parent_ids:
            GraphStore._walk_chain(parent_id, node_map, visited, chain)

    @staticmethod
    def _walk_downstream_chain(
        node_id: str,
        node_map: dict[str, UniversalNode],
        visited: set[str],
        chain: builtins.list[UniversalNode],
    ) -> None:
        if node_id in visited or node_id not in node_map:
            return
        visited.add(node_id)
        node = node_map[node_id]
        chain.append(node)
        children = [
            candidate
            for candidate in node_map.values()
            if node_id in candidate.parent_ids and candidate.id not in visited
        ]
        children.sort(
            key=lambda candidate: (
                _STAGE_SORT_ORDER.get(candidate.stage, 999),
                candidate.created_at,
                candidate.id,
            )
        )
        for child in children:
            GraphStore._walk_downstream_chain(child.id, node_map, visited, chain)


# Module-level singleton
_store: GraphStore | None = None


def get_graph_store() -> GraphStore:
    """Get or create the module-level GraphStore singleton."""
    global _store
    if _store is None:
        _store = GraphStore()
    return _store


__all__ = ["GraphStore", "get_graph_store"]
