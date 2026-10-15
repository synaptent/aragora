"""
Database connection resilience with retry logic.

Provides ResilientConnection for automatic retry on transient SQLite errors
like "database is locked" and "database is busy".

Also provides PostgreSQL resilience with:
- Transient error detection (connection refused, pool exhausted, network timeout)
- Circuit breaker pattern for database connectivity
- Pool configuration validation
"""

from __future__ import annotations

__all__ = [
    "TRANSIENT_ERRORS",
    "POSTGRES_TRANSIENT_ERRORS",
    "is_transient_error",
    "is_postgres_transient_error",
    "ResilientConnection",
    "ResilientPostgresConnection",
    "PostgresCircuitBreaker",
    "with_retry",
    "with_postgres_retry",
    "atomic_transaction",
    "ConnectionPool",
    "validate_postgres_pool_config",
]

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar
from collections.abc import Callable

from aragora.config import DB_TIMEOUT_SECONDS
from aragora.config import resolve_db_path
from aragora.exceptions import InfrastructureError

logger = logging.getLogger(__name__)

# Type variable for generic return type
T = TypeVar("T")

# Transient errors that can be retried (lowercase for comparison)
TRANSIENT_ERRORS = (
    "database is locked",
    "database is busy",
    "unable to open database file",
    "disk i/o error",
)


def is_transient_error(error: Exception) -> bool:
    """Check if an error is transient and can be retried."""
    error_msg = str(error).lower()
    return any(te in error_msg for te in TRANSIENT_ERRORS)


class ResilientConnection:
    """
    SQLite connection wrapper with automatic retry on transient errors.

    Provides exponential backoff retry logic for handling temporary failures
    like locked databases, busy connections, and I/O errors.

    Usage:
        conn = ResilientConnection("/path/to/db.sqlite")

        # Using transaction context manager
        with conn.transaction() as cursor:
            cursor.execute("SELECT * FROM users")
            rows = cursor.fetchall()

        # Using execute with automatic retry
        result = conn.execute("INSERT INTO logs (msg) VALUES (?)", ("hello",))
    """

    def __init__(
        self,
        db_path: str,
        max_retries: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 2.0,
        timeout: float = DB_TIMEOUT_SECONDS,
    ):
        """
        Initialize resilient connection.

        Args:
            db_path: Path to SQLite database file
            max_retries: Maximum number of retry attempts (default: 3)
            base_delay: Initial delay between retries in seconds (default: 0.1)
            max_delay: Maximum delay between retries in seconds (default: 2.0)
            timeout: SQLite busy timeout in seconds (default: DB_TIMEOUT_SECONDS)
        """
        self.db_path = Path(resolve_db_path(db_path))
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.timeout = timeout

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection with timeout configured."""
        conn = sqlite3.connect(self.db_path, timeout=self.timeout)
        conn.row_factory = sqlite3.Row
        return conn

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for exponential backoff."""
        delay = self.base_delay * (2**attempt)
        return min(delay, self.max_delay)

    @contextmanager
    def transaction(self):
        """
        Context manager for database transactions with auto-retry.

        Automatically retries on transient errors with exponential backoff.
        Commits on success, rolls back on error.

        Yields:
            sqlite3.Cursor: Database cursor for executing queries

        Raises:
            sqlite3.Error: If all retry attempts fail
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            conn: sqlite3.Connection | None = None
            try:
                conn = self._create_connection()
                cursor = conn.cursor()
                yield cursor
                conn.commit()
                return
            except sqlite3.Error as e:
                last_error = e
                if conn:
                    try:
                        conn.rollback()
                    except sqlite3.Error as rollback_err:
                        logger.debug("Rollback failed during error recovery: %s", rollback_err)

                if not is_transient_error(e) or attempt >= self.max_retries:
                    logger.error("Database error after %s attempts: %s", attempt + 1, e)
                    raise

                delay = self._calculate_delay(attempt)
                logger.warning(
                    f"Transient database error (attempt {attempt + 1}/{self.max_retries + 1}): {e}. "
                    f"Retrying in {delay:.2f}s"
                )
                time.sleep(delay)
            finally:
                if conn:
                    try:
                        conn.close()
                    except sqlite3.Error as close_err:
                        logger.debug("Connection close failed: %s", close_err)

        # Should not reach here, but just in case
        if last_error:
            raise last_error

    def execute(
        self,
        query: str,
        params: tuple = (),
        fetch: bool = False,
    ):
        """
        Execute a single query with automatic retry.

        Args:
            query: SQL query to execute
            params: Query parameters
            fetch: If True, return fetched rows; if False, return lastrowid

        Returns:
            If fetch=True: List of sqlite3.Row objects
            If fetch=False: Last row ID from insert
        """
        with self.transaction() as cursor:
            cursor.execute(query, params)
            if fetch:
                return cursor.fetchall()
            return cursor.lastrowid

    def executemany(
        self,
        query: str,
        params_list: list[tuple],
    ) -> int:
        """
        Execute a query with multiple parameter sets.

        Args:
            query: SQL query to execute
            params_list: List of parameter tuples

        Returns:
            Number of rows affected
        """
        with self.transaction() as cursor:
            cursor.executemany(query, params_list)
            return cursor.rowcount


def with_retry(
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 2.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for adding retry logic to database operations.

    Automatically retries functions that raise transient SQLite errors.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds

    Usage:
        @with_retry(max_retries=3)
        def save_record(db_path: str, data: dict):
            with sqlite3.connect(db_path) as conn:
                conn.execute("INSERT INTO records (data) VALUES (?)", (json.dumps(data),))
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_error: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except sqlite3.Error as e:
                    last_error = e

                    if not is_transient_error(e) or attempt >= max_retries:
                        logger.error(
                            "Database error in %s after %s attempts: %s",
                            func.__name__,
                            attempt + 1,
                            e,
                        )
                        raise

                    delay = min(base_delay * (2**attempt), max_delay)
                    logger.warning(
                        f"Transient error in {func.__name__} (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Retrying in {delay:.2f}s"
                    )
                    time.sleep(delay)

            # Should not reach here
            if last_error:
                raise last_error
            raise InfrastructureError("Unexpected retry loop exit in database resilience layer")

        return wrapper

    return decorator


@contextmanager
def atomic_transaction(
    db_path: str,
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 2.0,
):
    """
    Execute database operations atomically with retry on transient errors.

    Uses BEGIN IMMEDIATE to acquire a write lock early, preventing deadlocks
    when multiple operations need to be atomic. Automatically retries on
    transient errors like "database is locked".

    Args:
        db_path: Path to the SQLite database file
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay between retries in seconds (default: 0.1)
        max_delay: Maximum delay between retries in seconds (default: 2.0)

    Yields:
        sqlite3.Connection: Database connection with active transaction

    Raises:
        sqlite3.OperationalError: If all retry attempts fail

    Usage:
        from aragora.storage.resilience import atomic_transaction

        with atomic_transaction("/path/to/db.sqlite") as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE accounts SET balance = balance - ?", (amount,))
            cursor.execute("UPDATE accounts SET balance = balance + ?", (amount,))
            # Commit happens automatically on successful exit
    """
    from aragora.storage.schema import get_wal_connection

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        conn: sqlite3.Connection | None = None
        try:
            conn = get_wal_connection(db_path)
            # BEGIN IMMEDIATE acquires a write lock immediately,
            # failing fast if another process has the lock
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            last_error = e
            if conn:
                try:
                    conn.rollback()
                except sqlite3.Error as rollback_err:
                    logger.debug("Rollback failed in atomic_transaction: %s", rollback_err)

            if not is_transient_error(e) or attempt >= max_retries:
                logger.error("Atomic transaction failed after %s attempts: %s", attempt + 1, e)
                raise

            delay = min(base_delay * (2**attempt), max_delay)
            logger.warning(
                f"Transient error in atomic transaction (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                f"Retrying in {delay:.2f}s"
            )
            time.sleep(delay)
        finally:
            if conn:
                try:
                    conn.close()
                except sqlite3.Error as close_err:
                    logger.debug("Connection close failed in atomic_transaction: %s", close_err)

    # Should not reach here, but just in case
    if last_error:
        raise last_error


class ConnectionPool:
    """
    Thread-safe connection pool for SQLite with WAL mode and health checking.

    Maintains a pool of reusable connections to reduce connection overhead.
    Automatically removes stale connections and creates new ones as needed.

    Usage:
        pool = ConnectionPool("/path/to/db.sqlite")

        with pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users")

        # Get stats for observability
        stats = pool.get_stats()
    """

    def __init__(
        self,
        db_path: str,
        max_connections: int = 5,
        timeout: float = DB_TIMEOUT_SECONDS,
        enable_wal: bool = True,
    ):
        """
        Initialize connection pool.

        Args:
            db_path: Path to SQLite database
            max_connections: Maximum pool size
            timeout: SQLite busy timeout
            enable_wal: Enable WAL mode for better concurrency
        """
        self.db_path = Path(resolve_db_path(db_path))
        self.max_connections = max_connections
        self.timeout = timeout
        self.enable_wal = enable_wal
        self._pool: list[sqlite3.Connection] = []
        self._in_use: set[sqlite3.Connection] = set()
        self._lock = threading.Lock()

        # Observability metrics
        self._connections_created: int = 0
        self._connections_reused: int = 0
        self._connections_closed: int = 0
        self._health_check_failures: int = 0

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new connection with WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=self.timeout)
        conn.row_factory = sqlite3.Row

        # Enable WAL mode for better concurrency
        if self.enable_wal:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")  # 30 second busy timeout

        self._connections_created += 1
        return conn

    def _is_connection_healthy(self, conn: sqlite3.Connection) -> bool:
        """Check if connection is still usable."""
        try:
            conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            self._health_check_failures += 1
            return False

    @contextmanager
    def get_connection(self):
        """
        Get a connection from the pool (thread-safe).

        Yields:
            sqlite3.Connection: A database connection

        The connection is automatically returned to the pool when done.
        """
        conn: sqlite3.Connection | None = None

        with self._lock:
            # Try to get an existing connection from pool
            while self._pool:
                candidate = self._pool.pop()
                if self._is_connection_healthy(candidate):
                    conn = candidate
                    self._connections_reused += 1
                    break
                else:
                    try:
                        candidate.close()
                        self._connections_closed += 1
                    except sqlite3.Error as close_err:
                        logger.debug("Failed to close unhealthy connection: %s", close_err)

            # Create new connection if needed
            if conn is None:
                conn = self._create_connection()

            self._in_use.add(conn)

        try:
            yield conn
        finally:
            with self._lock:
                self._in_use.discard(conn)
                # Return to pool if not at max
                if len(self._pool) < self.max_connections:
                    self._pool.append(conn)
                else:
                    try:
                        conn.close()
                        self._connections_closed += 1
                    except sqlite3.Error as close_err:
                        logger.debug("Failed to close excess connection: %s", close_err)

    def close_all(self) -> None:
        """Close all connections in the pool (thread-safe)."""
        with self._lock:
            for conn in self._pool:
                try:
                    conn.close()
                    self._connections_closed += 1
                except sqlite3.Error as close_err:
                    logger.debug("Failed to close pooled connection: %s", close_err)
            self._pool.clear()

            for conn in list(self._in_use):
                try:
                    conn.close()
                    self._connections_closed += 1
                except sqlite3.Error as close_err:
                    logger.debug("Failed to close in-use connection: %s", close_err)
            self._in_use.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get connection pool statistics for observability."""
        with self._lock:
            return {
                "db_path": self.db_path,
                "max_connections": self.max_connections,
                "active": len(self._in_use),
                "idle": len(self._pool),
                "total": len(self._in_use) + len(self._pool),
                # Metrics
                "connections_created": self._connections_created,
                "connections_reused": self._connections_reused,
                "connections_closed": self._connections_closed,
                "health_check_failures": self._health_check_failures,
                "reuse_rate": (
                    self._connections_reused
                    / (self._connections_created + self._connections_reused)
                    if (self._connections_created + self._connections_reused) > 0
                    else 0.0
                ),
            }

    def reset_metrics(self) -> None:
        """Reset observability metrics (useful for testing)."""
        with self._lock:
            self._connections_created = 0
            self._connections_reused = 0
            self._connections_closed = 0
            self._health_check_failures = 0


# =============================================================================
# PostgreSQL Resilience
# =============================================================================

# PostgreSQL transient errors that can be retried
POSTGRES_TRANSIENT_ERRORS = (
    # Connection errors
    "connection refused",
    "connection reset",
    "connection timed out",
    "could not connect",
    "server closed the connection",
    "ssl connection has been closed",
    "connection is closed",
    # Pool exhaustion
    "connection pool exhausted",
    "too many connections",
    "too many clients",
    # Network errors
    "network is unreachable",
    "no route to host",
    "name or service not known",
    "temporary failure in name resolution",
    # Operational errors
    "canceling statement due to user request",
    "query_canceled",
    "lock wait timeout",
    "deadlock detected",
    "serialization_failure",
)


def is_postgres_transient_error(error: Exception) -> bool:
    """Check if a PostgreSQL error is transient and can be retried."""
    error_msg = str(error).lower()
    error_type = type(error).__name__.lower()

    # Check error message
    if any(te in error_msg for te in POSTGRES_TRANSIENT_ERRORS):
        return True

    # Check common psycopg2 error types
    transient_error_types = (
        "operationalerror",
        "interfaceerror",
        "databaseerror",
    )
    if error_type in transient_error_types:
        # These are transient if they contain connection-related messages
        connection_indicators = ("connection", "network", "timeout", "refused")
        if any(ind in error_msg for ind in connection_indicators):
            return True

    return False


class PostgresCircuitBreaker:
    """
    Circuit breaker for PostgreSQL connections.

    Prevents cascade failures by temporarily blocking database operations
    when the database is unavailable, allowing it time to recover.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Failures exceeded threshold, requests blocked for reset_timeout
    - HALF_OPEN: Testing if database has recovered

    Usage:
        breaker = PostgresCircuitBreaker(failure_threshold=5, reset_timeout=30)

        if not breaker.allow_request():
            raise DatabaseUnavailableError("Circuit breaker is open")

        try:
            result = execute_db_operation()
            breaker.record_success()
        except Exception as e:  # noqa: BLE001 - circuit breaker must track all failures
            breaker.record_failure(e)
            raise
    """

    # Circuit breaker states
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        half_open_max_calls: int = 3,
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            reset_timeout: Seconds to wait before trying half-open state
            half_open_max_calls: Max concurrent calls in half-open state
        """
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = self.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """Current circuit breaker state."""
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        """Current failure count."""
        with self._lock:
            return self._failure_count

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        with self._lock:
            if self._state == self.CLOSED:
                return True

            if self._state == self.OPEN:
                # Check if we should transition to half-open
                if self._last_failure_time is not None:
                    elapsed = time.time() - self._last_failure_time
                    if elapsed >= self.reset_timeout:
                        self._state = self.HALF_OPEN
                        self._half_open_calls = 0
                        logger.info("Circuit breaker transitioning to HALF_OPEN")
                        return True
                return False

            if self._state == self.HALF_OPEN:
                # Allow limited concurrent calls in half-open state
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False

            return False

    def record_success(self) -> None:
        """Record a successful database operation."""
        with self._lock:
            self._success_count += 1

            if self._state == self.HALF_OPEN:
                # One success in half-open closes the circuit
                self._state = self.CLOSED
                self._failure_count = 0
                self._half_open_calls = 0
                logger.info("Circuit breaker CLOSED after successful half-open call")
            elif self._state == self.CLOSED:
                # Reset failure count on success (sliding window would be better)
                if self._failure_count > 0:
                    self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self, error: Exception | None = None) -> None:
        """Record a failed database operation."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == self.HALF_OPEN:
                # Any failure in half-open reopens the circuit
                self._state = self.OPEN
                self._half_open_calls = 0
                logger.warning("Circuit breaker OPEN after half-open failure: %s", error)
            elif self._state == self.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._state = self.OPEN
                    logger.warning(
                        "Circuit breaker OPEN after %s failures: %s", self._failure_count, error
                    )

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self._state = self.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._half_open_calls = 0
            logger.info("Circuit breaker manually reset to CLOSED")

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        with self._lock:
            return {
                "state": self._state,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "failure_threshold": self.failure_threshold,
                "reset_timeout": self.reset_timeout,
                "last_failure_time": self._last_failure_time,
            }


class ResilientPostgresConnection:
    """
    PostgreSQL connection wrapper with automatic retry on transient errors.

    Provides exponential backoff retry logic and circuit breaker integration
    for handling temporary failures like connection refused, pool exhaustion,
    and network timeouts.

    Usage:
        conn = ResilientPostgresConnection(dsn="postgresql://user:pass@host/db")

        # Execute with automatic retry
        result = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,))

        # Use circuit breaker
        if not conn.circuit_breaker.allow_request():
            raise DatabaseUnavailableError("Database circuit breaker is open")
    """

    def __init__(
        self,
        dsn: str | None = None,
        host: str = "localhost",
        port: int = 5432,
        database: str = "aragora",
        user: str = "aragora",
        password: str = "",
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 10.0,
        connect_timeout: float = 10.0,
        circuit_breaker: PostgresCircuitBreaker | None = None,
    ):
        """
        Initialize resilient PostgreSQL connection.

        Args:
            dsn: PostgreSQL connection string (takes precedence)
            host: Database host
            port: Database port
            database: Database name
            user: Database user
            password: Database password
            max_retries: Maximum retry attempts
            base_delay: Initial retry delay in seconds
            max_delay: Maximum retry delay in seconds
            connect_timeout: Connection timeout in seconds
            circuit_breaker: Optional circuit breaker instance
        """
        self.dsn = dsn
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.connect_timeout = connect_timeout
        self.circuit_breaker = circuit_breaker or PostgresCircuitBreaker()

        self._psycopg2: Any = None
        self._initialized = False

        # Try to import psycopg2
        try:
            import psycopg2

            self._psycopg2 = psycopg2
            self._initialized = True
        except ImportError:
            logger.warning(
                "psycopg2 not installed. PostgreSQL resilience unavailable. "
                "Install with: pip install psycopg2-binary"
            )

    def _create_connection(self) -> Any:
        """Create a new PostgreSQL connection."""
        if not self._initialized or self._psycopg2 is None:
            raise InfrastructureError("PostgreSQL driver not available. Install psycopg2-binary.")

        if self.dsn:
            return self._psycopg2.connect(
                self.dsn,
                connect_timeout=int(self.connect_timeout),
            )

        return self._psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.database,
            user=self.user,
            password=self.password,
            connect_timeout=int(self.connect_timeout),
        )

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter."""
        import random

        delay = self.base_delay * (2**attempt)
        delay = min(delay, self.max_delay)
        # Add jitter (±25%)
        jitter = delay * 0.25 * (2 * random.random() - 1)
        return delay + jitter

    @contextmanager
    def transaction(self):
        """
        Context manager for PostgreSQL transactions with auto-retry.

        Automatically retries on transient errors with exponential backoff.
        Commits on success, rolls back on error.

        Yields:
            Database cursor for executing queries

        Raises:
            Exception: If all retry attempts fail or circuit breaker is open
        """
        if not self.circuit_breaker.allow_request():
            raise InfrastructureError("PostgreSQL circuit breaker is open. Database unavailable.")

        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            conn = None
            try:
                conn = self._create_connection()
                cursor = conn.cursor()
                yield cursor
                conn.commit()
                self.circuit_breaker.record_success()
                return
            except (OSError, RuntimeError, ConnectionError, TimeoutError, ValueError) as e:
                last_error = e
                if conn:
                    try:
                        conn.rollback()
                    except (OSError, RuntimeError, ConnectionError) as rollback_err:
                        logger.debug("Rollback failed: %s", rollback_err)

                if not is_postgres_transient_error(e) or attempt >= self.max_retries:
                    logger.error("PostgreSQL error after %s attempts: %s", attempt + 1, e)
                    self.circuit_breaker.record_failure(e)
                    raise

                delay = self._calculate_delay(attempt)
                logger.warning(
                    f"Transient PostgreSQL error (attempt {attempt + 1}/{self.max_retries + 1}): {e}. "
                    f"Retrying in {delay:.2f}s"
                )
                time.sleep(delay)
            finally:
                if conn:
                    try:
                        conn.close()
                    except (OSError, RuntimeError, ConnectionError) as close_err:
                        logger.debug("Connection close failed: %s", close_err)

        if last_error:
            self.circuit_breaker.record_failure(last_error)
            raise last_error

    def execute(
        self,
        query: str,
        params: tuple = (),
        fetch: bool = False,
    ):
        """
        Execute a single query with automatic retry.

        Args:
            query: SQL query to execute
            params: Query parameters
            fetch: If True, return fetched rows

        Returns:
            If fetch=True: List of tuples
            If fetch=False: Row count
        """
        with self.transaction() as cursor:
            cursor.execute(query, params)
            if fetch:
                return cursor.fetchall()
            return cursor.rowcount

    def fetch_one(self, query: str, params: tuple = ()) -> tuple | None:
        """Execute query and fetch single row."""
        with self.transaction() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()

    def fetch_all(self, query: str, params: tuple = ()) -> list[tuple]:
        """Execute query and fetch all rows."""
        with self.transaction() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()


def with_postgres_retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    circuit_breaker: PostgresCircuitBreaker | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for adding retry logic to PostgreSQL operations.

    Automatically retries functions that raise transient PostgreSQL errors.

    Args:
        max_retries: Maximum retry attempts
        base_delay: Initial retry delay in seconds
        max_delay: Maximum retry delay in seconds
        circuit_breaker: Optional circuit breaker instance

    Usage:
        @with_postgres_retry(max_retries=3)
        def save_to_postgres(conn, data):
            cursor = conn.cursor()
            cursor.execute("INSERT INTO records (data) VALUES (%s)", (data,))
            conn.commit()
    """
    import random

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            if circuit_breaker and not circuit_breaker.allow_request():
                raise InfrastructureError(
                    "PostgreSQL circuit breaker is open. Database unavailable."
                )

            last_error: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    if circuit_breaker:
                        circuit_breaker.record_success()
                    return result
                except (OSError, RuntimeError, ConnectionError, TimeoutError, ValueError) as e:
                    last_error = e

                    if not is_postgres_transient_error(e) or attempt >= max_retries:
                        logger.error(
                            "PostgreSQL error in %s after %s attempts: %s",
                            func.__name__,
                            attempt + 1,
                            e,
                        )
                        if circuit_breaker:
                            circuit_breaker.record_failure(e)
                        raise

                    delay = min(base_delay * (2**attempt), max_delay)
                    # Add jitter
                    jitter = delay * 0.25 * (2 * random.random() - 1)
                    delay += jitter

                    logger.warning(
                        f"Transient PostgreSQL error in {func.__name__} "
                        f"(attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Retrying in {delay:.2f}s"
                    )
                    time.sleep(delay)

            if last_error:
                if circuit_breaker:
                    circuit_breaker.record_failure(last_error)
                raise last_error
            raise InfrastructureError("Unexpected retry loop exit in PostgreSQL resilience layer")

        return wrapper

    return decorator


def validate_postgres_pool_config(
    pool_size: int | None = None,
    max_overflow: int | None = None,
) -> tuple[bool, list[str]]:
    """
    Validate PostgreSQL connection pool configuration.

    Checks that pool settings are reasonable for production use.

    Args:
        pool_size: Pool size (reads from ARAGORA_DB_POOL_SIZE if None)
        max_overflow: Max overflow (reads from ARAGORA_DB_POOL_MAX_OVERFLOW if None)

    Returns:
        Tuple of (is_valid, error_messages)

    Usage:
        valid, errors = validate_postgres_pool_config()
        if not valid:
            for error in errors:
                print(f"Pool config error: {error}")
    """
    import os

    errors: list[str] = []

    # Read from environment if not provided
    if pool_size is None:
        pool_size_str = os.environ.get("ARAGORA_DB_POOL_SIZE", "20")
        try:
            pool_size = int(pool_size_str)
        except ValueError:
            errors.append(f"ARAGORA_DB_POOL_SIZE must be an integer, got: {pool_size_str}")
            pool_size = 0

    if max_overflow is None:
        max_overflow_str = os.environ.get("ARAGORA_DB_POOL_MAX_OVERFLOW", "15")
        try:
            max_overflow = int(max_overflow_str)
        except ValueError:
            errors.append(
                f"ARAGORA_DB_POOL_MAX_OVERFLOW must be an integer, got: {max_overflow_str}"
            )
            max_overflow = 0

    # Validate pool size
    if pool_size < 1:
        errors.append(f"Pool size must be at least 1, got: {pool_size}")
    elif pool_size < 5:
        logger.warning(
            "Pool size %s is low for production. Consider increasing ARAGORA_DB_POOL_SIZE to at least 10.",
            pool_size,
        )
    elif pool_size > 100:
        errors.append(
            f"Pool size {pool_size} is too high. "
            "Most PostgreSQL servers have max_connections around 100. "
            "Set ARAGORA_DB_POOL_SIZE to a lower value."
        )

    # Validate max overflow
    if max_overflow < 0:
        errors.append(f"Max overflow must be non-negative, got: {max_overflow}")
    elif max_overflow > pool_size:
        logger.warning(
            "Max overflow (%s) exceeds pool size (%s). This may cause connection issues under load.",
            max_overflow,
            pool_size,
        )

    # Check total connections vs typical PostgreSQL limits
    total_possible = pool_size + max_overflow
    if total_possible > 80:
        logger.warning(
            "Total possible connections (%s) is high. Ensure PostgreSQL max_connections is configured appropriately.",
            total_possible,
        )

    return len(errors) == 0, errors
