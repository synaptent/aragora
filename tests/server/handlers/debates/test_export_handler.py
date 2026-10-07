"""
Tests for debate export handler operations (export.py).

Tests cover:
- Batch export job creation and validation
- Export format generation (JSON, CSV, HTML, MD, TXT)
- Progress tracking and SSE events
- Job status retrieval
- Error handling for missing debates
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.debates.export import (
    BatchExportItem,
    BatchExportJob,
    BatchExportStatus,
    ExportOperationsMixin,
    _batch_export_jobs,
    _batch_export_events,
)


ORG = "org-1"

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_debate():
    """Sample debate data for testing exports."""
    return {
        "id": "debate-123",
        "slug": "test-debate",
        "topic": "Should AI be regulated?",
        "started_at": "2024-01-15T10:00:00Z",
        "ended_at": "2024-01-15T11:30:00Z",
        "rounds_used": 3,
        "consensus_reached": True,
        "confidence": 0.85,
        "final_answer": "Yes, with appropriate safeguards.",
        "synthesis": "Consensus emerged around proportional regulation.",
        "messages": [
            {
                "round": 1,
                "agent": "Claude",
                "role": "speaker",
                "content": "AI regulation is necessary.",
                "timestamp": "2024-01-15T10:05:00Z",
            },
            {
                "round": 1,
                "agent": "GPT-4",
                "role": "speaker",
                "content": "Balance innovation with safety.",
                "timestamp": "2024-01-15T10:10:00Z",
            },
        ],
        "critiques": [],
        "votes": [],
    }


@pytest.fixture
def mock_storage(sample_debate):
    """Mock debate storage."""
    storage = MagicMock()
    storage.get_debate.return_value = sample_debate

    # Mock get_debates_batch to return a dict mapping debate_id -> debate data
    def mock_get_debates_batch(debate_ids):
        result = {}
        for did in debate_ids:
            # Use get_debate's return value for consistency
            result[did] = storage.get_debate.return_value
        return result

    storage.get_debates_batch = mock_get_debates_batch
    # Batch exports only include debates owned by the job's org.
    storage.get_access_info.side_effect = lambda ref: (ref, ORG, False)
    return storage


@pytest.fixture
def export_handler(mock_storage):
    """Create export handler mixin instance."""

    class MockDebatesHandler(ExportOperationsMixin):
        def __init__(self, storage):
            self.ctx = {}
            self._storage = storage

        def get_storage(self):
            return self._storage

        def _generate_export_content(self, debate, format):
            if format == "json":
                return json.dumps(debate)
            elif format == "csv":
                return f"id,topic\n{debate['id']},{debate['topic']}"
            elif format == "md":
                return f"# {debate['topic']}\n\n{debate.get('final_answer', '')}"
            elif format == "html":
                return f"<h1>{debate['topic']}</h1>"
            elif format == "txt":
                return f"Topic: {debate['topic']}"
            return str(debate)

        async def _emit_export_event(self, job_id, event_type, data):
            if job_id in _batch_export_events:
                await _batch_export_events[job_id].put({"type": event_type, "data": data})

    return MockDebatesHandler(mock_storage)


@pytest.fixture
def mock_http_handler():
    """Mock HTTP request handler."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    return handler


@pytest.fixture(autouse=True)
def cleanup_jobs():
    """Clean up batch export jobs between tests."""
    _batch_export_jobs.clear()
    _batch_export_events.clear()
    yield
    _batch_export_jobs.clear()
    _batch_export_events.clear()


# =============================================================================
# Test BatchExportItem
# =============================================================================


class TestBatchExportItem:
    """Tests for BatchExportItem dataclass."""

    def test_create_item(self):
        """Test creating a batch export item."""
        item = BatchExportItem(debate_id="debate-1", format="json")
        assert item.debate_id == "debate-1"
        assert item.format == "json"
        assert item.status == BatchExportStatus.PENDING
        assert item.result is None
        assert item.error is None

    def test_item_with_status(self):
        """Test item with different statuses."""
        item = BatchExportItem(
            debate_id="debate-2",
            format="csv",
            status=BatchExportStatus.COMPLETED,
            result="data",
        )
        assert item.status == BatchExportStatus.COMPLETED
        assert item.result == "data"

    def test_item_with_error(self):
        """Test item with error state."""
        item = BatchExportItem(
            debate_id="debate-3",
            format="md",
            status=BatchExportStatus.FAILED,
            error="Debate not found",
        )
        assert item.status == BatchExportStatus.FAILED
        assert item.error == "Debate not found"


# =============================================================================
# Test BatchExportJob
# =============================================================================


class TestBatchExportJob:
    """Tests for BatchExportJob dataclass."""

    def test_create_job(self):
        """Test creating a batch export job."""
        items = [BatchExportItem(debate_id=f"debate-{i}", format="json") for i in range(3)]
        job = BatchExportJob(job_id="export_abc123", items=items)

        assert job.job_id == "export_abc123"
        assert len(job.items) == 3
        assert job.status == BatchExportStatus.PENDING
        assert job.total_count == 3
        assert job.processed_count == 0

    def test_progress_percent_empty(self):
        """Test progress percent with no items."""
        job = BatchExportJob(job_id="empty", items=[])
        assert job.progress_percent == 100.0

    def test_progress_percent_partial(self):
        """Test progress percent with partial completion."""
        items = [BatchExportItem(debate_id=f"d-{i}", format="json") for i in range(4)]
        job = BatchExportJob(job_id="partial", items=items, processed_count=2)
        assert job.progress_percent == 50.0

    def test_progress_percent_complete(self):
        """Test progress percent when fully processed."""
        items = [BatchExportItem(debate_id=f"d-{i}", format="json") for i in range(5)]
        job = BatchExportJob(job_id="complete", items=items, processed_count=5)
        assert job.progress_percent == 100.0

    def test_to_dict(self):
        """Test job serialization to dictionary."""
        items = [BatchExportItem(debate_id=f"d-{i}", format="json") for i in range(2)]
        job = BatchExportJob(
            job_id="test_job",
            items=items,
            processed_count=1,
            success_count=1,
            error_count=0,
        )
        result = job.to_dict()

        assert result["job_id"] == "test_job"
        assert result["status"] == "pending"
        assert result["total_count"] == 2
        assert result["processed_count"] == 1
        assert result["success_count"] == 1
        assert result["progress_percent"] == 50.0


# =============================================================================
# Test _start_batch_export
# =============================================================================


class TestStartBatchExport:
    """Tests for _start_batch_export method."""

    def test_start_export_valid(self, export_handler, mock_http_handler):
        """Test starting a valid batch export."""
        with patch(
            "aragora.server.handlers.debates.export._run_in_background",
            side_effect=lambda coro: coro.close(),
        ):
            result = export_handler._start_batch_export(
                mock_http_handler,
                debate_ids=["debate-1", "debate-2"],
                format="json",
                org_id=ORG,
            )

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "job_id" in body
        assert body["total_count"] == 2
        assert body["status"] == "pending"
        assert "/stream" in body["stream_url"]
        assert "/status" in body["status_url"]

    def test_start_export_invalid_format(self, export_handler, mock_http_handler):
        """Test starting export with invalid format."""
        result = export_handler._start_batch_export(
            mock_http_handler,
            debate_ids=["debate-1"],
            format="invalid",
            org_id=ORG,
        )

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "error" in body
        assert "Invalid format" in body["error"]

    def test_start_export_empty_ids(self, export_handler, mock_http_handler):
        """Test starting export with empty debate_ids."""
        result = export_handler._start_batch_export(
            mock_http_handler,
            debate_ids=[],
            format="json",
            org_id=ORG,
        )

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "error" in body
        assert "cannot be empty" in body["error"]

    def test_start_export_too_many_ids(self, export_handler, mock_http_handler):
        """Test starting export with too many debate_ids."""
        result = export_handler._start_batch_export(
            mock_http_handler,
            debate_ids=[f"debate-{i}" for i in range(101)],
            format="json",
            org_id=ORG,
        )

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "error" in body
        assert "100" in body["error"]

    def test_start_export_all_valid_formats(self, export_handler, mock_http_handler):
        """Test starting export with all valid formats."""
        valid_formats = ["json", "csv", "html", "txt", "md"]

        for fmt in valid_formats:
            with patch(
                "aragora.server.handlers.debates.export._run_in_background",
                side_effect=lambda coro: coro.close(),
            ):
                result = export_handler._start_batch_export(
                    mock_http_handler,
                    debate_ids=["debate-1"],
                    format=fmt,
                    org_id=ORG,
                )
            assert result.status_code == 200, f"Format {fmt} should be valid"


# =============================================================================
# Test _process_batch_export
# =============================================================================


class TestProcessBatchExport:
    """Tests for _process_batch_export async method."""

    @pytest.mark.asyncio
    async def test_process_export_success(self, export_handler, sample_debate):
        """Test successful batch export processing."""
        items = [BatchExportItem(debate_id="debate-123", format="json")]
        job = BatchExportJob(job_id="test_job", items=items, org_id=ORG)
        _batch_export_jobs["test_job"] = job
        _batch_export_events["test_job"] = asyncio.Queue()

        await export_handler._process_batch_export(job)

        assert job.status == BatchExportStatus.COMPLETED
        assert job.processed_count == 1
        assert job.success_count == 1
        assert job.error_count == 0
        assert items[0].status == BatchExportStatus.COMPLETED
        assert items[0].result is not None

    @pytest.mark.asyncio
    async def test_process_export_debate_not_found(self, export_handler, mock_storage):
        """Test processing when debate not found."""
        # Override get_debates_batch to return None for missing debate
        mock_storage.get_debates_batch = lambda ids: dict.fromkeys(ids)

        items = [BatchExportItem(debate_id="missing-debate", format="json")]
        job = BatchExportJob(job_id="not_found_job", items=items, org_id=ORG)
        _batch_export_jobs["not_found_job"] = job
        _batch_export_events["not_found_job"] = asyncio.Queue()

        await export_handler._process_batch_export(job)

        assert job.status == BatchExportStatus.COMPLETED
        assert job.error_count == 1
        assert items[0].status == BatchExportStatus.FAILED
        assert "not found" in items[0].error.lower()

    @pytest.mark.asyncio
    async def test_process_export_no_storage(self, export_handler):
        """Test processing when storage not available."""
        export_handler._storage = None

        items = [BatchExportItem(debate_id="debate-1", format="json")]
        job = BatchExportJob(job_id="no_storage_job", items=items, org_id=ORG)
        _batch_export_jobs["no_storage_job"] = job
        _batch_export_events["no_storage_job"] = asyncio.Queue()

        await export_handler._process_batch_export(job)

        assert job.status == BatchExportStatus.FAILED

    @pytest.mark.asyncio
    async def test_process_export_multiple_items(self, export_handler, mock_storage):
        """Test processing multiple items."""
        # First debate found, second not found, third found
        debates_data = {
            "d1": {"id": "d1", "topic": "Test 1"},
            "d2": None,
            "d3": {"id": "d3", "topic": "Test 3"},
        }
        mock_storage.get_debates_batch = lambda ids: {did: debates_data.get(did) for did in ids}

        items = [
            BatchExportItem(debate_id="d1", format="json"),
            BatchExportItem(debate_id="d2", format="json"),
            BatchExportItem(debate_id="d3", format="json"),
        ]
        job = BatchExportJob(job_id="multi_job", items=items, org_id=ORG)
        _batch_export_jobs["multi_job"] = job
        _batch_export_events["multi_job"] = asyncio.Queue()

        await export_handler._process_batch_export(job)

        assert job.processed_count == 3
        assert job.success_count == 2
        assert job.error_count == 1

    @pytest.mark.asyncio
    async def test_process_export_emits_events(self, export_handler, sample_debate):
        """Test that processing emits SSE events."""
        items = [BatchExportItem(debate_id="debate-123", format="json")]
        job = BatchExportJob(job_id="events_job", items=items, org_id=ORG)
        _batch_export_jobs["events_job"] = job
        event_queue = asyncio.Queue()
        _batch_export_events["events_job"] = event_queue

        await export_handler._process_batch_export(job)

        # Should have emitted: started, progress, completed
        events = []
        while not event_queue.empty():
            events.append(await event_queue.get())

        event_types = [e["type"] for e in events]
        assert "started" in event_types
        assert "progress" in event_types
        assert "completed" in event_types

    @pytest.mark.asyncio
    async def test_process_export_uses_batch_fetch(self, export_handler, mock_storage):
        """Test that batch export uses batch fetching for efficiency."""
        # Track calls to verify batch fetch is used
        batch_called = []
        individual_called = []

        def mock_batch(ids):
            batch_called.append(ids)
            return {did: {"id": did, "topic": f"Topic {did}"} for did in ids}

        def mock_individual(did):
            individual_called.append(did)
            return {"id": did, "topic": f"Topic {did}"}

        mock_storage.get_debates_batch = mock_batch
        mock_storage.get_debate = mock_individual

        items = [
            BatchExportItem(debate_id="d1", format="json"),
            BatchExportItem(debate_id="d2", format="json"),
            BatchExportItem(debate_id="d3", format="json"),
        ]
        job = BatchExportJob(job_id="batch_test", items=items, org_id=ORG)
        _batch_export_jobs["batch_test"] = job
        _batch_export_events["batch_test"] = asyncio.Queue()

        await export_handler._process_batch_export(job)

        # Batch should be called once with all IDs
        assert len(batch_called) == 1
        assert set(batch_called[0]) == {"d1", "d2", "d3"}
        # Individual get_debate should NOT be called
        assert len(individual_called) == 0
        # All items should be processed successfully
        assert job.success_count == 3

    @pytest.mark.asyncio
    async def test_process_export_fallback_without_batch(self, export_handler, mock_storage):
        """Test fallback to individual queries when batch not available."""
        # Remove batch method to test fallback
        del mock_storage.get_debates_batch

        individual_called = []

        def mock_individual(did):
            individual_called.append(did)
            return {"id": did, "topic": f"Topic {did}"}

        mock_storage.get_debate = mock_individual

        items = [
            BatchExportItem(debate_id="d1", format="json"),
            BatchExportItem(debate_id="d2", format="json"),
        ]
        job = BatchExportJob(job_id="fallback_test", items=items, org_id=ORG)
        _batch_export_jobs["fallback_test"] = job
        _batch_export_events["fallback_test"] = asyncio.Queue()

        await export_handler._process_batch_export(job)

        # Individual get_debate should be called for each item
        assert set(individual_called) == {"d1", "d2"}
        assert job.success_count == 2


# =============================================================================
# Test _generate_export_content
# =============================================================================


class TestGenerateExportContent:
    """Tests for export content generation."""

    def test_generate_json_content(self, export_handler, sample_debate):
        """Test JSON format generation."""
        content = export_handler._generate_export_content(sample_debate, "json")
        parsed = json.loads(content)
        assert parsed["id"] == "debate-123"
        assert parsed["topic"] == "Should AI be regulated?"

    def test_generate_csv_content(self, export_handler, sample_debate):
        """Test CSV format generation."""
        content = export_handler._generate_export_content(sample_debate, "csv")
        assert "id,topic" in content
        assert "debate-123" in content

    def test_generate_md_content(self, export_handler, sample_debate):
        """Test Markdown format generation."""
        content = export_handler._generate_export_content(sample_debate, "md")
        assert "#" in content  # Markdown header
        assert sample_debate["topic"] in content

    def test_generate_html_content(self, export_handler, sample_debate):
        """Test HTML format generation."""
        content = export_handler._generate_export_content(sample_debate, "html")
        assert "<h1>" in content
        assert sample_debate["topic"] in content

    def test_generate_txt_content(self, export_handler, sample_debate):
        """Test plain text format generation."""
        content = export_handler._generate_export_content(sample_debate, "txt")
        assert "Topic:" in content
        assert sample_debate["topic"] in content


# =============================================================================
# Test BatchExportStatus enum
# =============================================================================


class TestBatchExportStatus:
    """Tests for BatchExportStatus enum."""

    def test_all_statuses_exist(self):
        """Test all expected statuses are defined."""
        expected = ["PENDING", "PROCESSING", "COMPLETED", "FAILED", "CANCELLED"]
        for status in expected:
            assert hasattr(BatchExportStatus, status)

    def test_status_values(self):
        """Test status string values."""
        assert BatchExportStatus.PENDING.value == "pending"
        assert BatchExportStatus.PROCESSING.value == "processing"
        assert BatchExportStatus.COMPLETED.value == "completed"
        assert BatchExportStatus.FAILED.value == "failed"
        assert BatchExportStatus.CANCELLED.value == "cancelled"
