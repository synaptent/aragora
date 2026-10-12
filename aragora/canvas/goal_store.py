"""
SQLite store for Goal Canvas metadata.

Stores canvas-level metadata (id, name, owner, workspace, description, source_canvas_id).
Node and edge data is delegated to the CanvasStateManager for in-memory
persistence, keeping this store thin.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aragora.storage.base_store import SQLiteStore

logger = logging.getLogger(__name__)


class GoalCanvasStore(SQLiteStore):
    """SQLite-backed store for goal canvas metadata."""

    SCHEMA_NAME = "goal_canvas"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS goal_canvases (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT 'Untitled Goals',
            owner_id TEXT,
            workspace_id TEXT,
            description TEXT DEFAULT '',
            source_canvas_id TEXT,
            metadata TEXT DEFAULT '{}',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_goal_canvases_owner
            ON goal_canvases(owner_id);
        CREATE INDEX IF NOT EXISTS idx_goal_canvases_workspace
            ON goal_canvases(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_goal_canvases_source
            ON goal_canvases(source_canvas_id);
    """

    def save_canvas(
        self,
        canvas_id: str,
        name: str,
        owner_id: str | None = None,
        workspace_id: str | None = None,
        description: str = "",
        source_canvas_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save or update a goal canvas."""
        meta_json = json.dumps(metadata or {})
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO goal_canvases
                   (id, name, owner_id, workspace_id, description, source_canvas_id, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       name = excluded.name,
                       owner_id = excluded.owner_id,
                       workspace_id = excluded.workspace_id,
                       description = excluded.description,
                       source_canvas_id = excluded.source_canvas_id,
                       metadata = excluded.metadata,
                       updated_at = CURRENT_TIMESTAMP""",
                (canvas_id, name, owner_id, workspace_id, description, source_canvas_id, meta_json),
            )
        return self.load_canvas(canvas_id) or {}

    def load_canvas(self, canvas_id: str) -> dict[str, Any] | None:
        """Load a goal canvas by ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM goal_canvases WHERE id = ?",
                (canvas_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def list_canvases(
        self,
        workspace_id: str | None = None,
        owner_id: str | None = None,
        source_canvas_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List goal canvases with optional filtering."""
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
                f"SELECT * FROM goal_canvases{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete_canvas(self, canvas_id: str) -> bool:
        """Delete a goal canvas. Returns True if deleted."""
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM goal_canvases WHERE id = ?",
                (canvas_id,),
            )
        return cursor.rowcount > 0

    def update_canvas(
        self,
        canvas_id: str,
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Update specific fields of a goal canvas."""
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

        if not updates:
            return self.load_canvas(canvas_id)

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(canvas_id)

        with self.connection() as conn:
            conn.execute(
                f"UPDATE goal_canvases SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        return self.load_canvas(canvas_id)

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a sqlite3.Row to dict."""
        d = dict(row)
        if "metadata" in d and isinstance(d["metadata"], str):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
        return d


# Singleton
_goal_canvas_store: GoalCanvasStore | None = None


def get_goal_canvas_store() -> GoalCanvasStore:
    """Get or create the global GoalCanvasStore."""
    global _goal_canvas_store
    if _goal_canvas_store is None:
        _goal_canvas_store = GoalCanvasStore("goal_canvas.db")
    return _goal_canvas_store


__all__ = ["GoalCanvasStore", "get_goal_canvas_store"]
