"""
Approval Request Storage Backends.

Persistent storage for human approval requests in workflows.

Backends:
- InMemoryApprovalRequestStore: For testing
- SQLiteApprovalRequestStore: For single-instance deployments
- RedisApprovalRequestStore: For multi-instance (with SQLite fallback)

Usage:
    from aragora.storage.approval_request_store import (
        get_approval_request_store,
        set_approval_request_store,
    )

    # Use default store (configured via environment)
    store = get_approval_request_store()
    await store.save(request_data_dict)
    data = await store.get("request-123")
"""

from __future__ import annotations

import json
import logging
import os
import threading
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from aragora.storage.generic_store import (
    GenericInMemoryStore,
    GenericPostgresStore,
    GenericSQLiteStore,
    GenericStoreBackend,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Global singleton
_approval_request_store: ApprovalRequestStoreBackend | None = None
_store_lock = threading.RLock()


@dataclass
class ApprovalRequestItem:
    """
    Approval request data for persistence.

    This is a storage-friendly representation of a human approval request.
    """

    request_id: str
    workflow_id: str
    step_id: str
    title: str
    status: str = "pending"  # pending, approved, rejected, expired

    # Request details
    description: str | None = None
    request_data: dict[str, Any] = field(default_factory=dict)
    response_data: dict[str, Any] | None = None

    # Requester/responder
    requester_id: str | None = None
    responder_id: str | None = None

    # Timing
    expires_at: str | None = None
    responded_at: str | None = None

    # Metadata
    workspace_id: str | None = None
    priority: int = 3  # 1=highest, 5=lowest
    tags: list[str] = field(default_factory=list)

    # Timestamps
    created_at: str = ""
    updated_at: str = ""

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
            "request_id": self.request_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "title": self.title,
            "status": self.status,
            "description": self.description,
            "request_data": self.request_data,
            "response_data": self.response_data,
            "requester_id": self.requester_id,
            "responder_id": self.responder_id,
            "expires_at": self.expires_at,
            "responded_at": self.responded_at,
            "workspace_id": self.workspace_id,
            "priority": self.priority,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRequestItem:
        """Create from dictionary."""
        return cls(
            request_id=data.get("request_id", ""),
            workflow_id=data.get("workflow_id", ""),
            step_id=data.get("step_id", ""),
            title=data.get("title", ""),
            status=data.get("status", "pending"),
            description=data.get("description"),
            request_data=data.get("request_data", {}),
            response_data=data.get("response_data"),
            requester_id=data.get("requester_id"),
            responder_id=data.get("responder_id"),
            expires_at=data.get("expires_at"),
            responded_at=data.get("responded_at"),
            workspace_id=data.get("workspace_id"),
            priority=data.get("priority", 3),
            tags=data.get("tags", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> ApprovalRequestItem:
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))


class ApprovalRequestStoreBackend(GenericStoreBackend):
    """Abstract base class for approval request storage backends."""

    @abstractmethod
    async def list_by_status(self, status: str) -> list[dict[str, Any]]:
        """List requests by status."""
        ...

    @abstractmethod
    async def list_by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        """List requests by workflow."""
        ...

    @abstractmethod
    async def list_pending(self) -> list[dict[str, Any]]:
        """List pending requests."""
        ...

    @abstractmethod
    async def list_expired(self) -> list[dict[str, Any]]:
        """List expired requests (past expires_at but still pending)."""
        ...

    @abstractmethod
    async def respond(
        self,
        request_id: str,
        status: str,
        responder_id: str,
        response_data: dict[str, Any] | None = None,
    ) -> bool:
        """Record a response to an approval request."""
        ...


class InMemoryApprovalRequestStore(GenericInMemoryStore, ApprovalRequestStoreBackend):
    """
    In-memory approval request store for testing.

    Data is lost on restart.
    """

    PRIMARY_KEY = "request_id"

    async def list_by_status(self, status: str) -> list[dict[str, Any]]:
        return self._filter_by("status", status)

    async def list_by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        return self._filter_by("workflow_id", workflow_id)

    async def list_pending(self) -> list[dict[str, Any]]:
        return self._filter_by("status", "pending")

    async def list_expired(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            return [
                r
                for r in self._data.values()
                if (
                    r.get("status") == "pending"
                    and r.get("expires_at")
                    and cast(str, r.get("expires_at")) < now
                )
            ]

    async def respond(
        self,
        request_id: str,
        status: str,
        responder_id: str,
        response_data: dict[str, Any] | None = None,
    ) -> bool:
        with self._lock:
            if request_id not in self._data:
                return False
            self._data[request_id]["status"] = status
            self._data[request_id]["responder_id"] = responder_id
            self._data[request_id]["responded_at"] = datetime.now(timezone.utc).isoformat()
            self._data[request_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
            if response_data is not None:
                self._data[request_id]["response_data"] = response_data
            return True


class SQLiteApprovalRequestStore(GenericSQLiteStore, ApprovalRequestStoreBackend):
    """
    SQLite-backed approval request store.

    Suitable for single-instance deployments.
    """

    TABLE_NAME = "approval_requests"
    PRIMARY_KEY = "request_id"
    SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS approval_requests (
            request_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            requester_id TEXT,
            responder_id TEXT,
            priority INTEGER DEFAULT 3,
            workspace_id TEXT,
            expires_at TEXT,
            responded_at TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            data_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status);
        CREATE INDEX IF NOT EXISTS idx_approval_workflow ON approval_requests(workflow_id);
        CREATE INDEX IF NOT EXISTS idx_approval_expires ON approval_requests(expires_at);
        CREATE INDEX IF NOT EXISTS idx_approval_workspace ON approval_requests(workspace_id);
    """
    INDEX_COLUMNS = {
        "workflow_id",
        "step_id",
        "title",
        "status",
        "requester_id",
        "responder_id",
        "priority",
        "workspace_id",
        "expires_at",
        "responded_at",
    }

    async def list_by_status(self, status: str) -> list[dict[str, Any]]:
        return self._query_by_column("status", status, order_by="priority ASC, created_at DESC")

    async def list_by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        return self._query_by_column("workflow_id", workflow_id)

    async def list_pending(self) -> list[dict[str, Any]]:
        return self._query_with_sql("status = 'pending'", order_by="priority ASC, created_at DESC")

    async def list_expired(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        return self._query_with_sql(
            "status = 'pending' AND expires_at IS NOT NULL AND expires_at < ?",
            (now,),
            order_by="expires_at ASC",
        )

    async def respond(
        self,
        request_id: str,
        status: str,
        responder_id: str,
        response_data: dict[str, Any] | None = None,
    ) -> bool:
        updates: dict[str, Any] = {
            "status": status,
            "responder_id": responder_id,
            "responded_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if response_data is not None:
            updates["response_data"] = response_data

        return self._update_json_field(
            request_id,
            updates,
            extra_column_updates={
                "status": status,
                "responder_id": responder_id,
                "responded_at": updates["responded_at"],
            },
        )


class RedisApprovalRequestStore(ApprovalRequestStoreBackend):
    """
    Redis-backed approval request store with SQLite fallback.

    For multi-instance deployments with optional horizontal scaling.
    Falls back to SQLite if Redis is unavailable.
    """

    REDIS_PREFIX = "aragora:approval_request:"
    REDIS_INDEX_STATUS = "aragora:approval_request:idx:status:"
    REDIS_INDEX_WORKFLOW = "aragora:approval_request:idx:workflow:"

    def __init__(
        self,
        fallback_db_path: Path | None = None,
        redis_url: str | None = None,
    ) -> None:
        self._redis_url = redis_url or os.getenv("ARAGORA_REDIS_URL", "")
        self._redis_client: Any = None
        self._fallback = SQLiteApprovalRequestStore(fallback_db_path)
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
            logger.info("Connected to Redis for approval request storage")
            self._using_fallback = False
        except (ConnectionError, TimeoutError, OSError, ImportError) as e:
            logger.warning("Redis connection failed, using SQLite fallback: %s", e)
            self._using_fallback = True
            self._redis_client = None

    async def get(self, request_id: str) -> dict[str, Any] | None:
        if self._using_fallback:
            return await self._fallback.get(request_id)
        try:
            data = self._redis_client.get(f"{self.REDIS_PREFIX}{request_id}")
            if data:
                return json.loads(data)
            return None
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Redis get failed, using fallback: %s", e)
            return await self._fallback.get(request_id)

    async def save(self, data: dict[str, Any]) -> None:
        request_id = data.get("request_id")
        if not request_id:
            raise ValueError("request_id is required")

        # Always save to SQLite fallback for durability
        await self._fallback.save(data)

        if self._using_fallback:
            return

        try:
            data_json = json.dumps(data)
            pipe = self._redis_client.pipeline()
            pipe.set(f"{self.REDIS_PREFIX}{request_id}", data_json)
            status = data.get("status", "pending")
            pipe.sadd(f"{self.REDIS_INDEX_STATUS}{status}", request_id)
            workflow_id = data.get("workflow_id")
            if workflow_id:
                pipe.sadd(f"{self.REDIS_INDEX_WORKFLOW}{workflow_id}", request_id)
            pipe.execute()
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis save failed (SQLite fallback used): %s", e)

    async def delete(self, request_id: str) -> bool:
        result = await self._fallback.delete(request_id)

        if self._using_fallback:
            return result

        try:
            data = self._redis_client.get(f"{self.REDIS_PREFIX}{request_id}")
            if data:
                request_data = json.loads(data)
                pipe = self._redis_client.pipeline()
                if request_data.get("status"):
                    pipe.srem(
                        f"{self.REDIS_INDEX_STATUS}{request_data['status']}",
                        request_id,
                    )
                if request_data.get("workflow_id"):
                    pipe.srem(
                        f"{self.REDIS_INDEX_WORKFLOW}{request_data['workflow_id']}",
                        request_id,
                    )
                pipe.delete(f"{self.REDIS_PREFIX}{request_id}")
                pipe.execute()
                return True
            return result
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Redis delete failed: %s", e)
            return result

    async def list_all(self) -> list[dict[str, Any]]:
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
                    data_keys = [k for k in keys if b":idx:" not in k and b"idx:" not in k]
                    if data_keys:
                        values = self._redis_client.mget(data_keys)
                        for v in values:
                            if v:
                                results.append(json.loads(v))
            return results
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Redis list_all failed, using fallback: %s", e)
            return await self._fallback.list_all()

    async def list_by_status(self, status: str) -> list[dict[str, Any]]:
        if self._using_fallback:
            return await self._fallback.list_by_status(status)

        try:
            request_ids = self._redis_client.smembers(f"{self.REDIS_INDEX_STATUS}{status}")
            if not request_ids:
                return []
            keys = [f"{self.REDIS_PREFIX}{rid.decode()}" for rid in request_ids]
            values = self._redis_client.mget(keys)
            return [json.loads(v) for v in values if v]
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Redis list_by_status failed, using fallback: %s", e)
            return await self._fallback.list_by_status(status)

    async def list_by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        if self._using_fallback:
            return await self._fallback.list_by_workflow(workflow_id)

        try:
            request_ids = self._redis_client.smembers(f"{self.REDIS_INDEX_WORKFLOW}{workflow_id}")
            if not request_ids:
                return []
            keys = [f"{self.REDIS_PREFIX}{rid.decode()}" for rid in request_ids]
            values = self._redis_client.mget(keys)
            return [json.loads(v) for v in values if v]
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Redis list_by_workflow failed, using fallback: %s", e)
            return await self._fallback.list_by_workflow(workflow_id)

    async def list_pending(self) -> list[dict[str, Any]]:
        return await self.list_by_status("pending")

    async def list_expired(self) -> list[dict[str, Any]]:
        # Use SQLite fallback for date comparison queries
        return await self._fallback.list_expired()

    async def respond(
        self,
        request_id: str,
        status: str,
        responder_id: str,
        response_data: dict[str, Any] | None = None,
    ) -> bool:
        result = await self._fallback.respond(request_id, status, responder_id, response_data)

        if self._using_fallback:
            return result

        try:
            data_bytes = self._redis_client.get(f"{self.REDIS_PREFIX}{request_id}")
            if not data_bytes:
                return result

            data = json.loads(data_bytes)
            old_status = data.get("status")

            data["status"] = status
            data["responder_id"] = responder_id
            data["responded_at"] = datetime.now(timezone.utc).isoformat()
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            if response_data is not None:
                data["response_data"] = response_data

            pipe = self._redis_client.pipeline()
            pipe.set(f"{self.REDIS_PREFIX}{request_id}", json.dumps(data))
            if old_status and old_status != status:
                pipe.srem(f"{self.REDIS_INDEX_STATUS}{old_status}", request_id)
            pipe.sadd(f"{self.REDIS_INDEX_STATUS}{status}", request_id)
            pipe.execute()
            return True
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Redis respond failed: %s", e)
            return result

    async def close(self) -> None:
        await self._fallback.close()
        if self._redis_client:
            try:
                self._redis_client.close()
            except (ConnectionError, OSError) as e:
                logger.debug("Redis close failed (connection already closed): %s", e)
            except (RuntimeError, ValueError) as e:
                logger.debug("Redis close failed: %s", e)


class PostgresApprovalRequestStore(GenericPostgresStore, ApprovalRequestStoreBackend):
    """
    PostgreSQL-backed approval request store.

    Async implementation for production multi-instance deployments
    with horizontal scaling and concurrent writes.
    """

    TABLE_NAME = "approval_requests"
    PRIMARY_KEY = "request_id"
    SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS approval_requests (
            request_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            requester_id TEXT,
            responder_id TEXT,
            priority INTEGER DEFAULT 3,
            workspace_id TEXT,
            expires_at TEXT,
            responded_at TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            data_json JSONB NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status);
        CREATE INDEX IF NOT EXISTS idx_approval_workflow ON approval_requests(workflow_id);
        CREATE INDEX IF NOT EXISTS idx_approval_expires ON approval_requests(expires_at);
        CREATE INDEX IF NOT EXISTS idx_approval_workspace ON approval_requests(workspace_id);
    """
    INDEX_COLUMNS = {
        "workflow_id",
        "step_id",
        "title",
        "status",
        "requester_id",
        "responder_id",
        "priority",
        "workspace_id",
        "expires_at",
        "responded_at",
    }

    async def list_by_status(self, status: str) -> list[dict[str, Any]]:
        return await self._query_by_column(
            "status", status, order_by="priority ASC, created_at DESC"
        )

    async def list_by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        return await self._query_by_column("workflow_id", workflow_id)

    async def list_pending(self) -> list[dict[str, Any]]:
        return await self._query_with_sql(
            "status = 'pending'", order_by="priority ASC, created_at DESC"
        )

    async def list_expired(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        return await self._query_with_sql(
            "status = 'pending' AND expires_at IS NOT NULL AND expires_at < $1",
            (now,),
            order_by="expires_at ASC",
        )

    async def respond(
        self,
        request_id: str,
        status: str,
        responder_id: str,
        response_data: dict[str, Any] | None = None,
    ) -> bool:
        updates: dict[str, Any] = {
            "status": status,
            "responder_id": responder_id,
            "responded_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if response_data is not None:
            updates["response_data"] = response_data

        return await self._update_json_field(
            request_id,
            updates,
            extra_column_updates={
                "status": status,
                "responder_id": responder_id,
                "responded_at": updates["responded_at"],
            },
        )

    # Backward-compatible async aliases
    async def get_async(self, request_id: str) -> dict[str, Any] | None:
        return await self.get(request_id)

    async def save_async(self, data: dict[str, Any]) -> None:
        return await self.save(data)

    async def delete_async(self, request_id: str) -> bool:
        return await self.delete(request_id)

    async def list_all_async(self) -> list[dict[str, Any]]:
        return await self.list_all()

    async def list_by_status_async(self, status: str) -> list[dict[str, Any]]:
        return await self.list_by_status(status)

    async def list_by_workflow_async(self, workflow_id: str) -> list[dict[str, Any]]:
        return await self.list_by_workflow(workflow_id)

    async def list_pending_async(self) -> list[dict[str, Any]]:
        return await self.list_pending()

    async def list_expired_async(self) -> list[dict[str, Any]]:
        return await self.list_expired()

    async def respond_async(
        self,
        request_id: str,
        status: str,
        responder_id: str,
        response_data: dict[str, Any] | None = None,
    ) -> bool:
        return await self.respond(request_id, status, responder_id, response_data)


def get_approval_request_store() -> ApprovalRequestStoreBackend:
    """
    Get the global approval request store instance.

    Backend is selected based on ARAGORA_APPROVAL_STORE_BACKEND env var:
    - "memory": InMemoryApprovalRequestStore (for testing)
    - "sqlite": SQLiteApprovalRequestStore (single-instance)
    - "postgres", "postgresql", or "supabase": PostgresApprovalRequestStore (multi-instance)
    - "redis": RedisApprovalRequestStore (multi-instance)

    Also checks ARAGORA_DB_BACKEND for global database backend selection.
    Uses unified Supabase → PostgreSQL → SQLite preference order.
    """
    global _approval_request_store

    with _store_lock:
        if _approval_request_store is not None:
            return _approval_request_store

        # Check store-specific backend first, then global database backend
        backend = os.getenv("ARAGORA_APPROVAL_STORE_BACKEND")
        if not backend:
            backend = os.getenv("ARAGORA_DB_BACKEND", "auto")
        backend = backend.lower()

        # Redis is handled specially (uses SQLite fallback internally)
        if backend == "redis":
            _approval_request_store = RedisApprovalRequestStore()
            logger.info("Using Redis approval request store")
            return _approval_request_store

        # Use unified factory for memory/sqlite/postgres/supabase
        from aragora.storage.connection_factory import create_persistent_store

        _approval_request_store = create_persistent_store(
            store_name="approval",
            sqlite_class=SQLiteApprovalRequestStore,
            postgres_class=PostgresApprovalRequestStore,
            db_filename="approval_requests.db",
            memory_class=InMemoryApprovalRequestStore,
        )

        return _approval_request_store


def set_approval_request_store(store: ApprovalRequestStoreBackend) -> None:
    """Set a custom approval request store instance."""
    global _approval_request_store

    with _store_lock:
        _approval_request_store = store


def reset_approval_request_store() -> None:
    """Reset the global approval request store (for testing)."""
    global _approval_request_store

    with _store_lock:
        _approval_request_store = None


__all__ = [
    "ApprovalRequestItem",
    "ApprovalRequestStoreBackend",
    "InMemoryApprovalRequestStore",
    "SQLiteApprovalRequestStore",
    "RedisApprovalRequestStore",
    "PostgresApprovalRequestStore",
    "get_approval_request_store",
    "set_approval_request_store",
    "reset_approval_request_store",
]
