"""
Base Repository class for database access abstraction.

Provides common patterns for CRUD operations with SQLite,
including connection management, transactions, and error handling.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generic, TypeVar
from collections.abc import Generator

from aragora.config import DB_TIMEOUT_SECONDS, resolve_db_path
from aragora.storage.schema import DatabaseManager

logger = logging.getLogger(__name__)

# =============================================================================
# SQL Injection Protection
# =============================================================================

# Valid SQL identifier pattern: alphanumeric and underscores, must start with letter/underscore
_SQL_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Maximum length for SQL identifiers (SQLite limit is 255, we use 128 for safety)
_MAX_IDENTIFIER_LENGTH = 128


def _validate_sql_identifier(name: str, context: str = "identifier") -> str:
    """
    Validate and return a safe SQL identifier.

    Prevents SQL injection by ensuring identifiers only contain safe characters.

    Args:
        name: The identifier to validate (table name, column name, etc.)
        context: Description for error messages (e.g., "table name", "column")

    Returns:
        The validated identifier (unchanged if valid)

    Raises:
        ValueError: If the identifier is invalid or potentially malicious
    """
    if not name:
        raise ValueError(f"Empty {context} not allowed")

    if len(name) > _MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"{context} too long: {len(name)} > {_MAX_IDENTIFIER_LENGTH}")

    if not _SQL_IDENTIFIER_PATTERN.match(name):
        raise ValueError(
            f"Invalid {context}: '{name[:50]}' - must contain only "
            "alphanumeric characters and underscores, starting with a letter or underscore"
        )

    # Additional check for SQL keywords that could be dangerous
    sql_keywords = frozenset(
        {
            "DROP",
            "DELETE",
            "TRUNCATE",
            "ALTER",
            "CREATE",
            "INSERT",
            "UPDATE",
            "EXEC",
            "EXECUTE",
            "UNION",
            "SELECT",
            "--",
            ";",
        }
    )
    if name.upper() in sql_keywords:
        raise ValueError(f"SQL keyword not allowed as {context}: '{name}'")

    return name


def _validate_where_clause(where: str) -> str:
    """
    Validate a WHERE clause for basic safety.

    This is a defense-in-depth measure. The WHERE clause should still use
    parameterized queries for values.

    Args:
        where: The WHERE clause (without the WHERE keyword)

    Returns:
        The validated WHERE clause

    Raises:
        ValueError: If the WHERE clause contains dangerous patterns
    """
    if not where:
        return where

    # Check for dangerous patterns (case-insensitive)
    where_upper = where.upper()
    dangerous_patterns = [
        "'",
        '"',
        ";",
        "--",
        "/*",
        "*/",
        "UNION SELECT",
        "UNION ALL",
        "EXEC(",
        "EXECUTE(",
    ]

    for pattern in dangerous_patterns:
        if pattern in where_upper:
            logger.warning("Potentially dangerous WHERE clause rejected: %s", where[:100])
            raise ValueError("WHERE clause contains forbidden pattern")

    return where


# Type variable for entities
T = TypeVar("T")


class RepositoryError(Exception):
    """Base exception for repository errors."""

    pass


class EntityNotFoundError(RepositoryError):
    """Raised when an entity is not found."""

    def __init__(self, entity_type: str, entity_id: str) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        super().__init__(f"{entity_type} not found: {entity_id}")


class BaseRepository(ABC, Generic[T]):
    """
    Abstract base class for repositories.

    Provides common database operations and connection management.
    Subclasses implement entity-specific logic.

    Usage:
        class DebateRepository(BaseRepository[Debate]):
            def __init__(self, db_path: str = "debates.db"):
                super().__init__(db_path)

            def _to_entity(self, row: sqlite3.Row) -> Debate:
                return Debate(id=row["id"], ...)

            def _from_entity(self, entity: Debate) -> dict[str, Any]:
                return {"id": entity.id, ...}
    """

    def __init__(
        self,
        db_path: str | Path,
        timeout: float = DB_TIMEOUT_SECONDS,
        use_wal: bool = True,
    ) -> None:
        """
        Initialize the repository.

        Args:
            db_path: Path to the SQLite database file.
            timeout: Connection timeout in seconds.
            use_wal: Whether to use WAL mode for better concurrency.
        """
        # Resolve the database path to the data directory
        resolved_path = resolve_db_path(str(db_path))
        self._db_path = Path(resolved_path)
        self._timeout = timeout
        self._use_wal = use_wal
        # Use centralized DatabaseManager for connection pooling
        self._db_manager = DatabaseManager.get_instance(str(self._db_path), timeout)
        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        """Get the database path."""
        return self._db_path

    @contextmanager
    def _connection(self, readonly: bool = False) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a database connection with proper configuration.

        Uses DatabaseManager for connection pooling and WAL mode.

        Args:
            readonly: If True, opens connection in read-only mode.
                     Note: read-only mode bypasses connection pooling.

        Yields:
            Configured SQLite connection.
        """
        if readonly:
            # Read-only mode uses direct connection (no pooling)
            uri = f"file:{self._db_path}?mode=ro"
            conn = sqlite3.connect(
                uri,
                uri=True,
                timeout=self._timeout,
            )
            try:
                conn.row_factory = sqlite3.Row
                yield conn
            finally:
                conn.close()
        else:
            # Use pooled connection from DatabaseManager
            with self._db_manager.fresh_connection() as conn:
                conn.row_factory = sqlite3.Row
                yield conn

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Execute operations within a transaction.

        Automatically commits on success, rolls back on exception.

        Yields:
            Connection with active transaction.

        Example:
            with self._transaction() as conn:
                conn.execute("INSERT INTO ...")
                conn.execute("UPDATE ...")
        """
        with self._connection() as conn:
            try:
                yield conn
                conn.commit()
            except Exception as e:  # noqa: BLE001 - rollback before re-raising
                logger.debug("Transaction rolled back: %s", e)
                conn.rollback()
                raise

    def _execute(
        self,
        query: str,
        params: tuple = (),
        readonly: bool = False,
    ) -> sqlite3.Cursor:
        """
        Execute a single query.

        Args:
            query: SQL query string.
            params: Query parameters.
            readonly: Whether this is a read-only query.

        Returns:
            Cursor with results.
        """
        with self._connection(readonly=readonly) as conn:
            return conn.execute(query, params)

    def _execute_many(
        self,
        query: str,
        params_list: list[tuple],
    ) -> int:
        """
        Execute a query with multiple parameter sets.

        Args:
            query: SQL query string.
            params_list: List of parameter tuples.

        Returns:
            Number of rows affected.
        """
        with self._transaction() as conn:
            cursor = conn.executemany(query, params_list)
            return cursor.rowcount

    def _fetch_one(
        self,
        query: str,
        params: tuple = (),
    ) -> sqlite3.Row | None:
        """
        Fetch a single row.

        Args:
            query: SQL query string.
            params: Query parameters.

        Returns:
            Row or None if not found.
        """
        with self._connection(readonly=True) as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchone()

    def _fetch_all(
        self,
        query: str,
        params: tuple = (),
    ) -> list[sqlite3.Row]:
        """
        Fetch all rows.

        Args:
            query: SQL query string.
            params: Query parameters.

        Returns:
            List of rows.
        """
        with self._connection(readonly=True) as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchall()

    def _count(self, table: str, where: str = "", params: tuple = ()) -> int:
        """
        Count rows in a table.

        Args:
            table: Table name (validated for SQL safety).
            where: Optional WHERE clause (without WHERE keyword, validated).
            params: Query parameters.

        Returns:
            Number of matching rows.

        Raises:
            ValueError: If table name or WHERE clause contains invalid characters.
        """
        # Validate inputs to prevent SQL injection
        safe_table = _validate_sql_identifier(table, "table name")
        safe_where = _validate_where_clause(where)

        # nosec B608: table name is regex-validated, where is validated for dangerous patterns, values are parameterized
        query = f"SELECT COUNT(*) FROM {safe_table}"  # nosec B608
        if safe_where:
            query += f" WHERE {safe_where}"  # nosec B608

        row = self._fetch_one(query, params)
        return row[0] if row else 0

    def _exists(self, table: str, where: str, params: tuple) -> bool:
        """
        Check if rows exist.

        Args:
            table: Table name (validated for SQL safety).
            where: WHERE clause (without WHERE keyword, validated).
            params: Query parameters.

        Returns:
            True if at least one row matches.

        Raises:
            ValueError: If table name or WHERE clause contains invalid characters.
        """
        return self._count(table, where, params) > 0

    @abstractmethod
    def _ensure_schema(self) -> None:
        """
        Ensure the database schema exists.

        Called during initialization. Implementations should create
        tables and indexes if they don't exist.
        """
        pass

    @abstractmethod
    def _to_entity(self, row: sqlite3.Row) -> T:
        """
        Convert a database row to an entity.

        Args:
            row: SQLite row with column data.

        Returns:
            Entity instance.
        """
        pass

    @abstractmethod
    def _from_entity(self, entity: T) -> dict[str, Any]:
        """
        Convert an entity to database columns.

        Args:
            entity: Entity instance.

        Returns:
            Dictionary of column name -> value.
        """
        pass

    # Common CRUD operations (can be overridden)

    def get(self, entity_id: str) -> T | None:
        """
        Get an entity by ID.

        Args:
            entity_id: Entity identifier.

        Returns:
            Entity or None if not found.
        """
        # nosec B608: _table_name is abstract property returning constant, entity_id is parameterized
        row = self._fetch_one(
            f"SELECT * FROM {self._table_name} WHERE id = ?",  # nosec B608
            (entity_id,),
        )
        return self._to_entity(row) if row else None

    def get_or_raise(self, entity_id: str) -> T:
        """
        Get an entity by ID or raise EntityNotFoundError.

        Args:
            entity_id: Entity identifier.

        Returns:
            Entity instance.

        Raises:
            EntityNotFoundError: If entity not found.
        """
        entity = self.get(entity_id)
        if entity is None:
            raise EntityNotFoundError(self._entity_name, entity_id)
        return entity

    def save(self, entity: T) -> str:
        """
        Save an entity (insert or update).

        Args:
            entity: Entity to save.

        Returns:
            Entity ID.
        """
        data = self._from_entity(entity)
        columns = list(data.keys())
        placeholders = ",".join("?" * len(columns))
        updates = ",".join(f"{col}=excluded.{col}" for col in columns if col != "id")

        # nosec B608: _table_name is abstract property returning constant, columns from entity schema, values parameterized
        query = f"""
            INSERT INTO {self._table_name} ({",".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(id) DO UPDATE SET {updates}
        """  # nosec B608

        with self._transaction() as conn:
            conn.execute(query, tuple(data.values()))

        return data.get("id", "")

    def delete(self, entity_id: str) -> bool:
        """
        Delete an entity by ID.

        Args:
            entity_id: Entity identifier.

        Returns:
            True if entity was deleted, False if not found.
        """
        with self._transaction() as conn:
            # nosec B608: _table_name is abstract property returning constant, entity_id is parameterized
            cursor = conn.execute(
                f"DELETE FROM {self._table_name} WHERE id = ?",  # nosec B608
                (entity_id,),
            )
            return cursor.rowcount > 0

    def list_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        """
        List all entities with pagination.

        Args:
            limit: Maximum number of entities to return.
            offset: Number of entities to skip.

        Returns:
            List of entities.
        """
        # nosec B608: _table_name is abstract property returning constant, limit/offset are parameterized
        rows = self._fetch_all(
            f"SELECT * FROM {self._table_name} LIMIT ? OFFSET ?",  # nosec B608
            (limit, offset),
        )
        return [self._to_entity(row) for row in rows]

    def count(self) -> int:
        """
        Count total entities.

        Returns:
            Number of entities.
        """
        return self._count(self._table_name)

    @property
    @abstractmethod
    def _table_name(self) -> str:
        """Get the main table name for this repository."""
        pass

    @property
    def _entity_name(self) -> str:
        """Get the entity name for error messages."""
        return self._table_name.rstrip("s").title()
