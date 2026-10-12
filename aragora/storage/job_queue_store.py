"""
Persistent Job Queue Store.

Provides durable storage for job queue entries, ensuring jobs survive
server restarts and enabling distributed job processing.

Backends:
- SQLiteJobStore: Persistent, single-instance (default)
- RedisJobStore: Distributed, multi-instance (with SQLite fallback)

Usage:
    from aragora.storage.job_queue_store import get_job_store

    store = get_job_store()
    await store.enqueue(job)
    job = await store.dequeue(worker_id="worker-1")
    await store.complete(job.id)
"""

from __future__ import annotations

import contextvars
import json
import logging
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from asyncpg import Pool


from aragora.config import resolve_db_path
from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Status of a job in the queue."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass
class QueuedJob:
    """A job in the durable queue."""

    id: str
    job_type: str  # "gauntlet", "workflow", "debate", etc.
    payload: dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    priority: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    attempts: int = 0
    max_attempts: int = 3
    worker_id: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    user_id: str | None = None
    workspace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "job_type": self.job_type,
            "payload": self.payload,
            "status": self.status.value if isinstance(self.status, JobStatus) else self.status,
            "priority": self.priority,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "worker_id": self.worker_id,
            "error": self.error,
            "result": self.result,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueuedJob:
        """Create from dictionary."""
        status = data.get("status", "pending")
        if isinstance(status, str):
            status = JobStatus(status)
        return cls(
            id=data["id"],
            job_type=data["job_type"],
            payload=data.get("payload", {}),
            status=status,
            priority=data.get("priority", 0),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            attempts=data.get("attempts", 0),
            max_attempts=data.get("max_attempts", 3),
            worker_id=data.get("worker_id"),
            error=data.get("error"),
            result=data.get("result"),
            user_id=data.get("user_id"),
            workspace_id=data.get("workspace_id"),
        )

    @classmethod
    def from_row(cls, row: tuple) -> QueuedJob:
        """Create from database row."""
        return cls(
            id=row[0],
            job_type=row[1],
            payload=json.loads(row[2]) if row[2] else {},
            status=JobStatus(row[3]),
            priority=row[4] or 0,
            created_at=row[5] or time.time(),
            updated_at=row[6] or time.time(),
            started_at=row[7],
            completed_at=row[8],
            attempts=row[9] or 0,
            max_attempts=row[10] or 3,
            worker_id=row[11],
            error=row[12],
            result=json.loads(row[13]) if row[13] else None,
            user_id=row[14],
            workspace_id=row[15],
        )


class JobStoreBackend(ABC):
    """Abstract base for job queue storage backends."""

    @abstractmethod
    async def enqueue(self, job: QueuedJob) -> None:
        """Add a job to the queue."""
        pass

    @abstractmethod
    async def dequeue(
        self,
        worker_id: str,
        job_types: list[str] | None = None,
    ) -> QueuedJob | None:
        """
        Get the next available job and mark it as processing.

        Args:
            worker_id: ID of the worker claiming the job
            job_types: Optional list of job types to filter by

        Returns:
            The claimed job, or None if no jobs available
        """
        pass

    @abstractmethod
    async def get(self, job_id: str) -> QueuedJob | None:
        """Get a job by ID."""
        pass

    @abstractmethod
    async def update(self, job: QueuedJob) -> None:
        """Update a job's state."""
        pass

    @abstractmethod
    async def complete(
        self,
        job_id: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Mark a job as completed."""
        pass

    @abstractmethod
    async def fail(
        self,
        job_id: str,
        error: str,
        should_retry: bool = True,
    ) -> None:
        """Mark a job as failed, optionally scheduling a retry."""
        pass

    @abstractmethod
    async def cancel(self, job_id: str) -> bool:
        """Cancel a pending job. Returns True if cancelled."""
        pass

    @abstractmethod
    async def recover_stale_jobs(
        self,
        stale_threshold_seconds: float = 300.0,
    ) -> int:
        """
        Recover jobs that have been processing too long.

        Returns the number of jobs recovered.
        """
        pass

    @abstractmethod
    async def list_jobs(
        self,
        status: JobStatus | None = None,
        job_type: str | None = None,
        limit: int = 100,
    ) -> list[QueuedJob]:
        """List jobs with optional filtering."""
        pass

    @abstractmethod
    async def get_stats(self) -> dict[str, int]:
        """Get queue statistics."""
        pass

    async def close(self) -> None:
        """Close connections."""
        pass


class SQLiteJobStore(JobStoreBackend):
    """
    SQLite-backed job store.

    Provides durable job queue storage that survives restarts.

    Raises:
        DistributedStateError: In production if PostgreSQL is not available
    """

    def __init__(self, db_path: Path | str):
        # SECURITY: Check production guards for SQLite usage
        try:
            from aragora.storage.production_guards import (
                require_distributed_store,
                StorageMode,
            )

            require_distributed_store(
                "job_queue_store",
                StorageMode.SQLITE,
                "Job queue store using SQLite - use PostgreSQL for multi-instance deployments",
            )
        except ImportError:
            pass  # Guards not available, allow SQLite

        self.db_path = Path(resolve_db_path(db_path))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # ContextVar for per-async-context connection (async-safe replacement for threading.local)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"jobqueue_conn_{id(self)}", default=None
        )
        # Track all connections for proper cleanup
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        self._init_schema()
        logger.info("SQLiteJobStore initialized: %s", self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        """Get per-context database connection."""
        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._conn_var.set(conn)
            with self._connections_lock:
                self._connections.add(conn)
        return conn

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_queue (
                id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                payload_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                started_at REAL,
                completed_at REAL,
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                worker_id TEXT,
                error TEXT,
                result_json TEXT,
                user_id TEXT,
                workspace_id TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_status ON job_queue(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_type ON job_queue(job_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_priority ON job_queue(priority DESC)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_pending ON job_queue(status, priority DESC, created_at)"
        )
        conn.commit()
        conn.close()

    async def enqueue(self, job: QueuedJob) -> None:
        """Add a job to the queue."""
        conn = self._get_conn()
        job.updated_at = time.time()
        conn.execute(
            """INSERT OR REPLACE INTO job_queue
               (id, job_type, payload_json, status, priority, created_at, updated_at,
                started_at, completed_at, attempts, max_attempts, worker_id, error,
                result_json, user_id, workspace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job.id,
                job.job_type,
                json.dumps(job.payload),
                job.status.value,
                job.priority,
                job.created_at,
                job.updated_at,
                job.started_at,
                job.completed_at,
                job.attempts,
                job.max_attempts,
                job.worker_id,
                job.error,
                json.dumps(job.result) if job.result else None,
                job.user_id,
                job.workspace_id,
            ),
        )
        conn.commit()
        logger.debug("Enqueued job %s (%s)", job.id, job.job_type)

    async def dequeue(
        self,
        worker_id: str,
        job_types: list[str] | None = None,
    ) -> QueuedJob | None:
        """Get the next available job and mark it as processing."""
        conn = self._get_conn()

        # Build query with optional type filter
        if job_types:
            placeholders = ",".join("?" * len(job_types))
            query = f"""
                SELECT id, job_type, payload_json, status, priority, created_at,
                       updated_at, started_at, completed_at, attempts, max_attempts,
                       worker_id, error, result_json, user_id, workspace_id
                FROM job_queue
                WHERE status = 'pending' AND job_type IN ({placeholders})
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            """  # parameterized query
            cursor = conn.execute(query, job_types)
        else:
            cursor = conn.execute(
                """SELECT id, job_type, payload_json, status, priority, created_at,
                          updated_at, started_at, completed_at, attempts, max_attempts,
                          worker_id, error, result_json, user_id, workspace_id
                   FROM job_queue
                   WHERE status = 'pending'
                   ORDER BY priority DESC, created_at ASC
                   LIMIT 1"""
            )

        row = cursor.fetchone()
        if not row:
            return None

        job = QueuedJob.from_row(row)

        # Atomically claim the job
        now = time.time()
        result = conn.execute(
            """UPDATE job_queue
               SET status = 'processing', worker_id = ?, started_at = ?,
                   updated_at = ?, attempts = attempts + 1
               WHERE id = ? AND status = 'pending'""",
            (worker_id, now, now, job.id),
        )
        conn.commit()

        if result.rowcount == 0:
            # Another worker claimed it
            return await self.dequeue(worker_id, job_types)

        job.status = JobStatus.PROCESSING
        job.worker_id = worker_id
        job.started_at = now
        job.updated_at = now
        job.attempts += 1

        logger.debug("Worker %s claimed job %s", worker_id, job.id)
        return job

    async def get(self, job_id: str) -> QueuedJob | None:
        """Get a job by ID."""
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT id, job_type, payload_json, status, priority, created_at,
                      updated_at, started_at, completed_at, attempts, max_attempts,
                      worker_id, error, result_json, user_id, workspace_id
               FROM job_queue WHERE id = ?""",
            (job_id,),
        )
        row = cursor.fetchone()
        return QueuedJob.from_row(row) if row else None

    async def update(self, job: QueuedJob) -> None:
        """Update a job's state."""
        conn = self._get_conn()
        job.updated_at = time.time()
        conn.execute(
            """UPDATE job_queue
               SET status = ?, priority = ?, updated_at = ?, started_at = ?,
                   completed_at = ?, attempts = ?, max_attempts = ?, worker_id = ?,
                   error = ?, result_json = ?
               WHERE id = ?""",
            (
                job.status.value,
                job.priority,
                job.updated_at,
                job.started_at,
                job.completed_at,
                job.attempts,
                job.max_attempts,
                job.worker_id,
                job.error,
                json.dumps(job.result) if job.result else None,
                job.id,
            ),
        )
        conn.commit()

    async def complete(
        self,
        job_id: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Mark a job as completed."""
        conn = self._get_conn()
        now = time.time()
        conn.execute(
            """UPDATE job_queue
               SET status = 'completed', completed_at = ?, updated_at = ?,
                   result_json = ?
               WHERE id = ?""",
            (now, now, json.dumps(result) if result else None, job_id),
        )
        conn.commit()
        logger.debug("Job %s completed", job_id)

    async def fail(
        self,
        job_id: str,
        error: str,
        should_retry: bool = True,
    ) -> None:
        """Mark a job as failed, optionally scheduling a retry."""
        job = await self.get(job_id)
        if not job:
            return

        now = time.time()
        if should_retry and job.attempts < job.max_attempts:
            # Schedule retry
            conn = self._get_conn()
            conn.execute(
                """UPDATE job_queue
                   SET status = 'pending', error = ?, updated_at = ?, worker_id = NULL
                   WHERE id = ?""",
                (error, now, job_id),
            )
            conn.commit()
            logger.info(
                "Job %s scheduled for retry (%s/%s)", job_id, job.attempts, job.max_attempts
            )
        else:
            # Final failure
            conn = self._get_conn()
            conn.execute(
                """UPDATE job_queue
                   SET status = 'failed', error = ?, completed_at = ?, updated_at = ?
                   WHERE id = ?""",
                (error, now, now, job_id),
            )
            conn.commit()
            logger.warning("Job %s failed permanently: %s", job_id, error)

    async def cancel(self, job_id: str) -> bool:
        """Cancel a pending job."""
        conn = self._get_conn()
        now = time.time()
        result = conn.execute(
            """UPDATE job_queue
               SET status = 'cancelled', completed_at = ?, updated_at = ?
               WHERE id = ? AND status = 'pending'""",
            (now, now, job_id),
        )
        conn.commit()
        cancelled = result.rowcount > 0
        if cancelled:
            logger.info("Job %s cancelled", job_id)
        return cancelled

    async def recover_stale_jobs(
        self,
        stale_threshold_seconds: float = 300.0,
    ) -> int:
        """Recover jobs that have been processing too long."""
        conn = self._get_conn()
        cutoff = time.time() - stale_threshold_seconds
        result = conn.execute(
            """UPDATE job_queue
               SET status = 'pending', worker_id = NULL, updated_at = ?
               WHERE status = 'processing' AND started_at < ?""",
            (time.time(), cutoff),
        )
        conn.commit()
        recovered = result.rowcount
        if recovered > 0:
            logger.info("Recovered %s stale jobs", recovered)
        return recovered

    async def list_jobs(
        self,
        status: JobStatus | None = None,
        job_type: str | None = None,
        limit: int = 100,
    ) -> list[QueuedJob]:
        """List jobs with optional filtering."""
        conn = self._get_conn()
        conditions = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status.value)
        if job_type:
            conditions.append("job_type = ?")
            params.append(job_type)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        cursor = conn.execute(
            f"""SELECT id, job_type, payload_json, status, priority, created_at,
                       updated_at, started_at, completed_at, attempts, max_attempts,
                       worker_id, error, result_json, user_id, workspace_id
                FROM job_queue {where_clause}
                ORDER BY created_at DESC
                LIMIT ?""",  # dynamic clause from internal state
            params,
        )
        return [QueuedJob.from_row(row) for row in cursor.fetchall()]

    async def get_stats(self) -> dict[str, int]:
        """Get queue statistics."""
        conn = self._get_conn()
        cursor = conn.execute("""SELECT status, COUNT(*) FROM job_queue GROUP BY status""")
        stats = {row[0]: row[1] for row in cursor.fetchall()}
        stats["total"] = sum(stats.values())
        return stats

    async def close(self) -> None:
        """Close all database connections."""
        with self._connections_lock:
            for conn in self._connections:
                try:
                    conn.close()
                except (OSError, RuntimeError, ValueError) as e:
                    logger.debug("Error closing connection: %s", e)
                    pass
            self._connections.clear()


class PostgresJobQueueStore(JobStoreBackend):
    """
    PostgreSQL-backed job store.

    Async implementation for production multi-instance deployments
    with horizontal scaling and concurrent job processing.
    """

    SCHEMA_NAME = "job_queue"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS job_queue (
            id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            payload_json JSONB,
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            attempts INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3,
            worker_id TEXT,
            error TEXT,
            result_json JSONB,
            user_id TEXT,
            workspace_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_job_status ON job_queue(status);
        CREATE INDEX IF NOT EXISTS idx_job_type ON job_queue(job_type);
        CREATE INDEX IF NOT EXISTS idx_job_priority ON job_queue(priority DESC);
        CREATE INDEX IF NOT EXISTS idx_job_pending ON job_queue(status, priority DESC, created_at);
    """

    def __init__(self, pool: Pool):
        self._pool = pool
        self._initialized = False
        logger.info("PostgresJobQueueStore initialized")

    async def initialize(self) -> None:
        """Initialize database schema."""
        if self._initialized:
            return

        async with self._pool.acquire() as conn:
            await conn.execute(self.INITIAL_SCHEMA)

        self._initialized = True
        logger.debug("[%s] Schema initialized", self.SCHEMA_NAME)

    def _run_sync(self, coro: Any) -> Any:
        """Run async coroutine synchronously."""
        return run_async(coro)

    async def enqueue(self, job: QueuedJob) -> None:
        """Add a job to the queue."""
        job.updated_at = time.time()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO job_queue
                   (id, job_type, payload_json, status, priority, created_at, updated_at,
                    started_at, completed_at, attempts, max_attempts, worker_id, error,
                    result_json, user_id, workspace_id)
                   VALUES ($1, $2, $3, $4, $5, to_timestamp($6), to_timestamp($7),
                           $8, $9, $10, $11, $12, $13, $14, $15, $16)
                   ON CONFLICT (id) DO UPDATE SET
                       status = EXCLUDED.status,
                       priority = EXCLUDED.priority,
                       updated_at = EXCLUDED.updated_at,
                       payload_json = EXCLUDED.payload_json""",
                job.id,
                job.job_type,
                json.dumps(job.payload),
                job.status.value,
                job.priority,
                job.created_at,
                job.updated_at,
                None,  # started_at
                None,  # completed_at
                job.attempts,
                job.max_attempts,
                job.worker_id,
                job.error,
                json.dumps(job.result) if job.result else None,
                job.user_id,
                job.workspace_id,
            )
        logger.debug("Enqueued job %s (%s)", job.id, job.job_type)

    async def dequeue(
        self,
        worker_id: str,
        job_types: list[str] | None = None,
    ) -> QueuedJob | None:
        """Get the next available job and mark it as processing."""
        time.time()

        async with self._pool.acquire() as conn:
            # Use FOR UPDATE SKIP LOCKED for atomic claim
            if job_types:
                placeholders = ", ".join(f"${i + 2}" for i in range(len(job_types)))
                row = await conn.fetchrow(
                    f"""UPDATE job_queue
                       SET status = 'processing', worker_id = $1, started_at = NOW(),
                           updated_at = NOW(), attempts = attempts + 1
                       WHERE id = (
                           SELECT id FROM job_queue
                           WHERE status = 'pending' AND job_type IN ({placeholders})
                           ORDER BY priority DESC, created_at ASC
                           LIMIT 1
                           FOR UPDATE SKIP LOCKED
                       )
                       RETURNING id, job_type, payload_json, status, priority,
                                 EXTRACT(EPOCH FROM created_at) as created_at,
                                 EXTRACT(EPOCH FROM updated_at) as updated_at,
                                 EXTRACT(EPOCH FROM started_at) as started_at,
                                 EXTRACT(EPOCH FROM completed_at) as completed_at,
                                 attempts, max_attempts, worker_id, error, result_json,
                                 user_id, workspace_id""",  # parameterized query
                    worker_id,
                    *job_types,
                )
            else:
                row = await conn.fetchrow(
                    """UPDATE job_queue
                       SET status = 'processing', worker_id = $1, started_at = NOW(),
                           updated_at = NOW(), attempts = attempts + 1
                       WHERE id = (
                           SELECT id FROM job_queue
                           WHERE status = 'pending'
                           ORDER BY priority DESC, created_at ASC
                           LIMIT 1
                           FOR UPDATE SKIP LOCKED
                       )
                       RETURNING id, job_type, payload_json, status, priority,
                                 EXTRACT(EPOCH FROM created_at) as created_at,
                                 EXTRACT(EPOCH FROM updated_at) as updated_at,
                                 EXTRACT(EPOCH FROM started_at) as started_at,
                                 EXTRACT(EPOCH FROM completed_at) as completed_at,
                                 attempts, max_attempts, worker_id, error, result_json,
                                 user_id, workspace_id""",
                    worker_id,
                )

            if not row:
                return None

            job = self._row_to_job(row)
            logger.debug("Worker %s claimed job %s", worker_id, job.id)
            return job

    def _row_to_job(self, row: Any) -> QueuedJob:
        """Convert database row to QueuedJob."""
        return QueuedJob(
            id=row["id"],
            job_type=row["job_type"],
            payload=json.loads(row["payload_json"]) if row["payload_json"] else {},
            status=JobStatus(row["status"]),
            priority=row["priority"] or 0,
            created_at=row["created_at"] or time.time(),
            updated_at=row["updated_at"] or time.time(),
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            attempts=row["attempts"] or 0,
            max_attempts=row["max_attempts"] or 3,
            worker_id=row["worker_id"],
            error=row["error"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            user_id=row["user_id"],
            workspace_id=row["workspace_id"],
        )

    async def get(self, job_id: str) -> QueuedJob | None:
        """Get a job by ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, job_type, payload_json, status, priority,
                          EXTRACT(EPOCH FROM created_at) as created_at,
                          EXTRACT(EPOCH FROM updated_at) as updated_at,
                          EXTRACT(EPOCH FROM started_at) as started_at,
                          EXTRACT(EPOCH FROM completed_at) as completed_at,
                          attempts, max_attempts, worker_id, error, result_json,
                          user_id, workspace_id
                   FROM job_queue WHERE id = $1""",
                job_id,
            )
            if row:
                return self._row_to_job(row)
            return None

    async def update(self, job: QueuedJob) -> None:
        """Update a job's state."""
        job.updated_at = time.time()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE job_queue
                   SET status = $1, priority = $2, updated_at = to_timestamp($3),
                       started_at = $4, completed_at = $5, attempts = $6,
                       max_attempts = $7, worker_id = $8, error = $9, result_json = $10
                   WHERE id = $11""",
                job.status.value,
                job.priority,
                job.updated_at,
                None if job.started_at is None else f"to_timestamp({job.started_at})",
                None if job.completed_at is None else f"to_timestamp({job.completed_at})",
                job.attempts,
                job.max_attempts,
                job.worker_id,
                job.error,
                json.dumps(job.result) if job.result else None,
                job.id,
            )

    async def complete(
        self,
        job_id: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Mark a job as completed."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE job_queue
                   SET status = 'completed', completed_at = NOW(), updated_at = NOW(),
                       result_json = $1
                   WHERE id = $2""",
                json.dumps(result) if result else None,
                job_id,
            )
        logger.debug("Job %s completed", job_id)

    async def fail(
        self,
        job_id: str,
        error: str,
        should_retry: bool = True,
    ) -> None:
        """Mark a job as failed, optionally scheduling a retry."""
        job = await self.get(job_id)
        if not job:
            return

        async with self._pool.acquire() as conn:
            if should_retry and job.attempts < job.max_attempts:
                # Schedule retry
                await conn.execute(
                    """UPDATE job_queue
                       SET status = 'pending', error = $1, updated_at = NOW(), worker_id = NULL
                       WHERE id = $2""",
                    error,
                    job_id,
                )
                logger.info(
                    "Job %s scheduled for retry (%s/%s)", job_id, job.attempts, job.max_attempts
                )
            else:
                # Final failure
                await conn.execute(
                    """UPDATE job_queue
                       SET status = 'failed', error = $1, completed_at = NOW(), updated_at = NOW()
                       WHERE id = $2""",
                    error,
                    job_id,
                )
                logger.warning("Job %s failed permanently: %s", job_id, error)

    async def cancel(self, job_id: str) -> bool:
        """Cancel a pending job."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE job_queue
                   SET status = 'cancelled', completed_at = NOW(), updated_at = NOW()
                   WHERE id = $1 AND status = 'pending'""",
                job_id,
            )
            cancelled = result != "UPDATE 0"
            if cancelled:
                logger.info("Job %s cancelled", job_id)
            return cancelled

    async def recover_stale_jobs(
        self,
        stale_threshold_seconds: float = 300.0,
    ) -> int:
        """Recover jobs that have been processing too long."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE job_queue
                   SET status = 'pending', worker_id = NULL, updated_at = NOW()
                   WHERE status = 'processing'
                   AND started_at < NOW() - INTERVAL '1 second' * $1""",
                stale_threshold_seconds,
            )
            # Parse the result to get row count
            try:
                recovered = int(result.split()[-1]) if result else 0
            except (ValueError, IndexError):
                recovered = 0
            if recovered > 0:
                logger.info("Recovered %s stale jobs", recovered)
            return recovered

    async def list_jobs(
        self,
        status: JobStatus | None = None,
        job_type: str | None = None,
        limit: int = 100,
    ) -> list[QueuedJob]:
        """List jobs with optional filtering."""
        query = """SELECT id, job_type, payload_json, status, priority,
                          EXTRACT(EPOCH FROM created_at) as created_at,
                          EXTRACT(EPOCH FROM updated_at) as updated_at,
                          EXTRACT(EPOCH FROM started_at) as started_at,
                          EXTRACT(EPOCH FROM completed_at) as completed_at,
                          attempts, max_attempts, worker_id, error, result_json,
                          user_id, workspace_id
                   FROM job_queue WHERE 1=1"""
        params: list[Any] = []
        param_idx = 1

        if status:
            query += f" AND status = ${param_idx}"
            params.append(status.value)
            param_idx += 1
        if job_type:
            query += f" AND job_type = ${param_idx}"
            params.append(job_type)
            param_idx += 1

        query += f" ORDER BY created_at DESC LIMIT ${param_idx}"
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_job(row) for row in rows]

    async def get_stats(self) -> dict[str, int]:
        """Get queue statistics."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT status, COUNT(*) as count FROM job_queue GROUP BY status"""
            )
            stats = {row["status"]: row["count"] for row in rows}
            stats["total"] = sum(stats.values())
            return stats

    async def close(self) -> None:
        """Close is a no-op for pool-based stores (pool managed externally)."""
        pass


# Global store singleton
_job_store: JobStoreBackend | None = None


def get_job_store() -> JobStoreBackend:
    """
    Get or create the job queue store.

    Backend selection (in preference order):
    1. Supabase PostgreSQL (if SUPABASE_URL + SUPABASE_DB_PASSWORD configured)
    2. Self-hosted PostgreSQL (if DATABASE_URL or ARAGORA_POSTGRES_DSN configured)
    3. SQLite (fallback, with production warning)

    Override via:
    - ARAGORA_JOB_STORE_BACKEND: "memory", "sqlite", "postgres", or "supabase"
    - ARAGORA_DB_BACKEND: Global override

    Returns:
        Configured JobStoreBackend instance
    """
    global _job_store
    if _job_store is not None:
        return _job_store

    from aragora.storage.connection_factory import create_persistent_store

    _job_store = create_persistent_store(
        store_name="job",
        sqlite_class=SQLiteJobStore,
        postgres_class=PostgresJobQueueStore,
        db_filename="job_queue.db",
    )

    return _job_store


def set_job_store(store: JobStoreBackend) -> None:
    """Set custom job store (for testing)."""
    global _job_store
    _job_store = store


def reset_job_store() -> None:
    """Reset the global job store (for testing)."""
    global _job_store
    _job_store = None


__all__ = [
    "JobStatus",
    "QueuedJob",
    "JobStoreBackend",
    "SQLiteJobStore",
    "PostgresJobQueueStore",
    "get_job_store",
    "set_job_store",
    "reset_job_store",
]
