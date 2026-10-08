"""
Durable job queue worker for TestFixer.

Lives in ``aragora.nomic.testfixer`` rather than ``aragora.queue.workers``
because it imports ``aragora.nomic.testfixer.http_api``, an application-layer
package (docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md §6.2, §10 Q4).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from aragora.storage.job_queue_store import QueuedJob, get_job_store
from aragora.nomic.testfixer.http_api import TestFixerRunConfig, run_fix_loop

logger = logging.getLogger(__name__)

JOB_TYPE_TESTFIXER = "testfixer"


class TestFixerWorker:
    """Worker that processes TestFixer jobs from the durable queue."""

    def __init__(self, worker_id: str | None = None, poll_interval: float = 5.0):
        self.worker_id = worker_id or f"testfixer-worker-{os.getpid()}"
        self.poll_interval = poll_interval
        self._store = get_job_store()
        self._running = False
        self._active_jobs: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        self._running = True
        logger.info("[%s] Starting testfixer worker", self.worker_id)

        cancelled_exc: asyncio.CancelledError | None = None
        while self._running:
            try:
                self._cleanup_completed_tasks()

                if len(self._active_jobs) >= 1:
                    await asyncio.sleep(0.5)
                    continue

                job = await self._store.dequeue(
                    worker_id=self.worker_id, job_types=[JOB_TYPE_TESTFIXER]
                )
                if job:
                    task = asyncio.create_task(self._process_job(job), name=f"testfixer-{job.id}")
                    self._active_jobs[job.id] = task
                    logger.info("[%s] Started job %s", self.worker_id, job.id)
                else:
                    await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError as exc:
                cancelled_exc = exc
                self._running = False
                break
            except (RuntimeError, ValueError, OSError, ConnectionError) as exc:  # noqa: BLE001 - worker isolation
                logger.error("[%s] Worker error: %s", self.worker_id, exc, exc_info=True)
                await asyncio.sleep(self.poll_interval)

        if self._active_jobs:
            await asyncio.gather(*self._active_jobs.values(), return_exceptions=True)

        logger.info("[%s] Worker stopped", self.worker_id)
        if cancelled_exc is not None:
            raise cancelled_exc

    async def stop(self) -> None:
        self._running = False

    def _cleanup_completed_tasks(self) -> None:
        completed = [job_id for job_id, task in self._active_jobs.items() if task.done()]
        for job_id in completed:
            task = self._active_jobs.pop(job_id)
            if not task.cancelled() and task.exception():
                logger.warning("[%s] Job %s failed: %s", self.worker_id, job_id, task.exception())

    async def _process_job(self, job: QueuedJob) -> None:
        start_time = time.time()
        try:
            payload = job.payload
            config = TestFixerRunConfig(
                repo_path=Path(payload["repo_path"]),
                test_command=payload["test_command"],
                agents=payload.get("agents", ["codex", "claude"]),
                max_iterations=payload.get("max_iterations", 10),
                min_confidence=payload.get("min_confidence", 0.5),
                timeout_seconds=payload.get("timeout_seconds", 300.0),
                attempt_store_path=Path(payload["attempt_store_path"])
                if payload.get("attempt_store_path")
                else None,
            )
            result = await run_fix_loop(config)
            duration = time.time() - start_time
            await self._store.complete(
                job.id, result={"duration_seconds": duration, **result.to_dict()}
            )
            logger.info("[%s] Completed job %s in %.1fs", self.worker_id, job.id, duration)
        except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as exc:
            logger.error("[%s] Job %s failed: %s", self.worker_id, job.id, exc, exc_info=True)
            should_retry = job.attempts < job.max_attempts
            await self._store.fail(job.id, error=str(exc), should_retry=should_retry)


async def recover_interrupted_testfixer_jobs(max_age_seconds: float = 3600) -> int:
    store = get_job_store()
    recovered = await store.recover_stale_jobs(stale_threshold_seconds=max_age_seconds)
    if recovered:
        logger.info("Recovered %s interrupted testfixer jobs", recovered)
    return recovered
