"""
Base SQLite store with integrated schema management.

Combines BaseDatabase functionality with SchemaManager for a unified pattern
that reduces boilerplate across the 26+ store implementations in Aragora.

Usage:
    from aragora.storage.base_store import SQLiteStore

    class MyStore(SQLiteStore):
        SCHEMA_NAME = "my_store"
        SCHEMA_VERSION = 1

        INITIAL_SCHEMA = '''
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
        '''

        def save_item(self, item_id: str, name: str) -> None:
            with self.connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO items (id, name) VALUES (?, ?)",
                    (item_id, name)
                )
"""

from __future__ import annotations

import logging
import sqlite3
from abc import ABC
from pathlib import Path

from aragora.config import DB_TIMEOUT_SECONDS
from aragora.config import resolve_db_path
from aragora.storage.base_database import BaseDatabase
from aragora.storage.schema import SchemaManager, safe_add_column

logger = logging.getLogger(__name__)


class SQLiteStore(BaseDatabase, ABC):
    """
    Base class for SQLite-backed stores with schema management.

    Provides:
    - Thread-safe connection management (via BaseDatabase)
    - WAL mode for concurrent access
    - Schema versioning and migrations (via SchemaManager)
    - Common CRUD helpers

    Subclasses must define:
    - SCHEMA_NAME: Unique identifier for schema versioning
    - SCHEMA_VERSION: Current schema version number
    - INITIAL_SCHEMA: SQL for initial table/index creation

    Optionally override:
    - register_migrations(): Add version migrations
    - _post_init(): Additional initialization after schema

    Example:
        class TodoStore(SQLiteStore):
            SCHEMA_NAME = "todo_store"
            SCHEMA_VERSION = 2

            INITIAL_SCHEMA = '''
                CREATE TABLE IF NOT EXISTS todos (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    completed INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            '''

            def register_migrations(self, manager: SchemaManager) -> None:
                manager.register_migration(
                    from_version=1,
                    to_version=2,
                    sql="ALTER TABLE todos ADD COLUMN priority INTEGER DEFAULT 0;",
                    description="Add priority field"
                )

            def add_todo(self, todo_id: str, title: str) -> None:
                with self.connection() as conn:
                    conn.execute(
                        "INSERT INTO todos (id, title) VALUES (?, ?)",
                        (todo_id, title)
                    )
    """

    # Subclasses must define these
    SCHEMA_NAME: str = ""
    SCHEMA_VERSION: int = 1
    INITIAL_SCHEMA: str = ""

    def __init__(
        self,
        db_path: str | Path,
        timeout: float = DB_TIMEOUT_SECONDS,
        auto_init: bool = True,
    ):
        """Initialize the store.

        Args:
            db_path: Path to SQLite database file
            timeout: Connection timeout in seconds
            auto_init: If True, initialize schema on construction
        """
        # Ensure parent directory exists
        db_path = Path(resolve_db_path(db_path))
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize base database
        super().__init__(db_path, timeout)

        # Validate subclass configuration
        if not self.SCHEMA_NAME:
            raise ValueError(f"{self.__class__.__name__} must define SCHEMA_NAME")
        if not self.INITIAL_SCHEMA:
            raise ValueError(f"{self.__class__.__name__} must define INITIAL_SCHEMA")

        # Initialize schema
        if auto_init:
            self._init_db()
            self._post_init()

    def _init_db(self) -> None:
        """Initialize database schema using SchemaManager.

        Creates tables, indexes, and runs any pending migrations.
        Called automatically during __init__ unless auto_init=False.
        """
        with self.connection() as conn:
            manager = SchemaManager(
                conn,
                self.SCHEMA_NAME,
                current_version=self.SCHEMA_VERSION,
            )

            # Allow subclasses to register migrations
            self.register_migrations(manager)

            # Apply schema (creates tables for new DBs, runs migrations for existing)
            manager.ensure_schema(initial_schema=self.INITIAL_SCHEMA)

            logger.debug(
                "[%s] Schema initialized at version %s", self.SCHEMA_NAME, self.SCHEMA_VERSION
            )

    def register_migrations(self, manager: SchemaManager) -> None:
        """Register schema migrations. Override in subclasses.

        Args:
            manager: SchemaManager to register migrations with

        Example:
            def register_migrations(self, manager: SchemaManager) -> None:
                manager.register_migration(
                    from_version=1,
                    to_version=2,
                    sql="ALTER TABLE items ADD COLUMN category TEXT;",
                    description="Add category field"
                )
                manager.register_migration(
                    from_version=2,
                    to_version=3,
                    function=self._migrate_v2_to_v3,
                    description="Normalize categories"
                )
        """
        pass

    def _post_init(self) -> None:
        """Called after schema initialization. Override for additional setup.

        Use for:
        - Loading cached data
        - Starting background tasks
        - Initializing related resources
        """
        pass

    # =========================================================================
    # Common CRUD Helpers
    # =========================================================================

    def exists(self, table: str, id_column: str, id_value: str) -> bool:
        """Check if a record exists.

        Args:
            table: Table name (must be alphanumeric/underscore only)
            id_column: Column name for ID lookup
            id_value: Value to check

        Returns:
            True if record exists
        """
        # Validate table/column names to prevent injection
        if not table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {table}")
        if not id_column.replace("_", "").isalnum():
            raise ValueError(f"Invalid column name: {id_column}")

        query = f"SELECT 1 FROM {table} WHERE {id_column} = ?"  # nosec B608
        row = self.fetch_one(query, (id_value,))
        return row is not None

    def _validate_where_clause(self, where: str, has_params: bool) -> None:
        """Validate WHERE clause for SQL injection patterns.

        Args:
            where: The WHERE clause to validate
            has_params: Whether parameters were provided for placeholders

        Raises:
            ValueError: If WHERE clause contains injection patterns
        """
        if not where:
            return

        # Block obvious injection patterns
        dangerous = ["'", '"', ";", "--", "/*", "*/"]
        where_check = where.upper()
        for pattern in dangerous:
            if pattern.upper() in where_check:
                raise ValueError(
                    "WHERE clause contains unsafe pattern. "
                    "Use parameterized placeholders (?) instead of literal values."
                )

        # Warn if WHERE has no placeholders but also no params
        has_placeholder = "?" in where
        if not has_placeholder and not has_params:
            # Allow simple column checks like "deleted_at IS NULL"
            safe_patterns = ["IS NULL", "IS NOT NULL", "TRUE", "FALSE"]
            if not any(p in where_check for p in safe_patterns):
                logger.warning(
                    "WHERE clause without placeholders or params may indicate SQL injection risk: %s",
                    where[:50],
                )

    def count(self, table: str, where: str = "", params: tuple = ()) -> int:
        """Count records in a table.

        Args:
            table: Table name
            where: Optional WHERE clause (without "WHERE" keyword).
                   MUST use parameterized placeholders (?) for values.
                   Example: "status = ? AND user_id = ?"
            params: Parameter values for WHERE clause placeholders

        Returns:
            Record count

        Raises:
            ValueError: If table name is invalid or WHERE contains injection patterns

        Security:
            Never pass user input directly in the WHERE clause.
            Always use placeholders: count("users", "status = ?", ("active",))
        """
        if not table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {table}")

        self._validate_where_clause(where, bool(params))

        sql = f"SELECT COUNT(*) FROM {table}"  # nosec B608 - table validated above
        if where:
            sql += f" WHERE {where}"  # nosec B608 - validated by _validate_where_clause

        row = self.fetch_one(sql, params)
        return row[0] if row else 0

    def delete_by_id(self, table: str, id_column: str, id_value: str) -> bool:
        """Delete a record by ID.

        Args:
            table: Table name
            id_column: Column name for ID
            id_value: ID value to delete

        Returns:
            True if a record was deleted
        """
        if not table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {table}")
        if not id_column.replace("_", "").isalnum():
            raise ValueError(f"Invalid column name: {id_column}")

        with self.connection() as conn:
            query = f"DELETE FROM {table} WHERE {id_column} = ?"  # nosec B608
            cursor = conn.execute(query, (id_value,))
            return cursor.rowcount > 0

    def safe_add_column(
        self,
        table: str,
        column: str,
        col_type: str,
        default: str | None = None,
    ) -> None:
        """Safely add a column if it doesn't exist.

        Uses the validated safe_add_column from schema module.

        Args:
            table: Table name
            column: Column name to add
            col_type: SQLite column type (TEXT, INTEGER, REAL, etc.)
            default: Optional default value
        """
        with self.connection() as conn:
            safe_add_column(conn, table, column, col_type, default)

    def vacuum(self) -> None:
        """Reclaim unused space in the database.

        Should be called periodically for databases with heavy delete operations.
        """
        with self.connection() as conn:
            conn.execute("VACUUM")
            logger.debug("[%s] Database vacuumed", self.SCHEMA_NAME)

    def get_schema_version(self) -> int:
        """Get the current schema version from database.

        Returns:
            Current schema version, or 0 if not yet initialized
        """
        try:
            row = self.fetch_one(
                "SELECT version FROM _schema_versions WHERE module = ?", (self.SCHEMA_NAME,)
            )
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    def get_table_info(self, table: str) -> list[dict]:
        """Get column information for a table.

        Args:
            table: Table name

        Returns:
            List of dicts with column info (name, type, notnull, default, pk)
        """
        if not table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {table}")

        rows = self.fetch_all(f"PRAGMA table_info({table})")
        return [
            {
                "cid": row[0],
                "name": row[1],
                "type": row[2],
                "notnull": bool(row[3]),
                "default": row[4],
                "pk": bool(row[5]),
            }
            for row in rows
        ]


__all__ = ["SQLiteStore"]
