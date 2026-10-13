"""
Database Query Profiling for Aragora.

Provides tools to identify slow queries, N+1 patterns, and optimize database access.

Usage:
    from aragora.db.profiling import QueryProfiler, profile_queries

    # Profile a code block
    with profile_queries() as profiler:
        # ... database operations ...

    print(profiler.report())

    # Or use decorator
    @profile_queries()
    async def my_function():
        ...
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, cast
from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

# Thresholds for query analysis
SLOW_QUERY_THRESHOLD_MS = 100  # Queries taking > 100ms
N_PLUS_ONE_THRESHOLD = 5  # Same query pattern executed > 5 times


@dataclass
class QueryRecord:
    """Record of a single query execution."""

    query: str
    params: tuple[Any, ...]
    duration_ms: float
    timestamp: float
    rows_affected: int = 0
    is_slow: bool = False

    def normalized_query(self) -> str:
        """Get normalized query for pattern matching (remove specific values)."""
        import re

        # Replace string literals
        q = re.sub(r"'[^']*'", "'?'", self.query)
        # Replace numbers
        q = re.sub(r"\b\d+\b", "?", q)
        # Normalize whitespace
        q = " ".join(q.split())
        return q


@dataclass
class QueryProfile:
    """Profile of queries executed during a session."""

    queries: list[QueryRecord] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None

    def add_query(
        self,
        query: str,
        params: tuple[Any, ...],
        duration_ms: float,
        rows_affected: int = 0,
    ) -> None:
        """Add a query to the profile."""
        record = QueryRecord(
            query=query,
            params=params,
            duration_ms=duration_ms,
            timestamp=time.time(),
            rows_affected=rows_affected,
            is_slow=duration_ms > SLOW_QUERY_THRESHOLD_MS,
        )
        self.queries.append(record)

        if record.is_slow:
            logger.warning(
                f"Slow query ({duration_ms:.1f}ms): {query[:100]}..."
                if len(query) > 100
                else f"Slow query ({duration_ms:.1f}ms): {query}"
            )

    def finish(self) -> None:
        """Mark profiling session as complete."""
        self.end_time = time.time()

    @property
    def total_queries(self) -> int:
        """Total number of queries executed."""
        return len(self.queries)

    @property
    def total_duration_ms(self) -> float:
        """Total time spent in queries."""
        return sum(q.duration_ms for q in self.queries)

    @property
    def slow_queries(self) -> list[QueryRecord]:
        """Get all slow queries."""
        return [q for q in self.queries if q.is_slow]

    @property
    def query_patterns(self) -> dict[str, list[QueryRecord]]:
        """Group queries by normalized pattern."""
        patterns: dict[str, list[QueryRecord]] = defaultdict(list)
        for q in self.queries:
            patterns[q.normalized_query()].append(q)
        return dict(patterns)

    @property
    def potential_n_plus_one(self) -> list[tuple[str, int]]:
        """Identify potential N+1 query patterns."""
        patterns = self.query_patterns
        n_plus_one = []
        for pattern, queries in patterns.items():
            if len(queries) > N_PLUS_ONE_THRESHOLD:
                n_plus_one.append((pattern, len(queries)))
        return sorted(n_plus_one, key=lambda x: x[1], reverse=True)

    def report(self, verbose: bool = False) -> str:
        """Generate a profiling report."""
        lines = [
            "=" * 60,
            "DATABASE QUERY PROFILE",
            "=" * 60,
            f"Total queries: {self.total_queries}",
            f"Total time: {self.total_duration_ms:.2f}ms",
            f"Slow queries: {len(self.slow_queries)}",
            "",
        ]

        # N+1 warnings
        n_plus_one = self.potential_n_plus_one
        if n_plus_one:
            lines.append("POTENTIAL N+1 QUERIES:")
            lines.append("-" * 40)
            for pattern, count in n_plus_one[:5]:
                lines.append(f"  [{count}x] {pattern[:70]}...")
            lines.append("")

        # Slow queries
        if self.slow_queries:
            lines.append("SLOW QUERIES:")
            lines.append("-" * 40)
            for q in sorted(self.slow_queries, key=lambda x: x.duration_ms, reverse=True)[:5]:
                lines.append(f"  [{q.duration_ms:.1f}ms] {q.query[:70]}...")
            lines.append("")

        # Query type breakdown
        lines.append("QUERY TYPES:")
        lines.append("-" * 40)
        type_counts: dict[str, int] = defaultdict(int)
        for q in self.queries:
            query_type = q.query.strip().split()[0].upper()
            type_counts[query_type] += 1
        for qtype, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {qtype}: {count}")

        if verbose:
            lines.append("")
            lines.append("ALL QUERIES:")
            lines.append("-" * 40)
            for i, q in enumerate(self.queries, 1):
                lines.append(f"  {i}. [{q.duration_ms:.1f}ms] {q.query[:70]}...")

        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert profile to dictionary for JSON serialization."""
        return {
            "total_queries": self.total_queries,
            "total_duration_ms": self.total_duration_ms,
            "slow_queries": len(self.slow_queries),
            "potential_n_plus_one": self.potential_n_plus_one,
            "query_type_counts": {q.query.strip().split()[0].upper(): 0 for q in self.queries},
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


class QueryProfiler:
    """
    Context manager for profiling database queries.

    Usage:
        profiler = QueryProfiler()
        with profiler:
            # Execute database operations
            ...
        print(profiler.profile.report())
    """

    _current: QueryProfiler | None = None

    def __init__(self) -> None:
        self.profile = QueryProfile()
        self._previous: QueryProfiler | None = None

    def __enter__(self) -> QueryProfiler:
        self._previous = QueryProfiler._current
        QueryProfiler._current = self
        return self

    def __exit__(self, *args: Any) -> None:
        self.profile.finish()
        QueryProfiler._current = self._previous

    @classmethod
    def current(cls) -> QueryProfiler | None:
        """Get the current active profiler, if any."""
        return cls._current

    def record(
        self,
        query: str,
        params: tuple[Any, ...],
        duration_ms: float,
        rows_affected: int = 0,
    ) -> None:
        """Record a query execution."""
        self.profile.add_query(query, params, duration_ms, rows_affected)

    def report(self, verbose: bool = False) -> str:
        """Generate profiling report."""
        return self.profile.report(verbose)


@contextmanager
def profile_queries():
    """Context manager for profiling queries."""
    profiler = QueryProfiler()
    with profiler:
        yield profiler


def profile_function(func: Callable) -> Callable:
    """Decorator to profile queries in a function."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with profile_queries() as profiler:
            result = func(*args, **kwargs)
            logger.info("Query profile for %s:\n%s", func.__name__, profiler.report())
            return result

    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        with profile_queries() as profiler:
            result = await func(*args, **kwargs)
            logger.info("Query profile for %s:\n%s", func.__name__, profiler.report())
            return result

    import asyncio

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return wrapper


class ProfiledConnection:
    """
    Wrapper around sqlite3.Connection that records queries to the current profiler.

    This class wraps a SQLite connection and intercepts execute/executemany calls
    to record timing information for query profiling.

    Usage:
        conn = sqlite3.connect(":memory:")
        profiled = ProfiledConnection(conn)
        # Use profiled.execute() and profiled.executemany()
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the underlying connection."""
        return getattr(self._conn, name)

    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> sqlite3.Cursor:
        """Execute SQL with profiling."""
        profiler = QueryProfiler.current()
        params_tuple = tuple(parameters) if not isinstance(parameters, tuple) else parameters
        start = time.perf_counter()
        try:
            # sqlite3 stubs accept only specific parameter types; Iterable[Any] is safe here
            result = self._conn.execute(sql, cast(Any, parameters))
            duration_ms = (time.perf_counter() - start) * 1000
            if profiler:
                profiler.record(sql, params_tuple, duration_ms, result.rowcount or 0)
            return result
        except (sqlite3.Error, ValueError) as e:
            duration_ms = (time.perf_counter() - start) * 1000
            if profiler:
                profiler.record(sql, params_tuple, duration_ms)
            logger.debug("Query failed after %.2fms: %s", duration_ms, e)
            raise

    def executemany(self, sql: str, seq_of_parameters: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        """Execute SQL for multiple parameter sets with profiling."""
        profiler = QueryProfiler.current()
        # Materialize to get count for logging
        params_list = list(seq_of_parameters)
        start = time.perf_counter()
        try:
            # sqlite3 stubs accept only specific parameter types; list[Iterable[Any]] is safe here
            result = self._conn.executemany(sql, cast(Any, params_list))
            duration_ms = (time.perf_counter() - start) * 1000
            if profiler:
                profiler.record(
                    f"{sql} (x{len(params_list)})", (), duration_ms, result.rowcount or 0
                )
            return result
        except (sqlite3.Error, ValueError) as e:
            duration_ms = (time.perf_counter() - start) * 1000
            if profiler:
                profiler.record(f"{sql} (x{len(params_list)})", (), duration_ms)
            logger.debug("Query batch failed after %.2fms: %s", duration_ms, e)
            raise


def instrument_sqlite_connection(conn: sqlite3.Connection) -> ProfiledConnection:
    """
    Instrument a SQLite connection to record queries to the current profiler.

    Returns a ProfiledConnection wrapper that intercepts execute/executemany calls.

    Usage:
        conn = sqlite3.connect(":memory:")
        conn = instrument_sqlite_connection(conn)
    """
    return ProfiledConnection(conn)


# Recommended indexes for common query patterns
RECOMMENDED_INDEXES = """
-- Debates table indexes
CREATE INDEX IF NOT EXISTS idx_debates_created_at ON debates(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_debates_status ON debates(status);
CREATE INDEX IF NOT EXISTS idx_debates_task_hash ON debates(task_hash);

-- Messages table indexes
CREATE INDEX IF NOT EXISTS idx_messages_debate_id ON messages(debate_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent_round ON messages(debate_id, agent_id, round_num);

-- Votes table indexes
CREATE INDEX IF NOT EXISTS idx_votes_debate_id ON votes(debate_id);
CREATE INDEX IF NOT EXISTS idx_votes_agent ON votes(agent_id);

-- ELO ratings indexes
CREATE INDEX IF NOT EXISTS idx_elo_agent ON elo_ratings(agent_id);
CREATE INDEX IF NOT EXISTS idx_elo_timestamp ON elo_ratings(timestamp DESC);

-- Audit events indexes
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_events(category);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor_id);

-- Memory tiers indexes
CREATE INDEX IF NOT EXISTS idx_memory_tier ON memories(tier);
CREATE INDEX IF NOT EXISTS idx_memory_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memory_created ON memories(created_at DESC);
"""


def get_index_recommendations() -> str:
    """Get SQL statements for recommended indexes."""
    return RECOMMENDED_INDEXES


def apply_recommended_indexes(conn: sqlite3.Connection) -> None:
    """Apply recommended indexes to a SQLite database."""
    for statement in RECOMMENDED_INDEXES.strip().split(";"):
        statement = statement.strip()
        if statement:
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as e:
                # Table might not exist - that's OK
                logger.debug("Could not create index: %s", e)
    conn.commit()
    logger.info("Applied recommended database indexes")
