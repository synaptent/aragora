"""
Receipt Retention Scheduler.

Automatically cleans up expired decision receipts according to retention policy.
Runs as a background task that periodically checks for and removes receipts
older than the configured retention period (default: 7 years).

Features:
- Background async task at configurable intervals
- Audit logging of all deletions for compliance
- Prometheus metrics for monitoring
- Graceful shutdown support

Usage:
    from aragora.scheduler.receipt_retention import ReceiptRetentionScheduler
    from aragora.storage.receipt_store import get_receipt_store

    scheduler = ReceiptRetentionScheduler(get_receipt_store())
    await scheduler.start()
    # ... later ...
    await scheduler.stop()
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.storage.receipt_store import ReceiptStore

logger = logging.getLogger(__name__)

# Configuration from environment
DEFAULT_CLEANUP_INTERVAL_HOURS = int(os.environ.get("ARAGORA_RECEIPT_CLEANUP_INTERVAL_HOURS", "24"))
DEFAULT_RETENTION_DAYS = int(
    os.environ.get("ARAGORA_RECEIPT_RETENTION_DAYS", "2555")  # ~7 years
)


@dataclass
class CleanupResult:
    """Result of a retention cleanup operation."""

    receipts_deleted: int
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    retention_days: int
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API/logging."""
        return {
            "receipts_deleted": self.receipts_deleted,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "retention_days": self.retention_days,
            "success": self.error is None,
            "error": self.error,
        }


@dataclass
class CleanupStats:
    """Cumulative statistics for cleanup operations."""

    total_runs: int = 0
    total_receipts_deleted: int = 0
    last_run: datetime | None = None
    last_result: CleanupResult | None = None
    failures: int = 0
    results: list[CleanupResult] = field(default_factory=list)

    def add_result(self, result: CleanupResult) -> None:
        """Add a cleanup result to statistics."""
        self.total_runs += 1
        if result.error:
            self.failures += 1
        else:
            self.total_receipts_deleted += result.receipts_deleted
        self.last_run = result.completed_at
        self.last_result = result
        # Keep last 100 results
        self.results.append(result)
        if len(self.results) > 100:
            self.results = self.results[-100:]

    def to_dict(self) -> dict:
        """Convert to dictionary for monitoring."""
        return {
            "total_runs": self.total_runs,
            "total_receipts_deleted": self.total_receipts_deleted,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "failures": self.failures,
            "success_rate": (
                ((self.total_runs - self.failures) / self.total_runs)
                if self.total_runs > 0
                else 1.0
            ),
            "last_result": self.last_result.to_dict() if self.last_result else None,
        }


class ReceiptRetentionScheduler:
    """
    Automatically clean up expired decision receipts.

    Runs as a background async task that:
    1. Periodically checks for expired receipts
    2. Logs deletions to audit trail for compliance
    3. Reports metrics for monitoring

    Usage:
        scheduler = ReceiptRetentionScheduler(receipt_store)
        await scheduler.start()
        # ... later ...
        await scheduler.stop()
    """

    def __init__(
        self,
        store: ReceiptStore,  # noqa: F821 - forward reference
        interval_hours: int = DEFAULT_CLEANUP_INTERVAL_HOURS,
        retention_days: int | None = None,
        on_cleanup_complete: Callable[[CleanupResult], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ):
        """
        Initialize the receipt retention scheduler.

        Args:
            store: Receipt store to clean up
            interval_hours: How often to run cleanup (default: 24 hours)
            retention_days: Override store's retention days (default: use store's setting)
            on_cleanup_complete: Callback after each cleanup
            on_error: Callback on errors
        """
        self.store = store
        self.interval_hours = interval_hours
        self.retention_days = retention_days
        self.on_cleanup_complete = on_cleanup_complete
        self.on_error = on_error

        self._task: asyncio.Task | None = None
        self._running = False
        self._stats = CleanupStats()

    @property
    def is_running(self) -> bool:
        """Check if the scheduler is currently running."""
        return self._running and self._task is not None and not self._task.done()

    @property
    def stats(self) -> CleanupStats:
        """Get cumulative cleanup statistics."""
        return self._stats

    async def start(self) -> None:
        """Start the background cleanup loop."""
        if self.is_running:
            logger.warning("Receipt retention scheduler is already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info(
            "Started receipt retention scheduler (interval=%sh, retention=%s days)",
            self.interval_hours,
            self.retention_days or "store default",
        )

    async def stop(self) -> None:
        """Stop the background cleanup loop gracefully."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Stopped receipt retention scheduler")

    async def _cleanup_loop(self) -> None:
        """Main cleanup loop that runs in the background."""
        # Small delay on startup to let system stabilize
        await asyncio.sleep(60)

        while self._running:
            try:
                result = await self.cleanup_now()
                self._stats.add_result(result)

                if result.error:
                    logger.warning("Receipt cleanup completed with error: %s", result.error)
                elif result.receipts_deleted > 0:
                    logger.info(
                        "Receipt cleanup completed: %s receipts deleted", result.receipts_deleted
                    )
                else:
                    logger.debug("Receipt cleanup completed: no expired receipts")

                if self.on_cleanup_complete:
                    try:
                        self.on_cleanup_complete(result)
                    except (TypeError, ValueError, RuntimeError) as e:
                        logger.error("Error in cleanup complete callback: %s", e)

            except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
                logger.error("Error in receipt cleanup cycle: %s", e, exc_info=True)
                error_result = CleanupResult(
                    receipts_deleted=0,
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    duration_seconds=0.0,
                    retention_days=self.retention_days or DEFAULT_RETENTION_DAYS,
                    error="Receipt cleanup cycle failed",
                )
                self._stats.add_result(error_result)

                if self.on_error:
                    try:
                        self.on_error(e)
                    except (TypeError, ValueError, RuntimeError) as callback_error:
                        logger.error("Error in error callback: %s", callback_error)

            # Wait for next cycle
            await asyncio.sleep(self.interval_hours * 3600)

    async def cleanup_now(self) -> CleanupResult:
        """
        Trigger an immediate cleanup (for testing or manual intervention).

        Returns:
            CleanupResult with operation details
        """
        started_at = datetime.now(timezone.utc)
        error: str | None = None
        receipts_deleted = 0

        try:
            # Run the synchronous cleanup in a thread pool
            loop = asyncio.get_running_loop()
            receipts_deleted = await loop.run_in_executor(
                None,
                lambda: self.store.cleanup_expired(
                    retention_days=self.retention_days,
                    operator="system:receipt_retention_scheduler",
                    log_deletions=True,
                ),
            )
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            logger.error("Exception during receipt cleanup: %s", e)
            error = "Receipt cleanup failed"

        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()

        return CleanupResult(
            receipts_deleted=receipts_deleted,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            retention_days=self.retention_days
            or cast(int, getattr(self.store, "retention_days", DEFAULT_RETENTION_DAYS)),
            error=error,
        )

    def get_status(self) -> dict:
        """Get current scheduler status for monitoring."""
        return {
            "running": self.is_running,
            "interval_hours": self.interval_hours,
            "retention_days": self.retention_days or "store default",
            "stats": self._stats.to_dict(),
        }


# Global instance management
_scheduler: ReceiptRetentionScheduler | None = None


def get_receipt_retention_scheduler(
    store: ReceiptStore | None = None,  # noqa: F821
) -> ReceiptRetentionScheduler | None:
    """
    Get or create the global receipt retention scheduler.

    Args:
        store: Receipt store to use (required on first call)

    Returns:
        ReceiptRetentionScheduler instance or None if store not provided
    """
    global _scheduler

    if _scheduler is not None:
        return _scheduler

    if store is None:
        return None

    _scheduler = ReceiptRetentionScheduler(store)
    return _scheduler


def set_receipt_retention_scheduler(scheduler: ReceiptRetentionScheduler | None) -> None:
    """Set the global scheduler (for testing)."""
    global _scheduler
    _scheduler = scheduler


__all__ = [
    "ReceiptRetentionScheduler",
    "CleanupResult",
    "CleanupStats",
    "get_receipt_retention_scheduler",
    "set_receipt_retention_scheduler",
]
