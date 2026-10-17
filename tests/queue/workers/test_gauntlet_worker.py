"""
Comprehensive Tests for Gauntlet Job Queue Worker.

Tests durable job processing for gauntlet stress-testing including:
- Job processing lifecycle (start, process, complete, fail)
- Error handling and retry logic
- Task validation and cleanup
- Worker concurrency management
- Recovery of interrupted jobs
"""

import asyncio
import inspect
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.workers.gauntlet_worker import (
    GauntletWorker,
    JOB_TYPE_GAUNTLET,
    enqueue_gauntlet_job,
    recover_interrupted_gauntlets,
)
from aragora.storage.job_queue_store import (
    JobStatus,
    QueuedJob,
    SQLiteJobStore,
    reset_job_store,
    set_job_store,
)


@pytest.fixture
def temp_db():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_gauntlet_jobs.db"


@pytest.fixture
def store(temp_db):
    """Create a SQLite job store for testing."""
    reset_job_store()
    store = SQLiteJobStore(temp_db)
    set_job_store(store)
    yield store
    reset_job_store()


# =============================================================================
# Enqueue Tests
# =============================================================================


class TestEnqueueGauntletJob:
    """Tests for enqueue_gauntlet_job function."""

    @pytest.mark.asyncio
    async def test_enqueues_job(self, store):
        """Should enqueue a gauntlet job."""
        job = await enqueue_gauntlet_job(
            gauntlet_id="gauntlet-test-123",
            input_content="Test content",
            input_type="spec",
            persona="sec-auditor",
            agents=["anthropic-api"],
            profile="default",
        )

        assert job.id == "gauntlet-test-123"
        assert job.job_type == JOB_TYPE_GAUNTLET
        assert job.payload["input_content"] == "Test content"
        assert job.payload["persona"] == "sec-auditor"

    @pytest.mark.asyncio
    async def test_persists_to_store(self, store):
        """Should persist job to store."""
        await enqueue_gauntlet_job(
            gauntlet_id="gauntlet-persist-test",
            input_content="Persist test",
            input_type="policy",
            persona=None,
            agents=["openai-api"],
            profile="strict",
        )

        # Verify in store
        stored = await store.get("gauntlet-persist-test")
        assert stored is not None
        assert stored.job_type == JOB_TYPE_GAUNTLET
        assert stored.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_includes_user_workspace(self, store):
        """Should include user and workspace IDs."""
        job = await enqueue_gauntlet_job(
            gauntlet_id="gauntlet-user-test",
            input_content="User test",
            input_type="spec",
            persona=None,
            agents=["anthropic-api"],
            profile="default",
            user_id="user-123",
            workspace_id="ws-456",
        )

        assert job.user_id == "user-123"
        assert job.workspace_id == "ws-456"

    @pytest.mark.asyncio
    async def test_priority(self, store):
        """Should set job priority."""
        job = await enqueue_gauntlet_job(
            gauntlet_id="gauntlet-priority-test",
            input_content="Priority test",
            input_type="spec",
            persona=None,
            agents=["anthropic-api"],
            profile="default",
            priority=10,
        )

        assert job.priority == 10

    @pytest.mark.asyncio
    async def test_payload_contains_all_fields(self, store):
        """Should store all input fields in payload."""
        job = await enqueue_gauntlet_job(
            gauntlet_id="gauntlet-payload-test",
            input_content="Payload test content",
            input_type="architecture",
            persona="compliance-officer",
            agents=["anthropic-api", "openai-api"],
            profile="strict",
        )

        assert job.payload["gauntlet_id"] == "gauntlet-payload-test"
        assert job.payload["input_content"] == "Payload test content"
        assert job.payload["input_type"] == "architecture"
        assert job.payload["persona"] == "compliance-officer"
        assert job.payload["agents"] == ["anthropic-api", "openai-api"]
        assert job.payload["profile"] == "strict"

    @pytest.mark.asyncio
    async def test_multiple_input_types(self, store):
        """Should handle all supported input types."""
        for input_type in ["spec", "architecture", "policy", "code", "strategy", "contract"]:
            job = await enqueue_gauntlet_job(
                gauntlet_id=f"gauntlet-type-{input_type}",
                input_content=f"Content for {input_type}",
                input_type=input_type,
                persona=None,
                agents=["anthropic-api"],
                profile="default",
            )
            assert job.payload["input_type"] == input_type


# =============================================================================
# Worker Initialization Tests
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attempts,status_write_fails", [(1, False), (3, False), (3, True), (3, "queue")]
)
async def test_execution_failure_visible_to_cached_consumers(
    store, tmp_path, monkeypatch, attempts, status_write_fails
):
    from aragora.gauntlet import storage
    from aragora.server.handlers.gauntlet import results, receipts

    result_store = storage.GauntletStorage(str(tmp_path / "results.db"), backend="sqlite")
    monkeypatch.setattr(storage, "GauntletStorage", lambda: result_store)
    run_id = "gauntlet-terminal-failure"
    result_store.save_inflight(run_id, "running", "spec", "fixture", "hash", None, "default", [])
    for module in (results, receipts):
        monkeypatch.setattr(module, "_get_storage_proxy", lambda: result_store)
        monkeypatch.setattr(
            module,
            "get_gauntlet_runs",
            lambda: {run_id: {"gauntlet_id": run_id, "status": "pending"}},
        )
    if status_write_fails is True:
        monkeypatch.setattr(
            result_store,
            "update_inflight_status",
            MagicMock(side_effect=sqlite3.OperationalError("secret path")),
        )
    job = QueuedJob(id=run_id, job_type="gauntlet", payload={"gauntlet_id": run_id})
    await store.enqueue(job)
    job = await store.dequeue(worker_id="test")
    job.attempts = attempts
    worker = GauntletWorker()
    worker._execute_gauntlet = AsyncMock(side_effect=RuntimeError("private execution details"))
    if status_write_fails == "queue":
        monkeypatch.setattr(
            store, "fail", AsyncMock(side_effect=sqlite3.OperationalError("secret queue"))
        )
        with pytest.raises(sqlite3.OperationalError):
            await worker._process_job(job)
    else:
        await worker._process_job(job)
    response = await inspect.unwrap(results.GauntletResultsMixin._get_status)(None, run_id)
    assert json.loads(response.body)["status"] == ("pending" if attempts == 1 else "failed")
    assert b"private execution" not in response.body
    receipt = await inspect.unwrap(receipts.GauntletReceiptsMixin._get_receipt)(None, run_id, {})
    assert receipt.status_code == 400
    if status_write_fails != "queue":
        assert (await store.get(run_id)).status == (
            JobStatus.PENDING if attempts == 1 else JobStatus.FAILED
        )
    worker._execute_gauntlet.assert_awaited_once()
    result_store.close()


class TestGauntletWorker:
    """Tests for GauntletWorker class."""

    @pytest.mark.asyncio
    async def test_initializes(self, store):
        """Should initialize with defaults."""
        worker = GauntletWorker()
        assert worker.worker_id.startswith("gauntlet-worker-")
        assert worker.poll_interval == 2.0
        assert worker.max_concurrent == 3

    @pytest.mark.asyncio
    async def test_custom_worker_id(self, store):
        """Should accept custom worker ID."""
        worker = GauntletWorker(worker_id="custom-worker-1")
        assert worker.worker_id == "custom-worker-1"

    @pytest.mark.asyncio
    async def test_custom_poll_interval(self, store):
        """Should accept custom poll interval."""
        worker = GauntletWorker(poll_interval=5.0)
        assert worker.poll_interval == 5.0

    @pytest.mark.asyncio
    async def test_custom_max_concurrent(self, store):
        """Should accept custom max concurrent value."""
        worker = GauntletWorker(max_concurrent=10)
        assert worker.max_concurrent == 10

    @pytest.mark.asyncio
    async def test_accepts_broadcast_fn(self, store):
        """Should accept a broadcast function."""
        mock_fn = MagicMock()
        worker = GauntletWorker(broadcast_fn=mock_fn)
        assert worker.broadcast_fn is mock_fn

    @pytest.mark.asyncio
    async def test_initial_state(self, store):
        """Should have correct initial state."""
        worker = GauntletWorker()
        assert worker._running is False
        assert worker._active_jobs == {}

    @pytest.mark.asyncio
    async def test_dequeues_gauntlet_jobs(self, store):
        """Should only dequeue gauntlet job types."""
        # Enqueue a gauntlet job
        await enqueue_gauntlet_job(
            gauntlet_id="gauntlet-dequeue-test",
            input_content="Dequeue test",
            input_type="spec",
            persona=None,
            agents=["anthropic-api"],
            profile="default",
        )

        # Enqueue a non-gauntlet job
        other_job = QueuedJob(
            id="other-job",
            job_type="workflow",
            payload={},
        )
        await store.enqueue(other_job)

        # Dequeue with gauntlet filter
        claimed = await store.dequeue(
            worker_id="test-worker",
            job_types=[JOB_TYPE_GAUNTLET],
        )

        assert claimed is not None
        assert claimed.id == "gauntlet-dequeue-test"

    @pytest.mark.asyncio
    async def test_stop_gracefully(self, store):
        """Should stop gracefully."""
        worker = GauntletWorker()

        # Start and immediately stop
        start_task = asyncio.create_task(worker.start())
        await asyncio.sleep(0.1)
        await worker.stop()

        # Wait for task to complete
        await asyncio.wait_for(start_task, timeout=2.0)

        assert not worker._running


# =============================================================================
# Worker Lifecycle Tests
# =============================================================================


class TestGauntletWorkerLifecycle:
    """Tests for worker start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running_true(self, store):
        """Start should set _running to True."""
        worker = GauntletWorker(poll_interval=0.05)
        task = asyncio.create_task(worker.start())
        await asyncio.sleep(0.1)

        assert worker._running is True

        await worker.stop()
        await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_handles_cancellation(self, store):
        """Worker should handle CancelledError gracefully."""
        worker = GauntletWorker(poll_interval=0.05)
        task = asyncio.create_task(worker.start())
        await asyncio.sleep(0.1)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_handles_event_loop_closed(self, store):
        """Worker should exit on event loop closed errors."""
        worker = GauntletWorker(poll_interval=0.05)

        with patch.object(
            worker._store,
            "dequeue",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Event loop is closed"),
        ):
            task = asyncio.create_task(worker.start())
            await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_handles_pool_closed(self, store):
        """Worker should exit on pool closed errors."""
        worker = GauntletWorker(poll_interval=0.05)

        with patch.object(
            worker._store,
            "dequeue",
            new_callable=AsyncMock,
            side_effect=RuntimeError("pool is closed"),
        ):
            task = asyncio.create_task(worker.start())
            await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_waits_for_active_jobs_on_shutdown(self, store):
        """Worker should wait for active jobs before shutting down."""
        worker = GauntletWorker(poll_interval=0.05)

        # Create a slow-completing task
        completed = False

        async def slow_task():
            nonlocal completed
            await asyncio.sleep(0.1)
            completed = True

        task = asyncio.create_task(slow_task())
        worker._active_jobs["slow-job"] = task

        # Start and stop
        start_task = asyncio.create_task(worker.start())
        await asyncio.sleep(0.05)
        await worker.stop()
        await asyncio.wait_for(start_task, timeout=3.0)

        assert completed


# =============================================================================
# Task Cleanup Tests
# =============================================================================


class TestCleanupCompletedTasks:
    """Tests for _cleanup_completed_tasks method."""

    @pytest.mark.asyncio
    async def test_removes_completed_tasks(self, store):
        """Should remove completed tasks from tracking."""
        worker = GauntletWorker()

        # Create completed task
        async def noop():
            pass

        task = asyncio.create_task(noop())
        await task
        worker._active_jobs["done-job"] = task

        worker._cleanup_completed_tasks()

        assert "done-job" not in worker._active_jobs

    @pytest.mark.asyncio
    async def test_keeps_running_tasks(self, store):
        """Should keep running tasks in tracking."""
        worker = GauntletWorker()

        # Create a running task
        event = asyncio.Event()

        async def wait_for_event():
            await event.wait()

        task = asyncio.create_task(wait_for_event())
        worker._active_jobs["running-job"] = task

        worker._cleanup_completed_tasks()

        assert "running-job" in worker._active_jobs

        # Cleanup
        event.set()
        await task

    @pytest.mark.asyncio
    async def test_logs_failed_tasks(self, store):
        """Should log warnings for failed tasks."""
        worker = GauntletWorker()

        async def fail():
            raise RuntimeError("Task failure")

        task = asyncio.create_task(fail())
        try:
            await task
        except RuntimeError:
            pass
        worker._active_jobs["failed-job"] = task

        # Should not raise
        worker._cleanup_completed_tasks()
        assert "failed-job" not in worker._active_jobs


# =============================================================================
# Recovery Tests
# =============================================================================


class TestRecoverInterruptedGauntlets:
    """Tests for recover_interrupted_gauntlets function."""

    @pytest.mark.asyncio
    async def test_recovers_stale_jobs(self, store):
        """Should recover stale jobs from queue."""
        # Enqueue a job and manually make it stale
        job = QueuedJob(
            id="stale-gauntlet",
            job_type=JOB_TYPE_GAUNTLET,
            payload={
                "gauntlet_id": "stale-gauntlet",
                "input_content": "Stale test",
                "input_type": "spec",
                "persona": None,
                "agents": ["anthropic-api"],
                "profile": "default",
            },
        )
        await store.enqueue(job)

        # Claim it (simulating a worker that crashed)
        await store.dequeue(worker_id="crashed-worker")

        # Manually backdate it
        conn = store._get_conn()
        conn.execute(
            "UPDATE job_queue SET started_at = ? WHERE id = ?",
            (time.time() - 400, "stale-gauntlet"),
        )
        conn.commit()

        # Recover stale jobs
        recovered = await store.recover_stale_jobs(stale_threshold_seconds=300.0)
        assert recovered == 1

        # Job should be pending again
        job_after = await store.get("stale-gauntlet")
        assert job_after is not None
        assert job_after.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_no_stale_jobs(self, store):
        """Should handle case with no stale jobs."""
        recovered = await recover_interrupted_gauntlets()
        assert recovered == 0

    @pytest.mark.asyncio
    async def test_recover_returns_count(self, store):
        """Should return the number of recovered jobs."""
        # Create two stale jobs
        for i in range(2):
            job = QueuedJob(
                id=f"stale-{i}",
                job_type=JOB_TYPE_GAUNTLET,
                payload={"gauntlet_id": f"stale-{i}"},
            )
            await store.enqueue(job)
            await store.dequeue(worker_id="crashed-worker")

        # Backdate both
        conn = store._get_conn()
        conn.execute(
            "UPDATE job_queue SET started_at = ?",
            (time.time() - 400,),
        )
        conn.commit()

        recovered = await store.recover_stale_jobs(stale_threshold_seconds=300.0)
        assert recovered == 2


# =============================================================================
# Job Processing Tests
# =============================================================================


class TestWorkerJobProcessing:
    """Tests for worker job processing logic."""

    @pytest.mark.asyncio
    async def test_marks_completed_on_success(self, store):
        """Should mark job completed on successful execution."""
        with patch(
            "aragora.server.workers.gauntlet_worker.GauntletWorker._execute_gauntlet",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = {
                "gauntlet_id": "test-gauntlet",
                "verdict": "pass",
                "confidence": 0.95,
            }

            worker = GauntletWorker()

            # Create a job
            job = QueuedJob(
                id="test-job",
                job_type=JOB_TYPE_GAUNTLET,
                payload={
                    "gauntlet_id": "test-gauntlet",
                    "input_content": "Test",
                    "input_type": "spec",
                    "persona": None,
                    "agents": ["anthropic-api"],
                    "profile": "default",
                },
            )
            await store.enqueue(job)
            claimed = await store.dequeue(worker_id=worker.worker_id)

            # Process job
            await worker._process_job(claimed)

            # Job should be completed
            job_after = await store.get("test-job")
            assert job_after is not None
            assert job_after.status == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_marks_failed_on_error(self, store):
        """Should mark job failed and schedule retry on error."""
        with patch(
            "aragora.server.workers.gauntlet_worker.GauntletWorker._execute_gauntlet",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.side_effect = RuntimeError("Test error")

            worker = GauntletWorker()

            # Create a job with 3 max attempts
            job = QueuedJob(
                id="fail-job",
                job_type=JOB_TYPE_GAUNTLET,
                payload={
                    "gauntlet_id": "fail-gauntlet",
                    "input_content": "Test",
                    "input_type": "spec",
                    "persona": None,
                    "agents": ["anthropic-api"],
                    "profile": "default",
                },
                max_attempts=3,
            )
            await store.enqueue(job)
            claimed = await store.dequeue(worker_id=worker.worker_id)

            # Process job (should fail)
            await worker._process_job(claimed)

            # Job should be back to pending for retry
            job_after = await store.get("fail-job")
            assert job_after is not None
            assert job_after.status == JobStatus.PENDING
            assert job_after.error == "Test error"

    @pytest.mark.asyncio
    async def test_uses_gauntlet_id_from_payload(self, store):
        """Should use gauntlet_id from payload for logging."""
        with patch(
            "aragora.server.workers.gauntlet_worker.GauntletWorker._execute_gauntlet",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = {
                "gauntlet_id": "custom-gauntlet-id",
                "verdict": "pass",
            }

            worker = GauntletWorker()
            job = QueuedJob(
                id="job-123",
                job_type=JOB_TYPE_GAUNTLET,
                payload={
                    "gauntlet_id": "custom-gauntlet-id",
                    "input_content": "Test",
                },
            )
            await store.enqueue(job)
            claimed = await store.dequeue(worker_id=worker.worker_id)

            await worker._process_job(claimed)

            # Verify the gauntlet was called
            mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_completed_result_includes_verdict(self, store):
        """Should store verdict in completed result."""
        with patch(
            "aragora.server.workers.gauntlet_worker.GauntletWorker._execute_gauntlet",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = {
                "gauntlet_id": "verdict-test",
                "verdict": "fail",
                "confidence": 0.8,
            }

            worker = GauntletWorker()
            job = QueuedJob(
                id="verdict-job",
                job_type=JOB_TYPE_GAUNTLET,
                payload={"gauntlet_id": "verdict-test"},
            )
            await store.enqueue(job)
            claimed = await store.dequeue(worker_id=worker.worker_id)

            await worker._process_job(claimed)

            job_after = await store.get("verdict-job")
            assert job_after is not None
            assert job_after.status == JobStatus.COMPLETED
            assert job_after.result is not None
            assert job_after.result["verdict"] == "fail"

    @pytest.mark.asyncio
    async def test_max_attempts_exhausted(self, store):
        """Should permanently fail when max attempts exhausted."""
        with patch(
            "aragora.server.workers.gauntlet_worker.GauntletWorker._execute_gauntlet",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.side_effect = RuntimeError("Persistent error")

            worker = GauntletWorker()

            # Create job with only 1 max attempt
            job = QueuedJob(
                id="exhaust-job",
                job_type=JOB_TYPE_GAUNTLET,
                payload={"gauntlet_id": "exhaust-test"},
                max_attempts=1,
            )
            await store.enqueue(job)
            claimed = await store.dequeue(worker_id=worker.worker_id)

            # After dequeue, attempts = 1, max_attempts = 1 so no retry
            await worker._process_job(claimed)

            job_after = await store.get("exhaust-job")
            assert job_after is not None
            assert job_after.status == JobStatus.FAILED

    @pytest.mark.asyncio
    async def test_fallback_gauntlet_id(self, store):
        """Should fall back to job.id when gauntlet_id not in payload."""
        with patch(
            "aragora.server.workers.gauntlet_worker.GauntletWorker._execute_gauntlet",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = {
                "gauntlet_id": "fallback-id",
                "verdict": "pass",
            }

            worker = GauntletWorker()
            job = QueuedJob(
                id="fallback-id",
                job_type=JOB_TYPE_GAUNTLET,
                payload={"input_content": "Test without gauntlet_id"},
            )
            await store.enqueue(job)
            claimed = await store.dequeue(worker_id=worker.worker_id)

            await worker._process_job(claimed)

            job_after = await store.get("fallback-id")
            assert job_after.status == JobStatus.COMPLETED


# =============================================================================
# Concurrency Tests
# =============================================================================


class TestGauntletWorkerConcurrency:
    """Tests for worker concurrency management."""

    @pytest.mark.asyncio
    async def test_respects_max_concurrent(self, store):
        """Worker should not exceed max_concurrent jobs."""
        worker = GauntletWorker(max_concurrent=2, poll_interval=0.05)

        # Fill active jobs to capacity
        events = []
        for i in range(2):
            event = asyncio.Event()
            events.append(event)

            async def wait_for(e=event):
                await e.wait()

            task = asyncio.create_task(wait_for())
            worker._active_jobs[f"active-{i}"] = task

        # Worker loop should skip dequeue when at capacity
        task = asyncio.create_task(worker.start())
        await asyncio.sleep(0.15)

        # Stop worker and cleanup
        await worker.stop()
        for event in events:
            event.set()
        await asyncio.wait_for(task, timeout=3.0)
