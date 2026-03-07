"""
SQLite-backed store for canvas pipeline results.

Persists pipeline state (ideas, goals, actions, orchestration stages)
so that pipelines survive server restarts and can be queried historically.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from aragora.storage.base_store import SQLiteStore
from aragora.storage.schema import SchemaManager
from aragora.storage.schema import safe_add_column

logger = logging.getLogger(__name__)


class PipelineResultStore(SQLiteStore):
    """Persistent storage for idea-to-execution pipeline results."""

    SCHEMA_NAME = "pipeline_results"
    SCHEMA_VERSION = 2

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS pipeline_results (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            stage_status_json TEXT DEFAULT '{}',
            ideas_json TEXT,
            goals_json TEXT,
            actions_json TEXT,
            orchestration_json TEXT,
            transitions_json TEXT DEFAULT '[]',
            provenance_count INTEGER DEFAULT 0,
            integrity_hash TEXT,
            receipt_json TEXT,
            execution_json TEXT,
            duration REAL DEFAULT 0.0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pipeline_status
            ON pipeline_results(status);
        CREATE INDEX IF NOT EXISTS idx_pipeline_created
            ON pipeline_results(created_at DESC);
    """

    def register_migrations(self, manager: SchemaManager) -> None:
        """Register schema migrations."""
        manager.register_migration(
            from_version=1,
            to_version=2,
            function=lambda conn: safe_add_column(
                conn,
                "pipeline_results",
                "execution_json",
                "TEXT",
            ),
            description="Persist canonical execution metadata",
        )

    def save(self, pipeline_id: str, result_dict: dict[str, Any]) -> None:
        """Save or update a pipeline result.

        Args:
            pipeline_id: Unique pipeline identifier
            result_dict: PipelineResult.to_dict() output
        """
        now = time.time()
        stage_status = result_dict.get("stage_status", {})

        # Determine overall status from stage statuses
        statuses = set(stage_status.values())
        if all(s == "complete" for s in statuses):
            status = "complete"
        elif "failed" in statuses:
            status = "failed"
        elif any(s == "complete" for s in statuses):
            status = "in_progress"
        else:
            status = "pending"

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO pipeline_results (
                    id, status, stage_status_json,
                    ideas_json, goals_json, actions_json, orchestration_json,
                    transitions_json, provenance_count, integrity_hash,
                    receipt_json, execution_json, duration, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    stage_status_json = excluded.stage_status_json,
                    ideas_json = excluded.ideas_json,
                    goals_json = excluded.goals_json,
                    actions_json = excluded.actions_json,
                    orchestration_json = excluded.orchestration_json,
                    transitions_json = excluded.transitions_json,
                    provenance_count = excluded.provenance_count,
                    integrity_hash = excluded.integrity_hash,
                    receipt_json = excluded.receipt_json,
                    execution_json = excluded.execution_json,
                    duration = excluded.duration,
                    updated_at = excluded.updated_at
                """,
                (
                    pipeline_id,
                    status,
                    json.dumps(stage_status),
                    json.dumps(result_dict.get("ideas")) if result_dict.get("ideas") else None,
                    json.dumps(result_dict.get("goals")) if result_dict.get("goals") else None,
                    json.dumps(result_dict.get("actions")) if result_dict.get("actions") else None,
                    json.dumps(result_dict.get("orchestration"))
                    if result_dict.get("orchestration")
                    else None,
                    json.dumps(result_dict.get("transitions", [])),
                    result_dict.get("provenance_count", 0),
                    result_dict.get("integrity_hash", ""),
                    json.dumps(result_dict.get("receipt")) if result_dict.get("receipt") else None,
                    json.dumps(result_dict.get("execution"))
                    if result_dict.get("execution")
                    else None,
                    result_dict.get("duration", 0.0),
                    now,
                    now,
                ),
            )

    def get(self, pipeline_id: str) -> dict[str, Any] | None:
        """Get a pipeline result by ID.

        Returns:
            Pipeline result dict or None if not found
        """
        with self.connection() as conn:
            conn.row_factory = _dict_factory
            row = conn.execute(
                "SELECT * FROM pipeline_results WHERE id = ?",
                (pipeline_id,),
            ).fetchone()

        if not row:
            return None
        return _deserialize_row(row)

    def list_pipelines(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List pipeline results with optional status filter.

        Returns summary info (not full stage data) for efficiency.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        with self.connection() as conn:
            conn.row_factory = _dict_factory
            rows = conn.execute(
                f"""
                SELECT id, status, stage_status_json, provenance_count,
                       integrity_hash, duration, created_at, updated_at
                FROM pipeline_results{where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,  # noqa: S608 -- internal query construction
                params,
            ).fetchall()

        results = []
        for row in rows:
            row["stage_status"] = _parse_json(row.pop("stage_status_json", "{}"))
            results.append(row)
        return results

    def delete(self, pipeline_id: str) -> bool:
        """Delete a pipeline result.

        Returns:
            True if deleted, False if not found
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM pipeline_results WHERE id = ?",
                (pipeline_id,),
            )
            return cursor.rowcount > 0

    def count(
        self,
        table: str = "pipeline_results",
        where: str = "",
        params: tuple[Any, ...] = (),
        *,
        status: str | None = None,
    ) -> int:
        """Count pipeline results with optional status filter.

        Extends the base ``SQLiteStore.count`` with a convenience *status*
        keyword argument.  When *status* is supplied it overrides *where* /
        *params* with a ``status = ?`` filter.

        Args:
            table: Table name (defaults to ``pipeline_results``).
            where: Optional WHERE clause (forwarded to base).
            params: Parameter values for WHERE clause placeholders.
            status: Shorthand -- filter by pipeline status column.
        """
        if status:
            where = "status = ?"
            params = (status,)
        return super().count(table, where, params)


# =============================================================================
# Helpers
# =============================================================================


def _dict_factory(cursor: Any, row: Any) -> dict[str, Any]:
    """SQLite row factory that returns dicts."""
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def _parse_json(value: str | None) -> Any:
    """Parse a JSON string, returning empty dict/list on failure."""
    if not value:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}


def _deserialize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Deserialize JSON columns from a pipeline result row."""
    result: dict[str, Any] = {
        "pipeline_id": row["id"],
        "status": row["status"],
        "stage_status": _parse_json(row.get("stage_status_json")),
        "ideas": _parse_json(row.get("ideas_json")),
        "goals": _parse_json(row.get("goals_json")),
        "actions": _parse_json(row.get("actions_json")),
        "orchestration": _parse_json(row.get("orchestration_json")),
        "transitions": _parse_json(row.get("transitions_json")) or [],
        "provenance_count": row.get("provenance_count", 0),
        "integrity_hash": row.get("integrity_hash", ""),
        "duration": row.get("duration", 0.0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    receipt_json = row.get("receipt_json")
    if receipt_json:
        result["receipt"] = _parse_json(receipt_json)
    execution_json = row.get("execution_json")
    if execution_json:
        result["execution"] = _parse_json(execution_json)
    return result


# =============================================================================
# Singleton
# =============================================================================

_pipeline_store: PipelineResultStore | None = None


def get_pipeline_store() -> PipelineResultStore:
    """Get the singleton PipelineResultStore instance."""
    global _pipeline_store
    if _pipeline_store is None:
        _pipeline_store = PipelineResultStore("pipeline_results.db")
    return _pipeline_store
