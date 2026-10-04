"""
Tests for batch processor module.

Tests cover:
- JobStatus and JobPriority enums
- DocumentJob dataclass and to_dict serialization
- BatchResult dataclass
- BatchProcessor construction and configuration
- submit(), get_status(), get_result(), cancel() methods
- get_stats() statistics
- start() and stop() lifecycle
- Worker processing with mocks
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.documents.ingestion.batch_processor import (
    BatchProcessor,
    BatchResult,
    DocumentJob,
    JobPriority,
    JobStatus,
    get_batch_processor,
)


class TestJobStatus:
    """Tests for JobStatus enum."""

    def test_all_values(self):
        assert JobStatus.QUEUED.value == "queued"
        assert JobStatus.PROCESSING.value == "processing"
        assert JobStatus.CHUNKING.value == "chunking"
        assert JobStatus.INDEXING.value == "indexing"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.CANCELLED.value == "cancelled"

    def test_member_count(self):
        assert len(JobStatus) == 7


class TestJobPriority:
    """Tests for JobPriority enum."""

    def test_all_values(self):
        assert JobPriority.LOW.value == 0
        assert JobPriority.NORMAL.value == 1
        assert JobPriority.HIGH.value == 2
        assert JobPriority.URGENT.value == 3

    def test_ordering(self):
        assert JobPriority.LOW.value < JobPriority.NORMAL.value
        assert JobPriority.NORMAL.value < JobPriority.HIGH.value
        assert JobPriority.HIGH.value < JobPriority.URGENT.value


class TestDocumentJob:
    """Tests for DocumentJob dataclass."""

    def test_default_creation(self):
        job = DocumentJob()
        assert job.id is not None
        assert len(job.id) == 36  # UUID format
        assert job.content == b""
        assert job.filename == ""
        assert job.workspace_id == ""
        assert job.status == JobStatus.QUEUED
        assert job.priority == JobPriority.NORMAL
        assert job.progress == 0.0
        assert job.chunks == []
        assert job.document is None

    def test_custom_creation(self):
        job = DocumentJob(
            content=b"test content",
            filename="test.pdf",
            workspace_id="ws-123",
            uploaded_by="user-456",
            tags=["important", "finance"],
            priority=JobPriority.HIGH,
            chunk_size=256,
            chunk_overlap=25,
        )
        assert job.content == b"test content"
        assert job.filename == "test.pdf"
        assert job.workspace_id == "ws-123"
        assert job.uploaded_by == "user-456"
        assert job.tags == ["important", "finance"]
        assert job.priority == JobPriority.HIGH
        assert job.chunk_size == 256
        assert job.chunk_overlap == 25

    def test_to_dict(self):
        job = DocumentJob(
            filename="doc.txt",
            workspace_id="ws-1",
            uploaded_by="user-1",
            tags=["test"],
            priority=JobPriority.URGENT,
            chunk_size=512,
            chunk_overlap=50,
        )
        job.status = JobStatus.PROCESSING
        job.progress = 0.5

        data = job.to_dict()

        assert data["filename"] == "doc.txt"
        assert data["workspace_id"] == "ws-1"
        assert data["uploaded_by"] == "user-1"
        assert data["tags"] == ["test"]
        assert data["priority"] == "URGENT"
        assert data["status"] == "processing"
        assert data["progress"] == 0.5
        assert data["chunk_size"] == 512
        assert data["chunk_overlap"] == 50
        assert data["document_id"] is None
        assert data["chunk_count"] == 0
        assert "created_at" in data
        assert data["started_at"] is None
        assert data["completed_at"] is None

    def test_to_dict_with_document(self):
        job = DocumentJob(filename="test.txt")

        # Mock document
        mock_doc = MagicMock()
        mock_doc.id = "doc-123"
        job.document = mock_doc

        mock_chunk = MagicMock()
        job.chunks = [mock_chunk, mock_chunk]

        data = job.to_dict()

        assert data["document_id"] == "doc-123"
        assert data["chunk_count"] == 2

    def test_to_dict_with_timestamps(self):
        job = DocumentJob(filename="test.txt")
        job.started_at = datetime(2024, 1, 15, 10, 30, 0)
        job.completed_at = datetime(2024, 1, 15, 10, 31, 0)

        data = job.to_dict()

        assert data["started_at"] == "2024-01-15T10:30:00"
        assert data["completed_at"] == "2024-01-15T10:31:00"


class TestBatchResult:
    """Tests for BatchResult dataclass."""

    def test_creation(self):
        jobs = [DocumentJob(filename="a.txt"), DocumentJob(filename="b.txt")]
        result = BatchResult(
            total_jobs=5,
            completed_jobs=3,
            failed_jobs=2,
            total_documents=3,
            total_chunks=150,
            total_tokens=10000,
            duration_ms=5000,
            jobs=jobs,
        )

        assert result.total_jobs == 5
        assert result.completed_jobs == 3
        assert result.failed_jobs == 2
        assert result.total_documents == 3
        assert result.total_chunks == 150
        assert result.total_tokens == 10000
        assert result.duration_ms == 5000
        assert len(result.jobs) == 2


class TestBatchProcessorConstruction:
    """Tests for BatchProcessor construction."""

    def test_default_config(self):
        processor = BatchProcessor()
        assert processor.max_workers == 4
        assert processor.max_queue_size == 1000
        assert processor.default_chunk_size == 512
        assert processor.default_chunk_overlap == 50
        assert processor._running is False
        assert processor._active_workers == 0

    def test_custom_config(self):
        processor = BatchProcessor(
            max_workers=8,
            max_queue_size=500,
            default_chunk_size=256,
            default_chunk_overlap=25,
        )
        assert processor.max_workers == 8
        assert processor.max_queue_size == 500
        assert processor.default_chunk_size == 256
        assert processor.default_chunk_overlap == 25


class TestBatchProcessorSubmit:
    """Tests for BatchProcessor.submit method."""

    @pytest.mark.asyncio
    async def test_submit_basic(self):
        processor = BatchProcessor()

        job_id = await processor.submit(
            content=b"test content",
            filename="test.pdf",
            workspace_id="ws-123",
        )

        assert job_id is not None
        assert len(job_id) == 36  # UUID
        assert job_id in processor._jobs

        job = processor._jobs[job_id]
        assert job.content == b"test content"
        assert job.filename == "test.pdf"
        assert job.workspace_id == "ws-123"
        assert job.status == JobStatus.QUEUED

    @pytest.mark.asyncio
    async def test_submit_with_all_options(self):
        processor = BatchProcessor()

        progress_callback = MagicMock()
        complete_callback = MagicMock()
        error_callback = MagicMock()

        job_id = await processor.submit(
            content=b"pdf content",
            filename="report.pdf",
            workspace_id="ws-456",
            uploaded_by="user-789",
            tags=["finance", "q1"],
            priority=JobPriority.URGENT,
            chunking_strategy="semantic",
            chunk_size=256,
            chunk_overlap=30,
            enable_ocr=False,
            on_progress=progress_callback,
            on_complete=complete_callback,
            on_error=error_callback,
        )

        job = processor._jobs[job_id]
        assert job.uploaded_by == "user-789"
        assert job.tags == ["finance", "q1"]
        assert job.priority == JobPriority.URGENT
        assert job.chunking_strategy == "semantic"
        assert job.chunk_size == 256
        assert job.chunk_overlap == 30
        assert job.enable_ocr is False
        assert job.on_progress is progress_callback
        assert job.on_complete is complete_callback
        assert job.on_error is error_callback

    @pytest.mark.asyncio
    async def test_submit_uses_default_chunk_settings(self):
        processor = BatchProcessor(
            default_chunk_size=1024,
            default_chunk_overlap=100,
        )

        job_id = await processor.submit(
            content=b"test",
            filename="test.txt",
        )

        job = processor._jobs[job_id]
        assert job.chunk_size == 1024
        assert job.chunk_overlap == 100


class TestBatchProcessorGetStatus:
    """Tests for BatchProcessor.get_status method."""

    @pytest.mark.asyncio
    async def test_get_status_existing_job(self):
        processor = BatchProcessor()
        job_id = await processor.submit(b"test", "test.txt")

        status = await processor.get_status(job_id)

        assert status is not None
        assert status["filename"] == "test.txt"
        assert status["status"] == "queued"

    @pytest.mark.asyncio
    async def test_get_status_nonexistent_job(self):
        processor = BatchProcessor()

        status = await processor.get_status("nonexistent-id")

        assert status is None


class TestBatchProcessorGetResult:
    """Tests for BatchProcessor.get_result method."""

    @pytest.mark.asyncio
    async def test_get_result_existing_job(self):
        processor = BatchProcessor()
        job_id = await processor.submit(b"test", "test.txt")

        result = await processor.get_result(job_id)

        assert result is not None
        assert isinstance(result, DocumentJob)
        assert result.filename == "test.txt"

    @pytest.mark.asyncio
    async def test_get_result_nonexistent_job(self):
        processor = BatchProcessor()

        result = await processor.get_result("nonexistent-id")

        assert result is None


class TestBatchProcessorCancel:
    """Tests for BatchProcessor.cancel method."""

    @pytest.mark.asyncio
    async def test_cancel_queued_job(self):
        processor = BatchProcessor()
        job_id = await processor.submit(b"test", "test.txt")

        result = await processor.cancel(job_id)

        assert result is True
        job = processor._jobs[job_id]
        assert job.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_processing_job_fails(self):
        processor = BatchProcessor()
        job_id = await processor.submit(b"test", "test.txt")
        processor._jobs[job_id].status = JobStatus.PROCESSING

        result = await processor.cancel(job_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job(self):
        processor = BatchProcessor()

        result = await processor.cancel("nonexistent-id")

        assert result is False


class TestBatchProcessorGetStats:
    """Tests for BatchProcessor.get_stats method."""

    @pytest.mark.asyncio
    async def test_initial_stats(self):
        processor = BatchProcessor(max_workers=8)

        stats = processor.get_stats()

        assert stats["running"] is False
        assert stats["max_workers"] == 8
        assert stats["active_workers"] == 0
        assert stats["queued_jobs"] == 0
        assert stats["processing_jobs"] == 0
        assert stats["total_processed"] == 0
        assert stats["total_failed"] == 0
        assert stats["total_chunks"] == 0
        assert stats["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_stats_with_queued_jobs(self):
        processor = BatchProcessor()
        await processor.submit(b"test1", "test1.txt")
        await processor.submit(b"test2", "test2.txt")
        await processor.submit(b"test3", "test3.txt")

        stats = processor.get_stats()

        assert stats["queued_jobs"] == 3


class TestBatchProcessorSubmitBatch:
    """Tests for BatchProcessor.submit_batch method."""

    @pytest.mark.asyncio
    async def test_submit_batch(self):
        processor = BatchProcessor()

        files = [
            (b"content1", "file1.txt"),
            (b"content2", "file2.pdf"),
            (b"content3", "file3.md"),
        ]

        job_ids = await processor.submit_batch(
            files=files,
            workspace_id="ws-batch",
            uploaded_by="batch-user",
            priority=JobPriority.HIGH,
        )

        assert len(job_ids) == 3
        for i, job_id in enumerate(job_ids):
            job = processor._jobs[job_id]
            assert job.workspace_id == "ws-batch"
            assert job.uploaded_by == "batch-user"
            assert job.priority == JobPriority.HIGH


class TestBatchProcessorLifecycle:
    """Tests for BatchProcessor start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_workers(self):
        processor = BatchProcessor(max_workers=2)

        await processor.start()

        assert processor._running is True
        assert len(processor._worker_tasks) == 2

        # Cleanup
        await processor.stop(wait=False)

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        processor = BatchProcessor(max_workers=2)

        await processor.start()
        await processor.start()  # Should not create more workers

        assert len(processor._worker_tasks) == 2

        # Cleanup
        await processor.stop(wait=False)

    @pytest.mark.asyncio
    async def test_stop_cancels_workers(self):
        processor = BatchProcessor(max_workers=2)
        await processor.start()

        await processor.stop(wait=False)

        assert processor._running is False
        assert len(processor._worker_tasks) == 0


class TestBatchProcessorWaitForJob:
    """Tests for BatchProcessor.wait_for_job method."""

    @pytest.mark.asyncio
    async def test_wait_for_completed_job(self):
        processor = BatchProcessor()
        job_id = await processor.submit(b"test", "test.txt")
        processor._jobs[job_id].status = JobStatus.COMPLETED

        result = await processor.wait_for_job(job_id, timeout=1.0)

        assert result is not None
        assert result.status == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_wait_for_failed_job(self):
        processor = BatchProcessor()
        job_id = await processor.submit(b"test", "test.txt")
        processor._jobs[job_id].status = JobStatus.FAILED

        result = await processor.wait_for_job(job_id, timeout=1.0)

        assert result is not None
        assert result.status == JobStatus.FAILED

    @pytest.mark.asyncio
    async def test_wait_for_cancelled_job(self):
        processor = BatchProcessor()
        job_id = await processor.submit(b"test", "test.txt")
        processor._jobs[job_id].status = JobStatus.CANCELLED

        result = await processor.wait_for_job(job_id, timeout=1.0)

        assert result is not None
        assert result.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_wait_for_job_timeout(self):
        processor = BatchProcessor()
        job_id = await processor.submit(b"test", "test.txt")
        # Job stays QUEUED

        result = await processor.wait_for_job(job_id, timeout=0.2)

        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_nonexistent_job(self):
        processor = BatchProcessor()

        result = await processor.wait_for_job("nonexistent", timeout=0.2)

        assert result is None


class TestBatchProcessorWaitForBatch:
    """Tests for BatchProcessor.wait_for_batch method."""

    @pytest.mark.asyncio
    async def test_wait_for_batch_all_completed(self):
        processor = BatchProcessor()

        job_ids = []
        for i in range(3):
            job_id = await processor.submit(b"test", f"test{i}.txt")
            processor._jobs[job_id].status = JobStatus.COMPLETED
            # Add mock chunks with token_count
            mock_chunk = MagicMock()
            mock_chunk.token_count = 100
            processor._jobs[job_id].chunks = [mock_chunk, mock_chunk]
            job_ids.append(job_id)

        result = await processor.wait_for_batch(job_ids, timeout=1.0)

        assert result.total_jobs == 3
        assert result.completed_jobs == 3
        assert result.failed_jobs == 0
        assert result.total_chunks == 6  # 2 chunks per job
        assert result.total_tokens == 600  # 100 tokens per chunk

    @pytest.mark.asyncio
    async def test_wait_for_batch_mixed_status(self):
        processor = BatchProcessor()

        job1 = await processor.submit(b"test", "test1.txt")
        job2 = await processor.submit(b"test", "test2.txt")

        processor._jobs[job1].status = JobStatus.COMPLETED
        processor._jobs[job1].chunks = []
        processor._jobs[job2].status = JobStatus.FAILED

        result = await processor.wait_for_batch([job1, job2], timeout=1.0)

        assert result.completed_jobs == 1
        assert result.failed_jobs == 1


class TestGetBatchProcessor:
    """Tests for get_batch_processor factory."""

    @pytest.mark.asyncio
    async def test_creates_and_starts_processor(self):
        # Reset global state
        import aragora.documents.ingestion.batch_processor as module

        module._batch_processor = None

        with patch.object(BatchProcessor, "start", new_callable=AsyncMock) as mock_start:
            processor = await get_batch_processor()

            assert processor is not None
            mock_start.assert_called_once()

        # Cleanup
        module._batch_processor = None

    @pytest.mark.asyncio
    async def test_returns_same_instance(self):
        import aragora.documents.ingestion.batch_processor as module

        module._batch_processor = None

        with patch.object(BatchProcessor, "start", new_callable=AsyncMock):
            processor1 = await get_batch_processor()
            processor2 = await get_batch_processor()

            assert processor1 is processor2

        # Cleanup
        module._batch_processor = None


class TestBatchProcessorOwnership:
    """Org ownership on jobs, and running jobs without the worker tasks."""

    @pytest.mark.asyncio
    async def test_submit_records_org_and_document_id(self):
        processor = BatchProcessor()

        job_id = await processor.submit(
            b"text", "a.txt", uploaded_by="user-a", org_id="org-a", document_id="doc-a"
        )

        status = await processor.get_status(job_id)
        assert status["org_id"] == "org-a"
        assert status["uploaded_by"] == "user-a"
        assert status["document_id"] == "doc-a"

    @pytest.mark.asyncio
    async def test_submit_while_stopped_does_not_fill_the_queue(self):
        processor = BatchProcessor(max_queue_size=1)

        await processor.submit(b"one", "1.txt")
        await asyncio.wait_for(processor.submit(b"two", "2.txt"), timeout=1)

        assert processor._queue.qsize() == 0
        assert processor.get_stats()["queued_jobs"] == 2

    @pytest.mark.asyncio
    async def test_start_queues_jobs_submitted_while_stopped(self):
        processor = BatchProcessor(max_workers=1)
        job_id = await processor.submit(b"# Title\n\nSome text.", "notes.md", org_id="org-a")

        await processor.start()
        try:
            job = await processor.wait_for_job(job_id, timeout=10)
        finally:
            await processor.stop(wait=False)

        assert job is not None
        assert job.status == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_process_queued_runs_jobs_and_keeps_the_document_id(self):
        processor = BatchProcessor()
        job_id = await processor.submit(
            b"# Title\n\nSome text.", "notes.md", org_id="org-a", document_id="doc-a"
        )
        cancelled_id = await processor.submit(b"skip me", "skip.txt", org_id="org-a")
        await processor.cancel(cancelled_id)

        await processor.process_queued([job_id, cancelled_id, "missing"])

        job = await processor.get_result(job_id)
        assert job.status == JobStatus.COMPLETED
        assert job.document.id == "doc-a"
        assert (await processor.get_result(cancelled_id)).status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_process_queued_records_a_failure_on_the_job(self):
        processor = BatchProcessor()
        job_id = await processor.submit(b"x", "x.txt", org_id="org-a")

        with patch.object(processor, "_process_job", side_effect=RuntimeError("boom")):
            await processor.process_queued([job_id])

        job = await processor.get_result(job_id)
        assert job.status == JobStatus.FAILED
        assert processor.get_stats()["total_failed"] == 1
        assert processor.get_stats()["active_workers"] == 0

    @pytest.mark.asyncio
    async def test_remove_only_forgets_finished_jobs(self):
        processor = BatchProcessor()
        queued_id = await processor.submit(b"q", "q.txt")
        done_id = await processor.submit(b"d", "d.txt")
        processor._jobs[done_id].status = JobStatus.COMPLETED

        assert await processor.remove(queued_id) is False
        assert await processor.remove(done_id) is True
        assert await processor.get_result(done_id) is None
        assert await processor.remove("missing") is False

    @pytest.mark.asyncio
    async def test_stats_per_org_count_only_that_orgs_jobs(self):
        processor = BatchProcessor()
        await processor.submit(b"a1", "a1.txt", org_id="org-a")
        await processor.submit(b"a2", "a2.txt", org_id="org-a")
        b_id = await processor.submit(b"b", "b.txt", org_id="org-b")
        await processor.submit(b"legacy", "legacy.txt")
        processor._jobs[b_id].status = JobStatus.FAILED

        stats_a = processor.get_stats(org_id="org-a")
        stats_b = processor.get_stats(org_id="org-b")

        assert stats_a["queued_jobs"] == 2
        assert stats_a["total_failed"] == 0
        assert "active_workers" not in stats_a
        assert stats_b["queued_jobs"] == 0
        assert stats_b["total_failed"] == 1
        assert processor.get_stats(org_id="org-c")["queued_jobs"] == 0
