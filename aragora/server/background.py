"""
Background task management for the Aragora server.

Provides periodic task execution for maintenance operations like:
- Memory tier cleanup (TTL enforcement)
- Stale debate cleanup
- Cache pruning

Task callbacks are organized as module-level factory functions for better
testability and reduced complexity in setup_default_tasks().
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

# =============================================================================
# Task Callback Factories
# =============================================================================
# Each factory returns a callback function. Factories that need shared state
# (like memory_instance) accept it as a parameter and close over it.


def create_memory_cleanup_callback(
    nomic_dir: str | None,
    memory_instance: Any | None,
    pressure_threshold: float,
) -> Callable[[], None]:
    """Create a memory tier cleanup callback.

    Cleans up expired memories when pressure exceeds threshold.
    """
    _shared_memory = memory_instance

    def memory_cleanup_task() -> None:
        nonlocal _shared_memory
        try:
            if _shared_memory is not None:
                memory = _shared_memory
            else:
                from aragora.memory.continuum import ContinuumMemory
                from aragora.persistence.db_config import DatabaseType, get_db_path

                db_path = get_db_path(
                    DatabaseType.CONTINUUM_MEMORY,
                    nomic_dir=Path(nomic_dir) if nomic_dir else None,
                )
                memory = ContinuumMemory(db_path=db_path)

            pressure = memory.get_memory_pressure()
            if pressure < pressure_threshold:
                logger.debug(
                    "Memory pressure %.1f%% below threshold %.1f%%, skipping cleanup",
                    pressure * 100,
                    pressure_threshold * 100,
                )
                return

            logger.info(
                "Memory pressure %.1f%% exceeds threshold, running cleanup",
                pressure * 100,
            )
            result = memory.cleanup_expired_memories(archive=True)

            if result["deleted"] > 0 or result["archived"] > 0:
                logger.info(
                    "Memory cleanup: archived=%d, deleted=%d",
                    result["archived"],
                    result["deleted"],
                )
        except ImportError:
            logger.debug("ContinuumMemory not available, skipping cleanup")
        except (sqlite3.Error, OSError) as e:
            logger.warning("Memory cleanup failed: %s", e)

    return memory_cleanup_task


def create_memory_consolidation_callback(
    nomic_dir: str | None,
    memory_instance: Any | None,
) -> Callable[[], None]:
    """Create a memory consolidation callback.

    Promotes/demotes memories between tiers based on access patterns.
    """
    _shared_memory = memory_instance

    def memory_consolidation_task() -> None:
        nonlocal _shared_memory
        try:
            if _shared_memory is not None:
                memory = _shared_memory
            else:
                from aragora.memory.continuum import ContinuumMemory
                from aragora.persistence.db_config import DatabaseType, get_db_path

                db_path = get_db_path(
                    DatabaseType.CONTINUUM_MEMORY,
                    nomic_dir=Path(nomic_dir) if nomic_dir else None,
                )
                memory = ContinuumMemory(db_path=db_path)

            result = memory.consolidate()
            logger.info(
                "Memory consolidation: promoted=%d, demoted=%d, evaluated=%d",
                result.get("promoted", 0),
                result.get("demoted", 0),
                result.get("evaluated", 0),
            )
        except ImportError:
            logger.debug("ContinuumMemory not available, skipping consolidation")
        except (sqlite3.Error, OSError) as e:
            logger.warning("Memory consolidation failed: %s", e)

    return memory_consolidation_task


def stale_debate_cleanup() -> None:
    """Clean up stale debates from state manager."""
    try:
        from aragora.server.state import get_state_manager

        state_mgr = get_state_manager()
        cleaned = state_mgr.cleanup_stale_debates(max_age_seconds=3600)
        if cleaned > 0:
            logger.info("Cleaned up %d stale debates", cleaned)
    except (ImportError, AttributeError) as e:
        logger.debug("Stale debate cleanup skipped: %s", e)
    except (sqlite3.Error, OSError) as e:
        logger.warning("Stale debate cleanup failed: %s", e)


def circuit_breaker_cleanup() -> None:
    """Clean up and persist circuit breakers."""
    try:
        from aragora.resilience import (
            cleanup_stale_persisted,
            persist_all_circuit_breakers,
            prune_circuit_breakers,
        )

        cleaned = prune_circuit_breakers()
        if cleaned > 0:
            logger.info("Cleaned up %d stale circuit breakers", cleaned)

        persisted = persist_all_circuit_breakers()
        if persisted > 0:
            logger.debug("Persisted %d circuit breakers to disk", persisted)

        cleanup_stale_persisted(max_age_hours=72.0)
    except ImportError:
        pass  # resilience module may not be available
    except (sqlite3.Error, OSError) as e:
        logger.warning("Circuit breaker cleanup failed: %s", e)


def circuit_breaker_metrics_export() -> None:
    """Export circuit breaker states to Prometheus."""
    try:
        from aragora.server.prometheus import export_circuit_breaker_metrics

        export_circuit_breaker_metrics()
    except ImportError:
        pass  # prometheus module may not be available
    except (ValueError, TypeError) as e:
        logger.debug("Circuit breaker metrics export failed: %s", e)


def consensus_cleanup_task() -> None:
    """Clean up old consensus memory records."""
    try:
        from aragora.memory.consensus import ConsensusMemory

        consensus = ConsensusMemory()
        result = consensus.cleanup_old_records(max_age_days=90, archive=True)

        if result.get("archived", 0) > 0 or result.get("deleted", 0) > 0:
            logger.info(
                "Consensus cleanup: archived=%d, deleted=%d",
                result.get("archived", 0),
                result.get("deleted", 0),
            )
    except ImportError:
        logger.debug("ConsensusMemory not available, skipping cleanup")
    except sqlite3.Error as e:
        logger.warning("Consensus cleanup database error: %s", e)
    except OSError as e:
        logger.warning("Consensus cleanup I/O error: %s", e)


def lru_cache_cleanup_task() -> None:
    """Clear module-level @lru_cache functions to prevent memory accumulation."""
    try:
        from aragora.utils.cache_registry import (
            clear_all_lru_caches,
            get_registered_cache_count,
        )

        cache_count = get_registered_cache_count()
        if cache_count > 0:
            cleared = clear_all_lru_caches()
            if cleared > 0:
                logger.info(
                    "LRU cache cleanup: cleared %d entries from %d caches",
                    cleared,
                    cache_count,
                )
    except ImportError:
        logger.debug("cache_registry not available, skipping LRU cleanup")
    except (TypeError, AttributeError) as e:
        logger.warning("LRU cache cleanup failed: %s", e)


def km_staleness_check_task() -> None:
    """Check for stale knowledge in the Knowledge Mound and emit events."""
    try:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def check_staleness() -> None:
            workspace_id = "default"
            try:
                from aragora.knowledge.mound import get_knowledge_mound

                mound = get_knowledge_mound()
                if mound is None:
                    logger.debug("Knowledge Mound not available, skipping staleness check")
                    _record_km_staleness_metric(workspace_id, "skipped", 0)
                    return

                from aragora.events.cross_subscribers import get_cross_subscriber_manager
                from aragora.knowledge.mound.staleness import (
                    StalenessConfig,
                    StalenessDetector,
                )

                manager = get_cross_subscriber_manager()
                detector = StalenessDetector(
                    mound=mound,
                    config=StalenessConfig(auto_revalidation_threshold=0.7),
                    event_emitter=manager,
                )

                stale_nodes = await detector.get_stale_nodes(
                    workspace_id=workspace_id,
                    threshold=0.7,
                    limit=50,
                )
                stale_count = len(stale_nodes) if stale_nodes else 0

                if stale_nodes:
                    logger.info(
                        "Knowledge staleness check: found %d stale nodes",
                        stale_count,
                    )

                _record_km_staleness_metric(workspace_id, "completed", stale_count)

            except ImportError as e:
                logger.debug("Knowledge Mound staleness check skipped: %s", e)
                _record_km_staleness_metric(workspace_id, "skipped", 0)

        if loop.is_running():
            asyncio.create_task(check_staleness())
        else:
            loop.run_until_complete(check_staleness())

    except (RuntimeError, ValueError) as e:
        logger.warning("KM staleness check failed: %s", e)
        _record_km_staleness_metric("default", "failed", 0)


def _record_km_staleness_metric(workspace_id: str, status: str, stale_count: int) -> None:
    """Record KM staleness check metric (helper to reduce code duplication)."""
    try:
        from aragora.server.prometheus_cross_pollination import record_km_staleness_check

        record_km_staleness_check(workspace_id, status, stale_count)
    except ImportError:
        pass


def snooze_processor_task() -> None:
    """Process due snoozed emails and return them to inbox."""
    try:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def process_snoozes() -> None:
            try:
                import json

                from aragora.server.handlers.email.email_services import (
                    handle_process_due_snoozes,
                )

                result = await handle_process_due_snoozes()
                # Handle both dict and HandlerResult responses
                data: dict[str, Any] = {}
                if hasattr(result, "body"):
                    # HandlerResult - parse the JSON body
                    try:
                        data = json.loads(result.body) if result.body else {}
                    except (json.JSONDecodeError, TypeError):
                        data = {}
                    success = result.status_code == 200
                else:
                    # Dict response (legacy)
                    data = result if isinstance(result, dict) else {}
                    success = data.get("success", False)

                # "count" is the integer, "processed" is the list of IDs
                processed_count = data.get("data", {}).get("count", 0)
                if success and processed_count > 0:
                    logger.info("Snooze processor: woke up %d emails", processed_count)
            except ImportError:
                logger.debug("Email services not available, skipping snooze processing")

        if loop.is_running():
            asyncio.create_task(process_snoozes())
        else:
            loop.run_until_complete(process_snoozes())

    except (RuntimeError, ValueError) as e:
        logger.warning("Snooze processing failed: %s", e)


def followup_checker_task() -> None:
    """Check for overdue follow-ups and send reminders."""
    try:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def check_followups() -> None:
            try:
                from aragora.services.followup_tracker import FollowUpTracker

                tracker = FollowUpTracker()
                overdue = await tracker.get_overdue_followups()
                if overdue:
                    logger.info(
                        "Follow-up checker: %d emails overdue for follow-up",
                        len(overdue),
                    )
            except ImportError:
                logger.debug("Follow-up tracker not available, skipping check")

        if loop.is_running():
            asyncio.create_task(check_followups())
        else:
            loop.run_until_complete(check_followups())

    except (RuntimeError, ValueError) as e:
        logger.warning("Follow-up check failed: %s", e)


def create_retention_gate_callback(
    nomic_dir: str | None,
    memory_instance: Any | None,
) -> Callable[[], None]:
    """Create a retention gate sweep callback.

    Gathers item metadata from Continuum memory and runs the MIRAS
    retention gate to identify items for demotion or archival.
    """
    _shared_memory = memory_instance

    def retention_gate_sweep_task() -> None:
        nonlocal _shared_memory
        try:
            from aragora.memory.retention import ItemMetadata, RetentionGate

            # Get or create continuum memory instance
            memory = _shared_memory
            if memory is None:
                try:
                    from aragora.memory.continuum import ContinuumMemory

                    base_dir = nomic_dir or "."
                    memory = ContinuumMemory(base_dir=base_dir)
                except (ImportError, OSError):
                    logger.debug("ContinuumMemory not available for retention sweep")
                    return

            # Gather items from memory tiers for evaluation
            items: list[ItemMetadata] = []
            import time as _time

            now = _time.time()
            for tier_name in ("fast", "medium", "slow", "glacial"):
                tier = getattr(memory, f"_{tier_name}", None)
                if tier is None:
                    continue
                for entry in getattr(tier, "entries", []):
                    items.append(
                        ItemMetadata(
                            item_id=getattr(entry, "id", str(id(entry))),
                            system="continuum",
                            created_at=getattr(entry, "timestamp", now),
                            last_accessed=getattr(entry, "last_accessed", now),
                            access_count=getattr(entry, "access_count", 1),
                            surprise_score=getattr(entry, "surprise_score", 0.5),
                        )
                    )

            if not items:
                return

            gate = RetentionGate()
            report = gate.sweep(items)
            if report.demote or report.archive:
                logger.info(
                    "Retention gate sweep: %d demote, %d archive (of %d evaluated)",
                    report.demote,
                    report.archive,
                    report.evaluated,
                )
        except ImportError:
            logger.debug("RetentionGate not available, skipping sweep")
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Retention gate sweep failed: %s", e)

    return retention_gate_sweep_task


@dataclass
class TaskConfig:
    """Configuration for a background task."""

    name: str
    interval_seconds: float
    callback: Callable[[], Any]
    enabled: bool = True
    run_on_startup: bool = False
    last_run: float | None = None
    run_count: int = 0
    error_count: int = 0


class BackgroundTaskManager:
    """
    Manages periodic background tasks for server maintenance.

    Thread-safe manager that runs tasks at configured intervals.
    Integrates with the server lifecycle via start/stop methods.

    Usage:
        manager = BackgroundTaskManager()
        manager.register_task(
            name="memory_cleanup",
            interval_seconds=3600,  # 1 hour
            callback=cleanup_memory,
        )
        manager.start()
        # ... server runs ...
        manager.stop()
    """

    def __init__(self):
        self._tasks: dict[str, TaskConfig] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def register_task(
        self,
        name: str,
        interval_seconds: float,
        callback: Callable[[], Any],
        enabled: bool = True,
        run_on_startup: bool = False,
    ) -> None:
        """
        Register a periodic background task.

        Args:
            name: Unique task identifier
            interval_seconds: How often to run (in seconds)
            callback: Function to call (should be quick and non-blocking)
            enabled: Whether task is active
            run_on_startup: Run immediately when manager starts
        """
        with self._lock:
            self._tasks[name] = TaskConfig(
                name=name,
                interval_seconds=interval_seconds,
                callback=callback,
                enabled=enabled,
                run_on_startup=run_on_startup,
            )
            logger.info(
                "Registered background task: %s (interval=%ds, enabled=%s)",
                name,
                interval_seconds,
                enabled,
            )

    def unregister_task(self, name: str) -> bool:
        """Remove a registered task."""
        with self._lock:
            if name in self._tasks:
                del self._tasks[name]
                logger.info("Unregistered background task: %s", name)
                return True
            return False

    def enable_task(self, name: str, enabled: bool = True) -> bool:
        """Enable or disable a task."""
        with self._lock:
            if name in self._tasks:
                self._tasks[name].enabled = enabled
                logger.info("Task %s enabled=%s", name, enabled)
                return True
            return False

    def start(self) -> None:
        """Start the background task runner."""
        if self._running:
            logger.warning("BackgroundTaskManager already running")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="BackgroundTaskManager",
        )
        self._thread.start()
        logger.info("BackgroundTaskManager started")

        # Register with lifecycle ThreadRegistry for coordinated shutdown
        try:
            from aragora.server.lifecycle import get_thread_registry

            get_thread_registry().register(
                "background-task-manager",
                self._thread,
                shutdown_fn=self.stop,
            )
        except ImportError:
            pass

        # Run startup tasks
        with self._lock:
            for task in self._tasks.values():
                if task.enabled and task.run_on_startup:
                    self._execute_task(task)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background task runner."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

        logger.info("BackgroundTaskManager stopped")

    def _run_loop(self) -> None:
        """Main loop that checks and runs tasks."""
        check_interval = 10.0  # Check every 10 seconds

        while not self._stop_event.is_set():
            now = time.time()

            with self._lock:
                tasks_to_run = []
                for task in self._tasks.values():
                    if not task.enabled:
                        continue
                    if task.last_run is None:
                        # Never run before - check if startup already ran it
                        if not task.run_on_startup or task.run_count == 0:
                            tasks_to_run.append(task)
                    elif now - task.last_run >= task.interval_seconds:
                        tasks_to_run.append(task)

            for task in tasks_to_run:
                self._execute_task(task)

            # Wait with interruptible sleep
            self._stop_event.wait(timeout=check_interval)

    def _execute_task(self, task: TaskConfig) -> None:
        """Execute a single task with error handling."""
        try:
            logger.debug("Running background task: %s", task.name)
            start = time.time()
            task.callback()
            duration = time.time() - start

            task.last_run = time.time()
            task.run_count += 1

            logger.info(
                "Background task %s completed (duration=%.2fs, runs=%d)",
                task.name,
                duration,
                task.run_count,
            )
        except Exception as e:  # noqa: BLE001 - Background task scheduler: must catch all errors to continue running other tasks
            task.error_count += 1
            logger.error(
                "Background task %s failed (errors=%d): %s",
                task.name,
                task.error_count,
                e,
                exc_info=True,
            )

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about background tasks."""
        with self._lock:
            return {
                "running": self._running,
                "task_count": len(self._tasks),
                "tasks": {
                    name: {
                        "enabled": task.enabled,
                        "interval_seconds": task.interval_seconds,
                        "last_run": task.last_run,
                        "run_count": task.run_count,
                        "error_count": task.error_count,
                        "seconds_until_next": (
                            max(0, task.interval_seconds - (time.time() - task.last_run))
                            if task.last_run
                            else 0
                        ),
                    }
                    for name, task in self._tasks.items()
                },
            }

    def run_task_now(self, name: str) -> bool:
        """Manually trigger a task to run immediately."""
        with self._lock:
            task = self._tasks.get(name)
            if not task:
                return False

        self._execute_task(task)
        return True


# Singleton instance
_background_manager: BackgroundTaskManager | None = None
_manager_lock = threading.Lock()


def get_background_manager() -> BackgroundTaskManager:
    """Get the singleton BackgroundTaskManager instance."""
    global _background_manager

    with _manager_lock:
        if _background_manager is None:
            _background_manager = BackgroundTaskManager()

    return _background_manager


def setup_default_tasks(
    nomic_dir: str | None = None,
    memory_instance: Any | None = None,
    pressure_threshold: float = 0.8,
) -> None:
    """
    Register default background tasks.

    Called during server startup to set up maintenance tasks.

    Args:
        nomic_dir: Path to nomic directory (for memory cleanup)
        memory_instance: Optional shared ContinuumMemory instance to use.
            If provided, cleanup uses this instance instead of creating a new one.
            This enables pressure-aware cleanup on the actual server memory.
        pressure_threshold: Trigger cleanup when memory pressure exceeds this
            threshold (0.0-1.0). Default 0.8 means cleanup at 80% capacity.
    """
    manager = get_background_manager()

    # Initialize circuit breaker metrics integration
    try:
        from aragora.server.prometheus import initialize_circuit_breaker_metrics

        initialize_circuit_breaker_metrics()
    except ImportError:
        pass  # prometheus module may not be available

    memory_cleanup_task = create_memory_cleanup_callback(
        nomic_dir=nomic_dir,
        memory_instance=memory_instance,
        pressure_threshold=pressure_threshold,
    )

    manager.register_task(
        name="memory_tier_cleanup",
        interval_seconds=6 * 3600,  # 6 hours
        callback=memory_cleanup_task,
        enabled=True,
        run_on_startup=False,  # Don't run on startup (let things settle first)
    )

    manager.register_task(
        name="stale_debate_cleanup",
        interval_seconds=30 * 60,  # 30 minutes
        callback=stale_debate_cleanup,
        enabled=True,
        run_on_startup=False,
    )

    manager.register_task(
        name="circuit_breaker_cleanup",
        interval_seconds=3600,  # 1 hour
        callback=circuit_breaker_cleanup,
        enabled=True,
        run_on_startup=False,
    )

    manager.register_task(
        name="circuit_breaker_metrics_export",
        interval_seconds=30,  # 30 seconds
        callback=circuit_breaker_metrics_export,
        enabled=True,
        run_on_startup=True,  # Export immediately on startup
    )

    memory_consolidation_task = create_memory_consolidation_callback(
        nomic_dir=nomic_dir,
        memory_instance=memory_instance,
    )

    manager.register_task(
        name="memory_consolidation",
        interval_seconds=24 * 3600,  # 24 hours
        callback=memory_consolidation_task,
        enabled=True,
        run_on_startup=False,
    )

    manager.register_task(
        name="consensus_cleanup",
        interval_seconds=24 * 3600,  # 24 hours
        callback=consensus_cleanup_task,
        enabled=True,
        run_on_startup=False,
    )

    manager.register_task(
        name="lru_cache_cleanup",
        interval_seconds=12 * 3600,  # 12 hours
        callback=lru_cache_cleanup_task,
        enabled=True,
        run_on_startup=False,
    )

    manager.register_task(
        name="km_staleness_check",
        interval_seconds=6 * 3600,  # 6 hours
        callback=km_staleness_check_task,
        enabled=True,
        run_on_startup=False,  # Don't run on startup (let KM settle first)
    )

    manager.register_task(
        name="snooze_processor",
        interval_seconds=5 * 60,  # 5 minutes
        callback=snooze_processor_task,
        enabled=True,
        run_on_startup=False,
    )

    manager.register_task(
        name="followup_checker",
        interval_seconds=30 * 60,  # 30 minutes
        callback=followup_checker_task,
        enabled=True,
        run_on_startup=False,
    )

    retention_gate_callback = create_retention_gate_callback(
        nomic_dir=nomic_dir,
        memory_instance=memory_instance,
    )

    manager.register_task(
        name="retention_gate_sweep",
        interval_seconds=12 * 3600,  # 12 hours
        callback=retention_gate_callback,
        enabled=True,
        run_on_startup=False,
    )

    logger.info("Default background tasks registered")
