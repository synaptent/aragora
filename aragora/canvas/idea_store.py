"""
SQLite store for Idea Canvas metadata.

Stores canvas-level metadata (id, name, owner, workspace, description).
Node and edge data is delegated to the IdeaCanvasAdapter for KnowledgeMound
persistence, keeping this store thin.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aragora.storage.base_store import SQLiteStore

logger = logging.getLogger(__name__)


class IdeaCanvasStore(SQLiteStore):
    """SQLite-backed store for idea canvas metadata."""

    SCHEMA_NAME = "idea_canvas"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS idea_canvases (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT 'Untitled Ideas',
            owner_id TEXT,
            workspace_id TEXT,
            description TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_idea_canvases_owner
            ON idea_canvases(owner_id);
        CREATE INDEX IF NOT EXISTS idx_idea_canvases_workspace
            ON idea_canvases(workspace_id);
    """

    def save_canvas(
        self,
        canvas_id: str,
        name: str,
        owner_id: str | None = None,
        workspace_id: str | None = None,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save or update an idea canvas."""
        meta_json = json.dumps(metadata or {})
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO idea_canvases
                   (id, name, owner_id, workspace_id, description, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       name = excluded.name,
                       owner_id = excluded.owner_id,
                       workspace_id = excluded.workspace_id,
                       description = excluded.description,
                       metadata = excluded.metadata,
                       updated_at = CURRENT_TIMESTAMP""",
                (canvas_id, name, owner_id, workspace_id, description, meta_json),
            )
        return self.load_canvas(canvas_id) or {}

    def load_canvas(self, canvas_id: str) -> dict[str, Any] | None:
        """Load an idea canvas by ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM idea_canvases WHERE id = ?",
                (canvas_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def list_canvases(
        self,
        workspace_id: str | None = None,
        owner_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List idea canvases with optional filtering."""
        conditions: list[str] = []
        params: list[Any] = []

        if workspace_id:
            conditions.append("workspace_id = ?")
            params.append(workspace_id)
        if owner_id:
            conditions.append("owner_id = ?")
            params.append(owner_id)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM idea_canvases{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete_canvas(self, canvas_id: str) -> bool:
        """Delete an idea canvas. Returns True if deleted."""
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM idea_canvases WHERE id = ?",
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
        """Update specific fields of an idea canvas."""
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
                f"UPDATE idea_canvases SET {', '.join(updates)} WHERE id = ?",
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
_idea_canvas_store: IdeaCanvasStore | None = None


def get_idea_canvas_store() -> IdeaCanvasStore:
    """Get or create the global IdeaCanvasStore."""
    global _idea_canvas_store
    if _idea_canvas_store is None:
        _idea_canvas_store = IdeaCanvasStore("idea_canvas.db")
    return _idea_canvas_store


__all__ = ["IdeaCanvasStore", "get_idea_canvas_store"]
