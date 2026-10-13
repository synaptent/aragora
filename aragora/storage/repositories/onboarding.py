"""
OnboardingRepository - Persistence for onboarding flow state.

Provides persistent storage for user onboarding flows, replacing the
in-memory dict approach with SQLite-backed persistence.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from contextlib import AbstractContextManager
from collections.abc import Callable

from aragora.config import resolve_db_path
from aragora.persistence.db_config import DatabaseType

logger = logging.getLogger(__name__)


class OnboardingRepository:
    """
    Repository for onboarding flow persistence.

    Stores onboarding state across sessions so users can resume
    their onboarding flow if interrupted.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        transaction_fn: Callable[[], AbstractContextManager[sqlite3.Cursor]] | None = None,
    ) -> None:
        """
        Initialize the onboarding repository.

        Args:
            db_path: Path to SQLite database file. If None, uses default location.
            transaction_fn: Optional transaction function for shared db connections.
        """
        self._transaction = transaction_fn
        if db_path is None:
            self._db_path = self._get_default_db_path()
        else:
            self._db_path = Path(resolve_db_path(db_path))
        self._init_schema()

    def _get_default_db_path(self) -> Path:
        """Get default database path."""
        from aragora.persistence.db_config import get_db_path

        return get_db_path(DatabaseType.ONBOARDING)

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS onboarding_flows (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    org_id TEXT,
                    current_step TEXT NOT NULL,
                    completed_steps TEXT NOT NULL,
                    use_case TEXT,
                    selected_template TEXT,
                    first_debate_id TEXT,
                    quick_start_profile TEXT,
                    metadata TEXT,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_onboarding_user_org
                ON onboarding_flows(user_id, org_id)
            """)
            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _flow_key(self, user_id: str, org_id: str | None) -> str:
        """Generate flow key for lookup."""
        return f"{user_id}:{org_id or 'personal'}"

    def create_flow(
        self,
        user_id: str,
        org_id: str | None,
        current_step: str,
        use_case: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Create a new onboarding flow.

        Args:
            user_id: User identifier
            org_id: Organization identifier (None for personal)
            current_step: Initial step name
            use_case: Selected use case
            metadata: Additional flow metadata

        Returns:
            Flow ID
        """
        import secrets

        flow_id = secrets.token_urlsafe(16)
        now = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO onboarding_flows (
                    id, user_id, org_id, current_step, completed_steps,
                    use_case, metadata, started_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    flow_id,
                    user_id,
                    org_id,
                    current_step,
                    json.dumps([]),
                    use_case,
                    json.dumps(metadata or {}),
                    now,
                    now,
                ),
            )
            conn.commit()

        logger.debug("Created onboarding flow %s for user %s", flow_id, user_id)
        return flow_id

    def get_flow(self, user_id: str, org_id: str | None) -> dict[str, Any] | None:
        """
        Get onboarding flow for user/org.

        Args:
            user_id: User identifier
            org_id: Organization identifier

        Returns:
            Flow dict if found, None otherwise
        """
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM onboarding_flows
                WHERE user_id = ? AND (org_id = ? OR (org_id IS NULL AND ? IS NULL))
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (user_id, org_id, org_id),
            ).fetchone()

        if not row:
            return None

        return self._row_to_flow(row)

    def get_flow_by_id(self, flow_id: str) -> dict[str, Any] | None:
        """
        Get onboarding flow by ID.

        Args:
            flow_id: Flow identifier

        Returns:
            Flow dict if found, None otherwise
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM onboarding_flows WHERE id = ?",
                (flow_id,),
            ).fetchone()

        if not row:
            return None

        return self._row_to_flow(row)

    def update_flow(
        self,
        flow_id: str,
        updates: dict[str, Any],
    ) -> bool:
        """
        Update an existing onboarding flow.

        Args:
            flow_id: Flow identifier
            updates: Dict of field -> value updates

        Returns:
            True if updated, False if flow not found
        """
        allowed_fields = {
            "current_step",
            "completed_steps",
            "use_case",
            "selected_template",
            "first_debate_id",
            "quick_start_profile",
            "metadata",
            "completed_at",
        }

        # Filter to allowed fields
        filtered = {k: v for k, v in updates.items() if k in allowed_fields}
        if not filtered:
            return False

        # Serialize lists and dicts
        for key in ("completed_steps", "metadata"):
            if key in filtered and not isinstance(filtered[key], str):
                filtered[key] = json.dumps(filtered[key])

        # Build SET clause
        set_parts = [f"{k} = ?" for k in filtered.keys()]
        set_parts.append("updated_at = ?")
        values = list(filtered.values())
        values.append(datetime.now(timezone.utc).isoformat())
        values.append(flow_id)

        with self._get_connection() as conn:
            cursor = conn.execute(
                # dynamic clause from internal state
                f"UPDATE onboarding_flows SET {', '.join(set_parts)} WHERE id = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount > 0

    def complete_flow(self, flow_id: str) -> bool:
        """
        Mark a flow as completed.

        Args:
            flow_id: Flow identifier

        Returns:
            True if updated
        """
        return self.update_flow(
            flow_id,
            {"completed_at": datetime.now(timezone.utc).isoformat()},
        )

    def _row_to_flow(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert database row to flow dict."""
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "org_id": row["org_id"],
            "current_step": row["current_step"],
            "completed_steps": json.loads(row["completed_steps"] or "[]"),
            "use_case": row["use_case"],
            "selected_template": row["selected_template"],
            "first_debate_id": row["first_debate_id"],
            "quick_start_profile": row["quick_start_profile"],
            "metadata": json.loads(row["metadata"] or "{}"),
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
        }

    def get_analytics(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Get onboarding analytics.

        Args:
            start_date: Optional start date filter (ISO format)
            end_date: Optional end date filter (ISO format)

        Returns:
            Analytics dict with counts and metrics
        """
        where_parts = []
        params: list = []

        if start_date:
            where_parts.append("started_at >= ?")
            params.append(start_date)
        if end_date:
            where_parts.append("started_at <= ?")
            params.append(end_date)

        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        with self._get_connection() as conn:
            # Total flows
            total = conn.execute(
                # dynamic clause from internal state
                f"SELECT COUNT(*) FROM onboarding_flows {where_clause}",
                params,
            ).fetchone()[0]

            # Completed flows
            completed_where = where_clause
            if completed_where:
                completed_where += " AND completed_at IS NOT NULL"
            else:
                completed_where = "WHERE completed_at IS NOT NULL"

            completed = conn.execute(
                # internal query construction
                f"SELECT COUNT(*) FROM onboarding_flows {completed_where}",
                params,
            ).fetchone()[0]

            # Step distribution
            step_counts = {}
            rows = conn.execute(
                f"""
                SELECT current_step, COUNT(*) as count
                FROM onboarding_flows {where_clause}
                GROUP BY current_step
                """,  # dynamic clause from internal state
                params,
            ).fetchall()
            for row in rows:
                step_counts[row["current_step"]] = row["count"]

        return {
            "total_flows": total,
            "completed_flows": completed,
            "completion_rate": (completed / total * 100) if total > 0 else 0,
            "step_distribution": step_counts,
        }


# Global repository instance
_onboarding_repo: OnboardingRepository | None = None


def get_onboarding_repository() -> OnboardingRepository:
    """Get or create the global onboarding repository."""
    global _onboarding_repo
    if _onboarding_repo is None:
        _onboarding_repo = OnboardingRepository()
    return _onboarding_repo
