"""
SQLite store for Action Canvas metadata and restart-safe graph snapshots.

Stores canvas-level metadata plus serialized nodes/edges so Stage 3 canvases
can be rehydrated after the in-memory CanvasStateManager is reset.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aragora.storage.base_store import SQLiteStore
from aragora.storage.schema import SchemaManager, safe_add_column

logger = logging.getLogger(__name__)


class ActionCanvasStore(SQLiteStore):
    """SQLite-backed store for action canvas metadata."""

    SCHEMA_NAME = "action_canvas"
    SCHEMA_VERSION = 2

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS action_canvases (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT 'Untitled Actions',
            owner_id TEXT,
            workspace_id TEXT,
            description TEXT DEFAULT '',
            source_canvas_id TEXT,
            metadata TEXT DEFAULT '{}',
            nodes TEXT DEFAULT '[]',
            edges TEXT DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_action_canvases_owner
            ON action_canvases(owner_id);
        CREATE INDEX IF NOT EXISTS idx_action_canvases_workspace
            ON action_canvases(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_action_canvases_source
            ON action_canvases(source_canvas_id);
    """

    def register_migrations(self, manager: SchemaManager) -> None:
        manager.register_migration(
            from_version=1,
            to_version=2,
            function=self._migrate_v1_to_v2,
            description="Persist action canvas graph snapshots",
        )

    @staticmethod
    def _migrate_v1_to_v2(conn) -> None:
        safe_add_column(conn, "action_canvases", "nodes", "TEXT", default="'[]'")
        safe_add_column(conn, "action_canvases", "edges", "TEXT", default="'[]'")

    def save_canvas(
        self,
        canvas_id: str,
        name: str,
        owner_id: str | None = None,
        workspace_id: str | None = None,
        description: str = "",
        source_canvas_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Save or update an action canvas."""
        meta_json = json.dumps(metadata or {})
        nodes_json = json.dumps(nodes or [])
        edges_json = json.dumps(edges or [])
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO action_canvases
                   (id, name, owner_id, workspace_id, description, source_canvas_id, metadata, nodes, edges)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       name = excluded.name,
                       owner_id = excluded.owner_id,
                       workspace_id = excluded.workspace_id,
                       description = excluded.description,
                       source_canvas_id = excluded.source_canvas_id,
                       metadata = excluded.metadata,
                       nodes = excluded.nodes,
                       edges = excluded.edges,
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    canvas_id,
                    name,
                    owner_id,
                    workspace_id,
                    description,
                    source_canvas_id,
                    meta_json,
                    nodes_json,
                    edges_json,
                ),
            )
        return self.load_canvas(canvas_id) or {}

    def load_canvas(self, canvas_id: str) -> dict[str, Any] | None:
        """Load an action canvas by ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM action_canvases WHERE id = ?",
                (canvas_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row, include_state=True)

    def list_canvases(
        self,
        workspace_id: str | None = None,
        owner_id: str | None = None,
        source_canvas_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List action canvases with optional filtering."""
        conditions: list[str] = []
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if owner_id:
            conditions.append("owner_id = ?")
            params.append(owner_id)
        if source_canvas_id:
            conditions.append("source_canvas_id = ?")
            params.append(source_canvas_id)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM action_canvases{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row_to_dict(r, include_state=False) for r in rows]

    def delete_canvas(self, canvas_id: str) -> bool:
        """Delete an action canvas. Returns True if deleted."""
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM action_canvases WHERE id = ?",
                (canvas_id,),
            )
        return cursor.rowcount > 0

    def update_canvas(
        self,
        canvas_id: str,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Update specific fields of an action canvas."""
        updates: list[str] = []
        params: list[Any] = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))
        if nodes is not None:
            updates.append("nodes = ?")
            params.append(json.dumps(nodes))
        if edges is not None:
            updates.append("edges = ?")
            params.append(json.dumps(edges))

        if not updates:
            return self.load_canvas(canvas_id)

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(canvas_id)

        with self.connection() as conn:
            conn.execute(
                f"UPDATE action_canvases SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        return self.load_canvas(canvas_id)

    @staticmethod
    def _row_to_dict(row: Any, include_state: bool = True) -> dict[str, Any]:
        """Convert a sqlite3.Row to dict."""
        d = dict(row)
        if "metadata" in d and isinstance(d["metadata"], str):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
        for key in ("nodes", "edges"):
            if key in d and include_state:
                if isinstance(d[key], str):
                    try:
                        value = json.loads(d[key])
                    except (json.JSONDecodeError, TypeError):
                        value = []
                else:
                    value = d[key] or []
                d[key] = value if isinstance(value, list) else []
            elif key in d:
                d.pop(key, None)
        return d


# Singleton
_action_canvas_store: ActionCanvasStore | None = None


def get_action_canvas_store() -> ActionCanvasStore:
    """Get or create the global ActionCanvasStore."""
    global _action_canvas_store
    if _action_canvas_store is None:
        _action_canvas_store = ActionCanvasStore("action_canvas.db")
    return _action_canvas_store


__all__ = ["ActionCanvasStore", "get_action_canvas_store"]
