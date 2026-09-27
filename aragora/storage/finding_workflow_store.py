"""
Finding Workflow Storage Backends.

Persistent storage for audit finding workflow state, assignments, and history.

Backends:
- InMemoryFindingWorkflowStore: For testing
- SQLiteFindingWorkflowStore: For single-instance deployments
- RedisFindingWorkflowStore: For multi-instance (with SQLite fallback)

Usage:
    from aragora.storage.finding_workflow_store import (
        get_finding_workflow_store,
        set_finding_workflow_store,
    )

    # Use default store (configured via environment)
    store = get_finding_workflow_store()
    await store.save(workflow_data_dict)
    data = await store.get("finding-123")
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from asyncpg import Pool


from aragora.config import resolve_db_path
from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)

# Global singleton
_finding_workflow_store: FindingWorkflowStoreBackend | None = None
_store_lock = threading.RLock()


@dataclass
class WorkflowDataItem:
    """
    Workflow data for a finding.

    This is a storage-friendly representation that wraps the FindingWorkflowData dict.
    """

    finding_id: str
    current_state: str = "open"
    history: list[dict[str, Any]] = field(default_factory=list)

    # Assignment
    assigned_to: str | None = None
    assigned_by: str | None = None
    assigned_at: str | None = None

    # Priority and scheduling
    priority: int = 3  # 1=highest, 5=lowest
    due_date: str | None = None

    # Linked findings
    linked_findings: list[str] = field(default_factory=list)
    parent_finding_id: str | None = None

    # Timestamps
    created_at: str = ""
    updated_at: str = ""

    # Metrics
    time_in_states: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set default timestamps if not provided."""
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "finding_id": self.finding_id,
            "current_state": self.current_state,
            "history": self.history,
            "assigned_to": self.assigned_to,
            "assigned_by": self.assigned_by,
            "assigned_at": self.assigned_at,
            "priority": self.priority,
            "due_date": self.due_date,
            "linked_findings": self.linked_findings,
            "parent_finding_id": self.parent_finding_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "time_in_states": self.time_in_states,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowDataItem:
        """Create from dictionary."""
        return cls(
            finding_id=data.get("finding_id", ""),
            current_state=data.get("current_state", "open"),
            history=data.get("history", []),
            assigned_to=data.get("assigned_to"),
            assigned_by=data.get("assigned_by"),
            assigned_at=data.get("assigned_at"),
            priority=data.get("priority", 3),
            due_date=data.get("due_date"),
            linked_findings=data.get("linked_findings", []),
            parent_finding_id=data.get("parent_finding_id"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            time_in_states=data.get("time_in_states", {}),
        )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> WorkflowDataItem:
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))


class FindingWorkflowStoreBackend(ABC):
    """Abstract base class for finding workflow storage backends."""

    @abstractmethod
    async def get(self, finding_id: str) -> dict[str, Any] | None:
        """Get workflow data for a finding."""
        pass

    @abstractmethod
    async def save(self, data: dict[str, Any]) -> None:
        """Save workflow data for a finding."""
        pass

    @abstractmethod
    async def delete(self, finding_id: str) -> bool:
        """Delete workflow data for a finding."""
        pass

    @abstractmethod
    async def list_all(self) -> list[dict[str, Any]]:
        """List all workflow data."""
        pass

    @abstractmethod
    async def list_by_assignee(self, user_id: str) -> list[dict[str, Any]]:
        """List all workflows assigned to a user."""
        pass

    @abstractmethod
    async def list_overdue(self) -> list[dict[str, Any]]:
        """List all overdue findings (past due date, not in terminal state)."""
        pass

    @abstractmethod
    async def list_by_state(self, state: str) -> list[dict[str, Any]]:
        """List all findings in a specific state."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close any resources."""
        pass


class InMemoryFindingWorkflowStore(FindingWorkflowStoreBackend):
    """
    In-memory finding workflow store for testing.

    Data is lost on restart.
    """

    def __init__(self) -> None:
        """Initialize in-memory store."""
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    async def get(self, finding_id: str) -> dict[str, Any] | None:
        """Get workflow data for a finding."""
        with self._lock:
            return self._data.get(finding_id)

    async def save(self, data: dict[str, Any]) -> None:
        """Save workflow data for a finding."""
        finding_id = data.get("finding_id")
        if not finding_id:
            raise ValueError("finding_id is required")
        with self._lock:
            self._data[finding_id] = data

    async def delete(self, finding_id: str) -> bool:
        """Delete workflow data for a finding."""
        with self._lock:
            if finding_id in self._data:
                del self._data[finding_id]
                return True
            return False

    async def list_all(self) -> list[dict[str, Any]]:
        """List all workflow data."""
        with self._lock:
            return list(self._data.values())

    async def list_by_assignee(self, user_id: str) -> list[dict[str, Any]]:
        """List all workflows assigned to a user."""
        with self._lock:
            return [wf for wf in self._data.values() if wf.get("assigned_to") == user_id]

    async def list_overdue(self) -> list[dict[str, Any]]:
        """List all overdue findings."""
        now = datetime.now(timezone.utc).isoformat()
        terminal_states = {"resolved", "false_positive", "duplicate", "accepted_risk"}
        with self._lock:
            return [
                wf
                for wf in self._data.values()
                if (
                    wf.get("due_date")
                    and cast(str, wf.get("due_date")) < now
                    and wf.get("current_state") not in terminal_states
                )
            ]

    async def list_by_state(self, state: str) -> list[dict[str, Any]]:
        """List all findings in a specific state."""
        with self._lock:
            return [wf for wf in self._data.values() if wf.get("current_state") == state]

    async def close(self) -> None:
        """No-op for in-memory store."""
        pass


class SQLiteFindingWorkflowStore(FindingWorkflowStoreBackend):
    """
    SQLite-backed finding workflow store.

    Suitable for single-instance deployments.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """
        Initialize SQLite store.

        Args:
            db_path: Path to SQLite database. Defaults to
                     $ARAGORA_DATA_DIR/finding_workflows.db
        """
        if db_path is None:
            db_path = Path("finding_workflows.db")

        self._db_path = Path(resolve_db_path(db_path))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS finding_workflows (
                        finding_id TEXT PRIMARY KEY,
                        current_state TEXT NOT NULL DEFAULT 'open',
                        assigned_to TEXT,
                        assigned_by TEXT,
                        assigned_at TEXT,
                        priority INTEGER DEFAULT 3,
                        due_date TEXT,
                        parent_finding_id TEXT,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        data_json TEXT NOT NULL
                    )
                    """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_workflow_assigned_to
                    ON finding_workflows(assigned_to)
                    """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_workflow_state
                    ON finding_workflows(current_state)
                    """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_workflow_due_date
                    ON finding_workflows(due_date)
                    """)
                conn.commit()
            finally:
                conn.close()

    async def get(self, finding_id: str) -> dict[str, Any] | None:
        """Get workflow data for a finding."""
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json FROM finding_workflows WHERE finding_id = ?",
                    (finding_id,),
                )
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0])
                return None
            finally:
                conn.close()

    async def save(self, data: dict[str, Any]) -> None:
        """Save workflow data for a finding."""
        finding_id = data.get("finding_id")
        if not finding_id:
            raise ValueError("finding_id is required")

        now = time.time()
        data_json = json.dumps(data)

        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO finding_workflows
                    (finding_id, current_state, assigned_to, assigned_by, assigned_at,
                     priority, due_date, parent_finding_id, created_at, updated_at, data_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding_id,
                        data.get("current_state", "open"),
                        data.get("assigned_to"),
                        data.get("assigned_by"),
                        data.get("assigned_at"),
                        data.get("priority", 3),
                        data.get("due_date"),
                        data.get("parent_finding_id"),
                        now,
                        now,
                        data_json,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    async def delete(self, finding_id: str) -> bool:
        """Delete workflow data for a finding."""
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM finding_workflows WHERE finding_id = ?",
                    (finding_id,),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    async def list_all(self) -> list[dict[str, Any]]:
        """List all workflow data."""
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT data_json FROM finding_workflows")
                return [json.loads(row[0]) for row in cursor.fetchall()]
            finally:
                conn.close()

    async def list_by_assignee(self, user_id: str) -> list[dict[str, Any]]:
        """List all workflows assigned to a user."""
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json FROM finding_workflows WHERE assigned_to = ?",
                    (user_id,),
                )
                return [json.loads(row[0]) for row in cursor.fetchall()]
            finally:
                conn.close()

    async def list_overdue(self) -> list[dict[str, Any]]:
        """List all overdue findings."""
        now = datetime.now(timezone.utc).isoformat()
        terminal_states = ("resolved", "false_positive", "duplicate", "accepted_risk")
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                placeholders = ",".join("?" for _ in terminal_states)
                cursor.execute(
                    f"""
                    SELECT data_json FROM finding_workflows
                    WHERE due_date IS NOT NULL
                      AND due_date < ?
                      AND current_state NOT IN ({placeholders})
                    """,  # noqa: S608 -- parameterized query
                    (now, *terminal_states),
                )
                return [json.loads(row[0]) for row in cursor.fetchall()]
            finally:
                conn.close()

    async def list_by_state(self, state: str) -> list[dict[str, Any]]:
        """List all findings in a specific state."""
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json FROM finding_workflows WHERE current_state = ?",
                    (state,),
                )
                return [json.loads(row[0]) for row in cursor.fetchall()]
            finally:
                conn.close()

    async def close(self) -> None:
        """No-op for SQLite (connections are per-operation)."""
        pass


class RedisFindingWorkflowStore(FindingWorkflowStoreBackend):
    """
    Redis-backed finding workflow store with SQLite fallback.

    For multi-instance deployments with optional horizontal scaling.
    Falls back to SQLite if Redis is unavailable.
    """

    REDIS_PREFIX = "aragora:finding_workflow:"
    REDIS_INDEX_ASSIGNEE = "aragora:finding_workflow:idx:assignee:"
    REDIS_INDEX_STATE = "aragora:finding_workflow:idx:state:"

    def __init__(
        self,
        fallback_db_path: Path | None = None,
        redis_url: str | None = None,
    ) -> None:
        """
        Initialize Redis store with SQLite fallback.

        Args:
            fallback_db_path: Path for SQLite fallback database
            redis_url: Redis connection URL (defaults to ARAGORA_REDIS_URL env var)
        """
        self._redis_url = redis_url or os.getenv("ARAGORA_REDIS_URL", "")
        self._redis_client: Any = None
        self._fallback = SQLiteFindingWorkflowStore(fallback_db_path)
        self._using_fallback = False
        self._lock = threading.RLock()

        self._connect_redis()

    def _connect_redis(self) -> None:
        """Attempt to connect to Redis."""
        if not self._redis_url:
            logger.info("No Redis URL configured, using SQLite fallback")
            self._using_fallback = True
            return

        try:
            import redis

            self._redis_client = redis.from_url(self._redis_url)
            self._redis_client.ping()
            logger.info("Connected to Redis for finding workflow storage")
            self._using_fallback = False
        except Exception as e:  # noqa: BLE001 - Redis transport failures must degrade to SQLite
            logger.warning("Redis connection failed, using SQLite fallback: %s", e)
            self._using_fallback = True
            self._redis_client = None

    async def get(self, finding_id: str) -> dict[str, Any] | None:
        """Get workflow data for a finding."""
        if self._using_fallback:
            return await self._fallback.get(finding_id)

        try:
            data = self._redis_client.get(f"{self.REDIS_PREFIX}{finding_id}")
            if data:
                return json.loads(data)
            return None
        except Exception as e:  # noqa: BLE001 - Redis reads must degrade to SQLite
            logger.warning("Redis get failed, using fallback: %s", e)
            return await self._fallback.get(finding_id)

    async def save(self, data: dict[str, Any]) -> None:
        """Save workflow data for a finding."""
        finding_id = data.get("finding_id")
        if not finding_id:
            raise ValueError("finding_id is required")

        # Always save to SQLite fallback for durability
        await self._fallback.save(data)

        if self._using_fallback:
            return

        try:
            data_json = json.dumps(data)
            pipe = self._redis_client.pipeline()

            # Save main data
            pipe.set(f"{self.REDIS_PREFIX}{finding_id}", data_json)

            # Update assignee index
            assigned_to = data.get("assigned_to")
            if assigned_to:
                pipe.sadd(f"{self.REDIS_INDEX_ASSIGNEE}{assigned_to}", finding_id)

            # Update state index
            current_state = data.get("current_state", "open")
            pipe.sadd(f"{self.REDIS_INDEX_STATE}{current_state}", finding_id)

            pipe.execute()
        except Exception as e:  # noqa: BLE001 - Redis writes must not break SQLite durability
            logger.warning("Redis save failed (SQLite fallback used): %s", e)

    async def delete(self, finding_id: str) -> bool:
        """Delete workflow data for a finding."""
        result = await self._fallback.delete(finding_id)

        if self._using_fallback:
            return result

        try:
            # Get current data to clean up indexes
            data = self._redis_client.get(f"{self.REDIS_PREFIX}{finding_id}")
            if data:
                workflow = json.loads(data)
                pipe = self._redis_client.pipeline()

                # Remove from assignee index
                if workflow.get("assigned_to"):
                    pipe.srem(
                        f"{self.REDIS_INDEX_ASSIGNEE}{workflow['assigned_to']}",
                        finding_id,
                    )

                # Remove from state index
                if workflow.get("current_state"):
                    pipe.srem(
                        f"{self.REDIS_INDEX_STATE}{workflow['current_state']}",
                        finding_id,
                    )

                # Delete main data
                pipe.delete(f"{self.REDIS_PREFIX}{finding_id}")
                pipe.execute()
                return True
            return result
        except Exception as e:  # noqa: BLE001 - Redis deletes must not break fallback behavior
            logger.warning("Redis delete failed: %s", e)
            return result

    async def list_all(self) -> list[dict[str, Any]]:
        """List all workflow data."""
        if self._using_fallback:
            return await self._fallback.list_all()

        try:
            results = []
            cursor = "0"
            while cursor != 0:
                cursor, keys = self._redis_client.scan(
                    cursor=cursor,
                    match=f"{self.REDIS_PREFIX}*",
                    count=100,
                )
                if keys:
                    # Filter out index keys (keys are bytes from Redis)
                    data_keys = [k for k in keys if b":idx:" not in k and b"idx:" not in k]
                    if data_keys:
                        values = self._redis_client.mget(data_keys)
                        for v in values:
                            if v:
                                results.append(json.loads(v))
            return results
        except Exception as e:  # noqa: BLE001 - Redis scans must degrade to SQLite
            logger.warning("Redis list_all failed, using fallback: %s", e)
            return await self._fallback.list_all()

    async def list_by_assignee(self, user_id: str) -> list[dict[str, Any]]:
        """List all workflows assigned to a user."""
        if self._using_fallback:
            return await self._fallback.list_by_assignee(user_id)

        try:
            finding_ids = self._redis_client.smembers(f"{self.REDIS_INDEX_ASSIGNEE}{user_id}")
            if not finding_ids:
                return []

            keys = [f"{self.REDIS_PREFIX}{fid.decode()}" for fid in finding_ids]
            values = self._redis_client.mget(keys)
            return [json.loads(v) for v in values if v]
        except Exception as e:  # noqa: BLE001 - Redis index reads must degrade to SQLite
            logger.warning("Redis list_by_assignee failed, using fallback: %s", e)
            return await self._fallback.list_by_assignee(user_id)

    async def list_overdue(self) -> list[dict[str, Any]]:
        """List all overdue findings."""
        # For overdue queries, use SQLite as it's more efficient for date comparisons
        return await self._fallback.list_overdue()

    async def list_by_state(self, state: str) -> list[dict[str, Any]]:
        """List all findings in a specific state."""
        if self._using_fallback:
            return await self._fallback.list_by_state(state)

        try:
            finding_ids = self._redis_client.smembers(f"{self.REDIS_INDEX_STATE}{state}")
            if not finding_ids:
                return []

            keys = [f"{self.REDIS_PREFIX}{fid.decode()}" for fid in finding_ids]
            values = self._redis_client.mget(keys)
            return [json.loads(v) for v in values if v]
        except Exception as e:  # noqa: BLE001 - Redis index reads must degrade to SQLite
            logger.warning("Redis list_by_state failed, using fallback: %s", e)
            return await self._fallback.list_by_state(state)

    async def close(self) -> None:
        """Close connections."""
        await self._fallback.close()
        if self._redis_client:
            try:
                self._redis_client.close()
            except Exception as e:  # noqa: BLE001 - best-effort cleanup
                logger.debug("Redis close failed: %s", e)


class PostgresFindingWorkflowStore(FindingWorkflowStoreBackend):
    """
    PostgreSQL-backed finding workflow store.

    Async implementation for production multi-instance deployments
    with horizontal scaling and concurrent writes.
    """

    SCHEMA_NAME = "finding_workflows"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS finding_workflows (
            finding_id TEXT PRIMARY KEY,
            current_state TEXT NOT NULL DEFAULT 'open',
            assigned_to TEXT,
            assigned_by TEXT,
            assigned_at TIMESTAMPTZ,
            priority INTEGER DEFAULT 3,
            due_date TIMESTAMPTZ,
            parent_finding_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            data_json JSONB NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_workflow_assigned_to ON finding_workflows(assigned_to);
        CREATE INDEX IF NOT EXISTS idx_workflow_state ON finding_workflows(current_state);
        CREATE INDEX IF NOT EXISTS idx_workflow_due_date ON finding_workflows(due_date);
    """

    def __init__(self, pool: Pool) -> None:
        self._pool = pool
        self._initialized = False
        logger.info("PostgresFindingWorkflowStore initialized")

    async def initialize(self) -> None:
        """Initialize database schema."""
        if self._initialized:
            return

        async with self._pool.acquire() as conn:
            await conn.execute(self.INITIAL_SCHEMA)

        self._initialized = True
        logger.debug("[%s] Schema initialized", self.SCHEMA_NAME)

    async def get(self, finding_id: str) -> dict[str, Any] | None:
        """Get workflow data for a finding."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data_json FROM finding_workflows WHERE finding_id = $1",
                finding_id,
            )
            if row:
                data = row["data_json"]
                return json.loads(data) if isinstance(data, str) else data
            return None

    def get_sync(self, finding_id: str) -> dict[str, Any] | None:
        """Get workflow data for a finding (sync wrapper)."""
        return run_async(self.get(finding_id))

    async def save(self, data: dict[str, Any]) -> None:
        """Save workflow data for a finding."""
        finding_id = data.get("finding_id")
        if not finding_id:
            raise ValueError("finding_id is required")

        now = time.time()
        data_json = json.dumps(data)

        # Parse assigned_at and due_date if they are ISO strings
        assigned_at = data.get("assigned_at")
        due_date = data.get("due_date")

        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO finding_workflows
                   (finding_id, current_state, assigned_to, assigned_by, assigned_at,
                    priority, due_date, parent_finding_id, created_at, updated_at, data_json)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, to_timestamp($9), to_timestamp($10), $11)
                   ON CONFLICT (finding_id) DO UPDATE SET
                       current_state = EXCLUDED.current_state,
                       assigned_to = EXCLUDED.assigned_to,
                       assigned_by = EXCLUDED.assigned_by,
                       assigned_at = EXCLUDED.assigned_at,
                       priority = EXCLUDED.priority,
                       due_date = EXCLUDED.due_date,
                       parent_finding_id = EXCLUDED.parent_finding_id,
                       updated_at = EXCLUDED.updated_at,
                       data_json = EXCLUDED.data_json""",
                finding_id,
                data.get("current_state", "open"),
                data.get("assigned_to"),
                data.get("assigned_by"),
                assigned_at,
                data.get("priority", 3),
                due_date,
                data.get("parent_finding_id"),
                now,
                now,
                data_json,
            )

    def save_sync(self, data: dict[str, Any]) -> None:
        """Save workflow data for a finding (sync wrapper)."""
        run_async(self.save(data))

    async def delete(self, finding_id: str) -> bool:
        """Delete workflow data for a finding."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM finding_workflows WHERE finding_id = $1",
                finding_id,
            )
            return result != "DELETE 0"

    def delete_sync(self, finding_id: str) -> bool:
        """Delete workflow data for a finding (sync wrapper)."""
        return run_async(self.delete(finding_id))

    async def list_all(self) -> list[dict[str, Any]]:
        """List all workflow data."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT data_json FROM finding_workflows ORDER BY created_at DESC"
            )
            results = []
            for row in rows:
                data = row["data_json"]
                results.append(json.loads(data) if isinstance(data, str) else data)
            return results

    def list_all_sync(self) -> list[dict[str, Any]]:
        """List all workflow data (sync wrapper)."""
        return run_async(self.list_all())

    async def list_by_assignee(self, user_id: str) -> list[dict[str, Any]]:
        """List all workflows assigned to a user."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT data_json FROM finding_workflows WHERE assigned_to = $1 ORDER BY created_at DESC",
                user_id,
            )
            results = []
            for row in rows:
                data = row["data_json"]
                results.append(json.loads(data) if isinstance(data, str) else data)
            return results

    def list_by_assignee_sync(self, user_id: str) -> list[dict[str, Any]]:
        """List all workflows assigned to a user (sync wrapper)."""
        return run_async(self.list_by_assignee(user_id))

    async def list_overdue(self) -> list[dict[str, Any]]:
        """List all overdue findings."""
        terminal_states = ("resolved", "false_positive", "duplicate", "accepted_risk")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT data_json FROM finding_workflows
                   WHERE due_date IS NOT NULL
                     AND due_date < NOW()
                     AND current_state NOT IN ($1, $2, $3, $4)
                   ORDER BY due_date ASC""",
                *terminal_states,
            )
            results = []
            for row in rows:
                data = row["data_json"]
                results.append(json.loads(data) if isinstance(data, str) else data)
            return results

    def list_overdue_sync(self) -> list[dict[str, Any]]:
        """List all overdue findings (sync wrapper)."""
        return run_async(self.list_overdue())

    async def list_by_state(self, state: str) -> list[dict[str, Any]]:
        """List all findings in a specific state."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT data_json FROM finding_workflows WHERE current_state = $1 ORDER BY created_at DESC",
                state,
            )
            results = []
            for row in rows:
                data = row["data_json"]
                results.append(json.loads(data) if isinstance(data, str) else data)
            return results

    def list_by_state_sync(self, state: str) -> list[dict[str, Any]]:
        """List all findings in a specific state (sync wrapper)."""
        return run_async(self.list_by_state(state))

    async def close(self) -> None:
        """Close is a no-op for pool-based stores (pool managed externally)."""
        pass


def get_finding_workflow_store() -> FindingWorkflowStoreBackend:
    """
    Get the global finding workflow store instance.

    Backend selection (in preference order):
    1. Supabase PostgreSQL (if SUPABASE_URL + SUPABASE_DB_PASSWORD configured)
    2. Self-hosted PostgreSQL (if DATABASE_URL or ARAGORA_POSTGRES_DSN configured)
    3. Redis (if ARAGORA_WORKFLOW_STORE_BACKEND=redis)
    4. SQLite (fallback, with production warning)

    Override via:
    - ARAGORA_WORKFLOW_STORE_BACKEND: "memory", "sqlite", "postgres", "supabase", or "redis"
    - ARAGORA_DB_BACKEND: Global override

    Returns:
        Configured FindingWorkflowStoreBackend instance
    """
    global _finding_workflow_store

    with _store_lock:
        if _finding_workflow_store is not None:
            return _finding_workflow_store

        # Check store-specific backend for Redis (not handled by create_persistent_store)
        backend = os.getenv("ARAGORA_WORKFLOW_STORE_BACKEND", "").lower()
        if backend == "redis":
            _finding_workflow_store = RedisFindingWorkflowStore()
            logger.info("Using Redis finding workflow store")
            return _finding_workflow_store

        # Use unified factory for memory/sqlite/postgres/supabase
        from aragora.storage.connection_factory import create_persistent_store

        _finding_workflow_store = create_persistent_store(
            store_name="workflow",
            sqlite_class=SQLiteFindingWorkflowStore,
            postgres_class=PostgresFindingWorkflowStore,
            db_filename="finding_workflows.db",
            memory_class=InMemoryFindingWorkflowStore,
        )

        return _finding_workflow_store


def set_finding_workflow_store(store: FindingWorkflowStoreBackend) -> None:
    """Set a custom finding workflow store instance."""
    global _finding_workflow_store

    with _store_lock:
        _finding_workflow_store = store


def reset_finding_workflow_store() -> None:
    """Reset the global finding workflow store (for testing)."""
    global _finding_workflow_store

    with _store_lock:
        _finding_workflow_store = None


__all__ = [
    "WorkflowDataItem",
    "FindingWorkflowStoreBackend",
    "InMemoryFindingWorkflowStore",
    "SQLiteFindingWorkflowStore",
    "RedisFindingWorkflowStore",
    "PostgresFindingWorkflowStore",
    "get_finding_workflow_store",
    "set_finding_workflow_store",
    "reset_finding_workflow_store",
]
