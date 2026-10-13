"""
Startup Transaction for server initialization with rollback support.

Provides transaction-like behavior for server startup:
- Tracks initialized components for cleanup on failure
- Measures startup time against SLO
- Enables rollback of partial initialization

Usage:
    async with StartupTransaction() as txn:
        txn.register_cleanup("redis", cleanup_redis)
        await init_redis()

        txn.register_cleanup("scheduler", stop_scheduler)
        await init_scheduler()

        txn.checkpoint("core_services")  # Mark partial success

    # If exception raised, all registered cleanups are called in reverse order
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)

# Default startup SLO: 30 seconds
DEFAULT_STARTUP_SLO_SECONDS = 30.0

# Prometheus metrics (lazy initialized)
_STARTUP_DURATION: Any = None
_STARTUP_COMPONENTS: Any = None


def _init_startup_metrics() -> bool:
    """Initialize Prometheus metrics for startup tracking."""
    global _STARTUP_DURATION, _STARTUP_COMPONENTS

    if _STARTUP_DURATION is not None:
        return True

    try:
        from prometheus_client import REGISTRY, Gauge, Histogram

        try:
            _STARTUP_DURATION = Histogram(
                "aragora_server_startup_duration_seconds",
                "Server startup duration in seconds",
                buckets=[1.0, 2.5, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0],
            )
        except ValueError:
            _STARTUP_DURATION = REGISTRY._names_to_collectors.get(
                "aragora_server_startup_duration_seconds"
            )

        try:
            _STARTUP_COMPONENTS = Gauge(
                "aragora_server_startup_components_initialized",
                "Number of components initialized during startup",
            )
        except ValueError:
            _STARTUP_COMPONENTS = REGISTRY._names_to_collectors.get(
                "aragora_server_startup_components_initialized"
            )

        return True
    except ImportError:
        return False


@dataclass
class StartupCheckpoint:
    """A checkpoint in the startup sequence."""

    name: str
    timestamp: datetime = field(default_factory=datetime.now)
    elapsed_seconds: float = 0.0
    components: list[str] = field(default_factory=list)


@dataclass
class StartupReport:
    """Report of a startup sequence."""

    success: bool
    total_duration_seconds: float
    slo_seconds: float
    slo_met: bool
    components_initialized: int
    components_failed: list[str]
    checkpoints: list[StartupCheckpoint]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "total_duration_seconds": round(self.total_duration_seconds, 3),
            "slo_seconds": self.slo_seconds,
            "slo_met": self.slo_met,
            "components_initialized": self.components_initialized,
            "components_failed": self.components_failed,
            "checkpoints": [
                {
                    "name": cp.name,
                    "timestamp": cp.timestamp.isoformat(),
                    "elapsed_seconds": round(cp.elapsed_seconds, 3),
                    "components": cp.components,
                }
                for cp in self.checkpoints
            ],
            "error": self.error,
        }


CleanupFunc = Callable[[], None] | Callable[[], Coroutine[Any, Any, None]]


class StartupTransaction:
    """
    Transaction-like wrapper for server startup sequence.

    Provides:
    - Cleanup registration for rollback on failure
    - Startup time tracking against SLO
    - Checkpointing for progress tracking
    - Prometheus metrics integration

    Usage:
        async with StartupTransaction(slo_seconds=30) as txn:
            await txn.run_step("redis", init_redis, cleanup_redis)
            await txn.run_step("scheduler", init_scheduler, stop_scheduler)
            txn.checkpoint("core")

    On success, cleanup functions are discarded.
    On failure, cleanup functions are called in reverse order.
    """

    def __init__(
        self,
        slo_seconds: float = DEFAULT_STARTUP_SLO_SECONDS,
        name: str = "server_startup",
    ):
        self.slo_seconds = slo_seconds
        self.name = name
        self._start_time: float | None = None
        self._cleanups: list[tuple[str, CleanupFunc]] = []
        self._checkpoints: list[StartupCheckpoint] = []
        self._components_initialized: list[str] = []
        self._components_failed: list[str] = []
        self._completed = False

    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed time since startup began."""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    def register_cleanup(self, component: str, cleanup: CleanupFunc) -> None:
        """Register a cleanup function for a component.

        Cleanup functions are called in reverse order on failure.

        Args:
            component: Name of the component (for logging)
            cleanup: Function to call for cleanup (sync or async)
        """
        self._cleanups.append((component, cleanup))
        logger.debug("Registered cleanup for: %s", component)

    def mark_initialized(self, component: str) -> None:
        """Mark a component as successfully initialized."""
        self._components_initialized.append(component)
        logger.debug("Initialized: %s (%.2fs)", component, self.elapsed_seconds)

    def mark_failed(self, component: str) -> None:
        """Mark a component as failed."""
        self._components_failed.append(component)
        logger.warning("Failed to initialize: %s", component)

    async def run_step(
        self,
        component: str,
        init_func: Callable[[], Coroutine[Any, Any, Any]],
        cleanup_func: CleanupFunc | None = None,
    ) -> Any:
        """Run an initialization step with automatic cleanup registration.

        Args:
            component: Name of the component
            init_func: Async function to initialize the component
            cleanup_func: Optional cleanup function to call on failure

        Returns:
            Result of init_func

        Raises:
            Exception: Re-raises any exception from init_func
        """
        if cleanup_func:
            self.register_cleanup(component, cleanup_func)

        try:
            result = await init_func()
            self.mark_initialized(component)
            return result
        except (
            Exception  # noqa: BLE001 - startup transaction records all failures before re-raising
        ):
            self.mark_failed(component)
            raise

    def checkpoint(self, name: str) -> StartupCheckpoint:
        """Create a checkpoint marking progress.

        Args:
            name: Name of the checkpoint

        Returns:
            StartupCheckpoint with timing information
        """
        cp = StartupCheckpoint(
            name=name,
            elapsed_seconds=self.elapsed_seconds,
            components=list(self._components_initialized),
        )
        self._checkpoints.append(cp)
        logger.info("Startup checkpoint: %s (%.2fs)", name, cp.elapsed_seconds)
        return cp

    async def _run_cleanups(self) -> None:
        """Run all registered cleanups in reverse order."""
        logger.warning("Running startup rollback cleanups...")

        for component, cleanup in reversed(self._cleanups):
            try:
                logger.info("Cleaning up: %s", component)
                if asyncio.iscoroutinefunction(cleanup):
                    await cleanup()
                else:
                    result = cleanup()
                    # Handle case where sync callable returns a coroutine
                    if asyncio.iscoroutine(result):
                        await result
            except (
                Exception  # noqa: BLE001 - cleanup must continue even if one cleanup fails
            ) as e:
                logger.exception("Cleanup failed for %s: %s", component, e)

        logger.info("Startup rollback complete")

    def get_report(self, error: str | None = None) -> StartupReport:
        """Generate a startup report.

        Args:
            error: Optional error message if startup failed

        Returns:
            StartupReport with timing and component information
        """
        duration = self.elapsed_seconds
        return StartupReport(
            success=self._completed and not self._components_failed,
            total_duration_seconds=duration,
            slo_seconds=self.slo_seconds,
            slo_met=duration <= self.slo_seconds,
            components_initialized=len(self._components_initialized),
            components_failed=self._components_failed,
            checkpoints=self._checkpoints,
            error=error,
        )

    async def __aenter__(self) -> StartupTransaction:
        """Start the transaction."""
        self._start_time = time.time()
        logger.info("Starting %s (SLO: %ss)", self.name, self.slo_seconds)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """End the transaction, running cleanups if needed."""
        duration = self.elapsed_seconds

        if exc_type is not None:
            # Failure - run cleanups
            error_msg = str(exc_val) if exc_val else "Unknown error"
            logger.error("Startup failed after %.2fs: %s", duration, error_msg)
            await self._run_cleanups()

            # Record metrics
            _init_startup_metrics()
            if _STARTUP_DURATION:
                _STARTUP_DURATION.observe(duration)

            return False  # Re-raise exception

        # Success
        self._completed = True
        self._cleanups.clear()  # Discard cleanups on success

        # Log SLO status
        if duration > self.slo_seconds:
            logger.warning(
                "Startup completed in %.2fs (exceeded SLO of %ss)", duration, self.slo_seconds
            )
        else:
            logger.info(
                "Startup completed in %.2fs (within SLO of %ss)", duration, self.slo_seconds
            )

        # Record metrics
        _init_startup_metrics()
        if _STARTUP_DURATION:
            _STARTUP_DURATION.observe(duration)
        if _STARTUP_COMPONENTS:
            _STARTUP_COMPONENTS.set(len(self._components_initialized))

        return False


# Global startup report for introspection
_last_startup_report: StartupReport | None = None


def get_last_startup_report() -> StartupReport | None:
    """Get the last startup report."""
    return _last_startup_report


def set_last_startup_report(report: StartupReport) -> None:
    """Set the last startup report."""
    global _last_startup_report
    _last_startup_report = report
