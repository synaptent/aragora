"""
PostgreSQL Transaction Handling with Savepoint Support.

Provides explicit transaction management for asyncpg connections with:
- Transaction commit and rollback
- Nested transactions via SAVEPOINTs
- Configurable isolation levels
- Deadlock detection and automatic retry
- Connection state validation

Usage:
    from aragora.persistence.transaction import (
        TransactionManager,
        TransactionIsolation,
        TransactionConfig,
    )

    # Basic transaction
    async with TransactionManager(pool) as txn:
        async with txn.transaction() as conn:
            await conn.execute("INSERT ...")

    # Nested transactions with savepoints
    async with txn.transaction() as conn:
        await conn.execute("INSERT ...")
        async with txn.savepoint(conn, "sp1"):
            await conn.execute("UPDATE ...")  # Can be rolled back independently
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class TransactionIsolation(str, Enum):
    """PostgreSQL transaction isolation levels.

    - READ_COMMITTED: Default. Each statement sees only data committed before it started.
    - REPEATABLE_READ: All statements see a snapshot from start of first statement.
    - SERIALIZABLE: Strictest. Transactions appear to run serially.
    """

    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"


class TransactionState(str, Enum):
    """States of a transaction lifecycle."""

    INACTIVE = "inactive"
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class DeadlockError(Exception):
    """Raised when a deadlock is detected and cannot be recovered."""

    def __init__(self, message: str, retry_count: int = 0):
        self.retry_count = retry_count
        super().__init__(message)


class TransactionError(Exception):
    """Base exception for transaction errors."""

    pass


class TransactionStateError(TransactionError):
    """Raised when transaction is in invalid state for operation."""

    def __init__(self, expected_state: str, actual_state: str, operation: str):
        self.expected_state = expected_state
        self.actual_state = actual_state
        self.operation = operation
        super().__init__(f"Cannot {operation}: expected state {expected_state}, got {actual_state}")


class SavepointError(TransactionError):
    """Raised when savepoint operations fail."""

    pass


@dataclass
class TransactionConfig:
    """Configuration for transaction behavior.

    Attributes:
        isolation: Default transaction isolation level
        timeout_seconds: Maximum time for a transaction (0 = no timeout)
        deadlock_retries: Number of times to retry on deadlock
        deadlock_base_delay: Base delay between deadlock retries (seconds)
        deadlock_max_delay: Maximum delay between deadlock retries (seconds)
        savepoint_on_nested: Whether to use savepoints for nested calls
        validate_connection_state: Check connection state before operations
    """

    isolation: TransactionIsolation = TransactionIsolation.READ_COMMITTED
    timeout_seconds: float = 30.0
    deadlock_retries: int = 3
    deadlock_base_delay: float = 0.1
    deadlock_max_delay: float = 2.0
    savepoint_on_nested: bool = True
    validate_connection_state: bool = True


@dataclass
class TransactionStats:
    """Statistics for transaction manager operations.

    Attributes:
        transactions_started: Total transactions started
        transactions_committed: Successfully committed transactions
        transactions_rolled_back: Explicitly rolled back transactions
        transactions_failed: Transactions that failed with errors
        savepoints_created: Total savepoints created
        savepoints_released: Successfully released savepoints
        savepoints_rolled_back: Savepoints that were rolled back
        deadlocks_detected: Number of deadlocks detected
        deadlocks_recovered: Number of deadlocks recovered via retry
        active_transactions: Currently active transaction count
        total_transaction_time_ms: Cumulative time spent in transactions
    """

    transactions_started: int = 0
    transactions_committed: int = 0
    transactions_rolled_back: int = 0
    transactions_failed: int = 0
    savepoints_created: int = 0
    savepoints_released: int = 0
    savepoints_rolled_back: int = 0
    deadlocks_detected: int = 0
    deadlocks_recovered: int = 0
    active_transactions: int = 0
    total_transaction_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "transactions_started": self.transactions_started,
            "transactions_committed": self.transactions_committed,
            "transactions_rolled_back": self.transactions_rolled_back,
            "transactions_failed": self.transactions_failed,
            "savepoints_created": self.savepoints_created,
            "savepoints_released": self.savepoints_released,
            "savepoints_rolled_back": self.savepoints_rolled_back,
            "deadlocks_detected": self.deadlocks_detected,
            "deadlocks_recovered": self.deadlocks_recovered,
            "active_transactions": self.active_transactions,
            "total_transaction_time_ms": round(self.total_transaction_time_ms, 2),
            "average_transaction_time_ms": (
                round(
                    self.total_transaction_time_ms
                    / max(self.transactions_committed + self.transactions_rolled_back, 1),
                    2,
                )
            ),
        }


@dataclass
class TransactionContext:
    """Context for an active transaction.

    Tracks state and metadata for a single transaction instance.
    """

    id: str
    connection: Any
    isolation: TransactionIsolation
    started_at: float = field(default_factory=time.time)
    state: TransactionState = TransactionState.INACTIVE
    savepoint_stack: list[str] = field(default_factory=list)
    nested_depth: int = 0

    @property
    def is_active(self) -> bool:
        """Check if transaction is currently active."""
        return self.state == TransactionState.ACTIVE

    @property
    def duration_ms(self) -> float:
        """Get transaction duration in milliseconds."""
        return (time.time() - self.started_at) * 1000


class TransactionManager:
    """
    Manages explicit transaction boundaries for PostgreSQL operations.

    Provides:
    - Explicit BEGIN/COMMIT/ROLLBACK
    - Savepoints for nested transactions
    - Timeout enforcement
    - Deadlock detection and retry
    - Connection state validation
    - Comprehensive statistics

    Usage:
        manager = TransactionManager(pool)

        async with manager.transaction() as conn:
            await conn.execute("INSERT INTO users ...")
            await conn.execute("UPDATE accounts ...")
            # Auto-commit on success, rollback on exception

        # With nested savepoint
        async with manager.transaction() as conn:
            await conn.execute("INSERT ...")
            async with manager.savepoint(conn, "checkpoint1"):
                try:
                    await conn.execute("RISKY UPDATE ...")
                except Exception:
                    # Only this part is rolled back
                    pass
            # Outer transaction continues
    """

    def __init__(
        self,
        pool: Any,
        config: TransactionConfig | None = None,
    ):
        """Initialize transaction manager.

        Args:
            pool: asyncpg connection pool (ReplicaAwarePool or asyncpg.Pool)
            config: Transaction configuration options
        """
        self._pool = pool
        self._config = config or TransactionConfig()
        self._stats = TransactionStats()
        self._active_contexts: dict[str, TransactionContext] = {}
        self._lock = asyncio.Lock()
        self._transaction_counter = 0

    def _generate_transaction_id(self) -> str:
        """Generate a unique transaction ID."""
        self._transaction_counter += 1
        return f"txn_{self._transaction_counter}_{int(time.time() * 1000)}"

    def _is_deadlock_error(self, error: Exception) -> bool:
        """Check if error is a deadlock error.

        PostgreSQL deadlock error codes:
        - 40001: serialization_failure
        - 40P01: deadlock_detected
        """
        error_str = str(error).lower()
        return (
            "deadlock" in error_str
            or "40001" in error_str
            or "40p01" in error_str
            or "serialization" in error_str
        )

    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter."""
        delay = self._config.deadlock_base_delay * (2**attempt)
        delay = min(delay, self._config.deadlock_max_delay)
        # Add jitter (+-25%)
        jitter = delay * (0.75 + random.random() * 0.5)
        return jitter

    async def _validate_connection(self, conn: Any) -> bool:
        """Validate that connection is in a usable state."""
        if not self._config.validate_connection_state:
            return True

        try:
            # Check connection is open and responsive
            await conn.fetchval("SELECT 1")
            return True
        except (ConnectionError, OSError, RuntimeError) as e:
            logger.warning("Connection validation failed: %s", e)
            return False

    @asynccontextmanager
    async def transaction(
        self,
        isolation: TransactionIsolation | None = None,
        timeout: float | None = None,
        readonly: bool = False,
    ) -> AsyncIterator[Any]:
        """
        Execute operations within an explicit transaction.

        Args:
            isolation: Override default isolation level
            timeout: Override default timeout (seconds)
            readonly: Hint that transaction is read-only (for replica routing)

        Yields:
            Database connection for executing queries

        Raises:
            TransactionError: If transaction cannot be started
            DeadlockError: If deadlock is detected (wrap with retry for auto-recovery)
            asyncio.TimeoutError: If timeout exceeded

        Note:
            This method does not automatically retry on deadlock internally.
            Deadlocks are detected and raised as DeadlockError. For automatic
            deadlock retry, use the `execute_with_retry` method instead.
        """
        isolation = isolation or self._config.isolation
        timeout = timeout if timeout is not None else self._config.timeout_seconds

        # Acquire connection from pool
        acquire_method = getattr(self._pool, "acquire", None)
        if acquire_method is None:
            raise TransactionError("Pool does not support acquire()")

        txn_id = self._generate_transaction_id()
        start_time = time.time()

        async with acquire_method(readonly=readonly) as conn:
            # Get the underlying connection if wrapped
            actual_conn = getattr(conn, "connection", conn)

            # Validate connection state
            if self._config.validate_connection_state:
                if not await self._validate_connection(actual_conn):
                    raise TransactionError("Connection validation failed")

            # Create transaction context
            ctx = TransactionContext(
                id=txn_id,
                connection=actual_conn,
                isolation=isolation,
                started_at=start_time,
                state=TransactionState.ACTIVE,
            )

            async with self._lock:
                self._active_contexts[txn_id] = ctx
                self._stats.transactions_started += 1
                self._stats.active_transactions += 1

            try:
                # Set isolation level and begin transaction
                await actual_conn.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation.value}")
                await actual_conn.execute("BEGIN")

                # Apply timeout if specified
                if timeout and timeout > 0:
                    async with asyncio.timeout(timeout):
                        yield actual_conn
                else:
                    yield actual_conn

                # Commit on success
                await actual_conn.execute("COMMIT")
                ctx.state = TransactionState.COMMITTED
                self._stats.transactions_committed += 1
                logger.debug("Transaction %s committed successfully", txn_id)

            except asyncio.TimeoutError:
                # Rollback on timeout
                await actual_conn.execute("ROLLBACK")
                ctx.state = TransactionState.ROLLED_BACK
                self._stats.transactions_rolled_back += 1
                logger.warning("Transaction %s rolled back: timeout", txn_id)
                raise

            except asyncio.CancelledError:
                # Rollback on cancellation
                await actual_conn.execute("ROLLBACK")
                ctx.state = TransactionState.ROLLED_BACK
                self._stats.transactions_rolled_back += 1
                raise

            except Exception as e:  # noqa: BLE001 - Intentional: rollback before re-raising
                # Rollback on any exception
                try:
                    await actual_conn.execute("ROLLBACK")
                except Exception as rollback_error:  # noqa: BLE001 - Intentional: rollback before re-raising
                    logger.error("Rollback failed: %s", rollback_error)

                ctx.state = TransactionState.FAILED
                self._stats.transactions_failed += 1

                # Check for deadlock and wrap in DeadlockError
                if self._is_deadlock_error(e):
                    self._stats.deadlocks_detected += 1
                    logger.warning("Deadlock detected in transaction %s", txn_id)
                    raise DeadlockError(str(e), retry_count=0) from e

                logger.warning("Transaction %s rolled back: %s", txn_id, e)
                raise

            finally:
                # Update stats
                duration_ms = (time.time() - start_time) * 1000
                self._stats.total_transaction_time_ms += duration_ms

                async with self._lock:
                    self._stats.active_transactions -= 1
                    self._active_contexts.pop(txn_id, None)

    @asynccontextmanager
    async def savepoint(
        self,
        conn: Any,
        name: str,
    ) -> AsyncIterator[None]:
        """
        Create a savepoint within an existing transaction.

        Savepoints allow partial rollback within a transaction.
        If code within the savepoint raises an exception, only
        changes since the savepoint are rolled back.

        Args:
            conn: Active database connection (from transaction context)
            name: Unique name for the savepoint

        Yields:
            None (savepoint is managed by context)

        Raises:
            SavepointError: If savepoint cannot be created/managed

        Example:
            async with manager.transaction() as conn:
                await conn.execute("INSERT INTO orders ...")

                async with manager.savepoint(conn, "inventory_update"):
                    await conn.execute("UPDATE inventory ...")
                    # If this fails, only inventory update is rolled back
        """
        # Validate savepoint name (alphanumeric + underscore only)
        if not name.replace("_", "").isalnum():
            raise SavepointError(f"Invalid savepoint name: {name}")

        self._stats.savepoints_created += 1

        try:
            await conn.execute(f"SAVEPOINT {name}")
            logger.debug("Savepoint '%s' created", name)
        except (OSError, ConnectionError, RuntimeError) as e:
            self._stats.savepoints_created -= 1  # Undo count
            raise SavepointError(f"Failed to create savepoint '{name}': {e}")

        try:
            yield
            # Release savepoint on success
            await conn.execute(f"RELEASE SAVEPOINT {name}")
            self._stats.savepoints_released += 1
            logger.debug("Savepoint '%s' released", name)

        except BaseException:
            # Rollback to savepoint on error
            try:
                await conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
                self._stats.savepoints_rolled_back += 1
                logger.debug("Rolled back to savepoint '%s'", name)
            except (ConnectionError, OSError, RuntimeError) as rollback_error:
                logger.error("Failed to rollback savepoint '%s': %s", name, rollback_error)
            raise

    async def begin(self, conn: Any, isolation: TransactionIsolation | None = None) -> None:
        """
        Manually begin a transaction on a connection.

        For cases where automatic context management isn't suitable.
        You must manually call commit() or rollback().

        Args:
            conn: Database connection
            isolation: Transaction isolation level
        """
        isolation = isolation or self._config.isolation
        await conn.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation.value}")
        await conn.execute("BEGIN")
        self._stats.transactions_started += 1
        self._stats.active_transactions += 1

    async def commit(self, conn: Any) -> None:
        """
        Manually commit a transaction.

        Args:
            conn: Database connection with active transaction
        """
        await conn.execute("COMMIT")
        self._stats.transactions_committed += 1
        self._stats.active_transactions -= 1

    async def rollback(self, conn: Any) -> None:
        """
        Manually rollback a transaction.

        Args:
            conn: Database connection with active transaction
        """
        await conn.execute("ROLLBACK")
        self._stats.transactions_rolled_back += 1
        self._stats.active_transactions -= 1

    def get_stats(self) -> TransactionStats:
        """Get transaction statistics."""
        return self._stats

    def get_stats_dict(self) -> dict[str, Any]:
        """Get transaction statistics as dictionary."""
        return self._stats.to_dict()

    def reset_stats(self) -> None:
        """Reset transaction statistics."""
        self._stats = TransactionStats()

    @property
    def active_transaction_count(self) -> int:
        """Get count of currently active transactions."""
        return self._stats.active_transactions

    @property
    def config(self) -> TransactionConfig:
        """Get transaction configuration."""
        return self._config


class NestedTransactionManager(TransactionManager):
    """
    Transaction manager with automatic nested transaction support.

    When a transaction is started while another is active on the same
    connection, automatically uses savepoints for nesting.
    """

    def __init__(
        self,
        pool: Any,
        config: TransactionConfig | None = None,
    ):
        super().__init__(pool, config)
        self._connection_depth: dict[int, int] = {}

    @asynccontextmanager
    async def transaction(
        self,
        isolation: TransactionIsolation | None = None,
        timeout: float | None = None,
        readonly: bool = False,
    ) -> AsyncIterator[Any]:
        """
        Execute operations within a transaction, with automatic nesting.

        If called while a transaction is already active, uses a savepoint
        instead of starting a new transaction.
        """
        isolation = isolation or self._config.isolation
        timeout = timeout if timeout is not None else self._config.timeout_seconds

        # Acquire connection
        async with self._pool.acquire(readonly=readonly) as conn:
            actual_conn = getattr(conn, "connection", conn)
            conn_id = id(actual_conn)

            # Check if we're already in a transaction
            current_depth = self._connection_depth.get(conn_id, 0)

            if current_depth > 0 and self._config.savepoint_on_nested:
                # Use savepoint for nested transaction
                savepoint_name = f"nested_{conn_id}_{current_depth}"
                self._connection_depth[conn_id] = current_depth + 1

                try:
                    async with self.savepoint(actual_conn, savepoint_name):
                        yield actual_conn
                finally:
                    self._connection_depth[conn_id] = current_depth
            else:
                # Start new transaction
                self._connection_depth[conn_id] = 1
                try:
                    async with super().transaction(
                        isolation=isolation,
                        timeout=timeout,
                        readonly=readonly,
                    ) as nested_conn:
                        yield nested_conn
                finally:
                    self._connection_depth[conn_id] = 0


# Factory function for easy instantiation
def create_transaction_manager(
    pool: Any,
    isolation: TransactionIsolation = TransactionIsolation.READ_COMMITTED,
    timeout_seconds: float = 30.0,
    deadlock_retries: int = 3,
    nested_support: bool = False,
) -> TransactionManager:
    """
    Create a transaction manager with common configuration.

    Args:
        pool: Database connection pool
        isolation: Default transaction isolation level
        timeout_seconds: Default transaction timeout
        deadlock_retries: Number of deadlock retry attempts
        nested_support: Use NestedTransactionManager for automatic nesting

    Returns:
        Configured TransactionManager instance
    """
    config = TransactionConfig(
        isolation=isolation,
        timeout_seconds=timeout_seconds,
        deadlock_retries=deadlock_retries,
    )

    if nested_support:
        return NestedTransactionManager(pool, config)
    return TransactionManager(pool, config)


__all__ = [
    "TransactionManager",
    "NestedTransactionManager",
    "TransactionConfig",
    "TransactionStats",
    "TransactionContext",
    "TransactionState",
    "TransactionIsolation",
    "TransactionError",
    "TransactionStateError",
    "SavepointError",
    "DeadlockError",
    "create_transaction_manager",
]
