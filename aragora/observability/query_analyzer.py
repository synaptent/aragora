"""
Query Plan Analysis Infrastructure.

Provides automatic detection of slow queries and suboptimal query plans,
including sequential scans on large tables.

Usage:
    from aragora.observability.query_analyzer import (
        QueryPlanAnalyzer,
        analyze_query,
        get_slow_queries,
    )

    # Automatic analysis
    analyzer = QueryPlanAnalyzer(slow_threshold_ms=100)
    issue = await analyzer.analyze(query, duration_ms=150)
    if issue:
        print(f"Query issue: {issue.issue} - {issue.suggestion}")

    # Get recent slow queries
    slow = get_slow_queries(threshold_seconds=1.0)

Configuration:
    ARAGORA_QUERY_ANALYSIS: Analysis mode (warn|off, default: off)
    ARAGORA_QUERY_SLOW_THRESHOLD_MS: Slow query threshold (default: 100)
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Configuration
ANALYSIS_MODE = os.environ.get("ARAGORA_QUERY_ANALYSIS", "off").lower()
SLOW_THRESHOLD_MS = float(os.environ.get("ARAGORA_QUERY_SLOW_THRESHOLD_MS", "100"))

# Maximum slow queries to retain
MAX_SLOW_QUERIES = 1000


@dataclass
class QueryPlanIssue:
    """An issue detected in a query plan."""

    query: str
    duration_ms: float
    issue: str
    suggestion: str
    table: str | None = None
    plan_details: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query[:200] + "..." if len(self.query) > 200 else self.query,
            "duration_ms": round(self.duration_ms, 2),
            "issue": self.issue,
            "suggestion": self.suggestion,
            "table": self.table,
            "timestamp": self.timestamp,
        }


@dataclass
class SlowQuery:
    """A slow query record."""

    query: str
    duration_ms: float
    table: str | None = None
    timestamp: float = field(default_factory=time.time)
    context: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query[:200] + "..." if len(self.query) > 200 else self.query,
            "duration_ms": round(self.duration_ms, 2),
            "table": self.table,
            "timestamp": self.timestamp,
            "context": self.context,
        }


# Global storage for slow queries
_slow_queries: deque[SlowQuery] = deque(maxlen=MAX_SLOW_QUERIES)


class QueryPlanAnalyzer:
    """
    Analyzes query execution plans to detect performance issues.

    Monitors queries for:
    - Sequential scans on large tables
    - Missing indexes
    - High row estimates
    - Slow execution times
    """

    # Tables considered "large" for sequential scan warnings
    LARGE_TABLE_THRESHOLD = 10000

    # Known large tables (can be extended)
    KNOWN_LARGE_TABLES = {
        "knowledge_nodes",
        "knowledge_relationships",
        "provenance_chains",
        "access_grants",
        "debate_messages",
        "critique_store",
        "continuum_memory",
    }

    def __init__(
        self,
        slow_threshold_ms: float = SLOW_THRESHOLD_MS,
        mode: str = ANALYSIS_MODE,
    ):
        """
        Initialize the query analyzer.

        Args:
            slow_threshold_ms: Threshold for slow query detection
            mode: Analysis mode ('warn' or 'off')
        """
        self.slow_threshold_ms = slow_threshold_ms
        self.mode = mode
        self._issues: list[QueryPlanIssue] = []

    async def analyze(
        self,
        query: str,
        duration_ms: float,
        connection: Any | None = None,
        context: str | None = None,
    ) -> QueryPlanIssue | None:
        """
        Analyze a query for performance issues.

        Args:
            query: The SQL query
            duration_ms: Execution duration in milliseconds
            connection: Optional database connection for EXPLAIN
            context: Optional context string (e.g., handler name)

        Returns:
            QueryPlanIssue if an issue was found, None otherwise
        """
        if self.mode == "off":
            return None

        # Always record slow queries
        if duration_ms >= self.slow_threshold_ms:
            table = self._extract_table(query)
            _slow_queries.append(
                SlowQuery(
                    query=query,
                    duration_ms=duration_ms,
                    table=table,
                    context=context,
                )
            )

        # Skip detailed analysis for fast queries
        if duration_ms < self.slow_threshold_ms:
            return None

        # Analyze query pattern
        issue = self._analyze_query_pattern(query, duration_ms)
        if issue:
            self._record_issue(issue)
            return issue

        # Try to get EXPLAIN output if connection available
        if connection:
            issue = await self._analyze_explain(query, duration_ms, connection)
            if issue:
                self._record_issue(issue)
                return issue

        return None

    def _analyze_query_pattern(
        self,
        query: str,
        duration_ms: float,
    ) -> QueryPlanIssue | None:
        """
        Analyze query pattern for common issues.

        Uses heuristics to detect potential problems without EXPLAIN.
        """
        table = self._extract_table(query)
        upper_query = query.upper()

        # Check for SELECT * on large tables
        if "SELECT *" in upper_query and table in self.KNOWN_LARGE_TABLES:
            return QueryPlanIssue(
                query=query,
                duration_ms=duration_ms,
                issue="select_star_large_table",
                suggestion=f"Avoid SELECT * on large table '{table}'. Select only needed columns.",
                table=table,
            )

        # Check for LIKE with leading wildcard
        if re.search(r"LIKE\s+'%", upper_query) or re.search(r"LIKE\s+\$\d+", upper_query):
            return QueryPlanIssue(
                query=query,
                duration_ms=duration_ms,
                issue="leading_wildcard_like",
                suggestion="LIKE with leading wildcard cannot use indexes. Consider full-text search.",
                table=table,
            )

        # Check for ORDER BY without index hint
        if "ORDER BY" in upper_query and table in self.KNOWN_LARGE_TABLES:
            if duration_ms > self.slow_threshold_ms * 2:  # Extra slow
                return QueryPlanIssue(
                    query=query,
                    duration_ms=duration_ms,
                    issue="slow_order_by",
                    suggestion=f"Slow ORDER BY on '{table}'. Consider adding index on sort columns.",
                    table=table,
                )

        # Check for missing WHERE clause on large tables
        if (
            "WHERE" not in upper_query
            and "SELECT" in upper_query
            and table in self.KNOWN_LARGE_TABLES
        ):
            return QueryPlanIssue(
                query=query,
                duration_ms=duration_ms,
                issue="missing_where_clause",
                suggestion=f"Query on large table '{table}' without WHERE clause.",
                table=table,
            )

        # Check for IN clause with many values
        in_match = re.search(r"IN\s*\(([^)]+)\)", query)
        if in_match:
            values = in_match.group(1).split(",")
            if len(values) > 100:
                return QueryPlanIssue(
                    query=query,
                    duration_ms=duration_ms,
                    issue="large_in_clause",
                    suggestion=f"IN clause with {len(values)} values. Consider using JOIN or temp table.",
                    table=table,
                )

        return None

    async def _analyze_explain(
        self,
        query: str,
        duration_ms: float,
        connection: Any,
    ) -> QueryPlanIssue | None:
        """
        Analyze query using EXPLAIN output.

        Args:
            query: The SQL query
            duration_ms: Execution duration
            connection: Database connection

        Returns:
            QueryPlanIssue if sequential scan on large table detected
        """
        try:
            # Get EXPLAIN output
            explain_query = f"EXPLAIN (FORMAT TEXT) {query}"
            result = await connection.fetch(explain_query)
            plan_text = "\n".join(str(row[0]) for row in result)

            table = self._extract_table(query)

            # Check for sequential scan
            if "Seq Scan" in plan_text:
                # Try to extract row estimate
                rows_match = re.search(r"rows=(\d+)", plan_text)
                rows = int(rows_match.group(1)) if rows_match else 0

                if rows > self.LARGE_TABLE_THRESHOLD or table in self.KNOWN_LARGE_TABLES:
                    return QueryPlanIssue(
                        query=query,
                        duration_ms=duration_ms,
                        issue="sequential_scan_large_table",
                        suggestion=f"Sequential scan on table with ~{rows} rows. Consider adding an index.",
                        table=table,
                        plan_details=plan_text[:500],
                    )

            # Check for high-cost operations
            cost_match = re.search(r"cost=[\d.]+\.\.(\d+\.?\d*)", plan_text)
            if cost_match:
                cost = float(cost_match.group(1))
                if cost > 10000:  # High cost threshold
                    return QueryPlanIssue(
                        query=query,
                        duration_ms=duration_ms,
                        issue="high_cost_query",
                        suggestion=f"Query has high estimated cost ({cost:.0f}). Review query plan.",
                        table=table,
                        plan_details=plan_text[:500],
                    )

        except (OSError, RuntimeError, AttributeError, ValueError) as e:
            logger.debug("EXPLAIN analysis failed: %s", e)

        return None

    def _extract_table(self, query: str) -> str | None:
        """Extract primary table name from query."""
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

        return None

    def _record_issue(self, issue: QueryPlanIssue) -> None:
        """Record a query plan issue."""
        self._issues.append(issue)

        if self.mode == "warn":
            logger.warning(
                "Query plan issue: %s on %s (%.1fms) - %s",
                issue.issue,
                issue.table or "unknown",
                issue.duration_ms,
                issue.suggestion,
            )

    def get_issues(self) -> list[QueryPlanIssue]:
        """Get all recorded issues."""
        return list(self._issues)

    def clear_issues(self) -> None:
        """Clear recorded issues."""
        self._issues.clear()


# Global analyzer instance
_analyzer: QueryPlanAnalyzer | None = None


def get_analyzer() -> QueryPlanAnalyzer:
    """Get the global query analyzer."""
    global _analyzer
    if _analyzer is None:
        _analyzer = QueryPlanAnalyzer()
    return _analyzer


async def analyze_query(
    query: str,
    duration_ms: float,
    connection: Any | None = None,
    context: str | None = None,
) -> QueryPlanIssue | None:
    """
    Analyze a query using the global analyzer.

    Args:
        query: SQL query string
        duration_ms: Execution duration
        connection: Optional database connection for EXPLAIN
        context: Optional context (e.g., handler name)

    Returns:
        QueryPlanIssue if issue detected
    """
    return await get_analyzer().analyze(query, duration_ms, connection, context)


def get_slow_queries(
    threshold_ms: float | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Get recent slow queries.

    Args:
        threshold_ms: Optional additional threshold filter
        limit: Maximum queries to return

    Returns:
        List of slow query dictionaries
    """
    queries = list(_slow_queries)

    if threshold_ms is not None:
        queries = [q for q in queries if q.duration_ms >= threshold_ms]

    # Sort by duration (slowest first)
    queries.sort(key=lambda q: q.duration_ms, reverse=True)

    return [q.to_dict() for q in queries[:limit]]


def clear_slow_queries() -> None:
    """Clear the slow query history."""
    _slow_queries.clear()


def get_query_analysis_stats() -> dict[str, Any]:
    """Get query analysis statistics."""
    analyzer = get_analyzer()
    issues = analyzer.get_issues()

    # Group issues by type
    issue_counts: dict[str, int] = {}
    for issue in issues:
        issue_counts[issue.issue] = issue_counts.get(issue.issue, 0) + 1

    return {
        "mode": ANALYSIS_MODE,
        "slow_threshold_ms": SLOW_THRESHOLD_MS,
        "slow_query_count": len(_slow_queries),
        "issue_count": len(issues),
        "issues_by_type": issue_counts,
    }


__all__ = [
    "QueryPlanAnalyzer",
    "QueryPlanIssue",
    "SlowQuery",
    "get_analyzer",
    "analyze_query",
    "get_slow_queries",
    "clear_slow_queries",
    "get_query_analysis_stats",
]
