"""
PostgreSQL store implementation for Aragora.

Provides async PostgreSQL-backed storage with connection pooling for production
deployments that need horizontal scaling and concurrent writes.

Features:
- Connection pooling with asyncpg
- Circuit breaker protection against pool exhaustion
- Automatic retry with exponential backoff
- Pool utilization metrics for monitoring
- Backpressure signaling when pool is near capacity

Usage:
    from aragora.storage.postgres_store import PostgresStore, get_postgres_pool

    # Initialize pool at startup
    pool = await get_postgres_pool()

    class MyStore(PostgresStore):
        SCHEMA_NAME = "my_store"
        SCHEMA_VERSION = 1

        INITIAL_SCHEMA = '''
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
        '''

    store = MyStore(pool)
    await store.initialize()

    # Check pool health
    metrics = get_pool_metrics()
    if metrics["backpressure"]:
        # Slow down or queue requests
        pass
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from abc import ABC
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from collections.abc import AsyncGenerator, Callable

# asyncio.timeout is available in Python 3.11+
if sys.version_info >= (3, 11):
    from asyncio import timeout as asyncio_timeout
else:
    # Fallback for older Python versions
    from contextlib import asynccontextmanager as _acm

    @_acm
    async def asyncio_timeout(delay: float | None) -> AsyncGenerator[None, None]:
        """Fallback timeout context manager for Python < 3.11."""
        if delay is None:
            yield
            return

        async def _timeout_task() -> None:
            await asyncio.sleep(delay)
            raise asyncio.TimeoutError()

        task = asyncio.create_task(_timeout_task())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


logger = logging.getLogger(__name__)

# Optional asyncpg import - graceful degradation
try:
    import asyncpg
    from asyncpg import Connection, Pool

    ASYNCPG_AVAILABLE = True
except ImportError:
    asyncpg = None
    Pool = Any
    Connection = Any
    ASYNCPG_AVAILABLE = False
    logger.debug("asyncpg not available, PostgreSQL backend disabled")

# Import circuit breaker from resilience module
try:
    from aragora.resilience import CircuitBreaker as _CircuitBreaker
    from aragora.resilience import CircuitOpenError as _CircuitOpenError
    from aragora.resilience import get_circuit_breaker as _get_circuit_breaker

    RESILIENCE_AVAILABLE = True
    CircuitBreaker: type[Any] | None = _CircuitBreaker
    CircuitOpenError: type[Exception] = _CircuitOpenError
    get_circuit_breaker: Callable[..., Any] | None = _get_circuit_breaker
except ImportError:
    RESILIENCE_AVAILABLE = False
    CircuitBreaker = None
    CircuitOpenError = Exception
    get_circuit_breaker = None
    logger.debug("resilience module not available, circuit breaker disabled")

# Global pool singleton
_pool: Pool | None = None

# Pool metrics tracking
_pool_metrics: dict[str, Any] = {
    "total_acquisitions": 0,
    "failed_acquisitions": 0,
    "timeouts": 0,
    "circuit_breaker_rejections": 0,
    "last_acquisition_time": 0.0,
    "total_wait_time": 0.0,
    "max_wait_time": 0.0,
}

# Pool configuration
POOL_ACQUIRE_TIMEOUT = 10.0  # Seconds to wait for connection
POOL_BACKPRESSURE_THRESHOLD = 0.8  # Trigger backpressure at 80% utilization
POOL_CIRCUIT_BREAKER_THRESHOLD = 5  # Failures before opening circuit
POOL_CIRCUIT_BREAKER_COOLDOWN = 30.0  # Seconds before retry


@dataclass
class PoolMetrics:
    """Metrics for connection pool health monitoring."""

    pool_size: int
    pool_min_size: int
    pool_max_size: int
    free_connections: int
    used_connections: int
    utilization: float
    backpressure: bool
    total_acquisitions: int
    failed_acquisitions: int
    timeouts: int
    circuit_breaker_rejections: int
    circuit_breaker_status: str
    avg_wait_time_ms: float
    max_wait_time_ms: float


class PoolExhaustedError(Exception):
    """Raised when the connection pool is exhausted and timeout occurs."""

    def __init__(self, timeout: float, utilization: float):
        self.timeout = timeout
        self.utilization = utilization
        super().__init__(
            f"Connection pool exhausted after {timeout:.1f}s timeout "
            f"(utilization: {utilization:.1%})"
        )


def get_pool_metrics() -> PoolMetrics | None:
    """
    Get current connection pool metrics for monitoring.

    Returns:
        PoolMetrics with current pool state, or None if pool not initialized.

    Example:
        metrics = get_pool_metrics()
        if metrics and metrics.backpressure:
            logger.warning("Pool under pressure, consider slowing requests")
    """
    global _pool, _pool_metrics

    if _pool is None:
        return None

    pool_size = _pool.get_size()
    pool_min = _pool.get_min_size()
    pool_max = _pool.get_max_size()
    free = _pool.get_idle_size()
    used = pool_size - free
    utilization = used / pool_max if pool_max > 0 else 0.0

    # Calculate average wait time
    total_acq = _pool_metrics["total_acquisitions"]
    avg_wait = (_pool_metrics["total_wait_time"] / total_acq * 1000) if total_acq > 0 else 0.0

    # Get circuit breaker status
    cb_status = "closed"
    if RESILIENCE_AVAILABLE and get_circuit_breaker:
        cb = get_circuit_breaker(
            "postgres_pool",
            failure_threshold=POOL_CIRCUIT_BREAKER_THRESHOLD,
            cooldown_seconds=POOL_CIRCUIT_BREAKER_COOLDOWN,
        )
        cb_status = cb.get_status()

    return PoolMetrics(
        pool_size=pool_size,
        pool_min_size=pool_min,
        pool_max_size=pool_max,
        free_connections=free,
        used_connections=used,
        utilization=utilization,
        backpressure=utilization >= POOL_BACKPRESSURE_THRESHOLD,
        total_acquisitions=_pool_metrics["total_acquisitions"],
        failed_acquisitions=_pool_metrics["failed_acquisitions"],
        timeouts=_pool_metrics["timeouts"],
        circuit_breaker_rejections=_pool_metrics["circuit_breaker_rejections"],
        circuit_breaker_status=cb_status,
        avg_wait_time_ms=avg_wait,
        max_wait_time_ms=_pool_metrics["max_wait_time"] * 1000,
    )


def is_pool_healthy() -> bool:
    """
    Quick health check for the connection pool.

    Returns:
        True if pool is healthy (not under backpressure and circuit is closed).
    """
    metrics = get_pool_metrics()
    if metrics is None:
        return False
    return not metrics.backpressure and metrics.circuit_breaker_status == "closed"


def reset_pool_metrics() -> None:
    """Reset pool metrics (for testing)."""
    global _pool_metrics
    _pool_metrics = {
        "total_acquisitions": 0,
        "failed_acquisitions": 0,
        "timeouts": 0,
        "circuit_breaker_rejections": 0,
        "last_acquisition_time": 0.0,
        "total_wait_time": 0.0,
        "max_wait_time": 0.0,
    }


async def get_postgres_pool(
    dsn: str | None = None,
    min_size: int = 5,
    max_size: int = 20,
    command_timeout: float = 60.0,
    statement_timeout: int = 60,
    pool_recycle: int = 1800,
) -> Pool:
    """
    Get or create the global PostgreSQL connection pool.

    Args:
        dsn: PostgreSQL connection string. If not provided, uses
             ARAGORA_POSTGRES_DSN or DATABASE_URL env vars.
        min_size: Minimum pool connections (default 5)
        max_size: Maximum pool connections (default 20)
        command_timeout: Max time (seconds) for any single command (default 60)
        statement_timeout: PostgreSQL statement_timeout in seconds (default 60)
        pool_recycle: Recycle connections older than this (seconds, default 1800)

    Returns:
        Connection pool instance

    Raises:
        RuntimeError: If asyncpg is not installed or connection fails
    """
    global _pool

    if not ASYNCPG_AVAILABLE:
        raise RuntimeError(
            "PostgreSQL backend requires 'asyncpg' package. "
            "Install with: pip install aragora[postgres] or pip install asyncpg"
        )

    if _pool is not None:
        return _pool

    # Get DSN from environment or secrets manager if not provided
    if dsn is None:
        dsn = os.environ.get("ARAGORA_POSTGRES_DSN") or os.environ.get("DATABASE_URL")

        # Try secrets manager as fallback
        if not dsn:
            try:
                from aragora.config.secrets import get_secret

                dsn = get_secret("ARAGORA_POSTGRES_DSN") or get_secret("DATABASE_URL")
            except ImportError:
                pass  # secrets module not available

    if not dsn:
        raise RuntimeError(
            "PostgreSQL DSN not configured. Set ARAGORA_POSTGRES_DSN or DATABASE_URL "
            "in environment, AWS Secrets Manager, or pass dsn parameter."
        )

    # Connection initialization callback to set session parameters
    async def init_connection(conn):
        # Set statement_timeout to prevent runaway queries
        await conn.execute(f"SET statement_timeout = '{statement_timeout}s'")
        # Set idle_in_transaction_session_timeout to prevent abandoned transactions
        await conn.execute("SET idle_in_transaction_session_timeout = '300s'")

    logger.info(
        "Creating PostgreSQL pool (min=%s, max=%s, command_timeout=%ss, statement_timeout=%ss)",
        min_size,
        max_size,
        command_timeout,
        statement_timeout,
    )
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        command_timeout=command_timeout,
        max_inactive_connection_lifetime=pool_recycle,
        init=init_connection,
    )

    return _pool


async def get_postgres_pool_from_settings() -> Pool:
    """
    Get or create PostgreSQL connection pool using centralized settings.

    This is the recommended way to get the pool in application code,
    as it uses the settings from aragora.config.settings.DatabaseSettings.

    Returns:
        Connection pool instance

    Raises:
        RuntimeError: If asyncpg is not installed or PostgreSQL not configured

    Example:
        from aragora.storage.postgres_store import get_postgres_pool_from_settings

        pool = await get_postgres_pool_from_settings()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM debates")
    """
    from aragora.config import get_settings

    settings = get_settings()
    db_settings = settings.database

    if not db_settings.is_postgresql:
        raise RuntimeError(
            "PostgreSQL backend not configured. Set ARAGORA_DB_BACKEND=postgresql "
            "and DATABASE_URL environment variable."
        )

    return await get_postgres_pool(
        dsn=db_settings.url,
        min_size=max(1, db_settings.pool_size // 4),  # min is ~25% of max
        max_size=db_settings.pool_size + db_settings.pool_max_overflow,
        command_timeout=db_settings.command_timeout,
        statement_timeout=db_settings.statement_timeout,
        pool_recycle=db_settings.pool_recycle,
    )


async def close_postgres_pool() -> None:
    """Close the global PostgreSQL connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL pool closed")


@asynccontextmanager
async def acquire_connection_resilient(
    pool: Pool,
    timeout: float = POOL_ACQUIRE_TIMEOUT,
    retries: int = 3,
    backoff_base: float = 0.5,
) -> AsyncGenerator[Connection, None]:
    """
    Acquire a connection from the pool with resilience patterns.

    Features:
    - Timeout on connection acquisition
    - Circuit breaker to fail fast when pool is overwhelmed
    - Exponential backoff retry on transient failures
    - Metrics collection for monitoring

    Args:
        pool: asyncpg connection pool
        timeout: Max seconds to wait for a connection (default 10)
        retries: Number of retry attempts (default 3)
        backoff_base: Base delay for exponential backoff (default 0.5s)

    Yields:
        asyncpg Connection

    Raises:
        PoolExhaustedError: If pool is exhausted after retries
        CircuitOpenError: If circuit breaker is open

    Example:
        pool = await get_postgres_pool()
        async with acquire_connection_resilient(pool) as conn:
            await conn.fetch("SELECT 1")
    """
    global _pool_metrics

    # Check circuit breaker first
    circuit_breaker = None
    if RESILIENCE_AVAILABLE and get_circuit_breaker:
        circuit_breaker = get_circuit_breaker(
            "postgres_pool",
            failure_threshold=POOL_CIRCUIT_BREAKER_THRESHOLD,
            cooldown_seconds=POOL_CIRCUIT_BREAKER_COOLDOWN,
        )
        if not circuit_breaker.can_proceed():
            _pool_metrics["circuit_breaker_rejections"] += 1
            cooldown = circuit_breaker.cooldown_remaining()
            raise CircuitOpenError("postgres_pool", cooldown)

    last_error: Exception | None = None
    start_time = time.time()

    for attempt in range(retries):
        try:
            acquire_start = time.time()

            # asyncpg's acquire() supports timeout parameter
            async with asyncio_timeout(timeout):
                async with pool.acquire() as conn:
                    # Track successful acquisition
                    wait_time = time.time() - acquire_start
                    _pool_metrics["total_acquisitions"] += 1
                    _pool_metrics["total_wait_time"] += wait_time
                    _pool_metrics["max_wait_time"] = max(_pool_metrics["max_wait_time"], wait_time)
                    _pool_metrics["last_acquisition_time"] = time.time()

                    # Record success with circuit breaker
                    if circuit_breaker:
                        circuit_breaker.record_success()

                    yield conn
                    return

        except asyncio.TimeoutError:
            _pool_metrics["timeouts"] += 1
            _pool_metrics["failed_acquisitions"] += 1
            last_error = PoolExhaustedError(
                timeout=timeout,
                utilization=(
                    pool.get_size() / pool.get_max_size() if pool.get_max_size() > 0 else 1.0
                ),
            )

            if circuit_breaker:
                circuit_breaker.record_failure()

            logger.warning(
                "Connection pool timeout (attempt %s/%s), pool utilization: %s/%s",
                attempt + 1,
                retries,
                pool.get_size(),
                pool.get_max_size(),
            )

        except Exception as e:  # noqa: BLE001 - retry loop must catch all transient pool/connection errors (asyncpg, network, etc.)
            _pool_metrics["failed_acquisitions"] += 1
            last_error = e

            if circuit_breaker:
                circuit_breaker.record_failure()

            logger.warning(
                "Connection acquisition error (attempt %s/%s): %s", attempt + 1, retries, e
            )

        # Exponential backoff before retry (except on last attempt)
        if attempt < retries - 1:
            delay = backoff_base * (2**attempt)
            await asyncio.sleep(delay)

    # All retries exhausted
    total_time = time.time() - start_time
    logger.error(
        f"Connection acquisition failed after {retries} attempts ({total_time:.2f}s total)"
    )

    if last_error:
        raise last_error
    raise PoolExhaustedError(timeout=timeout, utilization=1.0)


class PostgresStore(ABC):
    """
    Base class for PostgreSQL-backed stores with schema management.

    Provides:
    - Async connection management via connection pool
    - Schema versioning and migrations
    - Common CRUD helpers

    Subclasses must define:
    - SCHEMA_NAME: Unique identifier for schema versioning
    - SCHEMA_VERSION: Current schema version number
    - INITIAL_SCHEMA: SQL for initial table/index creation

    Example:
        class TodoStore(PostgresStore):
            SCHEMA_NAME = "todo_store"
            SCHEMA_VERSION = 1

            INITIAL_SCHEMA = '''
                CREATE TABLE IF NOT EXISTS todos (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    completed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            '''

            async def add_todo(self, todo_id: str, title: str) -> None:
                async with self.connection() as conn:
                    await conn.execute(
                        "INSERT INTO todos (id, title) VALUES ($1, $2)",
                        todo_id, title
                    )
    """

    # Subclasses must define these
    SCHEMA_NAME: str = ""
    SCHEMA_VERSION: int = 1
    INITIAL_SCHEMA: str = ""

    def __init__(
        self,
        pool: Pool,
        use_resilient: bool = True,
        acquire_timeout: float = POOL_ACQUIRE_TIMEOUT,
        acquire_retries: int = 3,
    ):
        """
        Initialize the store with a connection pool.

        Args:
            pool: asyncpg connection pool (from get_postgres_pool())
            use_resilient: Whether to use resilient connection acquisition with
                          circuit breaker, timeouts, and retries (default True)
            acquire_timeout: Timeout in seconds for connection acquisition (default 10)
            acquire_retries: Number of retries on acquisition failure (default 3)
        """
        if not ASYNCPG_AVAILABLE:
            raise RuntimeError("asyncpg is required for PostgresStore")

        self._pool = pool
        self._initialized = False
        self._use_resilient = use_resilient
        self._acquire_timeout = acquire_timeout
        self._acquire_retries = acquire_retries

        # Validate subclass configuration
        if not self.SCHEMA_NAME:
            raise ValueError(f"{self.__class__.__name__} must define SCHEMA_NAME")
        if not self.INITIAL_SCHEMA:
            raise ValueError(f"{self.__class__.__name__} must define INITIAL_SCHEMA")

    async def initialize(self) -> None:
        """
        Initialize database schema.

        Creates tables, indexes, and runs any pending migrations.
        Must be called before using the store.
        """
        if self._initialized:
            return

        async with self.connection() as conn:
            # Create schema version tracking table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS _schema_versions (
                    module TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # Check current version
            row = await conn.fetchrow(
                "SELECT version FROM _schema_versions WHERE module = $1", self.SCHEMA_NAME
            )
            current_version = row["version"] if row else 0

            if current_version == 0:
                # New database - run initial schema
                logger.info(
                    "[%s] Creating initial schema v%s", self.SCHEMA_NAME, self.SCHEMA_VERSION
                )
                await conn.execute(self.INITIAL_SCHEMA)
                await conn.execute(
                    """
                    INSERT INTO _schema_versions (module, version)
                    VALUES ($1, $2)
                    ON CONFLICT (module) DO UPDATE SET version = $2, updated_at = NOW()
                """,
                    self.SCHEMA_NAME,
                    self.SCHEMA_VERSION,
                )

            elif current_version < self.SCHEMA_VERSION:
                # Run migrations
                logger.info(
                    "[%s] Migrating from v%s to v%s",
                    self.SCHEMA_NAME,
                    current_version,
                    self.SCHEMA_VERSION,
                )
                await self._run_migrations(conn, current_version)
                await conn.execute(
                    """
                    UPDATE _schema_versions SET version = $1, updated_at = NOW()
                    WHERE module = $2
                """,
                    self.SCHEMA_VERSION,
                    self.SCHEMA_NAME,
                )

        self._initialized = True
        logger.debug("[%s] Schema initialized at version %s", self.SCHEMA_NAME, self.SCHEMA_VERSION)

    async def _run_migrations(self, conn: Connection, from_version: int) -> None:
        """
        Run migrations from current version to target version.

        Override in subclasses to define migrations.

        Args:
            conn: Database connection
            from_version: Current schema version
        """
        # Default: re-run initial schema (safe due to IF NOT EXISTS)
        await conn.execute(self.INITIAL_SCHEMA)

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[Connection, None]:
        """
        Context manager for database operations.

        Acquires a connection from the pool and returns it after use.
        Uses resilient acquisition with circuit breaker and retries if enabled.

        Yields:
            asyncpg Connection for database operations

        Raises:
            PoolExhaustedError: If pool is exhausted (when use_resilient=True)
            CircuitOpenError: If circuit breaker is open (when use_resilient=True)
        """
        if self._use_resilient:
            async with acquire_connection_resilient(
                self._pool,
                timeout=self._acquire_timeout,
                retries=self._acquire_retries,
            ) as conn:
                yield conn
        else:
            async with self._pool.acquire() as conn:
                yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[Connection, None]:
        """
        Context manager for transactional operations.

        Starts a transaction and commits on success, rolls back on error.
        Uses resilient acquisition with circuit breaker and retries if enabled.

        Yields:
            asyncpg Connection within a transaction

        Raises:
            PoolExhaustedError: If pool is exhausted (when use_resilient=True)
            CircuitOpenError: If circuit breaker is open (when use_resilient=True)
        """
        if self._use_resilient:
            async with acquire_connection_resilient(
                self._pool,
                timeout=self._acquire_timeout,
                retries=self._acquire_retries,
            ) as conn:
                async with conn.transaction():
                    yield conn
        else:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    yield conn

    # =========================================================================
    # Common Query Helpers
    # =========================================================================

    async def fetch_one(
        self,
        sql: str,
        *args: Any,
    ) -> Any | None:  # Returns asyncpg.Record when available
        """
        Execute query and fetch single row.

        Args:
            sql: SQL query with $1, $2, etc placeholders
            *args: Query parameters

        Returns:
            Single row as asyncpg.Record, or None if no results
        """
        async with self.connection() as conn:
            return await conn.fetchrow(sql, *args)

    async def fetch_all(
        self,
        sql: str,
        *args: Any,
    ) -> list[Any]:  # Returns list[asyncpg.Record] when available
        """
        Execute query and fetch all rows.

        Args:
            sql: SQL query with $1, $2, etc placeholders
            *args: Query parameters

        Returns:
            List of rows as asyncpg.Record
        """
        async with self.connection() as conn:
            return await conn.fetch(sql, *args)

    async def execute(
        self,
        sql: str,
        *args: Any,
    ) -> str:
        """
        Execute a write operation.

        Args:
            sql: SQL statement with $1, $2, etc placeholders
            *args: Statement parameters

        Returns:
            Command status string (e.g., "INSERT 0 1")
        """
        async with self.connection() as conn:
            return await conn.execute(sql, *args)

    async def executemany(
        self,
        sql: str,
        args_list: list[tuple[Any, ...]],
    ) -> None:
        """
        Execute a SQL statement with multiple parameter sets.

        Args:
            sql: SQL statement with $1, $2, etc placeholders
            args_list: List of parameter tuples
        """
        async with self.connection() as conn:
            await conn.executemany(sql, args_list)

    # =========================================================================
    # Common CRUD Helpers
    # =========================================================================

    async def exists(self, table: str, id_column: str, id_value: str) -> bool:
        """
        Check if a record exists.

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

        query = f"SELECT 1 FROM {table} WHERE {id_column} = $1"  # nosec B608
        row = await self.fetch_one(query, id_value)
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
        dangerous = ["'", '"', ";", "--", "/*", "*/", "xp_", "EXEC ", "EXECUTE "]
        where_check = where.upper()
        for pattern in dangerous:
            if pattern.upper() in where_check:
                raise ValueError(
                    "WHERE clause contains unsafe pattern. "
                    "Use parameterized placeholders ($1, $2) instead of literal values."
                )

        # Warn if WHERE has no placeholders but also no params
        # This suggests possible misuse (raw values in WHERE)
        has_placeholder = "$" in where or "?" in where
        if not has_placeholder and not has_params:
            # Allow simple column checks like "deleted_at IS NULL"
            safe_patterns = ["IS NULL", "IS NOT NULL", "TRUE", "FALSE"]
            if not any(p in where_check for p in safe_patterns):
                logger.warning(
                    "WHERE clause without placeholders or params may indicate SQL injection risk: %s",
                    where[:50],
                )

    async def count(
        self,
        table: str,
        where: str = "",
        *args: Any,
    ) -> int:
        """
        Count records in a table.

        Args:
            table: Table name
            where: Optional WHERE clause (without "WHERE" keyword).
                   MUST use parameterized placeholders ($1, $2, etc.) for values.
                   Example: "status = $1 AND user_id = $2"
            *args: Parameter values for WHERE clause placeholders

        Returns:
            Record count

        Raises:
            ValueError: If table name is invalid or WHERE contains injection patterns

        Security:
            Never pass user input directly in the WHERE clause.
            Always use placeholders: count("users", "status = $1", user_status)
        """
        if not table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {table}")

        self._validate_where_clause(where, bool(args))

        sql = f"SELECT COUNT(*) FROM {table}"  # nosec B608 - table validated above
        if where:
            sql += f" WHERE {where}"  # nosec B608 - validated by _validate_where_clause

        row = await self.fetch_one(sql, *args)
        return row[0] if row else 0

    async def delete_by_id(
        self,
        table: str,
        id_column: str,
        id_value: str,
    ) -> bool:
        """
        Delete a record by ID.

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

        query = f"DELETE FROM {table} WHERE {id_column} = $1"  # nosec B608
        result = await self.execute(query, id_value)
        # Result is like "DELETE 1" or "DELETE 0"
        return result.endswith(" 0") is False

    async def get_schema_version(self) -> int:
        """
        Get the current schema version from database.

        Returns:
            Current schema version, or 0 if not yet initialized
        """
        try:
            row = await self.fetch_one(
                "SELECT version FROM _schema_versions WHERE module = $1", self.SCHEMA_NAME
            )
            return row[0] if row else 0
        except (OSError, RuntimeError) as e:
            # Table may not exist yet, or connection issue
            logger.debug("Could not fetch schema version: %s", e)
            return 0


__all__ = [
    "PostgresStore",
    "get_postgres_pool",
    "get_postgres_pool_from_settings",
    "close_postgres_pool",
    "acquire_connection_resilient",
    "get_pool_metrics",
    "is_pool_healthy",
    "reset_pool_metrics",
    "PoolMetrics",
    "PoolExhaustedError",
    "ASYNCPG_AVAILABLE",
    "POOL_ACQUIRE_TIMEOUT",
    "POOL_BACKPRESSURE_THRESHOLD",
    "POOL_CIRCUIT_BREAKER_THRESHOLD",
    "POOL_CIRCUIT_BREAKER_COOLDOWN",
]
