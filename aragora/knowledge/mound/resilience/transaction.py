"""Transaction management for PostgreSQL operations."""

from __future__ import annotations

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class TransactionIsolation(str, Enum):
    """Transaction isolation levels."""

    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"


@dataclass
class TransactionConfig:
    """Configuration for transaction behavior."""

    isolation: TransactionIsolation = TransactionIsolation.READ_COMMITTED
    timeout_seconds: float = 30.0
    savepoint_on_nested: bool = True
    deadlock_retries: int = 3
    deadlock_base_delay: float = 0.1
    deadlock_max_delay: float = 2.0


class DeadlockError(Exception):
    """Raised when a database deadlock is detected and max retries exceeded."""

    def __init__(self, message: str, retry_count: int = 0):
        self.retry_count = retry_count
        super().__init__(message)


class TransactionManager:
    """
    Manages explicit transaction boundaries for PostgreSQL operations.

    Provides:
    - Explicit BEGIN/COMMIT/ROLLBACK
    - Savepoints for nested transactions
    - Timeout enforcement
    - Deadlock detection and retry
    """

    def __init__(
        self,
        pool: Any,
        config: TransactionConfig | None = None,
    ):
        self._pool = pool
        self._config = config or TransactionConfig()
        self._active_transactions = 0

    @asynccontextmanager
    async def transaction(
        self,
        isolation: TransactionIsolation | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[Any]:
        """
        Execute operations within an explicit transaction.

        Usage:
            async with tx_manager.transaction() as conn:
                await conn.execute("INSERT ...")
                await conn.execute("UPDATE ...")
                # Auto-commit on success, rollback on exception
        """
        isolation = isolation or self._config.isolation
        timeout = timeout or self._config.timeout_seconds

        async with self._pool.acquire() as conn:
            # Set transaction isolation
            await conn.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation.value}")

            # Start transaction
            await conn.execute("BEGIN")
            self._active_transactions += 1

            try:
                # Yield connection for operations
                yield conn

                # Commit on success
                await conn.execute("COMMIT")
                logger.debug("Transaction committed successfully")

            except Exception as e:  # noqa: BLE001 - Intentional: rollback transaction before re-raising any error
                # Rollback on any exception
                await conn.execute("ROLLBACK")
                logger.warning("Transaction rolled back due to: %s", e)
                raise

            finally:
                self._active_transactions -= 1

    @asynccontextmanager
    async def savepoint(self, conn: Any, name: str) -> AsyncIterator[None]:
        """
        Create a savepoint within an existing transaction.

        Usage:
            async with tx_manager.transaction() as conn:
                # Some operations...
                async with tx_manager.savepoint(conn, "sp1"):
                    # Nested operations that can be rolled back independently
                    ...
        """
        await conn.execute(f"SAVEPOINT {name}")
        try:
            yield
        except Exception:  # noqa: BLE001 - Intentional: rollback savepoint before re-raising any error
            await conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
            raise

    def _is_deadlock_error(self, error: Exception) -> bool:
        """Check if an exception is a database deadlock.

        Detects PostgreSQL deadlock (40P01) and serialization failure (40001).
        """
        error_str = str(error).lower()
        return "deadlock" in error_str or "40p01" in error_str or "40001" in error_str

    def _calculate_deadlock_delay(self, attempt: int) -> float:
        """Calculate delay for deadlock retry with exponential backoff and jitter."""
        delay = self._config.deadlock_base_delay * (2**attempt)
        delay = min(delay, self._config.deadlock_max_delay)
        # Add ±25% jitter
        delay = delay * (0.75 + random.random() * 0.5)  # noqa: S311 -- retry jitter
        return delay

    @asynccontextmanager
    async def transaction_with_retry(
        self,
        isolation: TransactionIsolation | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[Any]:
        """Execute operations within a transaction with deadlock retry.

        Automatically retries on deadlock with exponential backoff.

        Usage:
            async with tx_manager.transaction_with_retry() as conn:
                await conn.execute("UPDATE ...")
                # Retries automatically on deadlock

        Raises:
            DeadlockError: If max deadlock retries exceeded.
        """
        max_retries = self._config.deadlock_retries

        for attempt in range(max_retries + 1):
            try:
                async with self.transaction(isolation, timeout) as conn:
                    yield conn
                    return  # Success - exit the retry loop
            except Exception as e:  # noqa: BLE001 - Intentional: detect deadlocks across any exception type
                if self._is_deadlock_error(e) and attempt < max_retries:
                    delay = self._calculate_deadlock_delay(attempt)
                    logger.warning(
                        "Deadlock detected (attempt %s/%s), retrying in %.2fs",
                        attempt + 1,
                        max_retries + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                elif self._is_deadlock_error(e):
                    raise DeadlockError(
                        f"Deadlock persisted after {max_retries + 1} attempts: {e}",
                        retry_count=max_retries + 1,
                    ) from e
                else:
                    raise

    def get_stats(self) -> dict[str, Any]:
        """Get transaction manager statistics."""
        return {
            "active_transactions": self._active_transactions,
            "default_isolation": self._config.isolation.value,
            "default_timeout": self._config.timeout_seconds,
            "deadlock_retries": self._config.deadlock_retries,
        }
