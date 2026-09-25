"""Batch job storage for explainability with backend abstraction."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast, TYPE_CHECKING

from aragora.config import resolve_db_path

from aragora.storage.backends import (
    POSTGRESQL_AVAILABLE,
    DatabaseBackend,
    PostgreSQLBackend,
    SQLiteBackend,
)

if TYPE_CHECKING:
    from redis import Redis

# Type alias for database rows - can be sqlite3.Row (dict-like) or plain tuple
DatabaseRow = sqlite3.Row | tuple[Any, ...]

logger = logging.getLogger(__name__)


@dataclass
class BatchJob:
    """Batch explanation job."""

    batch_id: str
    debate_ids: list[str]
    status: str = "pending"  # pending, processing, completed, failed
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    processed_count: int = 0
    options: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "debate_ids": self.debate_ids,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "results": self.results,
            "processed_count": self.processed_count,
            "options": self.options,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchJob:
        return cls(**data)


class BatchJobStore(ABC):
    """Abstract batch job store interface."""

    @abstractmethod
    async def save_job(self, job: BatchJob) -> None:
        """Save or update a batch job."""
        pass

    @abstractmethod
    async def get_job(self, batch_id: str) -> BatchJob | None:
        """Get a batch job by ID."""
        pass

    @abstractmethod
    async def delete_job(self, batch_id: str) -> bool:
        """Delete a batch job."""
        pass

    @abstractmethod
    async def list_jobs(self, status: str | None = None, limit: int = 100) -> list[BatchJob]:
        """List batch jobs, optionally filtered by status."""
        pass


class RedisBatchJobStore(BatchJobStore):
    """Redis-backed batch job storage with TTL."""

    def __init__(self, redis_client: Redis, key_prefix: str = "aragora:batch:", ttl: int = 3600):
        self._redis = redis_client
        self._prefix = key_prefix
        self._ttl = ttl

    def _key(self, batch_id: str) -> str:
        return f"{self._prefix}{batch_id}"

    async def save_job(self, job: BatchJob) -> None:
        key = self._key(job.batch_id)
        self._redis.setex(key, self._ttl, json.dumps(job.to_dict()))

    async def get_job(self, batch_id: str) -> BatchJob | None:
        key = self._key(batch_id)
        # Redis get returns bytes | str | None for sync client
        data = cast(bytes | str | None, self._redis.get(key))
        if data:
            # json.loads returns Any; we know it's a dict from our schema
            parsed: dict[str, Any] = json.loads(data if isinstance(data, str) else data.decode())
            return BatchJob.from_dict(parsed)
        return None

    async def delete_job(self, batch_id: str) -> bool:
        key = self._key(batch_id)
        # Redis delete returns int for sync client
        deleted_count = cast(int, self._redis.delete(key))
        return deleted_count > 0

    async def list_jobs(self, status: str | None = None, limit: int = 100) -> list[BatchJob]:
        # Scan for keys and filter
        jobs: list[BatchJob] = []
        cursor: int = 0
        while len(jobs) < limit:
            # Redis scan returns tuple of (cursor, keys) but type stubs return Any
            scan_result = cast(
                tuple[int, list[bytes | str]],
                self._redis.scan(cursor, match=f"{self._prefix}*", count=100),
            )
            cursor, keys = scan_result
            for key in keys:
                # Redis get returns bytes | str | None for sync client
                data = cast(bytes | str | None, self._redis.get(key))
                if data:
                    # json.loads returns Any; we know it's a dict from our schema
                    parsed_job: dict[str, Any] = json.loads(
                        data if isinstance(data, str) else data.decode()
                    )
                    job = BatchJob.from_dict(parsed_job)
                    if status is None or job.status == status:
                        jobs.append(job)
                        if len(jobs) >= limit:
                            break
            if cursor == 0:
                break
        return jobs


class MemoryBatchJobStore(BatchJobStore):
    """In-memory batch job storage with LRU eviction (development fallback)."""

    def __init__(self, max_jobs: int = 100, ttl_seconds: int = 3600):
        self._jobs: OrderedDict[str, BatchJob] = OrderedDict()
        self._max_jobs = max_jobs
        self._ttl = ttl_seconds

    async def save_job(self, job: BatchJob) -> None:
        # Evict oldest if at capacity
        while len(self._jobs) >= self._max_jobs:
            self._jobs.popitem(last=False)
        self._jobs[job.batch_id] = job
        self._jobs.move_to_end(job.batch_id)

    async def get_job(self, batch_id: str) -> BatchJob | None:
        job = self._jobs.get(batch_id)
        if job:
            # Check TTL
            if time.time() - job.created_at > self._ttl:
                del self._jobs[batch_id]
                return None
            self._jobs.move_to_end(batch_id)
        return job

    async def delete_job(self, batch_id: str) -> bool:
        if batch_id in self._jobs:
            del self._jobs[batch_id]
            return True
        return False

    async def list_jobs(self, status: str | None = None, limit: int = 100) -> list[BatchJob]:
        result = []
        now = time.time()
        for job in list(self._jobs.values()):
            if now - job.created_at > self._ttl:
                continue
            if status is None or job.status == status:
                result.append(job)
                if len(result) >= limit:
                    break
        return result


class DatabaseBatchJobStore(BatchJobStore):
    """Database-backed batch job storage using SQLite or PostgreSQL."""

    _TABLE_NAME = "explainability_batch_jobs"

    def __init__(self, backend: DatabaseBackend, ttl_seconds: int = 3600):
        self._backend = backend
        self._ttl = ttl_seconds
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        self._backend.execute_write(f"""
            CREATE TABLE IF NOT EXISTS {self._TABLE_NAME} (
                batch_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                started_at REAL,
                completed_at REAL,
                processed_count INTEGER NOT NULL DEFAULT 0,
                debate_ids_json TEXT NOT NULL,
                results_json TEXT NOT NULL,
                options_json TEXT NOT NULL,
                error TEXT,
                expires_at REAL NOT NULL
            )
            """)
        self._backend.execute_write(
            f"CREATE INDEX IF NOT EXISTS idx_{self._TABLE_NAME}_status ON {self._TABLE_NAME}(status)"
        )
        self._backend.execute_write(
            f"CREATE INDEX IF NOT EXISTS idx_{self._TABLE_NAME}_expires ON {self._TABLE_NAME}(expires_at)"
        )

    def _row_to_job(self, row: DatabaseRow) -> BatchJob:
        """Convert a database row into a BatchJob."""
        data: dict[str, Any]
        if isinstance(row, sqlite3.Row):
            data = {key: row[key] for key in row.keys()}
        else:
            columns = [
                "batch_id",
                "status",
                "created_at",
                "started_at",
                "completed_at",
                "processed_count",
                "debate_ids_json",
                "results_json",
                "options_json",
                "error",
                "expires_at",
            ]
            data = dict(zip(columns, row))

        return BatchJob(
            batch_id=data["batch_id"],
            debate_ids=json.loads(data["debate_ids_json"] or "[]"),
            status=data["status"],
            created_at=data["created_at"],
            started_at=data["started_at"],
            completed_at=data["completed_at"],
            results=json.loads(data["results_json"] or "[]"),
            processed_count=data["processed_count"] or 0,
            options=json.loads(data["options_json"] or "{}"),
            error=data.get("error"),
        )

    def _is_expired(self, expires_at: float | None) -> bool:
        if expires_at is None:
            return False
        return time.time() > expires_at

    async def save_job(self, job: BatchJob) -> None:
        expires_at = job.created_at + self._ttl
        self._backend.execute_write(
            f"""
            INSERT INTO {self._TABLE_NAME} (
                batch_id,
                status,
                created_at,
                started_at,
                completed_at,
                processed_count,
                debate_ids_json,
                results_json,
                options_json,
                error,
                expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(batch_id) DO UPDATE SET
                status=excluded.status,
                created_at=excluded.created_at,
                started_at=excluded.started_at,
                completed_at=excluded.completed_at,
                processed_count=excluded.processed_count,
                debate_ids_json=excluded.debate_ids_json,
                results_json=excluded.results_json,
                options_json=excluded.options_json,
                error=excluded.error,
                expires_at=excluded.expires_at
            """,  # noqa: S608 -- table name interpolation, parameterized
            (
                job.batch_id,
                job.status,
                job.created_at,
                job.started_at,
                job.completed_at,
                job.processed_count,
                json.dumps(job.debate_ids),
                json.dumps(job.results),
                json.dumps(job.options),
                job.error,
                expires_at,
            ),
        )

    async def get_job(self, batch_id: str) -> BatchJob | None:
        row = self._backend.fetch_one(
            f"""
            SELECT
                batch_id,
                status,
                created_at,
                started_at,
                completed_at,
                processed_count,
                debate_ids_json,
                results_json,
                options_json,
                error,
                expires_at
            FROM {self._TABLE_NAME}
            WHERE batch_id = ?
            """,  # noqa: S608 -- table name interpolation, parameterized
            (batch_id,),
        )
        if not row:
            return None

        job = self._row_to_job(row)
        expires_at: float | None = None
        if isinstance(row, sqlite3.Row):
            expires_at = row["expires_at"]
        else:
            expires_at = row[-1]

        if self._is_expired(expires_at):
            self._backend.execute_write(
                f"DELETE FROM {self._TABLE_NAME} WHERE batch_id = ?",  # noqa: S608 -- table name interpolation, parameterized
                (batch_id,),
            )
            return None

        return job

    async def delete_job(self, batch_id: str) -> bool:
        self._backend.execute_write(
            f"DELETE FROM {self._TABLE_NAME} WHERE batch_id = ?",  # noqa: S608 -- table name interpolation, parameterized
            (batch_id,),
        )
        return True

    async def list_jobs(self, status: str | None = None, limit: int = 100) -> list[BatchJob]:
        params: list[Any] = []
        conditions = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._backend.fetch_all(
            f"""
            SELECT
                batch_id,
                status,
                created_at,
                started_at,
                completed_at,
                processed_count,
                debate_ids_json,
                results_json,
                options_json,
                error,
                expires_at
            FROM {self._TABLE_NAME}
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
            """,  # noqa: S608 -- table name interpolation, parameterized
            tuple(params + [limit]),
        )

        jobs: list[BatchJob] = []
        for row in rows:
            # Cast to DatabaseRow for type narrowing
            db_row: DatabaseRow = row
            if isinstance(db_row, sqlite3.Row):
                row_expires_at: float | None = db_row["expires_at"]
                row_batch_id: str = db_row["batch_id"]
            else:
                row_expires_at = db_row[-1]
                row_batch_id = db_row[0]
            if self._is_expired(row_expires_at):
                try:
                    self._backend.execute_write(
                        f"DELETE FROM {self._TABLE_NAME} WHERE batch_id = ?",  # noqa: S608 -- table name interpolation, parameterized
                        (row_batch_id,),
                    )
                except (OSError, RuntimeError, ValueError) as e:
                    logger.warning("Failed to delete expired batch %s: %s", row_batch_id, e)
                continue
            jobs.append(self._row_to_job(db_row))
        return jobs


class SQLiteBatchJobStore(DatabaseBatchJobStore):
    """SQLite-backed batch job storage."""

    def __init__(self, db_path: Path, ttl_seconds: int = 3600):
        super().__init__(SQLiteBackend(db_path), ttl_seconds=ttl_seconds)


class PostgresBatchJobStore(DatabaseBatchJobStore):
    """PostgreSQL-backed batch job storage."""

    def __init__(self, database_url: str, ttl_seconds: int = 3600):
        if not POSTGRESQL_AVAILABLE:
            raise ImportError("psycopg2 required for PostgreSQL batch job store")
        super().__init__(PostgreSQLBackend(database_url), ttl_seconds=ttl_seconds)


# Singleton management
_batch_store: BatchJobStore | None = None
_warned_memory: bool = False


def get_batch_job_store() -> BatchJobStore:
    """Get or create batch job store based on environment."""
    global _batch_store, _warned_memory

    if _batch_store is not None:
        return _batch_store

    ttl_seconds = int(os.environ.get("ARAGORA_EXPLAINABILITY_BATCH_TTL_SECONDS", "3600"))
    backend_pref = os.environ.get("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "").lower()

    # Determine default SQLite path
    db_override = os.environ.get("ARAGORA_EXPLAINABILITY_DB", "").strip()
    if db_override:
        db_path = Path(db_override)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        db_path = Path(resolve_db_path("explainability_batch_jobs.db"))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    def _require_distributed(mode: str, reason: str) -> None:
        from aragora.storage.production_guards import require_distributed_store, StorageMode

        require_distributed_store("explainability_batch_store", StorageMode(mode), reason)

    def _create_sqlite_store(reason: str) -> BatchJobStore:
        _require_distributed("sqlite", reason)
        return SQLiteBatchJobStore(db_path, ttl_seconds=ttl_seconds)

    def _create_memory_store(reason: str) -> BatchJobStore:
        _require_distributed("memory", reason)
        return MemoryBatchJobStore(ttl_seconds=ttl_seconds)

    # Explicit backend preference
    if backend_pref:
        if backend_pref == "redis":
            try:
                from aragora.utils.redis_config import get_redis_client, is_redis_available

                if is_redis_available():
                    redis_client = get_redis_client()
                    if redis_client:
                        _batch_store = RedisBatchJobStore(redis_client, ttl=ttl_seconds)
                        logger.info("batch_job_store_initialized", extra={"backend": "redis"})
                        return _batch_store
            except (ImportError, ConnectionError, OSError, RuntimeError) as e:
                logger.warning("Redis batch store unavailable: %s", e)
            _batch_store = _create_sqlite_store(
                "Redis not available for explainability batch store"
            )
            logger.info("batch_job_store_initialized", extra={"backend": "sqlite"})
            return _batch_store

        if backend_pref in ("postgres", "postgresql"):
            database_url = (
                os.environ.get("DATABASE_URL")
                or os.environ.get("ARAGORA_DATABASE_URL")
                or os.environ.get("ARAGORA_POSTGRES_DSN")
            )
            if not database_url:
                _batch_store = _create_sqlite_store("PostgreSQL DSN not configured")
                logger.info("batch_job_store_initialized", extra={"backend": "sqlite"})
                return _batch_store
            try:
                _batch_store = PostgresBatchJobStore(database_url, ttl_seconds=ttl_seconds)
                logger.info("batch_job_store_initialized", extra={"backend": "postgresql"})
                return _batch_store
            except (ImportError, ConnectionError, OSError, RuntimeError) as e:
                logger.warning("PostgreSQL batch store unavailable: %s", e)
                _batch_store = _create_sqlite_store(
                    "PostgreSQL unavailable for explainability batch store"
                )
                logger.info("batch_job_store_initialized", extra={"backend": "sqlite"})
                return _batch_store

        if backend_pref == "sqlite":
            _batch_store = _create_sqlite_store("Explicit SQLite backend selected")
            logger.info("batch_job_store_initialized", extra={"backend": "sqlite"})
            return _batch_store

        if backend_pref == "memory":
            _batch_store = _create_memory_store("Explicit memory backend selected")
            logger.info("batch_job_store_initialized", extra={"backend": "memory"})
            return _batch_store

    # Default behavior: try Redis first, then database backend
    try:
        from aragora.utils.redis_config import get_redis_client, is_redis_available

        if is_redis_available():
            redis_client = get_redis_client()
            if redis_client:
                _batch_store = RedisBatchJobStore(redis_client, ttl=ttl_seconds)
                logger.info("batch_job_store_initialized", extra={"backend": "redis"})
                return _batch_store
    except (ImportError, ConnectionError, OSError, RuntimeError) as e:
        logger.debug("Redis batch store unavailable: %s", e)

    # Fallback to SQLite, then memory
    try:
        _batch_store = _create_sqlite_store("Defaulting to SQLite for explainability batch store")
        logger.info("batch_job_store_initialized", extra={"backend": "sqlite"})
        return _batch_store
    except (OSError, RuntimeError, ImportError) as e:
        logger.warning("SQLite batch store unavailable: %s", e)

    if not _warned_memory:
        logger.warning(
            "batch_store_using_memory: Explainability batch jobs using in-memory "
            "storage. Data will be lost on restart. Configure Redis or PostgreSQL.",
        )
        _warned_memory = True

    _batch_store = _create_memory_store("SQLite unavailable for explainability batch store")
    logger.info("batch_job_store_initialized", extra={"backend": "memory"})
    return _batch_store


def reset_batch_job_store() -> None:
    """Reset the batch job store singleton (for testing)."""
    global _batch_store, _warned_memory
    _batch_store = None
    _warned_memory = False


__all__ = [
    "BatchJob",
    "BatchJobStore",
    "DatabaseBatchJobStore",
    "SQLiteBatchJobStore",
    "PostgresBatchJobStore",
    "RedisBatchJobStore",
    "MemoryBatchJobStore",
    "get_batch_job_store",
    "reset_batch_job_store",
]
