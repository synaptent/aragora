"""
Gauntlet Job Queue Worker.

Processes gauntlet jobs from the durable queue, enabling:
- Restart recovery after server crashes
- Retry logic on transient failures
- Priority-based scheduling

Lives in ``aragora.server.workers`` rather than ``aragora.queue.workers``
because it imports ``aragora.server.stream.gauntlet_emitter``, an
interface-layer package, alongside ``aragora.gauntlet``/``aragora.agents``/
``aragora.ranking`` (docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md §6.2,
§10 Q3).

Usage:
    from aragora.server.workers.gauntlet_worker import GauntletWorker

    worker = GauntletWorker()
    await worker.start()  # Starts processing loop
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.storage.job_queue_store import (
    QueuedJob,
    get_job_store,
)

if TYPE_CHECKING:
    from aragora.gauntlet import GauntletProgress

logger = logging.getLogger(__name__)

# Job type constant
JOB_TYPE_GAUNTLET = "gauntlet"


class GauntletWorker:
    """
    Worker that processes gauntlet jobs from the durable queue.

    Features:
    - Polls job queue for pending gauntlet jobs
    - Executes gauntlet with progress tracking
    - Handles failures with automatic retry
    - Supports graceful shutdown
    """

    def __init__(
        self,
        worker_id: str | None = None,
        poll_interval: float = 2.0,
        max_concurrent: int = 3,
        broadcast_fn: Callable[..., Any] | None = None,
    ):
        """
        Initialize gauntlet worker.

        Args:
            worker_id: Unique worker identifier (auto-generated if not provided)
            poll_interval: Seconds between queue polls when idle
            max_concurrent: Maximum concurrent gauntlet executions
            broadcast_fn: Optional WebSocket broadcast function for streaming
        """
        self.worker_id = worker_id or f"gauntlet-worker-{os.getpid()}"
        self.poll_interval = poll_interval
        self.max_concurrent = max_concurrent
        self.broadcast_fn = broadcast_fn

        self._running = False
        self._active_jobs: dict[str, asyncio.Task] = {}
        self._store = get_job_store()

    async def start(self) -> None:
        """Start the worker processing loop."""
        self._running = True
        logger.info("[%s] Starting gauntlet worker", self.worker_id)

        cancelled_exc: asyncio.CancelledError | None = None
        while self._running:
            try:
                # Clean up completed tasks
                self._cleanup_completed_tasks()

                # Check if we can take more jobs
                if len(self._active_jobs) >= self.max_concurrent:
                    await asyncio.sleep(0.5)
                    continue

                # Dequeue next job
                job = await self._store.dequeue(
                    worker_id=self.worker_id,
                    job_types=[JOB_TYPE_GAUNTLET],
                )

                if job:
                    # Start processing job
                    task = asyncio.create_task(
                        self._process_job(job),
                        name=f"gauntlet-{job.id}",
                    )
                    self._active_jobs[job.id] = task
                    logger.info("[%s] Started processing job %s", self.worker_id, job.id)
                else:
                    # No jobs available, wait before polling again
                    await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError as exc:
                logger.info("[%s] Worker cancelled", self.worker_id)
                cancelled_exc = exc
                self._running = False
                break
            except (RuntimeError, ValueError, OSError, ConnectionError) as e:  # noqa: BLE001 - worker isolation
                # Check for pool/connection closure errors that indicate shutdown
                err_msg = str(e).lower()
                if any(
                    phrase in err_msg
                    for phrase in ("pool is closed", "connection is closed", "event loop is closed")
                ):
                    logger.info(
                        "[%s] Database connection unavailable, exiting worker", self.worker_id
                    )
                    break
                logger.error("[%s] Worker error: %s", self.worker_id, e, exc_info=True)
                await asyncio.sleep(self.poll_interval)

        # Wait for active jobs to complete on shutdown
        if self._active_jobs:
            logger.info("[%s] Waiting for %s active jobs", self.worker_id, len(self._active_jobs))
            await asyncio.gather(*self._active_jobs.values(), return_exceptions=True)

        logger.info("[%s] Worker stopped", self.worker_id)
        if cancelled_exc is not None:
            raise cancelled_exc

    async def stop(self) -> None:
        """Stop the worker gracefully."""
        logger.info("[%s] Stopping worker", self.worker_id)
        self._running = False

    def _cleanup_completed_tasks(self) -> None:
        """Remove completed tasks from tracking dict."""
        completed = [job_id for job_id, task in self._active_jobs.items() if task.done()]
        for job_id in completed:
            task = self._active_jobs.pop(job_id)
            if not task.cancelled() and task.exception():
                logger.warning("[%s] Job %s failed: %s", self.worker_id, job_id, task.exception())

    async def _process_job(self, job: QueuedJob) -> None:
        """Process a single gauntlet job."""
        start_time = time.time()
        gauntlet_id = job.payload.get("gauntlet_id", job.id)

        try:
            logger.info("[%s] Processing gauntlet %s", self.worker_id, gauntlet_id)

            # Execute the gauntlet
            result = await self._execute_gauntlet(job)

            # Mark job as completed
            duration = time.time() - start_time
            await self._store.complete(
                job.id,
                result={
                    "gauntlet_id": gauntlet_id,
                    "verdict": result.get("verdict", "unknown"),
                    "duration_seconds": duration,
                },
            )

            logger.info(
                "[%s] Completed gauntlet %s in %.1fs", self.worker_id, gauntlet_id, duration
            )

        except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as e:
            logger.error(
                "[%s] Gauntlet %s failed: %s",
                self.worker_id,
                gauntlet_id,
                e,
                exc_info=True,
            )

            # Check if we should retry
            should_retry = job.attempts < job.max_attempts
            await self._store.fail(
                job.id,
                error=str(e),
                should_retry=should_retry,
            )

            if should_retry:
                logger.info(
                    "[%s] Gauntlet %s will retry (attempt %s/%s)",
                    self.worker_id,
                    gauntlet_id,
                    job.attempts,
                    job.max_attempts,
                )

    async def _execute_gauntlet(self, job: QueuedJob) -> dict:
        """
        Execute the actual gauntlet orchestration.

        Args:
            job: Queued job with gauntlet parameters

        Returns:
            Result dictionary
        """
        from aragora.agents.base import AgentType, create_agent
        from aragora.gauntlet import (
            GauntletOrchestrator,
            InputType,
            OrchestratorConfig,
        )
        from aragora.gauntlet.storage import GauntletStorage

        payload = job.payload
        gauntlet_id = payload.get("gauntlet_id", job.id)
        input_content = payload.get("input_content", "")
        input_type = payload.get("input_type", "spec")
        persona = payload.get("persona")
        agents = payload.get("agents", ["anthropic-api"])
        profile = payload.get("profile", "default")

        # Get storage for status updates
        storage = GauntletStorage()

        # Create stream emitter if broadcast function is available
        emitter = None
        if self.broadcast_fn:
            try:
                from aragora.server.stream.gauntlet_emitter import GauntletStreamEmitter

                emitter = GauntletStreamEmitter(
                    broadcast_fn=self.broadcast_fn,
                    gauntlet_id=gauntlet_id,
                )
            except ImportError:
                pass

        # Update status to running
        try:
            storage.update_inflight_status(gauntlet_id, "running")
        except (OSError, RuntimeError) as e:
            logger.debug("Failed to update inflight status: %s", e)

        # Create agents
        agent_instances = []
        for agent_type in agents:
            try:
                from typing import cast

                agent = create_agent(
                    model_type=cast(AgentType, agent_type),
                    name=f"{agent_type}_gauntlet",
                    role="auditor",
                )
                agent_instances.append(agent)
            except (ImportError, ValueError, RuntimeError) as e:
                logger.warning("Could not create agent %s: %s", agent_type, e)

        if not agent_instances:
            raise RuntimeError("No agents could be created")

        # Map input type
        input_type_map = {
            "spec": InputType.SPEC,
            "architecture": InputType.ARCHITECTURE,
            "policy": InputType.POLICY,
            "code": InputType.CODE,
            "strategy": InputType.STRATEGY,
            "contract": InputType.CONTRACT,
        }
        input_type_enum = input_type_map.get(input_type, InputType.SPEC)

        # Create config
        config = OrchestratorConfig(
            gauntlet_id=gauntlet_id,
            input_type=input_type_enum,
            input_content=input_content,
            persona=persona,
            max_duration_seconds=300,
        )

        # Emit start event
        if emitter:
            emitter.emit_start(
                gauntlet_id=gauntlet_id,
                input_type=input_type,
                input_summary=input_content[:500],
                agents=[a.name for a in agent_instances],
                config_summary={"profile": profile, "persona": persona},
            )

        # Progress callback
        def on_progress(progress: GauntletProgress) -> None:
            if emitter:
                emitter.emit_progress(
                    progress=progress.percent / 100.0,
                    phase=progress.phase,
                    message=progress.message,
                )
                if progress.current_task:
                    emitter.emit_phase(progress.current_task, progress.message)

            # Update persistent status (throttled)
            if int(progress.percent) % 10 == 0:
                try:
                    storage.update_inflight_status(
                        gauntlet_id,
                        "running",
                        current_phase=progress.phase,
                        progress_percent=progress.percent,
                    )
                except (OSError, RuntimeError) as e:
                    logger.warning(
                        "Failed to update inflight status for gauntlet %s: %s", gauntlet_id, e
                    )

        # Run gauntlet
        orchestrator = GauntletOrchestrator(agent_instances, on_progress=on_progress)
        result = await orchestrator.run(config)

        # Emit completion events
        if emitter:
            emitter.emit_verdict(
                verdict=result.verdict.value,
                confidence=result.confidence,
                risk_score=result.risk_score,
                robustness_score=result.robustness_score,
                critical_count=len(result.critical_findings),
                high_count=len(result.high_findings),
                medium_count=len(result.medium_findings),
                low_count=len(result.low_findings),
            )
            emitter.emit_complete(
                gauntlet_id=gauntlet_id,
                verdict=result.verdict.value,
                confidence=result.confidence,
                findings_count=result.total_findings,
                duration_seconds=result.duration_seconds,
            )

        # Persist result
        try:
            storage.save(result)
            storage.delete_inflight(gauntlet_id)
            logger.info("Gauntlet %s persisted to storage", gauntlet_id)
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to persist gauntlet %s: %s", gauntlet_id, e)

        # Feed gauntlet results back to ELO rankings
        try:
            from aragora.ranking.elo import EloSystem

            elo_system = EloSystem()
            for agent_name in agents:
                elo_system.record_redteam_result(
                    agent_name=agent_name,
                    robustness_score=result.robustness_score,
                    successful_attacks=len(result.critical_findings) + len(result.high_findings),
                    total_attacks=result.total_findings or 1,
                    critical_vulnerabilities=len(result.critical_findings),
                    session_id=gauntlet_id,
                )
            logger.info(
                "Gauntlet %s ELO updated for %s agents (robustness=%.2f)",
                gauntlet_id,
                len(agents),
                result.robustness_score,
            )
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to update ELO from gauntlet %s: %s", gauntlet_id, e)

        return {
            "gauntlet_id": gauntlet_id,
            "verdict": result.verdict.value,
            "confidence": result.confidence,
            "risk_score": result.risk_score,
            "robustness_score": result.robustness_score,
            "total_findings": result.total_findings,
        }


async def enqueue_gauntlet_job(
    gauntlet_id: str,
    input_content: str,
    input_type: str,
    persona: str | None,
    agents: list[str],
    profile: str,
    user_id: str | None = None,
    workspace_id: str | None = None,
    priority: int = 0,
) -> QueuedJob:
    """
    Enqueue a gauntlet job for durable processing.

    Args:
        gauntlet_id: Unique gauntlet identifier
        input_content: Content to validate
        input_type: Type of input (spec, architecture, etc.)
        persona: Regulatory persona
        agents: List of agent types
        profile: Gauntlet profile
        user_id: Optional user ID
        workspace_id: Optional workspace ID
        priority: Job priority (higher = more urgent)

    Returns:
        The queued job
    """
    job = QueuedJob(
        id=gauntlet_id,
        job_type=JOB_TYPE_GAUNTLET,
        payload={
            "gauntlet_id": gauntlet_id,
            "input_content": input_content,
            "input_type": input_type,
            "persona": persona,
            "agents": agents,
            "profile": profile,
        },
        priority=priority,
        user_id=user_id,
        workspace_id=workspace_id,
    )

    store = get_job_store()
    await store.enqueue(job)

    logger.info("Enqueued gauntlet job: %s", gauntlet_id)
    return job


async def recover_interrupted_gauntlets() -> int:
    """
    Recover interrupted gauntlet jobs after server restart.

    Finds gauntlet jobs that were in-flight when the server stopped
    and re-enqueues them for processing.

    Returns:
        Number of jobs recovered
    """
    from aragora.gauntlet.storage import GauntletStorage

    store = get_job_store()
    storage = GauntletStorage()
    recovered = 0

    try:
        # First, recover any stale jobs in the job queue itself
        stale_recovered = await store.recover_stale_jobs(stale_threshold_seconds=300.0)
        if stale_recovered:
            logger.info("Recovered %s stale jobs from queue", stale_recovered)
            recovered += stale_recovered

        # Also check gauntlet inflight table for runs not in job queue
        stale_runs = storage.list_stale_inflight(max_age_seconds=300)

        for run in stale_runs:
            # Check if this run is already in the job queue
            existing = await store.get(run.gauntlet_id)
            if existing:
                continue

            # Check if we have enough info to re-enqueue
            if not run.config_json:
                # Mark as interrupted, can't recover
                storage.update_inflight_status(
                    run.gauntlet_id,
                    "interrupted",
                    error="Server restarted, insufficient data to resume",
                )
                continue

            # Re-enqueue for processing
            import json

            try:
                config = json.loads(run.config_json)
                await enqueue_gauntlet_job(
                    gauntlet_id=run.gauntlet_id,
                    input_content=config.get("input_content", ""),
                    input_type=run.input_type,
                    persona=run.persona,
                    agents=run.agents,
                    profile=run.profile,
                    priority=5,  # Higher priority for recovered jobs
                )
                recovered += 1
                logger.info("Re-enqueued interrupted gauntlet: %s", run.gauntlet_id)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to re-enqueue %s: %s", run.gauntlet_id, e)
                storage.update_inflight_status(
                    run.gauntlet_id,
                    "interrupted",
                    error=f"Failed to resume: {e}",
                )

    except (RuntimeError, OSError, ConnectionError) as e:
        logger.error("Error recovering gauntlet jobs: %s", e, exc_info=True)

    if recovered:
        logger.info("Recovered %s interrupted gauntlet jobs", recovered)

    return recovered
