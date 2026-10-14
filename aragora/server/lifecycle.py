"""
Server lifecycle management - startup/shutdown coordination.

This module handles:
- Graceful shutdown with resource cleanup
- Signal handler setup
- Component shutdown sequencing
- Thread lifecycle management via ThreadRegistry
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.server.stream.server import GauntletStreamServer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics (lazy; None when prometheus_client not installed)
# ---------------------------------------------------------------------------
try:
    from prometheus_client import REGISTRY, Gauge, Histogram

    try:
        REGISTERED_THREADS_GAUGE: Gauge | None = Gauge(
            "aragora_registered_threads",
            "Number of threads registered with the lifecycle manager",
        )
    except ValueError:
        existing_threads_gauge = REGISTRY._names_to_collectors.get("aragora_registered_threads")
        REGISTERED_THREADS_GAUGE = (  # type: ignore[assignment]
            existing_threads_gauge if isinstance(existing_threads_gauge, Gauge) else None
        )

    try:
        SHUTDOWN_DURATION_HISTOGRAM: Histogram | None = Histogram(
            "aragora_shutdown_duration_seconds",
            "Time taken to shut down all registered threads",
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
        )
    except ValueError:
        existing_shutdown_histogram = REGISTRY._names_to_collectors.get(
            "aragora_shutdown_duration_seconds"
        )
        SHUTDOWN_DURATION_HISTOGRAM = (  # type: ignore[assignment]
            existing_shutdown_histogram
            if isinstance(existing_shutdown_histogram, Histogram)
            else None
        )
except ImportError:
    REGISTERED_THREADS_GAUGE = None
    SHUTDOWN_DURATION_HISTOGRAM = None


# ============================================================================
# ThreadRegistry -- central daemon thread tracking
# ============================================================================


@dataclass
class _ThreadEntry:
    """Internal bookkeeping for a registered thread."""

    thread: threading.Thread
    shutdown_fn: Callable[[], None]
    registered_at: float = field(default_factory=time.time)


class ThreadRegistry:
    """Central registry for daemon threads with coordinated shutdown.

    Keeps a {name: (thread, shutdown_fn)} mapping and exposes
    shutdown_all() to stop every thread within a timeout budget.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _ThreadEntry] = {}
        self._lock = threading.Lock()
        self._shutdown_called = False

    def register(
        self,
        name: str,
        thread: threading.Thread,
        shutdown_fn: Callable[[], None],
    ) -> None:
        """Register a thread for lifecycle management."""
        with self._lock:
            self._entries[name] = _ThreadEntry(
                thread=thread,
                shutdown_fn=shutdown_fn,
            )
            logger.debug("Thread registered: %s (alive=%s)", name, thread.is_alive())
            if REGISTERED_THREADS_GAUGE is not None:
                REGISTERED_THREADS_GAUGE.set(len(self._entries))

    def unregister(self, name: str) -> bool:
        """Remove a thread from the registry."""
        with self._lock:
            removed = self._entries.pop(name, None) is not None
            if removed:
                logger.debug("Thread unregistered: %s", name)
                if REGISTERED_THREADS_GAUGE is not None:
                    REGISTERED_THREADS_GAUGE.set(len(self._entries))
            return removed

    def shutdown_all(self, timeout: float = 10.0) -> dict[str, bool]:
        """Gracefully shut down every registered thread."""
        start = time.monotonic()
        self._shutdown_called = True

        with self._lock:
            snapshot = dict(self._entries)

        if not snapshot:
            logger.debug("ThreadRegistry.shutdown_all: no threads registered")
            return {}

        count = len(snapshot)
        logger.info("Shutting down %d registered thread(s) (timeout=%.1fs)", count, timeout)

        # Phase 1: signal all threads to stop
        for name, entry in snapshot.items():
            try:
                entry.shutdown_fn()
                logger.debug("Shutdown signal sent: %s", name)
            except (RuntimeError, OSError, ValueError) as exc:
                logger.warning("Error signalling thread %s: %s", name, exc)

        # Phase 2: join threads with fair timeout sharing
        results: dict[str, bool] = {}
        remaining_threads = [
            (name, entry) for name, entry in snapshot.items() if entry.thread.is_alive()
        ]

        for idx, (name, entry) in enumerate(remaining_threads):
            elapsed = time.monotonic() - start
            remaining_time = max(0.0, timeout - elapsed)
            if remaining_time <= 0:
                logger.warning("Timeout budget exhausted; skipping join for %s", name)
                results[name] = not entry.thread.is_alive()
                continue

            threads_left = len(remaining_threads) - idx
            share = remaining_time / max(1, threads_left)
            entry.thread.join(timeout=share)
            stopped = not entry.thread.is_alive()
            results[name] = stopped
            if not stopped:
                logger.warning("Thread %s did not stop within %.1fs", name, share)

        # Threads that were already dead before join phase
        for name in snapshot:
            if name not in results:
                results[name] = True

        elapsed_total = time.monotonic() - start
        succeeded = sum(1 for v in results.values() if v)
        logger.info(
            "Thread shutdown complete: %d/%d stopped in %.2fs",
            succeeded,
            count,
            elapsed_total,
        )

        if SHUTDOWN_DURATION_HISTOGRAM is not None:
            SHUTDOWN_DURATION_HISTOGRAM.observe(elapsed_total)

        return results

    def health(self) -> dict[str, Any]:
        """Return health status for all registered threads."""
        with self._lock:
            snapshot = dict(self._entries)

        threads: list[dict[str, Any]] = []
        alive_count = 0
        for name, entry in snapshot.items():
            alive = entry.thread.is_alive()
            if alive:
                alive_count += 1
            threads.append(
                {
                    "name": name,
                    "alive": alive,
                    "daemon": entry.thread.daemon,
                    "registered_at": entry.registered_at,
                }
            )

        return {
            "total": len(threads),
            "alive": alive_count,
            "shutdown_called": self._shutdown_called,
            "threads": threads,
        }

    @property
    def names(self) -> list[str]:
        """List of registered thread names."""
        with self._lock:
            return list(self._entries.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# ---------------------------------------------------------------------------
# Singleton access
# ---------------------------------------------------------------------------

_registry: ThreadRegistry | None = None
_registry_lock = threading.Lock()


def get_thread_registry() -> ThreadRegistry:
    """Get the global ThreadRegistry singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ThreadRegistry()
    return _registry


def reset_thread_registry() -> None:
    """Reset the singleton (for testing)."""
    global _registry
    with _registry_lock:
        _registry = None


# ---------------------------------------------------------------------------
# Signal handler integration
# ---------------------------------------------------------------------------


def register_lifecycle_signal_handlers() -> None:
    """Install SIGTERM/SIGINT handlers that trigger shutdown_all().

    Must be called from the main thread.
    """

    def _handle_signal(signum: int, _frame: Any) -> None:
        signame = signal.Signals(signum).name
        logger.info("Received %s -- shutting down registered threads", signame)
        registry = get_thread_registry()
        registry.shutdown_all(timeout=10.0)

    try:
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)
        logger.debug("Thread lifecycle signal handlers registered (SIGTERM, SIGINT)")
    except (ValueError, OSError) as exc:
        logger.warning("Could not register lifecycle signal handlers: %s", exc)


# ============================================================================
# ServerLifecycleManager -- existing server lifecycle coordination
# ============================================================================


class ServerLifecycleManager:
    """Manages server startup and shutdown lifecycle.

    Coordinates graceful shutdown of all server components in the correct
    order to prevent data loss and connection leaks.

    Usage:
        lifecycle = ServerLifecycleManager(stream_server=ws_server)
        lifecycle.setup_signal_handlers()

        # During shutdown:
        await lifecycle.graceful_shutdown()
    """

    def __init__(
        self,
        stream_server: GauntletStreamServer | None = None,
        get_active_debates: Callable | None = None,
    ):
        """Initialize lifecycle manager."""
        self.stream_server = stream_server
        self._get_active_debates = get_active_debates
        self._shutting_down = False
        self._shutdown_callbacks: list[Callable] = []

    @property
    def is_shutting_down(self) -> bool:
        """Check if server is in shutdown mode."""
        return self._shutting_down

    def register_shutdown_callback(self, callback: Callable) -> None:
        """Register a callback to run during shutdown."""
        self._shutdown_callbacks.append(callback)

    def setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""

        def signal_handler(signum, frame):
            signame = signal.Signals(signum).name
            logger.info("Received %s, initiating graceful shutdown...", signame)
            asyncio.create_task(self.graceful_shutdown())

        try:
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
            logger.debug("Signal handlers registered for graceful shutdown")
        except (ValueError, OSError) as e:
            logger.debug("Could not register signal handlers: %s", e)

    async def graceful_shutdown(self, timeout: float = 30.0) -> None:
        """Gracefully shut down the server."""
        logger.info("Starting graceful shutdown...")
        shutdown_start = time.time()

        self._shutting_down = True
        await self._wait_for_debates(timeout)
        self._persist_circuit_breakers()
        await self._stop_background_tasks()
        await self._close_websockets()
        await self._close_http_connector()
        self._close_database_connections()
        await self._run_shutdown_callbacks()

        elapsed = time.time() - shutdown_start
        logger.info("Graceful shutdown completed in %.1fs", elapsed)

    async def _wait_for_debates(self, timeout: float) -> None:
        """Wait for in-flight debates to complete."""
        if not self._get_active_debates:
            return

        logger.info("Waiting for in-flight debates to complete...")
        active_debates = self._get_active_debates()
        if not active_debates:
            return

        in_progress = [
            d_id for d_id, d in active_debates.items() if d.get("status") == "in_progress"
        ]
        if not in_progress:
            return

        logger.info("Waiting for %s in-flight debate(s)", len(in_progress))
        wait_start = time.time()

        sleep_interval = 0.2
        while time.time() - wait_start < timeout:
            active_debates = self._get_active_debates()
            still_running = sum(
                1
                for d_id in in_progress
                if d_id in active_debates
                and active_debates.get(d_id, {}).get("status") == "in_progress"
            )
            if still_running == 0:
                logger.info("All in-flight debates completed")
                return
            await asyncio.sleep(sleep_interval)

        logger.warning("Shutdown timeout reached with debates still running")

    def _persist_circuit_breakers(self) -> None:
        """Persist circuit breaker states."""
        try:
            from aragora.resilience import persist_all_circuit_breakers

            count = persist_all_circuit_breakers()
            if count > 0:
                logger.info("Persisted %s circuit breaker state(s)", count)
        except (ImportError, OSError, RuntimeError) as e:
            logger.warning("Failed to persist circuit breaker states: %s", e)

    async def _stop_background_tasks(self) -> None:
        """Stop background task manager."""
        try:
            from aragora.server.background import get_background_manager

            background_mgr = get_background_manager()
            background_mgr.stop()
            logger.info("Background tasks stopped")
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.debug("Background task shutdown: %s", e)

        try:
            from aragora.server.handlers.pulse import get_pulse_scheduler

            scheduler = get_pulse_scheduler()
            if scheduler and scheduler.state.value != "stopped":
                await scheduler.stop(graceful=True)
                logger.info("Pulse scheduler stopped")
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.debug("Pulse scheduler shutdown: %s", e)

        try:
            from aragora.scheduler.settlement_review import get_settlement_review_scheduler

            settlement_scheduler = get_settlement_review_scheduler()
            if settlement_scheduler is not None and settlement_scheduler.is_running:
                await settlement_scheduler.stop()
                logger.info("Settlement review scheduler stopped")
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.debug("Settlement review scheduler shutdown: %s", e)

        try:
            from aragora.debate.settlement_scheduler import (
                get_scheduler as _get_debate_sched,
            )

            _debate_sched = _get_debate_sched()
            if _debate_sched is not None and _debate_sched.is_running:
                await _debate_sched.stop()
                logger.info("Debate settlement scheduler stopped")
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.debug("Debate settlement scheduler shutdown: %s", e)

        # Stop API key proxy (frequency-hopping rotation)
        try:
            from aragora.security.api_key_proxy import get_api_key_proxy, reset_api_key_proxy

            proxy = get_api_key_proxy()
            await proxy.stop()
            reset_api_key_proxy()
            logger.info("API key proxy stopped")
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.debug("API key proxy shutdown: %s", e)

        # Stop key rotation schedulers (security + ops modules)
        try:
            from aragora.security.key_rotation import (
                get_key_rotation_scheduler as _get_sec_scheduler,
                stop_key_rotation_scheduler,
            )

            sec_scheduler = _get_sec_scheduler()
            if sec_scheduler is not None and sec_scheduler.status.value != "stopped":
                await stop_key_rotation_scheduler()
                logger.info("Security key rotation scheduler stopped")
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.debug("Security key rotation scheduler shutdown: %s", e)

        try:
            from aragora.ops.key_rotation import (
                get_key_rotation_scheduler as _get_ops_scheduler,
            )

            ops_scheduler = _get_ops_scheduler()
            if ops_scheduler is not None:
                await ops_scheduler.stop()
                logger.info("Ops key rotation scheduler stopped")
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.debug("Ops key rotation scheduler shutdown: %s", e)

    async def _close_websockets(self) -> None:
        """Close WebSocket connections."""
        if not self.stream_server:
            return

        try:
            await self.stream_server.graceful_shutdown()
            logger.info("WebSocket connections closed")
        except (OSError, RuntimeError, asyncio.CancelledError) as e:
            logger.warning("WebSocket shutdown error: %s", e)

    async def _close_http_connector(self) -> None:
        """Close shared HTTP connector."""
        try:
            from aragora.agents.api_agents.common import close_shared_connector

            await close_shared_connector()
            logger.info("Shared HTTP connector closed")
        except (ImportError, OSError, RuntimeError) as e:
            logger.debug("Connector shutdown: %s", e)

    def _close_database_connections(self) -> None:
        """Close database connections."""
        try:
            from aragora.storage.schema import DatabaseManager

            DatabaseManager.clear_instances()
            logger.info("Database connections closed")
        except (ImportError, sqlite3.Error) as e:
            logger.debug("Database shutdown: %s", e)

    async def _run_shutdown_callbacks(self) -> None:
        """Run registered shutdown callbacks."""
        for callback in self._shutdown_callbacks:
            try:
                result = callback()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:  # noqa: BLE001 - Shutdown must continue despite individual callback failures
                logger.warning("Shutdown callback error: %s", e)


__all__ = [
    "ServerLifecycleManager",
    "ThreadRegistry",
    "get_thread_registry",
    "reset_thread_registry",
    "register_lifecycle_signal_handlers",
]
