"""
Database-backed Computer Use task and policy storage.

Provides persistent storage for computer use tasks and policies with
support for listing, filtering, and status tracking across restarts.

Supports both SQLite (default) and PostgreSQL (via DATABASE_URL env var).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from aragora.config import resolve_db_path
from aragora.storage.backends import (
    POSTGRESQL_AVAILABLE,
    DatabaseBackend,
    PostgreSQLBackend,
    SQLiteBackend,
)
from aragora.utils.datetime_helpers import parse_timestamp, utc_now

logger = logging.getLogger(__name__)


@dataclass
class ComputerUseTask:
    """Stored computer use task record."""

    task_id: str
    goal: str
    max_steps: int
    dry_run: bool
    status: str  # pending, running, completed, failed, cancelled
    created_at: datetime
    updated_at: datetime
    steps_json: str = "[]"
    result_json: str | None = None
    cancelled_at: datetime | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        steps: list[Any] = []
        try:
            steps = json.loads(self.steps_json) if self.steps_json else []
        except json.JSONDecodeError as e:
            logger.debug("Failed to parse JSON data: %s", e)

        result = None
        try:
            result = json.loads(self.result_json) if self.result_json else None
        except json.JSONDecodeError as e:
            logger.debug("Failed to parse JSON data: %s", e)

        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "max_steps": self.max_steps,
            "dry_run": self.dry_run,
            "status": self.status,
            "created_at": (
                self.created_at.isoformat()
                if isinstance(self.created_at, datetime)
                else self.created_at
            ),
            "updated_at": (
                self.updated_at.isoformat()
                if isinstance(self.updated_at, datetime)
                else self.updated_at
            ),
            "steps": steps,
            "result": result,
            "cancelled_at": (
                self.cancelled_at.isoformat()
                if isinstance(self.cancelled_at, datetime)
                else self.cancelled_at
            ),
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "error": self.error,
        }


@dataclass
class ComputerUsePolicy:
    """Stored computer use policy record."""

    policy_id: str
    name: str
    description: str
    allowed_actions_json: str
    blocked_domains_json: str
    created_at: datetime
    updated_at: datetime
    tenant_id: str | None = None
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        allowed_actions: list[str] = []
        blocked_domains: list[str] = []
        try:
            allowed_actions = (
                json.loads(self.allowed_actions_json) if self.allowed_actions_json else []
            )
        except json.JSONDecodeError as e:
            logger.debug("Failed to parse JSON data: %s", e)
        try:
            blocked_domains = (
                json.loads(self.blocked_domains_json) if self.blocked_domains_json else []
            )
        except json.JSONDecodeError as e:
            logger.debug("Failed to parse JSON data: %s", e)

        return {
            "id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "allowed_actions": allowed_actions,
            "blocked_domains": blocked_domains,
            "created_at": (
                self.created_at.isoformat()
                if isinstance(self.created_at, datetime)
                else self.created_at
            ),
            "is_active": self.is_active,
            "tenant_id": self.tenant_id,
        }


class ComputerUseStorage:
    """
    Persistent storage for Computer Use tasks and policies.

    Stores complete task records with support for:
    - Save/load individual tasks
    - List tasks with pagination and filters
    - Track task status across server restarts
    - Store and manage custom policies

    Supports both SQLite (default) and PostgreSQL backends.

    Usage:
        # SQLite (default)
        storage = ComputerUseStorage()

        # PostgreSQL (via environment or explicit)
        storage = ComputerUseStorage(backend="postgresql")

        # Save a task
        storage.save_task(task)

        # Get a task
        task = storage.get_task("task-abc123")

        # List recent tasks
        tasks = storage.list_tasks(limit=20)
    """

    def __init__(
        self,
        db_path: str = "aragora_computer_use.db",
        backend: str | None = None,
        database_url: str | None = None,
    ):
        """
        Initialize storage with database backend.

        Args:
            db_path: Path to SQLite database file (used when backend="sqlite").
            backend: Database backend type ("sqlite" or "postgresql").
                    If not specified, uses DATABASE_URL env var if set,
                    otherwise defaults to SQLite.
            database_url: PostgreSQL connection URL. Overrides DATABASE_URL env var.
        """
        # Determine backend type
        env_url = os.environ.get("DATABASE_URL") or os.environ.get("ARAGORA_DATABASE_URL")
        actual_url = database_url or env_url

        if backend is None:
            # Auto-detect based on URL presence
            backend = "postgresql" if actual_url else "sqlite"

        self.backend_type = backend

        # Create appropriate backend
        if backend == "postgresql":
            if not actual_url:
                raise ValueError(
                    "PostgreSQL backend requires DATABASE_URL or database_url parameter"
                )
            if not POSTGRESQL_AVAILABLE:
                raise ImportError(
                    "psycopg2 is required for PostgreSQL support. "
                    "Install with: pip install psycopg2-binary"
                )
            self._backend: DatabaseBackend = PostgreSQLBackend(actual_url)
            logger.info("ComputerUseStorage using PostgreSQL backend")
        else:
            # SQLite backend
            resolved_path = resolve_db_path(db_path)
            self.db_path = Path(resolved_path)
            self._backend = SQLiteBackend(resolved_path)
            logger.info("ComputerUseStorage using SQLite backend: %s", resolved_path)

        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        # Create tasks table
        create_tasks_sql = """
            CREATE TABLE IF NOT EXISTS computer_use_tasks (
                task_id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                max_steps INTEGER DEFAULT 10,
                dry_run INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                steps_json TEXT DEFAULT '[]',
                result_json TEXT,
                error TEXT,
                user_id TEXT,
                tenant_id TEXT,
                cancelled_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        self._backend.execute_write(create_tasks_sql)

        # Create indexes for tasks
        task_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_cu_tasks_status ON computer_use_tasks(status)",
            "CREATE INDEX IF NOT EXISTS idx_cu_tasks_created ON computer_use_tasks(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_cu_tasks_tenant ON computer_use_tasks(tenant_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_cu_tasks_user ON computer_use_tasks(user_id)",
        ]
        for idx_sql in task_indexes:
            try:
                self._backend.execute_write(idx_sql)
            except (RuntimeError, OSError) as e:  # DB index creation errors
                logger.debug("Index creation skipped: %s", e)

        # Create policies table
        create_policies_sql = """
            CREATE TABLE IF NOT EXISTS computer_use_policies (
                policy_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                allowed_actions_json TEXT DEFAULT '[]',
                blocked_domains_json TEXT DEFAULT '[]',
                is_active INTEGER DEFAULT 1,
                tenant_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        self._backend.execute_write(create_policies_sql)

        # Create indexes for policies
        policy_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_cu_policies_tenant ON computer_use_policies(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_cu_policies_active ON computer_use_policies(is_active)",
        ]
        for idx_sql in policy_indexes:
            try:
                self._backend.execute_write(idx_sql)
            except (RuntimeError, OSError) as e:  # DB index creation errors
                logger.debug("Index creation skipped: %s", e)

    # =========================================================================
    # Task Operations
    # =========================================================================

    def save_task(self, task: dict[str, Any]) -> str:
        """
        Save a computer use task to storage.

        Args:
            task: Task dictionary with task_id, goal, status, etc.

        Returns:
            The task_id of the saved task
        """
        task_id = task.get("task_id", "")
        if not task_id:
            raise ValueError("task_id is required")

        goal = task.get("goal", "")
        max_steps = task.get("max_steps", 10)
        dry_run = 1 if task.get("dry_run", False) else 0
        status = task.get("status", "pending")
        steps = task.get("steps", [])
        steps_json = json.dumps(steps) if steps else "[]"
        result = task.get("result")
        result_json = json.dumps(result) if result else None
        error = task.get("error")
        user_id = task.get("user_id")
        tenant_id = task.get("tenant_id")
        cancelled_at = task.get("cancelled_at")
        now = utc_now().isoformat()

        # Upsert logic - try insert first, then update on conflict
        sql = """
            INSERT INTO computer_use_tasks
            (task_id, goal, max_steps, dry_run, status, steps_json, result_json,
             error, user_id, tenant_id, cancelled_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                status = excluded.status,
                steps_json = excluded.steps_json,
                result_json = excluded.result_json,
                error = excluded.error,
                cancelled_at = excluded.cancelled_at,
                updated_at = excluded.updated_at
        """
        params = (
            task_id,
            goal,
            max_steps,
            dry_run,
            status,
            steps_json,
            result_json,
            error,
            user_id,
            tenant_id,
            cancelled_at,
            task.get("created_at", now),
            now,
        )
        self._backend.execute_write(sql, params)
        return task_id

    def get_task(self, task_id: str) -> ComputerUseTask | None:
        """
        Get a task by ID.

        Args:
            task_id: The task ID to look up

        Returns:
            ComputerUseTask if found, None otherwise
        """
        sql = """
            SELECT task_id, goal, max_steps, dry_run, status, steps_json,
                   result_json, error, user_id, tenant_id, cancelled_at,
                   created_at, updated_at
            FROM computer_use_tasks
            WHERE task_id = ?
        """
        rows = self._backend.execute_read(sql, (task_id,))
        if not rows:
            return None

        row = rows[0]
        return self._row_to_task(row)

    def list_tasks(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> list[ComputerUseTask]:
        """
        List tasks with optional filtering.

        Args:
            limit: Maximum number of tasks to return
            offset: Number of tasks to skip
            status: Filter by status (pending, running, completed, failed, cancelled)
            tenant_id: Filter by tenant
            user_id: Filter by user

        Returns:
            List of ComputerUseTask objects
        """
        conditions = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        sql = f"""
            SELECT task_id, goal, max_steps, dry_run, status, steps_json,
                   result_json, error, user_id, tenant_id, cancelled_at,
                   created_at, updated_at
            FROM computer_use_tasks
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """  # dynamic clause from internal state
        params.extend([limit, offset])
        rows = self._backend.execute_read(sql, tuple(params))
        return [self._row_to_task(row) for row in rows]

    def count_tasks(
        self,
        status: str | None = None,
        tenant_id: str | None = None,
    ) -> int:
        """Count tasks with optional filtering."""
        conditions = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # dynamic clause from internal state
        sql = f"SELECT COUNT(*) FROM computer_use_tasks WHERE {where_clause}"
        result = self._backend.fetch_one(sql, tuple(params))
        return result[0] if result else 0

    def update_task_status(
        self,
        task_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        steps: list[dict[str, Any]] | None = None,
    ) -> bool:
        """
        Update task status and optionally result/error.

        Args:
            task_id: Task to update
            status: New status
            result: Optional result dict
            error: Optional error message
            steps: Optional steps list

        Returns:
            True if task was found and updated
        """
        updates = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, utc_now().isoformat()]

        if result is not None:
            updates.append("result_json = ?")
            params.append(json.dumps(result))
        if error is not None:
            updates.append("error = ?")
            params.append(error)
        if steps is not None:
            updates.append("steps_json = ?")
            params.append(json.dumps(steps))
        if status == "cancelled":
            updates.append("cancelled_at = ?")
            params.append(utc_now().isoformat())

        params.append(task_id)
        # dynamic clause from internal state
        sql = f"UPDATE computer_use_tasks SET {', '.join(updates)} WHERE task_id = ?"
        self._backend.execute_write(sql, tuple(params))

        # Check if row was affected by re-fetching
        return self.get_task(task_id) is not None

    def delete_task(self, task_id: str) -> bool:
        """Delete a task by ID."""
        sql = "DELETE FROM computer_use_tasks WHERE task_id = ?"
        self._backend.execute_write(sql, (task_id,))
        return True

    def _row_to_task(self, row: dict[str, Any]) -> ComputerUseTask:
        """Convert database row to ComputerUseTask."""
        created_at = row.get("created_at")
        updated_at = row.get("updated_at")
        cancelled_at = row.get("cancelled_at")

        if isinstance(created_at, str):
            created_at = parse_timestamp(created_at)
        if isinstance(updated_at, str):
            updated_at = parse_timestamp(updated_at)
        if isinstance(cancelled_at, str):
            cancelled_at = parse_timestamp(cancelled_at)

        return ComputerUseTask(
            task_id=row.get("task_id", ""),
            goal=row.get("goal", ""),
            max_steps=row.get("max_steps", 10),
            dry_run=bool(row.get("dry_run", 0)),
            status=row.get("status", "pending"),
            steps_json=row.get("steps_json", "[]"),
            result_json=row.get("result_json"),
            error=row.get("error"),
            user_id=row.get("user_id"),
            tenant_id=row.get("tenant_id"),
            cancelled_at=cancelled_at,
            created_at=created_at or utc_now(),
            updated_at=updated_at or utc_now(),
        )

    # =========================================================================
    # Policy Operations
    # =========================================================================

    def save_policy(self, policy: dict[str, Any]) -> str:
        """
        Save a computer use policy to storage.

        Args:
            policy: Policy dictionary with policy_id, name, etc.

        Returns:
            The policy_id of the saved policy
        """
        policy_id = policy.get("policy_id", policy.get("id", ""))
        if not policy_id:
            raise ValueError("policy_id is required")

        name = policy.get("name", "")
        description = policy.get("description", "")
        allowed_actions = policy.get("allowed_actions", [])
        allowed_actions_json = json.dumps(allowed_actions)
        blocked_domains = policy.get("blocked_domains", [])
        blocked_domains_json = json.dumps(blocked_domains)
        is_active = 1 if policy.get("is_active", True) else 0
        tenant_id = policy.get("tenant_id")
        now = utc_now().isoformat()

        sql = """
            INSERT INTO computer_use_policies
            (policy_id, name, description, allowed_actions_json, blocked_domains_json,
             is_active, tenant_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(policy_id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                allowed_actions_json = excluded.allowed_actions_json,
                blocked_domains_json = excluded.blocked_domains_json,
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
        """
        params = (
            policy_id,
            name,
            description,
            allowed_actions_json,
            blocked_domains_json,
            is_active,
            tenant_id,
            policy.get("created_at", now),
            now,
        )
        self._backend.execute_write(sql, params)
        return policy_id

    def get_policy(self, policy_id: str) -> ComputerUsePolicy | None:
        """Get a policy by ID."""
        sql = """
            SELECT policy_id, name, description, allowed_actions_json,
                   blocked_domains_json, is_active, tenant_id, created_at, updated_at
            FROM computer_use_policies
            WHERE policy_id = ?
        """
        rows = self._backend.execute_read(sql, (policy_id,))
        if not rows:
            return None

        row = rows[0]
        return self._row_to_policy(row)

    def list_policies(
        self,
        tenant_id: str | None = None,
        active_only: bool = True,
    ) -> list[ComputerUsePolicy]:
        """
        List policies with optional filtering.

        Args:
            tenant_id: Filter by tenant
            active_only: Only return active policies

        Returns:
            List of ComputerUsePolicy objects
        """
        conditions = []
        params: list[Any] = []

        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)
        if active_only:
            conditions.append("is_active = 1")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        sql = f"""
            SELECT policy_id, name, description, allowed_actions_json,
                   blocked_domains_json, is_active, tenant_id, created_at, updated_at
            FROM computer_use_policies
            WHERE {where_clause}
            ORDER BY created_at DESC
        """  # dynamic clause from internal state
        rows = self._backend.execute_read(sql, tuple(params))
        return [self._row_to_policy(row) for row in rows]

    def delete_policy(self, policy_id: str) -> bool:
        """Delete a policy by ID."""
        sql = "DELETE FROM computer_use_policies WHERE policy_id = ?"
        self._backend.execute_write(sql, (policy_id,))
        return True

    def _row_to_policy(self, row: dict[str, Any]) -> ComputerUsePolicy:
        """Convert database row to ComputerUsePolicy."""
        created_at = row.get("created_at")
        updated_at = row.get("updated_at")

        if isinstance(created_at, str):
            created_at = parse_timestamp(created_at)
        if isinstance(updated_at, str):
            updated_at = parse_timestamp(updated_at)

        return ComputerUsePolicy(
            policy_id=row.get("policy_id", ""),
            name=row.get("name", ""),
            description=row.get("description", ""),
            allowed_actions_json=row.get("allowed_actions_json", "[]"),
            blocked_domains_json=row.get("blocked_domains_json", "[]"),
            is_active=bool(row.get("is_active", 1)),
            tenant_id=row.get("tenant_id"),
            created_at=created_at or utc_now(),
            updated_at=updated_at or utc_now(),
        )

    # =========================================================================
    # Action Stats (derived from tasks)
    # =========================================================================

    def get_action_stats(self, tenant_id: str | None = None) -> dict[str, dict[str, int]]:
        """
        Get aggregated action statistics from completed tasks.

        Args:
            tenant_id: Optional tenant filter

        Returns:
            Dictionary of action types to success/fail counts
        """
        conditions = ["status IN ('completed', 'failed')"]
        params: list[Any] = []

        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)

        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT steps_json
            FROM computer_use_tasks
            WHERE {where_clause}
        """  # dynamic clause from internal state
        rows = self._backend.execute_read(sql, tuple(params))

        stats: dict[str, dict[str, int]] = {
            "click": {"total": 0, "success": 0, "failed": 0},
            "type": {"total": 0, "success": 0, "failed": 0},
            "screenshot": {"total": 0, "success": 0, "failed": 0},
            "scroll": {"total": 0, "success": 0, "failed": 0},
            "key": {"total": 0, "success": 0, "failed": 0},
        }

        for row in rows:
            steps_json = row.get("steps_json", "[]")
            try:
                steps = json.loads(steps_json) if steps_json else []
            except json.JSONDecodeError:
                continue

            for step in steps:
                action = step.get("action", "").lower()
                if action in stats:
                    stats[action]["total"] += 1
                    if step.get("success"):
                        stats[action]["success"] += 1
                    else:
                        stats[action]["failed"] += 1

        return stats

    def close(self) -> None:
        """Close the database connection."""
        self._backend.close()


# Global storage instance (lazy initialized)
_storage: ComputerUseStorage | None = None


def get_computer_use_storage() -> ComputerUseStorage:
    """Get or create the global ComputerUseStorage instance."""
    global _storage
    if _storage is None:
        _storage = ComputerUseStorage()
    return _storage


__all__ = [
    "ComputerUseStorage",
    "ComputerUseTask",
    "ComputerUsePolicy",
    "get_computer_use_storage",
]
