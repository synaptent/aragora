"""
SQL Database Connector - Evidence collection from SQL databases.

Supports PostgreSQL, MySQL, and SQLite databases.
Uses parameterized queries only to prevent SQL injection.

Usage:
    from aragora.connectors.sql import SQLConnector

    # Connect to PostgreSQL
    connector = SQLConnector(
        connection_string="postgresql://user:pass@localhost:5432/db"
    )

    # Search for evidence using a query template
    evidence = await connector.search(
        query="SELECT * FROM articles WHERE topic LIKE %s",
        params=("%AI safety%",),
        limit=10
    )

SECURITY:
- All queries use parameterized statements (no string interpolation)
- Connection strings should use environment variables, not hardcoded credentials
- Read-only queries recommended (SELECT only, no INSERT/UPDATE/DELETE)
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from collections.abc import Sequence

from aragora.connectors.base import BaseConnector, Evidence
from aragora.reasoning.provenance import ProvenanceManager, SourceType

logger = logging.getLogger(__name__)


@dataclass
class SQLQueryResult:
    """Result from a SQL query."""

    rows: list[dict[str, Any]]
    column_names: list[str]
    row_count: int
    query_time_ms: float
    database_type: str


class SQLConnector(BaseConnector):
    """
    SQL Database connector for evidence collection.

    Supports:
    - PostgreSQL (requires psycopg2 or asyncpg)
    - MySQL (requires aiomysql)
    - SQLite (uses built-in sqlite3, wrapped for async)

    Connection string formats:
    - PostgreSQL: postgresql://user:pass@host:port/database  # nosec
    - MySQL: mysql://user:pass@host:port/database  # nosec
    - SQLite: sqlite:///path/to/database.db or sqlite://:memory:

    IMPORTANT: Only parameterized queries are allowed.
    """

    # Max content length per evidence piece
    MAX_CONTENT_LENGTH = 10000

    # Query patterns that are blocked for security
    BLOCKED_PATTERNS = [
        r"\b(DROP|DELETE|TRUNCATE|ALTER|CREATE|INSERT|UPDATE)\b",
        r"--",  # SQL comments (potential injection)
        r";.*\b(SELECT|DROP|DELETE)\b",  # Multiple statements
    ]

    def __init__(
        self,
        connection_string: str | None = None,
        database_type: str | None = None,
        provenance: ProvenanceManager | None = None,
        default_confidence: float = 0.7,
        read_only: bool = True,
        query_timeout: float = 30.0,
    ):
        """
        Initialize SQL connector.

        Args:
            connection_string: Database connection string.
                              Can also use ARAGORA_SQL_CONNECTION env var.
            database_type: Force database type (postgresql, mysql, sqlite).
                          Auto-detected from connection string if not specified.
            provenance: Optional provenance manager for tracking.
            default_confidence: Default confidence score for evidence.
            read_only: If True, only SELECT queries are allowed.
            query_timeout: Query timeout in seconds.
        """
        super().__init__(provenance=provenance, default_confidence=default_confidence)

        self._connection_string = connection_string or os.environ.get("ARAGORA_SQL_CONNECTION")
        self._database_type = database_type or self._detect_database_type()
        self._read_only = read_only
        self._query_timeout = query_timeout
        self._connection: Any | None = None

    @property
    def source_type(self) -> SourceType:
        return SourceType.DATABASE

    @property
    def name(self) -> str:
        return f"SQL ({self._database_type or 'unknown'})"

    @property
    def is_available(self) -> bool:
        """Check if database connection is possible."""
        if not self._connection_string:
            return False

        db_type = self._database_type
        if db_type == "postgresql":
            try:
                import asyncpg  # noqa: F401

                return True
            except ImportError:
                try:
                    import psycopg2  # noqa: F401

                    return True
                except ImportError:
                    return False
        elif db_type == "mysql":
            try:
                import aiomysql  # noqa: F401

                return True
            except ImportError:
                return False
        elif db_type == "sqlite":
            return True  # Built-in
        return False

    def _detect_database_type(self) -> str | None:
        """Detect database type from connection string."""
        if not self._connection_string:
            return None

        conn = self._connection_string.lower()
        if conn.startswith("postgresql://") or conn.startswith("postgres://"):
            return "postgresql"
        elif conn.startswith("mysql://"):
            return "mysql"
        elif conn.startswith("sqlite://"):
            return "sqlite"
        return None

    def _validate_query(self, query: str) -> None:
        """
        Validate query for security.

        Raises ValueError if query contains blocked patterns.
        """
        if self._read_only:
            # Check for blocked patterns
            for pattern in self.BLOCKED_PATTERNS:
                if re.search(pattern, query, re.IGNORECASE):
                    raise ValueError(
                        "Query contains blocked pattern. "
                        "Only SELECT queries are allowed in read-only mode."
                    )

            # Ensure it's a SELECT query
            stripped = query.strip().upper()
            if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
                raise ValueError("Only SELECT queries are allowed in read-only mode.")

    async def _get_connection(self) -> Any:
        """Get or create database connection."""
        if self._connection is not None:
            return self._connection

        if not self._connection_string:
            raise ValueError("No connection string provided")

        db_type = self._database_type

        if db_type == "postgresql":
            try:
                import asyncpg

                self._connection = await asyncpg.connect(
                    self._connection_string,
                    timeout=self._query_timeout,
                )
            except ImportError:
                # Fall back to psycopg2 with sync wrapper
                import psycopg2

                self._connection = psycopg2.connect(self._connection_string)

        elif db_type == "mysql":
            import aiomysql

            # Parse connection string
            # mysql://user:pass@host:port/database  # nosec
            import urllib.parse

            parsed = urllib.parse.urlparse(self._connection_string)
            self._connection = await aiomysql.connect(
                host=parsed.hostname or "localhost",
                port=parsed.port or 3306,
                user=parsed.username or "root",
                password=parsed.password or "",
                db=parsed.path.lstrip("/"),
                connect_timeout=int(self._query_timeout),
            )

        elif db_type == "sqlite":
            import sqlite3

            # sqlite:///path/to/db.sqlite or sqlite://:memory:
            path = self._connection_string.replace("sqlite://", "")
            if path.startswith("/"):
                path = path[1:]  # Remove leading slash for relative paths
            elif path == ":memory:":
                pass  # Keep as-is for in-memory DB
            self._connection = sqlite3.connect(path, timeout=self._query_timeout)
            self._connection.row_factory = sqlite3.Row

        else:
            raise ValueError(f"Unsupported database type: {db_type}")

        return self._connection

    async def execute_query(
        self,
        query: str,
        params: Sequence[Any] | None = None,
    ) -> SQLQueryResult:
        """
        Execute a parameterized SQL query.

        Args:
            query: SQL query with parameter placeholders.
                  Use %s for PostgreSQL/MySQL, ? for SQLite.
            params: Query parameters (tuple or list).

        Returns:
            SQLQueryResult with rows and metadata.

        Raises:
            ValueError: If query is invalid or blocked.
        """
        import time

        self._validate_query(query)

        start_time = time.time()
        conn = await self._get_connection()

        rows: list[dict[str, Any]] = []
        column_names: list[str] = []

        try:
            db_type = self._database_type

            if db_type == "postgresql":
                # asyncpg uses $1, $2 style parameters
                # Convert %s to $1, $2, etc.
                converted_query = query
                if "%s" in query and params:
                    for i in range(len(params)):
                        converted_query = converted_query.replace("%s", f"${i + 1}", 1)

                if hasattr(conn, "fetch"):  # asyncpg
                    result = await conn.fetch(converted_query, *(params or []))
                    if result:
                        column_names = list(result[0].keys())
                        rows = [dict(row) for row in result]
                else:  # psycopg2
                    cursor = conn.cursor()
                    cursor.execute(query, params)
                    column_names = [desc[0] for desc in cursor.description or []]
                    rows = [dict(zip(column_names, row)) for row in cursor.fetchall()]
                    cursor.close()

            elif db_type == "mysql":
                async with conn.cursor() as cursor:
                    await cursor.execute(query, params)
                    column_names = [desc[0] for desc in cursor.description or []]
                    raw_rows = await cursor.fetchall()
                    rows = [dict(zip(column_names, row)) for row in raw_rows]

            elif db_type == "sqlite":
                cursor = conn.execute(query, params or [])
                column_names = [desc[0] for desc in cursor.description or []]
                rows = [dict(row) for row in cursor.fetchall()]

        except (OSError, ValueError, RuntimeError) as e:
            logger.error("SQL query failed: %s", e)
            raise

        elapsed_ms = (time.time() - start_time) * 1000

        return SQLQueryResult(
            rows=rows,
            column_names=column_names,
            row_count=len(rows),
            query_time_ms=elapsed_ms,
            database_type=self._database_type or "unknown",
        )

    def _row_to_evidence(
        self,
        row: dict[str, Any],
        content_column: str = "content",
        title_column: str = "title",
        id_column: str = "id",
        created_column: str = "created_at",
        author_column: str = "author",
    ) -> Evidence:
        """
        Convert a database row to Evidence object.

        Args:
            row: Dictionary representing a database row.
            content_column: Column name for main content.
            title_column: Column name for title.
            id_column: Column name for unique ID.
            created_column: Column name for creation timestamp.
            author_column: Column name for author.

        Returns:
            Evidence object.
        """
        # Get content (fall back to concatenating all columns if no content column)
        content = row.get(content_column)
        if content is None:
            # Concatenate all string columns
            content = "\n".join(f"{k}: {v}" for k, v in row.items() if isinstance(v, str) and v)

        # Truncate if too long
        if len(content) > self.MAX_CONTENT_LENGTH:
            content = content[: self.MAX_CONTENT_LENGTH] + "..."

        # Generate ID if not present
        row_id = row.get(id_column)
        if row_id is None:
            row_id = hashlib.sha256(str(row).encode()).hexdigest()[:12]

        # Get timestamps
        created_at = row.get(created_column)
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()
        elif created_at is not None:
            created_at = str(created_at)

        # Calculate freshness
        freshness = self.calculate_freshness(created_at) if created_at else 0.5

        return Evidence(
            id=f"sql:{row_id}",
            source_type=SourceType.DATABASE,
            source_id=f"{self._database_type}:{row_id}",
            content=content,
            title=str(row.get(title_column, "")),
            created_at=created_at,
            author=str(row.get(author_column, "")) if row.get(author_column) else None,
            confidence=self.default_confidence,
            freshness=freshness,
            authority=0.6,  # Database evidence is generally reliable
            metadata={
                "database_type": self._database_type,
                "row_data": {k: str(v)[:200] for k, v in row.items()},
            },
        )

    async def search(
        self,
        query: str,
        limit: int = 10,
        params: Sequence[Any] | None = None,
        content_column: str = "content",
        title_column: str = "title",
        id_column: str = "id",
        **kwargs,
    ) -> list[Evidence]:
        """
        Search database using a parameterized query.

        Args:
            query: SQL SELECT query with parameter placeholders.
            limit: Maximum results (added as LIMIT clause if not present).
            params: Query parameters.
            content_column: Column to use as evidence content.
            title_column: Column to use as evidence title.
            id_column: Column to use as evidence ID.
            **kwargs: Additional column mappings.

        Returns:
            List of Evidence objects.
        """
        # Add LIMIT if not present
        if "LIMIT" not in query.upper():
            query = f"{query} LIMIT {limit}"

        result = await self.execute_query(query, params)

        evidence_list = []
        for row in result.rows[:limit]:
            evidence = self._row_to_evidence(
                row,
                content_column=content_column,
                title_column=title_column,
                id_column=id_column,
                created_column=kwargs.get("created_column", "created_at"),
                author_column=kwargs.get("author_column", "author"),
            )
            evidence_list.append(evidence)

        logger.info(
            "SQL search returned %s results in %.1fms", len(evidence_list), result.query_time_ms
        )

        return evidence_list

    async def fetch(self, evidence_id: str) -> Evidence | None:
        """
        Fetch a specific evidence by ID.

        Note: This requires knowing the table and ID column.
        For SQL, it's better to use search() with a specific WHERE clause.
        """
        # Check cache first
        cached = self._cache_get(evidence_id)
        if cached:
            return cached

        # Can't fetch by ID without knowing the table structure
        logger.warning(
            "SQL fetch by ID not supported without table context. "
            "Use search() with a WHERE clause instead."
        )
        return None

    async def close(self) -> None:
        """Close database connection."""
        if self._connection is not None:
            try:
                if hasattr(self._connection, "close"):
                    if hasattr(self._connection.close, "__call__"):
                        result = self._connection.close()
                        if hasattr(result, "__await__"):
                            await result
            except (OSError, RuntimeError) as e:
                logger.warning("Error closing SQL connection: %s", e)
            finally:
                self._connection = None

    async def __aenter__(self) -> SQLConnector:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()


__all__ = ["SQLConnector", "SQLQueryResult"]
