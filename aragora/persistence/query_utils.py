"""
Query utilities for database performance optimization.

Provides batch query helpers and common patterns to avoid N+1 queries
and improve database performance.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from typing import Any, TypeVar
from collections.abc import Iterator

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependencies
_n1_detector_imported = False
_record_query = None


def _get_record_query():
    """Lazy import of N+1 detector to avoid circular imports."""
    global _n1_detector_imported, _record_query
    if not _n1_detector_imported:
        try:
            from aragora.observability.n1_detector import record_query

            _record_query = record_query
        except ImportError:
            _record_query = None
        _n1_detector_imported = True
    return _record_query


def _extract_table_name(query: str) -> str:
    """Extract table name from a SQL query for N+1 tracking."""
    # Handle SELECT ... FROM table
    match = re.search(r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)", query, re.IGNORECASE)
    if match:
        return match.group(1)

    # Handle INSERT INTO table
    match = re.search(r"\bINTO\s+([a-zA-Z_][a-zA-Z0-9_]*)", query, re.IGNORECASE)
    if match:
        return match.group(1)

    # Handle UPDATE table
    match = re.search(r"\bUPDATE\s+([a-zA-Z_][a-zA-Z0-9_]*)", query, re.IGNORECASE)
    if match:
        return match.group(1)

    # Handle DELETE FROM table
    match = re.search(r"\bDELETE\s+FROM\s+([a-zA-Z_][a-zA-Z0-9_]*)", query, re.IGNORECASE)
    if match:
        return match.group(1)

    return "unknown"


T = TypeVar("T")


def chunked(iterable: list[T], size: int) -> Iterator[list[T]]:
    """Split a list into chunks of the specified size.

    Args:
        iterable: List to split
        size: Maximum chunk size

    Yields:
        Lists of at most `size` elements
    """
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def batch_select(
    conn: sqlite3.Connection,
    table: str,
    ids: list[str],
    columns: list[str] | None = None,
    id_column: str = "id",
    batch_size: int = 100,
) -> list[sqlite3.Row]:
    """Batch SELECT with chunked IN clauses.

    Splits large ID lists into smaller batches to avoid SQLite's
    expression tree depth limit and improve performance.

    Args:
        conn: SQLite connection
        table: Table name (validated against injection)
        ids: List of IDs to fetch
        columns: Columns to select (None = all)
        id_column: Name of the ID column
        batch_size: Maximum IDs per query

    Returns:
        List of Row objects from all batches
    """
    if not ids:
        return []

    # Validate table name to prevent SQL injection
    if not table.replace("_", "").isalnum():
        raise ValueError(f"Invalid table name: {table}")
    if not id_column.replace("_", "").isalnum():
        raise ValueError(f"Invalid column name: {id_column}")

    # Validate column names if provided
    if columns:
        for col in columns:
            if not col.replace("_", "").isalnum():
                raise ValueError(f"Invalid column name: {col}")

    results: list[sqlite3.Row] = []
    cols = "*" if not columns else ", ".join(columns)  # nosec B608 - validated above

    for chunk in chunked(ids, batch_size):
        placeholders = ", ".join("?" * len(chunk))
        query = f"SELECT {cols} FROM {table} WHERE {id_column} IN ({placeholders})"  # nosec B608  # noqa: S608

        try:
            cursor = conn.execute(query, chunk)
            results.extend(cursor.fetchall())
        except sqlite3.Error as e:
            logger.error("Batch select failed: %s", e)
            raise

    return results


def batch_exists(
    conn: sqlite3.Connection,
    table: str,
    ids: list[str],
    id_column: str = "id",
    batch_size: int = 100,
) -> set[str]:
    """Check which IDs exist in a table.

    Args:
        conn: SQLite connection
        table: Table name
        ids: List of IDs to check
        id_column: Name of the ID column
        batch_size: Maximum IDs per query

    Returns:
        Set of IDs that exist in the table
    """
    if not ids:
        return set()

    # Validate table name
    if not table.replace("_", "").isalnum():
        raise ValueError(f"Invalid table name: {table}")
    if not id_column.replace("_", "").isalnum():
        raise ValueError(f"Invalid column name: {id_column}")

    existing: set[str] = set()

    for chunk in chunked(ids, batch_size):
        placeholders = ", ".join("?" * len(chunk))
        query = f"SELECT {id_column} FROM {table} WHERE {id_column} IN ({placeholders})"  # nosec B608  # noqa: S608

        try:
            cursor = conn.execute(query, chunk)
            for row in cursor.fetchall():
                existing.add(row[0])
        except sqlite3.Error as e:
            logger.error("Batch exists check failed: %s", e)
            raise

    return existing


def timed_query(
    conn: sqlite3.Connection,
    query: str,
    params: tuple | None = None,
    operation_name: str = "query",
    threshold_ms: float = 500.0,
) -> sqlite3.Cursor:
    """Execute a query with timing, slow query logging, and N+1 detection.

    Args:
        conn: SQLite connection
        query: SQL query string
        params: Query parameters
        operation_name: Name for logging
        threshold_ms: Slow query threshold in milliseconds

    Returns:
        Cursor with query results
    """
    start = time.monotonic()
    try:
        if params:
            cursor = conn.execute(query, params)
        else:
            cursor = conn.execute(query)

        elapsed_ms = (time.monotonic() - start) * 1000

        # Record query for N+1 detection
        record_fn = _get_record_query()
        if record_fn is not None:
            table = _extract_table_name(query)
            record_fn(table, query, elapsed_ms)

        if elapsed_ms > threshold_ms:
            # Truncate query for logging
            short_query = query[:200] + "..." if len(query) > 200 else query
            logger.warning("Slow query (%.1fms): %s: %s", elapsed_ms, operation_name, short_query)

        return cursor
    except sqlite3.Error:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.error("Query failed after %.1fms: %s", elapsed_ms, operation_name)
        raise


def get_table_stats(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    """Get basic statistics for a table.

    Args:
        conn: SQLite connection
        table: Table name

    Returns:
        Dict with row_count, table_name
    """
    if not table.replace("_", "").isalnum():
        raise ValueError(f"Invalid table name: {table}")

    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")  # nosec B608  # noqa: S608
    row = cursor.fetchone()

    return {
        "table": table,
        "row_count": row[0] if row else 0,
    }


__all__ = [
    "chunked",
    "batch_select",
    "batch_exists",
    "timed_query",
    "get_table_stats",
]
