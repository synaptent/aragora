"""
Generic Store Backend - Eliminates boilerplate across 40+ storage modules.

Provides base implementations for the common "abstract + InMemory + SQLite + Postgres"
pattern used throughout aragora/storage/. Each store typically has:

  1. Abstract backend (~50 lines) with get/save/delete/list_all
  2. InMemory implementation (~100 lines) for testing
  3. SQLite implementation (~250 lines) with data_json blob pattern
  4. Postgres implementation (~200 lines) with async pool
  5. Singleton factory (~30 lines)

This module provides generic versions of 1-5, so domain stores only need to
define their table schema, primary key, and domain-specific query methods.

Usage:
    from aragora.storage.generic_store import (
        GenericStoreBackend,
        GenericInMemoryStore,
        GenericSQLiteStore,
        GenericPostgresStore,
        create_store_factory,
    )

    # Define domain abstract class with extra methods
    class ApprovalRequestStoreBackend(GenericStoreBackend):
        @abstractmethod
        async def list_by_status(self, status: str) -> list[dict[str, Any]]:
            ...

    # SQLite implementation - only define domain-specific methods
    class SQLiteApprovalRequestStore(GenericSQLiteStore, ApprovalRequestStoreBackend):
        TABLE_NAME = "approval_requests"
        PRIMARY_KEY = "request_id"
        SCHEMA_SQL = '''
            CREATE TABLE IF NOT EXISTS approval_requests (
                request_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                workflow_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                data_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_status ON approval_requests(status);
        '''
        INDEX_COLUMNS = {"status", "workflow_id"}

        async def list_by_status(self, status: str) -> list[dict[str, Any]]:
            return self._query_by_column("status", status)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.config import resolve_db_path

if TYPE_CHECKING:
    from asyncpg import Pool

logger = logging.getLogger(__name__)


# =============================================================================
# Abstract Base
# =============================================================================


class GenericStoreBackend(ABC):
    """
    Abstract base for all store backends.

    Provides the universal CRUD interface that every store implements.
    Domain stores extend this with additional query/mutation methods.
    """

    @abstractmethod
    async def get(self, item_id: str) -> dict[str, Any] | None:
        """Get item by primary key."""
        ...

    @abstractmethod
    async def save(self, data: dict[str, Any]) -> None:
        """Save (upsert) item data."""
        ...

    @abstractmethod
    async def delete(self, item_id: str) -> bool:
        """Delete item. Returns True if item existed."""
        ...

    @abstractmethod
    async def list_all(self) -> list[dict[str, Any]]:
        """List all items."""
        ...

    async def exists(self, item_id: str) -> bool:
        """Check if item exists."""
        return await self.get(item_id) is not None

    async def count(self) -> int:
        """Count all items."""
        return len(await self.list_all())

    async def close(self) -> None:
        """Close resources. Default no-op."""
        pass


# =============================================================================
# In-Memory Implementation
# =============================================================================


class GenericInMemoryStore(GenericStoreBackend):
    """
    Thread-safe in-memory store for testing.

    Subclasses only need to set PRIMARY_KEY and implement domain-specific methods.
    """

    PRIMARY_KEY: str = "id"

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    async def get(self, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._data.get(item_id)

    async def save(self, data: dict[str, Any]) -> None:
        item_id = data.get(self.PRIMARY_KEY)
        if not item_id:
            raise ValueError(f"{self.PRIMARY_KEY} is required")
        with self._lock:
            self._data[item_id] = data

    async def delete(self, item_id: str) -> bool:
        with self._lock:
            if item_id in self._data:
                del self._data[item_id]
                return True
            return False

    async def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._data.values())

    async def exists(self, item_id: str) -> bool:
        with self._lock:
            return item_id in self._data

    async def count(self) -> int:
        with self._lock:
            return len(self._data)

    def _filter_by(self, key: str, value: Any) -> list[dict[str, Any]]:
        """Helper: filter items by a field value (thread-safe)."""
        with self._lock:
            return [item for item in self._data.values() if item.get(key) == value]


# =============================================================================
# SQLite Implementation (data_json blob pattern)
# =============================================================================


class GenericSQLiteStore(GenericStoreBackend):
    """
    Thread-safe SQLite store using the data_json blob pattern.

    Stores the full dict as JSON in a `data_json` column, with selected
    columns extracted alongside for indexed queries.

    Subclasses must define:
        TABLE_NAME: str        - SQL table name
        PRIMARY_KEY: str       - Primary key column name
        SCHEMA_SQL: str        - CREATE TABLE + CREATE INDEX DDL
        INDEX_COLUMNS: set     - Columns extracted from data_json for indexing

    Subclasses may override:
        _extract_columns(data) - Extract indexed columns from data dict
    """

    TABLE_NAME: str = ""
    PRIMARY_KEY: str = "id"
    SCHEMA_SQL: str = ""
    INDEX_COLUMNS: set[str] = set()

    def __init__(self, db_path: Path | str | None = None) -> None:
        if not self.TABLE_NAME:
            raise ValueError("TABLE_NAME must be set")
        if not self.SCHEMA_SQL:
            raise ValueError("SCHEMA_SQL must be set")

        if db_path is None:
            db_path = Path(f"{self.TABLE_NAME}.db")

        self._db_path = Path(resolve_db_path(db_path))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                conn.executescript(self.SCHEMA_SQL)
                conn.commit()
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection."""
        return sqlite3.connect(str(self._db_path))

    def _extract_columns(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract indexed columns from data dict.

        Override this to customize column extraction. Default extracts
        all INDEX_COLUMNS from the data dict.
        """
        result: dict[str, Any] = {}
        for col in self.INDEX_COLUMNS:
            if col in data:
                result[col] = data[col]
        return result

    async def get(self, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    # table/column name interpolation, parameterized
                    f"SELECT data_json FROM {self.TABLE_NAME} WHERE {self.PRIMARY_KEY} = ?",
                    (item_id,),
                )
                row = cursor.fetchone()
                return json.loads(row[0]) if row else None
            finally:
                conn.close()

    async def save(self, data: dict[str, Any]) -> None:
        item_id = data.get(self.PRIMARY_KEY)
        if not item_id:
            raise ValueError(f"{self.PRIMARY_KEY} is required")

        now = time.time()
        data_json = json.dumps(data)
        extra_cols = self._extract_columns(data)

        # Build column list: primary_key, index columns, timestamps, data_json
        columns = [self.PRIMARY_KEY]
        values: list[Any] = [item_id]

        for col, val in extra_cols.items():
            columns.append(col)
            values.append(val)

        columns.extend(["created_at", "updated_at", "data_json"])
        values.extend([now, now, data_json])

        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(columns)

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    # table/column name interpolation, parameterized
                    f"INSERT OR REPLACE INTO {self.TABLE_NAME} ({col_names}) VALUES ({placeholders})",
                    values,
                )
                conn.commit()
            finally:
                conn.close()

    async def delete(self, item_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    # table/column name interpolation, parameterized
                    f"DELETE FROM {self.TABLE_NAME} WHERE {self.PRIMARY_KEY} = ?",
                    (item_id,),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    async def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    # table name interpolation, parameterized
                    f"SELECT data_json FROM {self.TABLE_NAME} ORDER BY created_at DESC"
                )
                return [json.loads(row[0]) for row in cursor.fetchall()]
            finally:
                conn.close()

    async def exists(self, item_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    # table/column name interpolation, parameterized
                    f"SELECT 1 FROM {self.TABLE_NAME} WHERE {self.PRIMARY_KEY} = ?",
                    (item_id,),
                )
                return cursor.fetchone() is not None
            finally:
                conn.close()

    async def count(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                # table name interpolation, parameterized
                cursor = conn.execute(f"SELECT COUNT(*) FROM {self.TABLE_NAME}")
                row = cursor.fetchone()
                return row[0] if row else 0
            finally:
                conn.close()

    def _query_by_column(
        self,
        column: str,
        value: Any,
        order_by: str = "created_at DESC",
    ) -> list[dict[str, Any]]:
        """Helper: query items by an indexed column value."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    # table/column name interpolation, parameterized
                    f"SELECT data_json FROM {self.TABLE_NAME} WHERE {column} = ? ORDER BY {order_by}",
                    (value,),
                )
                return [json.loads(row[0]) for row in cursor.fetchall()]
            finally:
                conn.close()

    def _query_with_sql(
        self,
        where_clause: str,
        params: tuple[Any, ...] = (),
        order_by: str = "created_at DESC",
    ) -> list[dict[str, Any]]:
        """Helper: query items with custom WHERE clause."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    # table name interpolation, parameterized
                    f"SELECT data_json FROM {self.TABLE_NAME} WHERE {where_clause} ORDER BY {order_by}",
                    params,
                )
                return [json.loads(row[0]) for row in cursor.fetchall()]
            finally:
                conn.close()

    def _update_json_field(
        self,
        item_id: str,
        updates: dict[str, Any],
        extra_column_updates: dict[str, Any] | None = None,
    ) -> bool:
        """Helper: update specific fields in the data_json blob."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    # table/column name interpolation, parameterized
                    f"SELECT data_json FROM {self.TABLE_NAME} WHERE {self.PRIMARY_KEY} = ?",
                    (item_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return False

                data = json.loads(row[0])
                data.update(updates)

                # Build SET clause
                set_parts = ["updated_at = ?", "data_json = ?"]
                values: list[Any] = [time.time(), json.dumps(data)]

                if extra_column_updates:
                    for col, val in extra_column_updates.items():
                        set_parts.append(f"{col} = ?")
                        values.append(val)

                values.append(item_id)
                set_clause = ", ".join(set_parts)

                conn.execute(
                    # table/column name interpolation, parameterized
                    f"UPDATE {self.TABLE_NAME} SET {set_clause} WHERE {self.PRIMARY_KEY} = ?",
                    values,
                )
                conn.commit()
                return True
            finally:
                conn.close()


# =============================================================================
# PostgreSQL Implementation
# =============================================================================


class GenericPostgresStore(GenericStoreBackend):
    """
    Async PostgreSQL store using connection pooling.

    Stores data as JSONB in a `data_json` column with indexed columns
    extracted alongside for queries.

    Subclasses must define:
        TABLE_NAME: str        - SQL table name
        PRIMARY_KEY: str       - Primary key column name
        SCHEMA_SQL: str        - CREATE TABLE + CREATE INDEX DDL (Postgres syntax)
        INDEX_COLUMNS: set     - Columns extracted from data_json for indexing
    """

    TABLE_NAME: str = ""
    PRIMARY_KEY: str = "id"
    SCHEMA_SQL: str = ""
    INDEX_COLUMNS: set[str] = set()

    def __init__(self, pool: Pool) -> None:
        if not self.TABLE_NAME:
            raise ValueError("TABLE_NAME must be set")
        self._pool = pool
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize schema. Call once before using the store."""
        if self._initialized:
            return
        if self.SCHEMA_SQL:
            async with self._pool.acquire() as conn:
                await conn.execute(self.SCHEMA_SQL)
        self._initialized = True

    def _extract_columns(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract indexed columns from data dict."""
        result: dict[str, Any] = {}
        for col in self.INDEX_COLUMNS:
            if col in data:
                result[col] = data[col]
        return result

    async def get(self, item_id: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                # table/column name interpolation, parameterized
                f"SELECT data_json FROM {self.TABLE_NAME} WHERE {self.PRIMARY_KEY} = $1",
                item_id,
            )
            if row:
                return self._parse_data_json(row["data_json"])
            return None

    async def save(self, data: dict[str, Any]) -> None:
        item_id = data.get(self.PRIMARY_KEY)
        if not item_id:
            raise ValueError(f"{self.PRIMARY_KEY} is required")

        now = datetime.now(timezone.utc)
        data_json = json.dumps(data)
        extra_cols = self._extract_columns(data)

        # Build column list
        columns = [self.PRIMARY_KEY]
        values: list[Any] = [item_id]

        for col, val in extra_cols.items():
            columns.append(col)
            values.append(val)

        columns.extend(["created_at", "updated_at", "data_json"])
        values.extend([now, now, data_json])

        # Build parameterized query
        col_names = ", ".join(columns)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))

        # Build ON CONFLICT update
        update_parts = [f"{col} = EXCLUDED.{col}" for col in columns if col != self.PRIMARY_KEY]
        update_clause = ", ".join(update_parts)

        async with self._pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.TABLE_NAME} ({col_names})
                VALUES ({placeholders})
                ON CONFLICT ({self.PRIMARY_KEY}) DO UPDATE SET {update_clause}
                """,  # table name interpolation, parameterized
                *values,
            )

    async def delete(self, item_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                # table/column name interpolation, parameterized
                f"DELETE FROM {self.TABLE_NAME} WHERE {self.PRIMARY_KEY} = $1",
                item_id,
            )
            return result == "DELETE 1"

    @staticmethod
    def _parse_data_json(value: Any) -> dict[str, Any]:
        """Parse data_json value (handles both str and dict from JSONB)."""
        if isinstance(value, dict):
            return value
        return json.loads(value)

    async def list_all(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                # table name interpolation, parameterized
                f"SELECT data_json FROM {self.TABLE_NAME} ORDER BY created_at DESC"
            )
            return [self._parse_data_json(row["data_json"]) for row in rows]

    async def exists(self, item_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                # table/column name interpolation, parameterized
                f"SELECT 1 FROM {self.TABLE_NAME} WHERE {self.PRIMARY_KEY} = $1",
                item_id,
            )
            return row is not None

    async def count(self) -> int:
        async with self._pool.acquire() as conn:
            # table name interpolation, parameterized
            row = await conn.fetchrow(f"SELECT COUNT(*) as cnt FROM {self.TABLE_NAME}")
            return row["cnt"] if row else 0

    async def _query_by_column(
        self,
        column: str,
        value: Any,
        order_by: str = "created_at DESC",
    ) -> list[dict[str, Any]]:
        """Helper: query items by an indexed column value."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                # table/column name interpolation, parameterized
                f"SELECT data_json FROM {self.TABLE_NAME} WHERE {column} = $1 ORDER BY {order_by}",
                value,
            )
            return [self._parse_data_json(row["data_json"]) for row in rows]

    async def _query_with_sql(
        self,
        where_clause: str,
        params: tuple[Any, ...] = (),
        order_by: str = "created_at DESC",
    ) -> list[dict[str, Any]]:
        """Helper: query with custom WHERE clause."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                # table name interpolation, parameterized
                f"SELECT data_json FROM {self.TABLE_NAME} WHERE {where_clause} ORDER BY {order_by}",
                *params,
            )
            return [self._parse_data_json(row["data_json"]) for row in rows]

    async def _update_json_field(
        self,
        item_id: str,
        updates: dict[str, Any],
        extra_column_updates: dict[str, Any] | None = None,
    ) -> bool:
        """Helper: update specific fields in the data_json blob."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                # table/column name interpolation, parameterized
                f"SELECT data_json FROM {self.TABLE_NAME} WHERE {self.PRIMARY_KEY} = $1",
                item_id,
            )
            if not row:
                return False

            data = self._parse_data_json(row["data_json"])
            data.update(updates)

            # Build SET clause
            set_parts = ["updated_at = $1", "data_json = $2"]
            values: list[Any] = [datetime.now(timezone.utc), json.dumps(data)]
            param_idx = 3

            if extra_column_updates:
                for col, val in extra_column_updates.items():
                    set_parts.append(f"{col} = ${param_idx}")
                    values.append(val)
                    param_idx += 1

            values.append(item_id)
            set_clause = ", ".join(set_parts)

            await conn.execute(
                # table/column name interpolation, parameterized
                f"UPDATE {self.TABLE_NAME} SET {set_clause} WHERE {self.PRIMARY_KEY} = ${param_idx}",
                *values,
            )
            return True


# =============================================================================
# Factory Helper
# =============================================================================


def create_store_factory(
    *,
    store_name: str,
    sqlite_class: type[GenericSQLiteStore],
    postgres_class: type[GenericPostgresStore] | None = None,
    memory_class: type[GenericInMemoryStore] | None = None,
    default_db_name: str | None = None,
) -> tuple:
    """
    Create get_xxx_store() and set_xxx_store() factory functions.

    Returns:
        Tuple of (get_store, set_store) functions

    Usage:
        get_approval_store, set_approval_store = create_store_factory(
            store_name="approval_request",
            sqlite_class=SQLiteApprovalRequestStore,
            postgres_class=PostgresApprovalRequestStore,
        )
    """
    _store: GenericStoreBackend | None = None
    _lock = threading.RLock()

    def get_store() -> GenericStoreBackend:
        nonlocal _store
        if _store is None:
            with _lock:
                if _store is None:
                    # Check for Postgres
                    use_pg = os.environ.get("ARAGORA_USE_POSTGRES", "").lower() in (
                        "1",
                        "true",
                        "yes",
                    )
                    if use_pg and postgres_class is not None:
                        try:
                            from aragora.storage.postgres_store import get_postgres_pool

                            pool = get_postgres_pool()
                            if pool:
                                _store = postgres_class(pool)
                                logger.info("[%s] Using PostgreSQL backend", store_name)
                                return _store
                        except (ImportError, RuntimeError) as e:
                            logger.warning(
                                "[%s] Postgres unavailable, falling back to SQLite: %s",
                                store_name,
                                e,
                            )

                    # Default to SQLite
                    db_name = default_db_name or f"{store_name}.db"
                    _store = sqlite_class(Path(db_name))
                    logger.debug("[%s] Using SQLite backend", store_name)
        return _store

    def set_store(store: GenericStoreBackend) -> None:
        nonlocal _store
        _store = store

    return get_store, set_store


__all__ = [
    "GenericStoreBackend",
    "GenericInMemoryStore",
    "GenericSQLiteStore",
    "GenericPostgresStore",
    "create_store_factory",
]
