"""
Debate worker for processing jobs from the queue.

Provides a worker pattern for horizontal scaling with:
- Concurrent job processing
- Graceful shutdown
- Health reporting
- Stale job recovery
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import signal
import time
from typing import Any
from collections.abc import Callable, Coroutine

from aragora.queue.base import Job, JobQueue
from aragora.queue.config import get_queue_config
from aragora.queue.retry import RetryPolicy, is_retryable_error

logger = logging.getLogger(__name__)

# Type alias for the debate executor function
DebateExecutor = Callable[[Job], Coroutine[Any, Any, dict[str, Any]]]

# Domain-free job-handler registry (zero domain imports, eager or lazy). Lets
# domain/application/interface home modules self-register their worker and job
# handler instances instead of being imported directly by aragora.queue.
_REGISTERED_WORKERS: dict[str, Any] = {}
_REGISTERED_JOB_HANDLERS: dict[str, DebateExecutor] = {}


def _same_job_handler(existing: DebateExecutor, handler: DebateExecutor) -> bool:
    """Return whether two handler callables represent the same registration."""
    if existing is handler:
        return True

    existing_self = getattr(existing, "__self__", None)
    handler_self = getattr(handler, "__self__", None)
    existing_func = getattr(existing, "__func__", None)
    handler_func = getattr(handler, "__func__", None)
    if existing_self is None or handler_self is None:
        return False
    if existing_func is None or handler_func is None:
        return False
    return existing_self is handler_self and existing_func is handler_func


def register_worker(name: str, worker: Any) -> None:
    """Register a queue worker instance under ``name`` (keyed).

    Re-registering a *different* instance under an existing name is allowed
    (a worker may legitimately be recreated and re-registered under the same
    name, e.g. on restart) but is logged as a warning so an unexpected clobber
    stays visible instead of silently swapping the running instance.
    """
    existing = _REGISTERED_WORKERS.get(name)
    if existing is not None and existing is not worker:
        logger.warning(
            "Overwriting registered worker %r (existing=%r, new=%r)",
            name,
            existing,
            worker,
        )
    _REGISTERED_WORKERS[name] = worker


def register_job_handler(job_type: str, handler: DebateExecutor) -> None:
    """Register a job handler (executor) for ``job_type``.

    ``handler`` must be callable and a coroutine function (``async def`` or a
    bound method thereof) so a mis-registered sync callable fails at
    registration time instead of surfacing as a runtime "coroutine expected"
    error deep in the queue's job-processing loop.

    Re-registering the same handler is a no-op. Registering a different handler
    for an existing job type fails closed so import order cannot silently
    redirect queue execution.
    """
    if not callable(handler):
        raise TypeError(
            f"job handler for job type {job_type!r} must be callable, got {type(handler).__name__}"
        )
    if not inspect.iscoroutinefunction(handler):
        raise TypeError(
            f"job handler for job type {job_type!r} must be an async callable "
            "(inspect.iscoroutinefunction(handler) must be True)"
        )
    existing = _REGISTERED_JOB_HANDLERS.get(job_type)
    if existing is not None and not _same_job_handler(existing, handler):
        raise ValueError(f"job handler already registered for job type {job_type!r}")
    _REGISTERED_JOB_HANDLERS[job_type] = handler


def get_registered_workers() -> dict[str, Any]:
    """Return a shallow copy of all registered workers, keyed by name."""
    return dict(_REGISTERED_WORKERS)


def get_registered_job_handlers() -> dict[str, DebateExecutor]:
    """Return a shallow copy of all registered job handlers, keyed by job type."""
    return dict(_REGISTERED_JOB_HANDLERS)


def get_job_handler(job_type: str) -> DebateExecutor | None:
    """Return the registered handler for ``job_type``, or ``None`` if unregistered."""
    return _REGISTERED_JOB_HANDLERS.get(job_type)


def registered_worker_names() -> list[str]:
    """Return the sorted names of all registered workers."""
    return sorted(_REGISTERED_WORKERS)


def registered_job_handler_names() -> list[str]:
    """Return the sorted job types of all registered job handlers."""
    return sorted(_REGISTERED_JOB_HANDLERS)


def reset_registry() -> None:
    """Clear both the worker and job-handler registries (for tests)."""
    _REGISTERED_WORKERS.clear()
    _REGISTERED_JOB_HANDLERS.clear()


class DebateWorker:
    """
    Worker that processes debate jobs from the queue.

    Designed for horizontal scaling:
    - Each worker has a unique ID
    - Uses consumer groups for work distribution
    - Handles graceful shutdown
    - Reports health via heartbeat
    - Recovers stale jobs from dead workers
    """

    def __init__(
        self,
        queue: JobQueue,
        worker_id: str,
        executor: DebateExecutor,
        max_concurrent: int = 3,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """
        Initialize the worker.

        Args:
            queue: The job queue to process from
            worker_id: Unique identifier for this worker
            executor: Async function to execute debates
            max_concurrent: Maximum concurrent jobs to process
            retry_policy: Policy for retrying failed jobs
        """
        self._queue = queue
        self._worker_id = worker_id
        self._executor = executor
        self._max_concurrent = max_concurrent
        self._retry_policy = retry_policy or RetryPolicy.from_config()
        self._config = get_queue_config()

        self._running = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._shutdown_event = asyncio.Event()

        # Metrics
        self._jobs_processed = 0
        self._jobs_failed = 0
        self._start_time: float | None = None

    @property
    def worker_id(self) -> str:
        """Get the worker ID."""
        return self._worker_id

    @property
    def is_running(self) -> bool:
        """Check if worker is running."""
        return self._running

    @property
    def active_jobs(self) -> int:
        """Get number of currently processing jobs."""
        return self._max_concurrent - self._semaphore._value

    def get_stats(self) -> dict[str, Any]:
        """Get worker statistics."""
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "worker_id": self._worker_id,
            "running": self._running,
            "active_jobs": self.active_jobs,
            "max_concurrent": self._max_concurrent,
            "jobs_processed": self._jobs_processed,
            "jobs_failed": self._jobs_failed,
            "uptime_seconds": uptime,
        }

    async def start(self) -> None:
        """
        Start the worker.

        Runs until stop() is called or a signal is received.
        """
        if self._running:
            logger.warning("Worker %s is already running", self._worker_id)
            return

        self._running = True
        self._start_time = time.time()
        self._shutdown_event.clear()

        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

        logger.info("Worker %s started (max_concurrent=%s)", self._worker_id, self._max_concurrent)

        try:
            # Start background tasks
            claim_task = asyncio.create_task(self._claim_stale_jobs_loop())
            self._tasks.add(claim_task)

            # Main processing loop
            while self._running:
                try:
                    # Wait for a slot
                    await self._semaphore.acquire()

                    if not self._running:
                        self._semaphore.release()
                        break

                    # Try to get a job
                    job = await self._queue.dequeue(
                        self._worker_id,
                        timeout_ms=self._config.worker_block_ms,
                    )

                    if job is None:
                        self._semaphore.release()
                        continue

                    # Process the job in background
                    task = asyncio.create_task(self._process_job(job))
                    self._tasks.add(task)
                    task.add_done_callback(lambda t: self._tasks.discard(t))

                except asyncio.CancelledError:
                    self._semaphore.release()
                    break
                except (RuntimeError, ValueError, OSError) as e:  # noqa: BLE001 - worker isolation
                    self._semaphore.release()
                    logger.error("Error in worker loop: %s", e, exc_info=True)
                    await asyncio.sleep(1)  # Brief pause before retrying

        finally:
            # Clean up signal handlers
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(sig)

            self._running = False
            logger.info("Worker %s stopped", self._worker_id)

    async def stop(self, timeout: float = 30.0) -> None:
        """
        Stop the worker gracefully.

        Waits for current jobs to complete up to the timeout.

        Args:
            timeout: Maximum time to wait for jobs to complete
        """
        if not self._running:
            return

        logger.info("Worker %s stopping (timeout=%ss)", self._worker_id, timeout)
        self._running = False
        self._shutdown_event.set()

        # Wait for active tasks with timeout
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for %s tasks", len(self._tasks))
                # Cancel remaining tasks
                for task in self._tasks:
                    task.cancel()

        await self._queue.close()

    def _handle_signal(self) -> None:
        """Handle shutdown signal."""
        logger.info("Worker %s received shutdown signal", self._worker_id)
        self._running = False
        self._shutdown_event.set()

    async def _process_job(self, job: Job) -> None:
        """
        Process a single job.

        Args:
            job: The job to process
        """
        try:
            logger.info("Processing job %s (attempt %s)", job.id, job.attempts)
            start_time = time.time()

            # Execute the debate
            result = await self._executor(job)

            # Mark completed
            job.mark_completed(result)
            await self._queue.ack(job.id)

            duration = time.time() - start_time
            self._jobs_processed += 1

            logger.info("Job %s completed in %.2fs", job.id, duration)

        except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as e:
            error_msg = str(e)
            logger.error("Job %s failed: %s", job.id, error_msg, exc_info=True)

            job.mark_retrying(error_msg)
            self._jobs_failed += 1

            # Determine if we should retry
            should_retry = is_retryable_error(e) and self._retry_policy.should_retry(
                job.attempts, e
            )

            if should_retry:
                # Calculate retry delay
                delay = self._retry_policy.get_delay(job.attempts - 1)
                logger.info(
                    "Job %s will retry in %.1fs (attempt %s/%s)",
                    job.id,
                    delay,
                    job.attempts,
                    job.max_attempts,
                )
                # Leave in pending list for retry
                await self._queue.nack(job.id, requeue=True)
            else:
                # Mark as permanently failed
                job.mark_failed(error_msg)
                await self._queue.nack(job.id, requeue=False)
                logger.warning("Job %s permanently failed after %s attempts", job.id, job.attempts)

        finally:
            self._semaphore.release()

    async def _claim_stale_jobs_loop(self) -> None:
        """
        Periodically claim stale jobs from dead workers.
        """
        while self._running:
            try:
                # Wait between claim attempts
                await asyncio.sleep(self._config.claim_idle_ms / 1000 / 2)

                if not self._running:
                    break

                # Claim stale jobs
                claimed = await self._queue.claim_stale_jobs(self._config.claim_idle_ms)
                if claimed > 0:
                    logger.info("Claimed %s stale jobs", claimed)

            except asyncio.CancelledError:
                break
            except (RuntimeError, OSError, ConnectionError) as e:
                logger.error("Error claiming stale jobs: %s", e)
