"""Tests for debate export handler (ExportOperationsMixin).

Tests covering:
- _start_batch_export: validation, job creation, format checks
- _get_batch_export_status: found/not-found cases, item summaries
- _get_batch_export_results: complete/incomplete jobs
- _list_batch_exports: listing and sorting
- _process_batch_export: batch processing with storage
- _generate_export_content: all format types
- _emit_export_event: event emission to queues
- _stream_batch_export_progress: SSE streaming
- _export_debate: single debate export, all formats, error handling
- _format_csv / _format_html / _format_txt / _format_md / _format_latex
- BatchExportJob / BatchExportItem dataclass behavior
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.debates.export import (
    BatchExportItem,
    BatchExportJob,
    BatchExportStatus,
    ExportOperationsMixin,
    _batch_export_events,
    _batch_export_jobs,
    _format_csv,
    _format_html,
    _format_latex,
    _format_md,
    _format_txt,
)
from aragora.server.handlers.utils.responses import HandlerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: HandlerResult) -> dict[str, Any]:
    """Extract JSON body from a HandlerResult."""
    if result is None:
        return {}
    raw = result.body
    if isinstance(raw, bytes):
        return json.loads(raw.decode())
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _status(result: HandlerResult) -> int:
    """Extract status code from a HandlerResult."""
    if result is None:
        return 0
    return result.status_code


def _sample_debate(debate_id: str = "debate-1", topic: str = "Test Topic") -> dict:
    """Build a minimal debate dict for testing."""
    return {
        "id": debate_id,
        "slug": f"slug-{debate_id}",
        "topic": topic,
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": "2026-01-01T01:00:00Z",
        "rounds_used": 3,
        "consensus_reached": True,
        "final_answer": "The answer is 42.",
        "synthesis": "All agents agreed.",
        "messages": [
            {
                "round": 1,
                "agent": "claude",
                "role": "speaker",
                "content": "I propose X.",
                "timestamp": "2026-01-01T00:10:00Z",
            },
            {
                "round": 2,
                "agent": "gpt-4",
                "role": "critic",
                "content": "I disagree because Y.",
                "timestamp": "2026-01-01T00:20:00Z",
            },
        ],
        "critiques": [
            {
                "round": 1,
                "critic": "gpt-4",
                "target": "claude",
                "severity": 0.5,
                "summary": "Weak reasoning",
                "timestamp": "2026-01-01T00:15:00Z",
            }
        ],
        "votes": [
            {
                "round": 3,
                "voter": "gemini",
                "choice": "claude",
                "reason": "Better argument",
                "timestamp": "2026-01-01T00:30:00Z",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Test handler class that includes the mixin
# ---------------------------------------------------------------------------


def _make_handler(storage=None, ctx_extra: dict[str, Any] | None = None):
    """Build a minimal handler with the ExportOperationsMixin."""
    from aragora.server.handlers.base import BaseHandler

    ctx: dict[str, Any] = {}
    if storage is not None:
        ctx["storage"] = storage
    if ctx_extra:
        ctx.update(ctx_extra)

    class _Handler(ExportOperationsMixin, BaseHandler):
        def __init__(self):
            self.ctx = ctx

        def get_storage(self):
            return ctx.get("storage")

    return _Handler()


ORG = "org-1"


def _owned_by(storage: MagicMock, org_id: str = ORG) -> MagicMock:
    """Make every debate id in ``storage`` a private debate of ``org_id``."""
    storage.get_access_info = MagicMock(side_effect=lambda ref: (ref, org_id, False))
    return storage


def _mock_http_handler(command: str = "GET") -> MagicMock:
    """Create a mock HTTP handler object."""
    h = MagicMock()
    h.command = command
    h.headers = {"Content-Length": "2"}
    h.rfile = MagicMock()
    h.rfile.read.return_value = b"{}"
    return h


# ---------------------------------------------------------------------------
# Fixture to clean up global state between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_batch_state():
    """Clean up global batch export state between tests."""
    _batch_export_jobs.clear()
    _batch_export_events.clear()
    yield
    _batch_export_jobs.clear()
    _batch_export_events.clear()


# ===========================================================================
# BatchExportJob / BatchExportItem dataclass tests
# ===========================================================================


class TestBatchExportItem:
    """Tests for the BatchExportItem dataclass."""

    def test_default_status_is_pending(self):
        item = BatchExportItem(debate_id="d1", format="json")
        assert item.status == BatchExportStatus.PENDING

    def test_default_result_is_none(self):
        item = BatchExportItem(debate_id="d1", format="csv")
        assert item.result is None

    def test_default_error_is_none(self):
        item = BatchExportItem(debate_id="d1", format="csv")
        assert item.error is None

    def test_default_timestamps_none(self):
        item = BatchExportItem(debate_id="d1", format="json")
        assert item.started_at is None
        assert item.completed_at is None

    def test_fields_set(self):
        item = BatchExportItem(
            debate_id="d1",
            format="md",
            status=BatchExportStatus.COMPLETED,
            result="# Title",
            error=None,
            started_at=100.0,
            completed_at=200.0,
        )
        assert item.debate_id == "d1"
        assert item.format == "md"
        assert item.status == BatchExportStatus.COMPLETED
        assert item.result == "# Title"
        assert item.started_at == 100.0
        assert item.completed_at == 200.0


class TestBatchExportJob:
    """Tests for the BatchExportJob dataclass."""

    def test_total_count(self):
        items = [BatchExportItem(debate_id=f"d{i}", format="json") for i in range(5)]
        job = BatchExportJob(job_id="j1", items=items)
        assert job.total_count == 5

    def test_total_count_empty(self):
        job = BatchExportJob(job_id="j1", items=[])
        assert job.total_count == 0

    def test_progress_percent_zero_items(self):
        job = BatchExportJob(job_id="j1", items=[])
        assert job.progress_percent == 100.0

    def test_progress_percent_partial(self):
        items = [BatchExportItem(debate_id=f"d{i}", format="json") for i in range(4)]
        job = BatchExportJob(job_id="j1", items=items, processed_count=2)
        assert job.progress_percent == 50.0

    def test_progress_percent_complete(self):
        items = [BatchExportItem(debate_id=f"d{i}", format="json") for i in range(3)]
        job = BatchExportJob(job_id="j1", items=items, processed_count=3)
        assert job.progress_percent == 100.0

    def test_default_status_pending(self):
        job = BatchExportJob(job_id="j1", items=[])
        assert job.status == BatchExportStatus.PENDING

    def test_to_dict_keys(self):
        job = BatchExportJob(job_id="j1", items=[])
        d = job.to_dict()
        assert d["job_id"] == "j1"
        assert d["status"] == "pending"
        assert d["total_count"] == 0
        assert d["processed_count"] == 0
        assert d["success_count"] == 0
        assert d["error_count"] == 0
        assert "progress_percent" in d
        assert "created_at" in d
        assert d["completed_at"] is None

    def test_to_dict_progress_rounded(self):
        items = [BatchExportItem(debate_id=f"d{i}", format="json") for i in range(3)]
        job = BatchExportJob(job_id="j1", items=items, processed_count=1)
        d = job.to_dict()
        assert d["progress_percent"] == 33.3

    def test_to_dict_completed_at(self):
        job = BatchExportJob(job_id="j1", items=[], completed_at=12345.0)
        assert job.to_dict()["completed_at"] == 12345.0


class TestBatchExportStatus:
    """Tests for the BatchExportStatus enum."""

    def test_all_values(self):
        assert BatchExportStatus.PENDING.value == "pending"
        assert BatchExportStatus.PROCESSING.value == "processing"
        assert BatchExportStatus.COMPLETED.value == "completed"
        assert BatchExportStatus.FAILED.value == "failed"
        assert BatchExportStatus.CANCELLED.value == "cancelled"

    def test_enum_count(self):
        assert len(BatchExportStatus) == 5


# ===========================================================================
# _start_batch_export tests
# ===========================================================================


class TestStartBatchExport:
    """Tests for _start_batch_export."""

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_valid_json_format(self, mock_task):
        handler = _make_handler()
        http = _mock_http_handler("POST")
        result = handler._start_batch_export(http, ["d1", "d2"], "json", org_id=ORG)
        assert _status(result) == 200
        body = _body(result)
        assert "job_id" in body
        assert body["total_count"] == 2
        assert body["status"] == "pending"
        assert "/stream" in body["stream_url"]
        assert "/status" in body["status_url"]

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_valid_csv_format(self, mock_task):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "csv", org_id=ORG)
        assert _status(result) == 200

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_valid_html_format(self, mock_task):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "html", org_id=ORG)
        assert _status(result) == 200

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_valid_txt_format(self, mock_task):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "txt", org_id=ORG)
        assert _status(result) == 200

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_valid_md_format(self, mock_task):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "md", org_id=ORG)
        assert _status(result) == 200

    def test_invalid_format(self):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "pdf", org_id=ORG)
        assert _status(result) == 400
        assert "Invalid format" in _body(result).get("error", "")

    def test_invalid_format_latex(self):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "latex", org_id=ORG)
        assert _status(result) == 400

    def test_empty_debate_ids(self):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), [], "json", org_id=ORG)
        assert _status(result) == 400
        assert "cannot be empty" in _body(result).get("error", "")

    def test_exceeds_100_debates(self):
        handler = _make_handler()
        ids = [f"d{i}" for i in range(101)]
        result = handler._start_batch_export(_mock_http_handler(), ids, "json", org_id=ORG)
        assert _status(result) == 400
        assert "100" in _body(result).get("error", "")

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_exactly_100_debates_ok(self, mock_task):
        handler = _make_handler()
        ids = [f"d{i}" for i in range(100)]
        result = handler._start_batch_export(_mock_http_handler(), ids, "json", org_id=ORG)
        assert _status(result) == 200
        assert _body(result)["total_count"] == 100

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_job_stored_in_global_dict(self, mock_task):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "json", org_id=ORG)
        job_id = _body(result)["job_id"]
        assert job_id in _batch_export_jobs

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_event_queue_created(self, mock_task):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "json", org_id=ORG)
        job_id = _body(result)["job_id"]
        assert job_id in _batch_export_events

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_job_id_format(self, mock_task):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "json", org_id=ORG)
        job_id = _body(result)["job_id"]
        assert job_id.startswith("export_")
        # 12 hex chars after prefix
        assert len(job_id) == len("export_") + 12

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_stream_url_contains_job_id(self, mock_task):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "json", org_id=ORG)
        body = _body(result)
        assert body["job_id"] in body["stream_url"]

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_status_url_contains_job_id(self, mock_task):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "json", org_id=ORG)
        body = _body(result)
        assert body["job_id"] in body["status_url"]

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_background_run_called(self, mock_task):
        handler = _make_handler()
        handler._start_batch_export(_mock_http_handler(), ["d1"], "json", org_id=ORG)
        mock_task.assert_called_once()


# ===========================================================================
# _get_batch_export_status tests
# ===========================================================================


class TestGetBatchExportStatus:
    """Tests for _get_batch_export_status."""

    def test_job_not_found(self):
        handler = _make_handler()
        result = handler._get_batch_export_status("nonexistent-id", org_id=ORG)
        assert _status(result) == 404
        assert _body(result) == {"error": "Export job not found", "code": "not_found"}

    def test_other_org_job_not_found(self):
        _batch_export_jobs["j1"] = BatchExportJob(job_id="j1", items=[], org_id="org-2")

        handler = _make_handler()
        result = handler._get_batch_export_status("j1", org_id=ORG)
        assert _status(result) == 404
        assert _body(result) == {"error": "Export job not found", "code": "not_found"}

    def test_pending_job_status(self):
        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job

        handler = _make_handler()
        result = handler._get_batch_export_status("j1", org_id=ORG)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "pending"
        assert body["total_count"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["debate_id"] == "d1"
        assert body["items"][0]["status"] == "pending"
        assert body["items"][0]["has_result"] is False

    def test_completed_item_has_result(self):
        item = BatchExportItem(
            debate_id="d1",
            format="json",
            status=BatchExportStatus.COMPLETED,
            result='{"data": "value"}',
        )
        job = BatchExportJob(
            job_id="j2", items=[item], status=BatchExportStatus.COMPLETED, org_id=ORG
        )
        _batch_export_jobs["j2"] = job

        handler = _make_handler()
        result = handler._get_batch_export_status("j2", org_id=ORG)
        body = _body(result)
        assert body["items"][0]["has_result"] is True
        assert body["items"][0]["error"] is None

    def test_failed_item_shows_error(self):
        item = BatchExportItem(
            debate_id="d1",
            format="json",
            status=BatchExportStatus.FAILED,
            error="Debate not found: d1",
        )
        job = BatchExportJob(job_id="j3", items=[item], org_id=ORG)
        _batch_export_jobs["j3"] = job

        handler = _make_handler()
        result = handler._get_batch_export_status("j3", org_id=ORG)
        body = _body(result)
        assert body["items"][0]["error"] == "Debate not found: d1"

    def test_multiple_items_summary(self):
        items = [
            BatchExportItem(
                debate_id="d1", format="json", status=BatchExportStatus.COMPLETED, result="{}"
            ),
            BatchExportItem(
                debate_id="d2", format="json", status=BatchExportStatus.FAILED, error="not found"
            ),
            BatchExportItem(debate_id="d3", format="json"),
        ]
        job = BatchExportJob(job_id="j4", items=items, org_id=ORG)
        _batch_export_jobs["j4"] = job

        handler = _make_handler()
        result = handler._get_batch_export_status("j4", org_id=ORG)
        body = _body(result)
        assert len(body["items"]) == 3
        assert body["items"][0]["status"] == "completed"
        assert body["items"][1]["status"] == "failed"
        assert body["items"][2]["status"] == "pending"


# ===========================================================================
# _get_batch_export_results tests
# ===========================================================================


class TestGetBatchExportResults:
    """Tests for _get_batch_export_results."""

    def test_job_not_found(self):
        handler = _make_handler()
        result = handler._get_batch_export_results("nonexistent", org_id=ORG)
        assert _status(result) == 404
        assert _body(result) == {"error": "Export job not found", "code": "not_found"}

    def test_job_not_complete(self):
        job = BatchExportJob(job_id="j1", items=[], status=BatchExportStatus.PROCESSING, org_id=ORG)
        _batch_export_jobs["j1"] = job

        handler = _make_handler()
        result = handler._get_batch_export_results("j1", org_id=ORG)
        assert _status(result) == 400
        assert "not complete" in _body(result).get("error", "")

    def test_job_pending_not_complete(self):
        job = BatchExportJob(job_id="j1", items=[], status=BatchExportStatus.PENDING, org_id=ORG)
        _batch_export_jobs["j1"] = job

        handler = _make_handler()
        result = handler._get_batch_export_results("j1", org_id=ORG)
        assert _status(result) == 400

    def test_job_failed_not_complete(self):
        job = BatchExportJob(job_id="j1", items=[], status=BatchExportStatus.FAILED, org_id=ORG)
        _batch_export_jobs["j1"] = job

        handler = _make_handler()
        result = handler._get_batch_export_results("j1", org_id=ORG)
        assert _status(result) == 400

    def test_completed_job_returns_results(self):
        items = [
            BatchExportItem(
                debate_id="d1",
                format="json",
                status=BatchExportStatus.COMPLETED,
                result='{"id": "d1"}',
            ),
            BatchExportItem(
                debate_id="d2",
                format="json",
                status=BatchExportStatus.FAILED,
                error="not found",
            ),
        ]
        job = BatchExportJob(
            job_id="j1", items=items, status=BatchExportStatus.COMPLETED, org_id=ORG
        )
        _batch_export_jobs["j1"] = job

        handler = _make_handler()
        result = handler._get_batch_export_results("j1", org_id=ORG)
        assert _status(result) == 200
        body = _body(result)
        assert body["job_id"] == "j1"
        assert body["status"] == "completed"
        assert len(body["results"]) == 2
        assert body["results"][0]["content"] == '{"id": "d1"}'
        assert body["results"][0]["format"] == "json"
        assert body["results"][1]["error"] == "not found"
        assert body["results"][1]["content"] is None


# ===========================================================================
# _list_batch_exports tests
# ===========================================================================


class TestListBatchExports:
    """Tests for _list_batch_exports."""

    def test_empty_list(self):
        handler = _make_handler()
        result = handler._list_batch_exports(org_id=ORG)
        assert _status(result) == 200
        body = _body(result)
        assert body["jobs"] == []
        assert body["count"] == 0

    def test_single_job(self):
        job = BatchExportJob(job_id="j1", items=[], org_id=ORG)
        _batch_export_jobs["j1"] = job

        handler = _make_handler()
        result = handler._list_batch_exports(org_id=ORG)
        body = _body(result)
        assert body["count"] == 1
        assert body["jobs"][0]["job_id"] == "j1"

    def test_sorted_newest_first(self):
        job1 = BatchExportJob(job_id="j1", items=[], created_at=100.0, org_id=ORG)
        job2 = BatchExportJob(job_id="j2", items=[], created_at=200.0, org_id=ORG)
        job3 = BatchExportJob(job_id="j3", items=[], created_at=150.0, org_id=ORG)
        _batch_export_jobs["j1"] = job1
        _batch_export_jobs["j2"] = job2
        _batch_export_jobs["j3"] = job3

        handler = _make_handler()
        result = handler._list_batch_exports(org_id=ORG)
        body = _body(result)
        job_ids = [j["job_id"] for j in body["jobs"]]
        assert job_ids == ["j2", "j3", "j1"]

    def test_limit_applied(self):
        for i in range(10):
            _batch_export_jobs[f"j{i}"] = BatchExportJob(
                job_id=f"j{i}", items=[], created_at=float(i), org_id=ORG
            )

        handler = _make_handler()
        result = handler._list_batch_exports(limit=3, org_id=ORG)
        body = _body(result)
        assert body["count"] == 3

    def test_default_limit_50(self):
        for i in range(55):
            _batch_export_jobs[f"j{i}"] = BatchExportJob(
                job_id=f"j{i}", items=[], created_at=float(i), org_id=ORG
            )

        handler = _make_handler()
        result = handler._list_batch_exports(org_id=ORG)
        body = _body(result)
        assert body["count"] == 50


# ===========================================================================
# _process_batch_export tests
# ===========================================================================


class TestProcessBatchExport:
    """Tests for _process_batch_export (async)."""

    @pytest.mark.asyncio
    async def test_no_storage_fails_job(self):
        handler = _make_handler(storage=None)
        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        assert job.status == BatchExportStatus.FAILED

    @pytest.mark.asyncio
    async def test_no_storage_emits_error_event(self):
        handler = _make_handler(storage=None)
        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        queue = asyncio.Queue()
        _batch_export_events["j1"] = queue

        await handler._process_batch_export(job)
        # Should have started event and error event
        events = []
        while not queue.empty():
            events.append(await queue.get())
        assert any(e["type"] == "error" for e in events)

    @pytest.mark.asyncio
    async def test_successful_batch_processing(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=_owned_by(storage))

        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        assert job.status == BatchExportStatus.COMPLETED
        assert job.success_count == 1
        assert job.error_count == 0
        assert items[0].status == BatchExportStatus.COMPLETED
        assert items[0].result is not None

    @pytest.mark.asyncio
    async def test_debate_not_found_in_batch(self):
        storage = MagicMock()
        storage.get_debates_batch.return_value = {"d1": None}
        handler = _make_handler(storage=_owned_by(storage))

        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        assert job.status == BatchExportStatus.COMPLETED
        assert job.error_count == 1
        assert items[0].status == BatchExportStatus.FAILED
        assert "not found" in items[0].error

    @pytest.mark.asyncio
    async def test_other_org_debate_not_exported(self):
        storage = MagicMock()
        storage.get_debates_batch.return_value = {"d1": _sample_debate("d1")}
        handler = _make_handler(storage=_owned_by(storage, "org-2"))

        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        assert job.success_count == 0
        assert items[0].status == BatchExportStatus.FAILED
        assert items[0].error == "Debate not found"
        assert items[0].result is None

    @pytest.mark.asyncio
    async def test_batch_uses_batch_query_when_available(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debates_batch.return_value = {"d1": debate}
        handler = _make_handler(storage=_owned_by(storage))

        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        storage.get_debates_batch.assert_called_once_with(["d1"])
        assert job.success_count == 1

    @pytest.mark.asyncio
    async def test_batch_fallback_on_no_batch_support(self):
        debate = _sample_debate()
        storage = MagicMock(spec=[])  # No get_debates_batch
        storage.get_debate = MagicMock(return_value=debate)
        handler = _make_handler(storage=_owned_by(storage))

        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        storage.get_debate.assert_called()
        assert job.success_count == 1

    @pytest.mark.asyncio
    async def test_batch_fallback_on_batch_query_exception(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debates_batch.side_effect = RuntimeError("batch query failed")
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=_owned_by(storage))

        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        assert job.success_count == 1

    @pytest.mark.asyncio
    async def test_batch_individual_fetch_error_skips_item(self):
        storage = MagicMock()
        storage.get_debates_batch.side_effect = RuntimeError("batch failed")
        storage.get_debate.side_effect = OSError("disk error")
        handler = _make_handler(storage=_owned_by(storage))

        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        # debate_id maps to None in debates_map, so it counts as "not found"
        assert job.error_count == 1
        assert items[0].status == BatchExportStatus.FAILED

    @pytest.mark.asyncio
    async def test_multiple_items_mixed_results(self):
        debate1 = _sample_debate("d1")
        storage = MagicMock()
        storage.get_debates_batch.return_value = {"d1": debate1, "d2": None}
        handler = _make_handler(storage=_owned_by(storage))

        items = [
            BatchExportItem(debate_id="d1", format="json"),
            BatchExportItem(debate_id="d2", format="json"),
        ]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        assert job.success_count == 1
        assert job.error_count == 1
        assert job.processed_count == 2

    @pytest.mark.asyncio
    async def test_progress_events_emitted(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=_owned_by(storage))

        items = [
            BatchExportItem(debate_id="d1", format="json"),
            BatchExportItem(debate_id="d2", format="json"),
        ]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        queue = asyncio.Queue()
        _batch_export_events["j1"] = queue

        await handler._process_batch_export(job)

        events = []
        while not queue.empty():
            events.append(await queue.get())

        event_types = [e["type"] for e in events]
        assert "started" in event_types
        assert "progress" in event_types
        assert "completed" in event_types

    @pytest.mark.asyncio
    async def test_completed_at_set(self):
        storage = MagicMock()
        storage.get_debate.return_value = _sample_debate()
        handler = _make_handler(storage=_owned_by(storage))

        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        assert job.completed_at is not None

    @pytest.mark.asyncio
    async def test_item_timestamps_set(self):
        storage = MagicMock()
        storage.get_debate.return_value = _sample_debate()
        handler = _make_handler(storage=_owned_by(storage))

        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        assert items[0].started_at is not None
        assert items[0].completed_at is not None


# ===========================================================================
# _generate_export_content tests
# ===========================================================================


class TestGenerateExportContent:
    """Tests for _generate_export_content."""

    def test_json_format(self):
        handler = _make_handler()
        debate = _sample_debate()
        content = handler._generate_export_content(debate, "json")
        parsed = json.loads(content)
        assert parsed["topic"] == "Test Topic"

    def test_csv_format(self):
        handler = _make_handler()
        debate = _sample_debate()
        content = handler._generate_export_content(debate, "csv")
        assert isinstance(content, str)
        assert "round" in content.lower() or "agent" in content.lower()

    def test_html_format(self):
        handler = _make_handler()
        debate = _sample_debate()
        content = handler._generate_export_content(debate, "html")
        assert "<html" in content.lower()
        assert "Test Topic" in content

    def test_txt_format(self):
        handler = _make_handler()
        debate = _sample_debate()
        content = handler._generate_export_content(debate, "txt")
        assert "ARAGORA" in content.upper() or "Test Topic" in content

    def test_md_format(self):
        handler = _make_handler()
        debate = _sample_debate()
        content = handler._generate_export_content(debate, "md")
        assert "# " in content or "Test Topic" in content

    def test_unknown_format_falls_back_to_json(self):
        handler = _make_handler()
        debate = _sample_debate()
        content = handler._generate_export_content(debate, "unknown")
        parsed = json.loads(content)
        assert parsed["topic"] == "Test Topic"

    def test_json_handles_non_serializable(self):
        handler = _make_handler()
        from datetime import datetime

        debate = _sample_debate()
        debate["timestamp"] = datetime(2026, 1, 1)
        # Should not raise thanks to default=str
        content = handler._generate_export_content(debate, "json")
        assert "2026" in content


# ===========================================================================
# _emit_export_event tests
# ===========================================================================


class TestEmitExportEvent:
    """Tests for _emit_export_event (async)."""

    @pytest.mark.asyncio
    async def test_emits_to_existing_queue(self):
        handler = _make_handler()
        queue = asyncio.Queue()
        _batch_export_events["j1"] = queue

        await handler._emit_export_event("j1", "progress", {"index": 1})
        event = await queue.get()
        assert event["type"] == "progress"
        assert event["index"] == 1
        assert "timestamp" in event

    @pytest.mark.asyncio
    async def test_no_queue_does_nothing(self):
        handler = _make_handler()
        # Should not raise
        await handler._emit_export_event("nonexistent", "progress", {"index": 1})

    @pytest.mark.asyncio
    async def test_event_has_timestamp(self):
        handler = _make_handler()
        queue = asyncio.Queue()
        _batch_export_events["j1"] = queue

        before = time.time()
        await handler._emit_export_event("j1", "test", {})
        event = await queue.get()
        assert event["timestamp"] >= before


# ===========================================================================
# _stream_batch_export_progress tests
# ===========================================================================


class TestStreamBatchExportProgress:
    """Tests for _stream_batch_export_progress (async generator)."""

    @pytest.mark.asyncio
    async def test_job_not_found_yields_error(self):
        handler = _make_handler()
        chunks = []
        async for chunk in handler._stream_batch_export_progress("nonexistent"):
            chunks.append(chunk)

        assert len(chunks) == 1
        data = json.loads(chunks[0].replace("data: ", "").strip())
        assert data["type"] == "error"
        assert "not found" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_initial_status_sent(self):
        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        queue = asyncio.Queue()
        _batch_export_events["j1"] = queue

        # Put a completed event so the stream ends
        await queue.put({"type": "completed", "status": "completed"})

        handler = _make_handler()
        chunks = []
        async for chunk in handler._stream_batch_export_progress("j1"):
            chunks.append(chunk)

        # First chunk is the connected event
        connected_data = json.loads(chunks[0].replace("data: ", "").strip())
        assert connected_data["type"] == "connected"
        assert connected_data["job_id"] == "j1"

    @pytest.mark.asyncio
    async def test_stream_ends_on_completed_event(self):
        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        queue = asyncio.Queue()
        _batch_export_events["j1"] = queue

        await queue.put({"type": "completed"})

        handler = _make_handler()
        chunks = []
        async for chunk in handler._stream_batch_export_progress("j1"):
            chunks.append(chunk)

        # Should have connected + completed = 2 chunks
        assert len(chunks) == 2

    @pytest.mark.asyncio
    async def test_stream_ends_on_failed_event(self):
        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        queue = asyncio.Queue()
        _batch_export_events["j1"] = queue

        await queue.put({"type": "failed"})

        handler = _make_handler()
        chunks = []
        async for chunk in handler._stream_batch_export_progress("j1"):
            chunks.append(chunk)

        assert len(chunks) == 2

    @pytest.mark.asyncio
    async def test_stream_ends_on_cancelled_event(self):
        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        queue = asyncio.Queue()
        _batch_export_events["j1"] = queue

        await queue.put({"type": "cancelled"})

        handler = _make_handler()
        chunks = []
        async for chunk in handler._stream_batch_export_progress("j1"):
            chunks.append(chunk)

        assert len(chunks) == 2

    @pytest.mark.asyncio
    async def test_creates_queue_if_missing(self):
        items = [BatchExportItem(debate_id="d1", format="json")]
        job = BatchExportJob(
            job_id="j1", items=items, status=BatchExportStatus.COMPLETED, org_id=ORG
        )
        _batch_export_jobs["j1"] = job
        # No queue created intentionally

        handler = _make_handler()
        gen = handler._stream_batch_export_progress("j1")

        # First chunk triggers queue creation
        first = await gen.__anext__()
        assert "j1" in _batch_export_events
        assert "connected" in first

        # Put a terminal event so the generator can finish
        await _batch_export_events["j1"].put({"type": "completed"})

        chunks = [first]
        async for chunk in gen:
            chunks.append(chunk)
            if len(chunks) > 5:
                break  # Safety exit

        assert len(chunks) >= 2


# ===========================================================================
# _export_debate tests (single export endpoint)
# ===========================================================================


class TestExportDebate:
    """Tests for _export_debate (single debate export)."""

    def test_no_storage_returns_503(self):
        handler = _make_handler(storage=None)
        result = handler._export_debate(_mock_http_handler(), "d1", "json", "summary")
        assert _status(result) == 503

    def test_invalid_format_returns_400(self):
        storage = MagicMock()
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "pdf", "summary")
        assert _status(result) == 400
        assert "Invalid format" in _body(result).get("error", "")

    def test_invalid_format_latex_string(self):
        """latex is not in valid_formats for the batch endpoint check."""
        storage = MagicMock()
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "xml", "summary")
        assert _status(result) == 400

    def test_debate_not_found_returns_404(self):
        storage = MagicMock()
        storage.get_debate.return_value = None
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "json", "summary")
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_record_not_found_error_returns_404(self):
        from aragora.exceptions import RecordNotFoundError

        storage = MagicMock()
        storage.get_debate.side_effect = RecordNotFoundError("debates", "d1")
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "json", "summary")
        assert _status(result) == 404

    def test_database_error_returns_500(self):
        from aragora.exceptions import DatabaseError

        storage = MagicMock()
        storage.get_debate.side_effect = DatabaseError("connection lost")
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "json", "summary")
        assert _status(result) == 500
        assert "Database error" in _body(result).get("error", "")

    def test_storage_error_returns_500(self):
        from aragora.exceptions import StorageError

        storage = MagicMock()
        storage.get_debate.side_effect = StorageError("disk error")
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "json", "summary")
        assert _status(result) == 500

    def test_value_error_returns_400(self):
        storage = MagicMock()
        storage.get_debate.side_effect = ValueError("bad data")
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "json", "summary")
        assert _status(result) == 400
        assert "Invalid export format" in _body(result).get("error", "")

    def test_json_export(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "json", "summary")
        assert _status(result) == 200
        body = _body(result)
        assert body["topic"] == "Test Topic"

    def test_csv_export_summary(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "csv", "summary")
        assert _status(result) == 200
        assert result.content_type == "text/csv; charset=utf-8"
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "field" in content.lower()

    def test_csv_export_messages(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "csv", "messages")
        assert _status(result) == 200
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "round" in content.lower()

    def test_html_export(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "html", "summary")
        assert _status(result) == 200
        assert "text/html" in result.content_type
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "<html" in content.lower()

    def test_txt_export(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "txt", "summary")
        assert _status(result) == 200
        assert "text/plain" in result.content_type

    def test_md_export(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "md", "summary")
        assert _status(result) == 200
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "#" in content

    def test_csv_export_has_content_disposition(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "csv", "summary")
        assert "Content-Disposition" in (result.headers or {})
        assert "attachment" in result.headers["Content-Disposition"]

    def test_html_export_has_content_disposition(self):
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "html", "summary")
        assert "Content-Disposition" in (result.headers or {})


# ===========================================================================
# Standalone format function tests
# ===========================================================================


class TestFormatCsv:
    """Tests for _format_csv standalone function."""

    def test_summary_table(self):
        debate = _sample_debate()
        result = _format_csv(debate, "summary")
        assert result.status_code == 200
        assert result.content_type == "text/csv; charset=utf-8"
        assert "Content-Disposition" in result.headers

    def test_messages_table(self):
        debate = _sample_debate()
        result = _format_csv(debate, "messages")
        assert result.status_code == 200
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "round" in content.lower()

    def test_critiques_table(self):
        debate = _sample_debate()
        result = _format_csv(debate, "critiques")
        assert result.status_code == 200

    def test_votes_table(self):
        debate = _sample_debate()
        result = _format_csv(debate, "votes")
        assert result.status_code == 200

    def test_invalid_table_defaults_to_summary(self):
        debate = _sample_debate()
        result = _format_csv(debate, "invalid")
        assert result.status_code == 200
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "field" in content.lower()

    def test_filename_contains_debate_slug(self):
        debate = _sample_debate()
        result = _format_csv(debate, "summary")
        assert "slug-debate-1" in result.headers.get("Content-Disposition", "")


class TestFormatHtml:
    """Tests for _format_html standalone function."""

    def test_returns_html_content(self):
        debate = _sample_debate()
        result = _format_html(debate)
        assert result.status_code == 200
        assert "text/html" in result.content_type
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "<!DOCTYPE html>" in content

    def test_contains_topic(self):
        debate = _sample_debate(topic="Custom Topic")
        result = _format_html(debate)
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "Custom Topic" in content

    def test_has_content_disposition(self):
        debate = _sample_debate()
        result = _format_html(debate)
        assert "Content-Disposition" in result.headers


class TestFormatTxt:
    """Tests for _format_txt standalone function."""

    def test_returns_plain_text(self):
        debate = _sample_debate()
        result = _format_txt(debate)
        assert result.status_code == 200
        assert "text/plain" in result.content_type

    def test_contains_debate_content(self):
        debate = _sample_debate()
        result = _format_txt(debate)
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "Test Topic" in content

    def test_has_content_disposition(self):
        debate = _sample_debate()
        result = _format_txt(debate)
        assert "Content-Disposition" in result.headers


class TestFormatMd:
    """Tests for _format_md standalone function."""

    def test_returns_markdown(self):
        debate = _sample_debate()
        result = _format_md(debate)
        assert result.status_code == 200

    def test_contains_heading(self):
        debate = _sample_debate()
        result = _format_md(debate)
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "#" in content
        assert "Test Topic" in content

    def test_has_content_disposition(self):
        debate = _sample_debate()
        result = _format_md(debate)
        assert "Content-Disposition" in result.headers


class TestFormatLatex:
    """Tests for _format_latex standalone function."""

    def test_returns_latex(self):
        debate = _sample_debate()
        result = _format_latex(debate)
        assert result.status_code == 200

    def test_contains_latex_markers(self):
        debate = _sample_debate()
        result = _format_latex(debate)
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "\\begin{document}" in content or "documentclass" in content

    def test_has_content_disposition(self):
        debate = _sample_debate()
        result = _format_latex(debate)
        assert "Content-Disposition" in result.headers

    def test_content_type_set(self):
        debate = _sample_debate()
        result = _format_latex(debate)
        assert result.content_type is not None


# ===========================================================================
# Edge case and integration tests
# ===========================================================================


class TestEdgeCases:
    """Edge case and integration tests."""

    def test_empty_dict_debate_returns_404(self):
        """An empty dict is falsy-like but actually truthy in Python.
        However, 'not {}' is True, so the handler returns 404."""
        storage = MagicMock()
        storage.get_debate.return_value = {}
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "json", "summary")
        # Empty dict {} evaluates to falsy: `not {}` is True
        assert _status(result) == 404

    def test_minimal_debate_json_export(self):
        storage = MagicMock()
        storage.get_debate.return_value = {"id": "d1", "topic": "T"}
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "json", "summary")
        assert _status(result) == 200

    def test_empty_debate_csv_export(self):
        storage = MagicMock()
        storage.get_debate.return_value = {"id": "d1"}
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "csv", "summary")
        assert _status(result) == 200

    def test_empty_debate_html_export(self):
        storage = MagicMock()
        storage.get_debate.return_value = {"id": "d1"}
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "html", "summary")
        assert _status(result) == 200

    def test_empty_debate_txt_export(self):
        storage = MagicMock()
        storage.get_debate.return_value = {"id": "d1"}
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "txt", "summary")
        assert _status(result) == 200

    def test_empty_debate_md_export(self):
        storage = MagicMock()
        storage.get_debate.return_value = {"id": "d1"}
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "md", "summary")
        assert _status(result) == 200

    def test_debate_with_special_chars_in_topic(self):
        debate = _sample_debate(topic='<script>alert("xss")</script>')
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)
        result = handler._export_debate(_mock_http_handler(), "d1", "html", "summary")
        assert _status(result) == 200
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        # HTML escaping should prevent raw script tags
        assert "<script>" not in content

    def test_generate_export_content_empty_debate(self):
        handler = _make_handler()
        content = handler._generate_export_content({}, "json")
        parsed = json.loads(content)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_batch_export_with_export_error(self):
        """Test that export errors on individual items are caught."""
        debate = _sample_debate()
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=_owned_by(storage))

        # Patch _generate_export_content to raise on second call
        call_count = [0]
        original = handler._generate_export_content

        def side_effect(d, f):
            call_count[0] += 1
            if call_count[0] == 2:
                raise ValueError("format error")
            return original(d, f)

        handler._generate_export_content = side_effect

        items = [
            BatchExportItem(debate_id="d1", format="json"),
            BatchExportItem(debate_id="d2", format="json"),
        ]
        job = BatchExportJob(job_id="j1", items=items, org_id=ORG)
        _batch_export_jobs["j1"] = job
        _batch_export_events["j1"] = asyncio.Queue()

        await handler._process_batch_export(job)
        assert job.success_count == 1
        assert job.error_count == 1
        assert items[0].status == BatchExportStatus.COMPLETED
        assert items[1].status == BatchExportStatus.FAILED

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_single_debate_id_batch(self, mock_task):
        handler = _make_handler()
        result = handler._start_batch_export(_mock_http_handler(), ["d1"], "json", org_id=ORG)
        assert _status(result) == 200
        assert _body(result)["total_count"] == 1

    @patch(
        "aragora.server.handlers.debates.export._run_in_background",
        side_effect=lambda coro: coro.close(),
    )
    def test_all_valid_formats_accepted_by_batch(self, mock_task):
        handler = _make_handler()
        for fmt in ("json", "csv", "html", "txt", "md"):
            result = handler._start_batch_export(_mock_http_handler(), ["d1"], fmt, org_id=ORG)
            assert _status(result) == 200, f"Format {fmt} should be accepted"

    def test_csv_export_critiques_table(self):
        debate = _sample_debate()
        result = _format_csv(debate, "critiques")
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "critic" in content.lower()

    def test_csv_export_votes_table(self):
        debate = _sample_debate()
        result = _format_csv(debate, "votes")
        content = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
        assert "voter" in content.lower()
