"""
In-memory storage management and helper functions for gauntlet runs.

This module contains:
- In-memory storage for in-flight gauntlet runs
- Memory management and cleanup functions
- Helper functions for task creation and exception handling
- Persistent storage access
- WebSocket broadcast function management
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from datetime import datetime
from importlib import import_module
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.gauntlet.storage import GauntletStorage

logger = logging.getLogger(__name__)

# Keep driver errors explicit without coupling the HTTP reader to the queue worker.
_STORAGE_ERRORS: tuple[type[Exception], ...] = (OSError, RuntimeError, ValueError, sqlite3.Error)
for _driver, _error in (
    ("psycopg2", "Error"),
    ("asyncpg", "PostgresError"),
    ("asyncpg", "InterfaceError"),
):
    try:
        _STORAGE_ERRORS += (getattr(import_module(_driver), _error),)
    except ImportError:
        pass


async def resolve_gauntlet_run(
    gauntlet_id: str, cached: dict[str, Any] | None, get_storage: Callable[..., Any]
) -> dict[str, Any] | None:
    """Prefer durable completion, then queue state, over stale HTTP/inflight caches."""
    if cached and cached.get("status") == "completed":
        return cached  # Preserve the in-process result_obj receipt conversion.
    from .receipts import _call_nonblocking
    from aragora.storage.job_queue_store import get_job_store, JobStatus

    storage = get_storage()
    stored = await _call_nonblocking(storage, "get", gauntlet_id)
    inflight = await _call_nonblocking(storage, "get_inflight", gauntlet_id)
    if not stored and inflight and inflight.status in ("failed", "cancelled"):
        return inflight.to_dict()  # Survives a failed queue terminal-state write.
    job = await get_job_store().get(gauntlet_id) if is_durable_queue_enabled() else None
    if stored:
        if not isinstance(stored, dict) or stored.get("gauntlet_id", gauntlet_id) != gauntlet_id:
            raise ValueError("Stored gauntlet identity mismatch")
        run = {"gauntlet_id": gauntlet_id, "status": "completed", "result": stored}
        if (job and job.status == JobStatus.FAILED) or (inflight and inflight.status == "failed"):
            run["error"] = "Gauntlet result persisted; delivery bookkeeping failed"
        return run
    if job:
        status = job.status
        if status == JobStatus.COMPLETED:
            raise RuntimeError("Completed gauntlet result unavailable")
        run = {"gauntlet_id": gauntlet_id, "status": status.value}
        if status in (JobStatus.FAILED, JobStatus.CANCELLED):
            run["error"] = "Gauntlet execution or result delivery failed"
        else:
            run["status"] = "running" if status == JobStatus.PROCESSING else "pending"
        return run
    return inflight.to_dict() if inflight else cached


# In-memory storage for in-flight gauntlet runs (pending/running)
# Completed runs are persisted to GauntletStorage
# Using OrderedDict for FIFO eviction when memory limit reached
_gauntlet_runs: OrderedDict[str, dict[str, Any]] = OrderedDict()

# Memory management for gauntlet runs
MAX_GAUNTLET_RUNS_IN_MEMORY = 500
_GAUNTLET_COMPLETED_TTL = 3600  # Keep completed runs for 1 hour
_GAUNTLET_MAX_AGE_SECONDS = 7200  # Max 2 hours for any entry regardless of status

# Lock for atomic quota check-and-increment (prevents TOCTOU race)
_quota_lock = threading.Lock()

# Enable durable job queue for gauntlet execution (survives restarts)
# Set ARAGORA_DURABLE_GAUNTLET=0 to disable (enabled by default)
_USE_DURABLE_QUEUE = os.environ.get("ARAGORA_DURABLE_GAUNTLET", "1").lower() not in (
    "0",
    "false",
    "no",
)

# Persistent storage singleton
_storage: GauntletStorage | None = None

# WebSocket broadcast function (set by unified server when streaming is enabled)
_gauntlet_broadcast_fn: Callable[..., Any] | None = None


def set_gauntlet_broadcast_fn(broadcast_fn: Callable[..., Any]) -> None:
    """Set the broadcast function for WebSocket streaming."""
    global _gauntlet_broadcast_fn
    _gauntlet_broadcast_fn = broadcast_fn


def get_gauntlet_broadcast_fn() -> Callable[..., Any] | None:
    """Get the broadcast function for WebSocket streaming."""
    return _gauntlet_broadcast_fn


def _get_storage() -> GauntletStorage:
    """Get or create the persistent storage instance."""
    global _storage
    if _storage is None:
        from aragora.gauntlet.storage import GauntletStorage

        _storage = GauntletStorage()
    return _storage


def _handle_task_exception(task: asyncio.Task[Any], task_name: str) -> None:
    """Handle exceptions from fire-and-forget async tasks."""
    if task.cancelled():
        logger.debug("Task %s was cancelled", task_name)
    elif task.exception():
        exc = task.exception()
        logger.error("Task %s failed with exception: %s", task_name, exc, exc_info=exc)


def create_tracked_task(coro: Any, name: str) -> asyncio.Task[Any]:
    """Create an async task with exception logging.

    Use this instead of raw asyncio.create_task() for fire-and-forget tasks
    to ensure exceptions are logged rather than silently ignored.
    """
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(lambda t: _handle_task_exception(t, name))
    return task


def _cleanup_gauntlet_runs() -> None:
    """Remove old runs from memory to prevent unbounded growth.

    Cleanup strategy:
    1. Remove any entry older than MAX_AGE (regardless of status)
    2. Remove completed entries older than COMPLETED_TTL
    3. If still over limit, evict oldest entries (FIFO)
    """
    global _gauntlet_runs
    now = time.time()
    to_remove = []

    for run_id, run in _gauntlet_runs.items():
        created_at = run.get("created_at")

        # Try to get creation time from various fields
        entry_time = None
        if isinstance(created_at, (int, float)):
            entry_time = created_at
        elif isinstance(created_at, str):
            try:
                entry_time = datetime.fromisoformat(created_at).timestamp()
            except (ValueError, TypeError):
                pass

        # If no valid timestamp, check completed_at
        if entry_time is None:
            completed_at = run.get("completed_at")
            if completed_at:
                try:
                    entry_time = datetime.fromisoformat(completed_at).timestamp()
                except (ValueError, TypeError):
                    pass

        # Remove entries older than MAX_AGE regardless of status
        if entry_time and (now - entry_time) > _GAUNTLET_MAX_AGE_SECONDS:
            to_remove.append(run_id)
            continue

        # Remove completed entries older than TTL
        if run.get("status") == "completed":
            completed_at = run.get("completed_at")
            if completed_at:
                try:
                    completed_time = datetime.fromisoformat(completed_at).timestamp()
                    if now - completed_time > _GAUNTLET_COMPLETED_TTL:
                        to_remove.append(run_id)
                except (ValueError, TypeError):
                    pass

    for run_id in to_remove:
        _gauntlet_runs.pop(run_id, None)

    # If still over limit, evict oldest entries (FIFO via OrderedDict)
    while len(_gauntlet_runs) > MAX_GAUNTLET_RUNS_IN_MEMORY:
        _gauntlet_runs.popitem(last=False)  # Remove oldest


def recover_stale_gauntlet_runs(max_age_seconds: int = 7200) -> int:
    """
    Recover stale inflight gauntlet runs after server restart.

    Finds runs that were pending/running when the server stopped and marks
    them as interrupted. This should be called during server startup.

    Args:
        max_age_seconds: Maximum age in seconds for a run to be considered stale

    Returns:
        Number of stale runs recovered/marked as interrupted
    """
    try:
        from . import _get_storage as get_storage

        storage = get_storage()
        stale_runs = storage.list_stale_inflight(max_age_seconds=max_age_seconds)

        if not stale_runs:
            logger.debug("No stale gauntlet runs found to recover")
            return 0

        recovered = 0
        for run in stale_runs:
            try:
                # Mark as interrupted with error message
                storage.update_inflight_status(
                    gauntlet_id=run.gauntlet_id,
                    status="interrupted",
                    error=f"Server restarted while run was {run.status}. "
                    f"Progress was {run.progress_percent:.0f}% in phase '{run.current_phase or 'unknown'}'.",
                )

                # Also add to in-memory dict for immediate access
                _gauntlet_runs[run.gauntlet_id] = {
                    "gauntlet_id": run.gauntlet_id,
                    "status": "interrupted",
                    "input_type": run.input_type,
                    "input_summary": run.input_summary,
                    "persona": run.persona,
                    "agents": run.agents,
                    "profile": run.profile,
                    "created_at": run.created_at.isoformat(),
                    "error": f"Server restarted while run was {run.status}",
                    "progress_percent": run.progress_percent,
                    "current_phase": run.current_phase,
                }

                logger.info(
                    f"Marked stale gauntlet run {run.gauntlet_id} as interrupted "
                    f"(was {run.status}, {run.progress_percent:.0f}% complete)"
                )
                recovered += 1

            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("Failed to recover stale run %s: %s", run.gauntlet_id, e)

        if recovered:
            logger.info("Recovered %s stale gauntlet runs after server restart", recovered)

        return recovered

    except (ImportError, OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to recover stale gauntlet runs: %s", e)
        return 0


def get_gauntlet_runs() -> OrderedDict[str, dict[str, Any]]:
    """Get the in-memory gauntlet runs storage.

    Returns the OrderedDict for direct access by handler methods.
    """
    return _gauntlet_runs


def get_quota_lock() -> threading.Lock:
    """Get the quota lock for atomic operations."""
    return _quota_lock


def is_durable_queue_enabled() -> bool:
    """Check if durable job queue is enabled."""
    return _USE_DURABLE_QUEUE
