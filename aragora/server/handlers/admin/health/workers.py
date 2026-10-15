"""
Health checks for background workers and job queues.

Provides health endpoints for monitoring:
- Background worker status (gauntlet, notification, consensus healing)
- Job queue depth and connectivity
- Queue processing metrics

These checks help detect:
- Stalled workers
- Queue backlogs
- Redis/database connectivity issues
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ...base import HandlerResult, json_response

logger = logging.getLogger(__name__)


@dataclass
class WorkerStatus:
    """Status of a background worker."""

    name: str
    running: bool
    active_jobs: int
    jobs_processed: int
    jobs_failed: int
    uptime_seconds: float
    last_heartbeat: datetime | None = None
    error: str | None = None


@dataclass
class QueueStatus:
    """Status of a job queue."""

    name: str
    connected: bool
    pending: int
    processing: int
    completed: int
    failed: int
    total: int
    error: str | None = None


def worker_health_status(handler: Any) -> HandlerResult:
    """Get health status of all background workers.

    Returns status of registered workers including:
    - Worker name and running state
    - Active job count
    - Jobs processed/failed counts
    - Uptime and last heartbeat

    This endpoint helps identify:
    - Workers that have stopped unexpectedly
    - Workers with high failure rates
    - Workers that are overloaded

    Returns:
        JSON response with worker health report
    """
    workers: list[dict[str, Any]] = []
    errors: list[str] = []

    # Check gauntlet worker
    try:
        from aragora.server.startup.workers import get_gauntlet_worker

        gauntlet_worker = get_gauntlet_worker()
        if gauntlet_worker:
            # Access worker stats
            stats = {
                "name": "gauntlet",
                "running": gauntlet_worker._running,
                "active_jobs": len(gauntlet_worker._active_jobs),
                "max_concurrent": gauntlet_worker.max_concurrent,
                "worker_id": gauntlet_worker.worker_id,
            }
            workers.append(stats)
        else:
            workers.append(
                {
                    "name": "gauntlet",
                    "running": False,
                    "active_jobs": 0,
                    "note": "Worker not initialized",
                }
            )
    except ImportError as e:
        errors.append(f"gauntlet_worker import failed: {e}")
    except (AttributeError, RuntimeError) as e:
        errors.append(f"gauntlet_worker access error: {type(e).__name__}")

    # Check notification worker via dispatcher
    try:
        from aragora.control_plane.notifications import get_default_notification_dispatcher

        dispatcher = get_default_notification_dispatcher()
        if dispatcher and hasattr(dispatcher, "_worker_task"):
            worker_running = (
                dispatcher._worker_task is not None and not dispatcher._worker_task.done()
            )
            workers.append(
                {
                    "name": "notification",
                    "running": worker_running,
                    "queue_enabled": dispatcher._config.queue_enabled
                    if dispatcher._config
                    else False,
                    "max_concurrent": (
                        dispatcher._config.max_concurrent_deliveries if dispatcher._config else 0
                    ),
                }
            )
        else:
            workers.append(
                {
                    "name": "notification",
                    "running": False,
                    "note": "Dispatcher not initialized or no worker task",
                }
            )
    except ImportError:
        workers.append(
            {
                "name": "notification",
                "running": False,
                "note": "Module not available",
            }
        )
    except (AttributeError, RuntimeError) as e:
        errors.append(f"notification_worker access error: {type(e).__name__}")

    # Check consensus healing worker
    try:
        from aragora.memory.consensus_healing_worker import get_consensus_healing_worker

        healing_worker = get_consensus_healing_worker()
        if healing_worker:
            workers.append(
                {
                    "name": "consensus_healing",
                    "running": healing_worker._running,
                    "candidates_processed": getattr(healing_worker, "_candidates_processed", 0),
                    "healed_count": getattr(healing_worker, "_healed_count", 0),
                }
            )
        else:
            workers.append(
                {
                    "name": "consensus_healing",
                    "running": False,
                    "note": "Worker not initialized",
                }
            )
    except ImportError:
        workers.append(
            {
                "name": "consensus_healing",
                "running": False,
                "note": "Module not available",
            }
        )
    except (AttributeError, RuntimeError) as e:
        errors.append(f"consensus_healing_worker access error: {type(e).__name__}")

    # Determine overall status
    running_workers = sum(1 for w in workers if w.get("running", False))
    total_workers = len(workers)

    if running_workers == total_workers and total_workers > 0:
        status = "healthy"
    elif running_workers > 0:
        status = "degraded"
    else:
        status = "unhealthy"

    return json_response(
        {
            "status": status,
            "summary": {
                "total_workers": total_workers,
                "running_workers": running_workers,
                "stopped_workers": total_workers - running_workers,
            },
            "workers": workers,
            "errors": errors if errors else None,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }
    )


def job_queue_health_status(handler: Any) -> HandlerResult:
    """Get health status of the job queue system.

    Returns comprehensive queue status including:
    - Queue connectivity (Redis/PostgreSQL/SQLite)
    - Job counts by status (pending, processing, completed, failed)
    - Queue depth thresholds and warnings

    This endpoint helps identify:
    - Queue connectivity issues
    - Job backlogs (high pending count)
    - Stuck jobs (high processing count with no completions)

    Returns:
        JSON response with job queue health report
    """
    queue_stats: dict[str, Any] = {}
    connected = False
    backend_type = "unknown"
    errors: list[str] = []
    warnings: list[str] = []

    # Get queue stats from job store
    try:
        # Imported first so the name is bound before the store can raise; an
        # ImportError here is matched by the ImportError clause before the
        # DistributedStateError clause is evaluated.
        from aragora.storage.production_guards import DistributedStateError
        from aragora.storage.job_queue_store import get_job_store

        store = get_job_store()
        connected = True

        # Determine backend type
        backend_type = type(store).__name__
        if "SQLite" in backend_type:
            backend_type = "sqlite"
        elif "Postgres" in backend_type:
            backend_type = "postgresql"
        elif "Redis" in backend_type:
            backend_type = "redis"

        # Get stats - run async method
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop:
            # We're in an async context, use run_coroutine_threadsafe
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, store.get_stats())
                queue_stats = future.result(timeout=5.0)
        else:
            queue_stats = asyncio.run(store.get_stats())

    except ImportError as e:
        errors.append(f"job_queue_store import failed: {e}")
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.warning("Queue connectivity error: %s: %s", type(e).__name__, e)
        errors.append("Queue connectivity error")
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
        logger.warning("Queue status error: %s: %s", type(e).__name__, e)
        errors.append("Queue status error")
    except DistributedStateError as e:
        # The guard's message names the store and its env overrides; keep it in
        # the server log and report only the type.
        logger.warning("Queue store refused by distributed-state guard: %s", e)
        errors.append(f"Queue status error: {type(e).__name__}")

    # Calculate thresholds and warnings
    pending_count = queue_stats.get("pending", 0)
    processing_count = queue_stats.get("processing", 0)
    failed_count = queue_stats.get("failed", 0)

    # Configurable thresholds
    import os

    pending_warning_threshold = int(os.getenv("ARAGORA_QUEUE_PENDING_WARNING", "50"))
    pending_critical_threshold = int(os.getenv("ARAGORA_QUEUE_PENDING_CRITICAL", "200"))
    processing_warning_threshold = int(os.getenv("ARAGORA_QUEUE_PROCESSING_WARNING", "20"))

    if pending_count >= pending_critical_threshold:
        warnings.append(
            f"Critical: {pending_count} pending jobs (threshold: {pending_critical_threshold})"
        )
    elif pending_count >= pending_warning_threshold:
        warnings.append(
            f"Warning: {pending_count} pending jobs (threshold: {pending_warning_threshold})"
        )

    if processing_count >= processing_warning_threshold:
        warnings.append(f"Warning: {processing_count} jobs processing (may indicate stuck jobs)")

    if failed_count > 0:
        warnings.append(f"{failed_count} failed jobs in queue")

    # Determine overall status
    if not connected:
        status = "unhealthy"
    elif pending_count >= pending_critical_threshold:
        status = "critical"
    elif warnings:
        status = "degraded"
    else:
        status = "healthy"

    return json_response(
        {
            "status": status,
            "connected": connected,
            "backend": backend_type,
            "stats": {
                "pending": pending_count,
                "processing": processing_count,
                "completed": queue_stats.get("completed", 0),
                "failed": failed_count,
                "cancelled": queue_stats.get("cancelled", 0),
                "total": queue_stats.get("total", 0),
            },
            "thresholds": {
                "pending_warning": pending_warning_threshold,
                "pending_critical": pending_critical_threshold,
                "processing_warning": processing_warning_threshold,
            },
            "warnings": warnings if warnings else None,
            "errors": errors if errors else None,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }
    )


def combined_worker_queue_health(handler: Any) -> HandlerResult:
    """Get combined health status of workers and job queues.

    Provides a unified view of background processing health including:
    - All worker statuses
    - Job queue statistics
    - Overall system health determination

    This is the recommended endpoint for monitoring dashboards
    as it provides a complete picture of background processing.

    Returns:
        JSON response with combined worker and queue health
    """
    import json

    # Get worker health
    worker_result = worker_health_status(handler)
    worker_data = json.loads(worker_result.body.decode("utf-8"))

    # Get queue health
    queue_result = job_queue_health_status(handler)
    queue_data = json.loads(queue_result.body.decode("utf-8"))

    # Determine overall status (worst of the two)
    status_priority = {"healthy": 0, "degraded": 1, "critical": 2, "unhealthy": 3}
    worker_status = worker_data.get("status", "unknown")
    queue_status = queue_data.get("status", "unknown")

    worker_priority = status_priority.get(worker_status, 4)
    queue_priority = status_priority.get(queue_status, 4)

    if worker_priority >= queue_priority:
        overall_status = worker_status
    else:
        overall_status = queue_status

    return json_response(
        {
            "status": overall_status,
            "workers": worker_data,
            "job_queue": queue_data,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }
    )


__all__ = [
    "worker_health_status",
    "job_queue_health_status",
    "combined_worker_queue_health",
    "WorkerStatus",
    "QueueStatus",
]
