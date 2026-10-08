"""
Export format operations handler mixin.

Extracted from handler.py for modularity. Provides export formatting methods
for debates in various formats (CSV, HTML, TXT, MD, LaTeX).

Also provides batch export with SSE progress streaming.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol
from collections.abc import AsyncGenerator, Coroutine

from aragora.rbac.decorators import require_permission
from aragora.tenancy.debate_access import find_debate_access
from aragora.tenancy.record_scope import record_not_found
from ..openapi_decorator import api_endpoint

from ..base import (
    HandlerResult,
    error_response,
    json_response,
    require_storage,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# =============================================================================
# Batch Export Types
# =============================================================================


class BatchExportStatus(Enum):
    """Status of a batch export job."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BatchExportItem:
    """Single item in a batch export."""

    debate_id: str
    format: str
    status: BatchExportStatus = BatchExportStatus.PENDING
    result: str | None = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None


@dataclass
class BatchExportJob:
    """Batch export job tracking."""

    job_id: str
    items: list[BatchExportItem]
    # The org that started the job; only it sees the job, and only its debates
    # are exported.
    org_id: str | None = None
    status: BatchExportStatus = BatchExportStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    processed_count: int = 0
    success_count: int = 0
    error_count: int = 0

    @property
    def total_count(self) -> int:
        return len(self.items)

    @property
    def progress_percent(self) -> float:
        if self.total_count == 0:
            return 100.0
        return (self.processed_count / self.total_count) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "total_count": self.total_count,
            "processed_count": self.processed_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "progress_percent": round(self.progress_percent, 1),
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


# In-memory job storage (production would use Redis)
_batch_export_jobs: dict[str, BatchExportJob] = {}
_batch_export_events: dict[str, asyncio.Queue] = {}

_EXPORT_NOT_FOUND = "Debate not found"
_export_tasks: set[asyncio.Task[None]] = set()


def _run_in_background(coro: Coroutine[Any, Any, None]) -> None:
    """Run an export job without blocking the request.

    The legacy server calls handlers on threads with no running event loop,
    where ``asyncio.create_task`` raises; such jobs get their own thread.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        threading.Thread(
            target=asyncio.run, args=(coro,), name="debate-batch-export", daemon=True
        ).start()
        return
    task = loop.create_task(coro)
    _export_tasks.add(task)
    task.add_done_callback(_export_tasks.discard)


def _job_visible(job: BatchExportJob | None, org_id: str | None) -> bool:
    return job is not None and bool(job.org_id) and job.org_id == org_id


class _DebatesHandlerProtocol(Protocol):
    """Protocol defining the interface expected by ExportOperationsMixin.

    This protocol enables proper type checking for mixin classes that
    expect to be mixed into a class providing these methods/attributes.
    """

    ctx: dict[str, Any]

    def get_storage(self) -> Any:
        """Get debate storage instance (``@require_storage`` routes never see None)."""
        ...

    def _process_batch_export(self, job: BatchExportJob) -> Any:
        """Process batch export items and emit progress events."""
        ...

    def _emit_export_event(self, job_id: str, event_type: str, data: dict[str, Any]) -> Any:
        """Emit an event to all connected SSE clients."""
        ...

    def _generate_export_content(self, debate: dict[str, Any], format: str) -> str:
        """Generate export content for a debate."""
        ...


class ExportOperationsMixin:
    """Mixin providing export formatting operations for DebatesHandler."""

    @api_endpoint(
        method="POST",
        path="/api/v1/debates/export/batch",
        summary="Start batch export",
        description="Start a batch export job for multiple debates. Returns job ID for progress tracking.",
        tags=["Debates", "Export"],
        responses={
            "200": {"description": "Batch export job started"},
            "400": {"description": "Invalid format or empty debate_ids"},
        },
    )
    def _start_batch_export(
        self: _DebatesHandlerProtocol,
        handler: Any,
        debate_ids: list[str],
        format: str,
        *,
        org_id: str,
    ) -> HandlerResult:
        """
        Start a batch export job owned by ``org_id``.

        Only ``org_id``'s debates are exported; any other id (another org's,
        one with no org, or a missing one) is reported as not found.

        POST body:
        {
            "debate_ids": ["id1", "id2", ...],
            "format": "json" | "csv" | "md" | "html" | "txt"
        }

        Returns:
        {
            "job_id": "export_abc123",
            "total_count": 10,
            "status": "pending",
            "stream_url": "/api/v1/debates/export/batch/export_abc123/stream"
        }
        """
        valid_formats = {"json", "csv", "html", "txt", "md"}
        if format not in valid_formats:
            return error_response(f"Invalid format: {format}. Valid: {valid_formats}", 400)

        if not debate_ids:
            return error_response("debate_ids is required and cannot be empty", 400)

        if len(debate_ids) > 100:
            return error_response("Batch cannot exceed 100 debates", 400)

        # Create job
        job_id = f"export_{uuid.uuid4().hex[:12]}"
        items = [BatchExportItem(debate_id=did, format=format) for did in debate_ids]
        job = BatchExportJob(job_id=job_id, items=items, org_id=org_id)
        _batch_export_jobs[job_id] = job

        # Create event queue for SSE streaming
        _batch_export_events[job_id] = asyncio.Queue()

        _run_in_background(self._process_batch_export(job))

        logger.info("Batch export %s started with %s items", job_id, len(items))

        return json_response(
            {
                "job_id": job_id,
                "total_count": len(items),
                "status": job.status.value,
                "stream_url": f"/api/v1/debates/export/batch/{job_id}/stream",
                "status_url": f"/api/v1/debates/export/batch/{job_id}/status",
            }
        )

    async def _process_batch_export(self: _DebatesHandlerProtocol, job: BatchExportJob) -> None:
        """Process batch export items and emit progress events."""
        if not (job.org_id or "").strip():
            # A job with no tenant could only export unowned debates; refuse it
            # before any storage read rather than guess an owner.
            job.status = BatchExportStatus.FAILED
            job.completed_at = time.time()
            logger.warning("Refusing batch export job %s: no org recorded", job.job_id)
            await self._emit_export_event(job.job_id, "error", {"message": "Export not permitted"})
            return

        job.status = BatchExportStatus.PROCESSING
        await self._emit_export_event(job.job_id, "started", job.to_dict())

        storage = self.get_storage()
        if not storage:
            job.status = BatchExportStatus.FAILED
            await self._emit_export_event(
                job.job_id,
                "error",
                {
                    "message": "Storage not available",
                },
            )
            return

        # Only the job's org's debates are exported. Another org's debate, one
        # with no recorded org and a missing id all get the same error.
        owned: dict[str, str] = {}
        for item in job.items:
            access = find_debate_access(storage, item.debate_id)
            if access is not None and job.org_id and access.org_id == job.org_id:
                owned[item.debate_id] = access.debate_id

        # Pre-fetch all debates in a single batch query to avoid N+1 pattern
        debate_ids = sorted(set(owned.values()))
        debates_map: dict[str, dict | None] = {}
        try:
            if hasattr(storage, "get_debates_batch"):
                debates_map = storage.get_debates_batch(debate_ids)
            else:
                # Fallback for storage backends without batch support
                for debate_id in debate_ids:
                    debates_map[debate_id] = storage.get_debate(debate_id)
        except (KeyError, ValueError, OSError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning("Batch fetch failed, falling back to individual queries: %s", e)
            for debate_id in debate_ids:
                try:
                    debates_map[debate_id] = storage.get_debate(debate_id)
                except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
                    logger.warning(
                        "Failed to fetch debate %s: %s: %s", debate_id, type(e).__name__, e
                    )
                    debates_map[debate_id] = None

        for i, item in enumerate(job.items):
            try:
                item.status = BatchExportStatus.PROCESSING
                item.started_at = time.time()

                # Use pre-fetched debate data
                owned_id = owned.get(item.debate_id)
                debate = debates_map.get(owned_id) if owned_id else None
                if not debate:
                    item.status = BatchExportStatus.FAILED
                    item.error = _EXPORT_NOT_FOUND
                    job.error_count += 1
                else:
                    # Generate export content
                    content = self._generate_export_content(debate, item.format)
                    item.result = content
                    item.status = BatchExportStatus.COMPLETED
                    job.success_count += 1

                item.completed_at = time.time()

            except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
                item.status = BatchExportStatus.FAILED
                item.error = "Export failed"
                item.completed_at = time.time()
                job.error_count += 1
                logger.warning("Batch export item failed: %s: %s", item.debate_id, e)

            job.processed_count += 1

            # Emit progress event
            await self._emit_export_event(
                job.job_id,
                "progress",
                {
                    "debate_id": item.debate_id,
                    "index": i + 1,
                    "total": job.total_count,
                    "percent": job.progress_percent,
                    "status": item.status.value,
                    "error": item.error,
                },
            )

            # Small delay to prevent overwhelming clients
            await asyncio.sleep(0.05)

        # Mark job complete
        job.status = BatchExportStatus.COMPLETED
        job.completed_at = time.time()

        await self._emit_export_event(job.job_id, "completed", job.to_dict())

    def _generate_export_content(self: _DebatesHandlerProtocol, debate: dict, format: str) -> str:
        """Generate export content for a debate."""
        from aragora.server.debate_export import (
            format_debate_csv,
            format_debate_html,
            format_debate_md,
            format_debate_txt,
        )

        if format == "json":
            return json.dumps(debate, indent=2, default=str)
        elif format == "csv":
            result = format_debate_csv(debate, "messages")
            return (
                result.content.decode("utf-8")
                if isinstance(result.content, bytes)
                else result.content
            )
        elif format == "html":
            result = format_debate_html(debate)
            return (
                result.content.decode("utf-8")
                if isinstance(result.content, bytes)
                else result.content
            )
        elif format == "txt":
            result = format_debate_txt(debate)
            return (
                result.content.decode("utf-8")
                if isinstance(result.content, bytes)
                else result.content
            )
        elif format == "md":
            result = format_debate_md(debate)
            return (
                result.content.decode("utf-8")
                if isinstance(result.content, bytes)
                else result.content
            )
        else:
            return json.dumps(debate, indent=2, default=str)

    async def _emit_export_event(
        self: _DebatesHandlerProtocol, job_id: str, event_type: str, data: dict[str, Any]
    ) -> None:
        """Emit an event to all connected SSE clients."""
        queue = _batch_export_events.get(job_id)
        if queue:
            await queue.put(
                {
                    "type": event_type,
                    "timestamp": time.time(),
                    **data,
                }
            )

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/export/batch/{job_id}/status",
        summary="Get batch export status",
        description="Get the status and progress of a batch export job.",
        tags=["Debates", "Export"],
        parameters=[
            {"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "Job status returned"},
            "404": {"description": "Export job not found"},
        },
    )
    def _get_batch_export_status(
        self: _DebatesHandlerProtocol, job_id: str, *, org_id: str
    ) -> HandlerResult:
        """Get status of one of ``org_id``'s batch export jobs."""
        job = _batch_export_jobs.get(job_id)
        if job is None or not _job_visible(job, org_id):
            return record_not_found("Export job")

        items_summary = []
        for item in job.items:
            items_summary.append(
                {
                    "debate_id": item.debate_id,
                    "status": item.status.value,
                    "error": item.error,
                    "has_result": item.result is not None,
                }
            )

        return json_response(
            {
                **job.to_dict(),
                "items": items_summary,
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/export/batch/{job_id}/results",
        summary="Get batch export results",
        description="Get the results of a completed batch export job.",
        tags=["Debates", "Export"],
        parameters=[
            {"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "Export results returned"},
            "400": {"description": "Export job not complete"},
            "404": {"description": "Export job not found"},
        },
    )
    def _get_batch_export_results(
        self: _DebatesHandlerProtocol, job_id: str, *, org_id: str
    ) -> HandlerResult:
        """Get results of one of ``org_id``'s completed batch exports."""
        job = _batch_export_jobs.get(job_id)
        if job is None or not _job_visible(job, org_id):
            return record_not_found("Export job")

        if job.status != BatchExportStatus.COMPLETED:
            return error_response(f"Export job not complete (status: {job.status.value})", 400)

        results = []
        for item in job.items:
            results.append(
                {
                    "debate_id": item.debate_id,
                    "format": item.format,
                    "status": item.status.value,
                    "content": item.result,
                    "error": item.error,
                }
            )

        return json_response(
            {
                "job_id": job_id,
                "status": job.status.value,
                "results": results,
            }
        )

    async def _stream_batch_export_progress(
        self: _DebatesHandlerProtocol, job_id: str
    ) -> AsyncGenerator[str, None]:
        """Stream batch export progress via SSE."""
        job = _batch_export_jobs.get(job_id)
        if not job:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Job not found'})}\n\n"
            return

        queue = _batch_export_events.get(job_id)
        if not queue:
            queue = asyncio.Queue()
            _batch_export_events[job_id] = queue

        # Send initial status
        yield f"data: {json.dumps({'type': 'connected', 'job_id': job_id, **job.to_dict()})}\n\n"

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"

                    # Stop streaming after completion
                    if event.get("type") in ("completed", "failed", "cancelled"):
                        break

                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"

                    # Check if job is already complete
                    if job.status in (
                        BatchExportStatus.COMPLETED,
                        BatchExportStatus.FAILED,
                        BatchExportStatus.CANCELLED,
                    ):
                        yield f"data: {json.dumps({'type': 'completed', **job.to_dict()})}\n\n"
                        break

        except (ConnectionError, OSError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("SSE stream error for %s: %s", job_id, e)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Stream error'})}\n\n"

    def _batch_export_visible(self: _DebatesHandlerProtocol, job_id: str, org_id: str) -> bool:
        """Whether ``job_id`` is one of ``org_id``'s batch export jobs."""
        return _job_visible(_batch_export_jobs.get(job_id), org_id)

    def _list_batch_exports(
        self: _DebatesHandlerProtocol, limit: int = 50, *, org_id: str
    ) -> HandlerResult:
        """List ``org_id``'s batch export jobs."""
        jobs = sorted(
            (job for job in _batch_export_jobs.values() if _job_visible(job, org_id)),
            key=lambda j: j.created_at,
            reverse=True,
        )[:limit]

        return json_response(
            {
                "jobs": [job.to_dict() for job in jobs],
                "count": len(jobs),
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{id}/export/{format}",
        summary="Export debate",
        description="Export debate in specified format (json, csv, html, txt, md).",
        tags=["Debates", "Export"],
        parameters=[
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
            {
                "name": "format",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "enum": ["json", "csv", "html", "txt", "md"]},
            },
            {"name": "table", "in": "query", "schema": {"type": "string", "default": "summary"}},
        ],
        responses={
            "200": {
                "description": "Export returned in requested format",
                "content": {
                    "application/json": {"schema": {"type": "object"}},
                    "text/plain": {"schema": {"type": "string"}},
                    "text/csv": {"schema": {"type": "string"}},
                    "text/markdown": {"schema": {"type": "string"}},
                    "text/html": {"schema": {"type": "string"}},
                },
            },
            "400": {"description": "Invalid format or table"},
            "404": {"description": "Debate not found"},
            "500": {"description": "Database error"},
        },
    )
    @require_permission("debates:read")
    @require_storage
    def _export_debate(
        self: _DebatesHandlerProtocol,
        handler: Any,
        debate_id: str,
        format: str,
        table: str,
    ) -> HandlerResult:
        """Export debate in specified format."""
        from aragora.exceptions import (
            DatabaseError,
            RecordNotFoundError,
            StorageError,
        )

        valid_formats = {"json", "csv", "html", "txt", "md"}
        if format not in valid_formats:
            return error_response(f"Invalid format: {format}. Valid: {valid_formats}", 400)

        storage = self.get_storage()
        try:
            debate = storage.get_debate(debate_id)
            if not debate:
                return error_response(f"Debate not found: {debate_id}", 404)

            if format == "json":
                return json_response(debate)
            elif format == "csv":
                return _format_csv(debate, table)
            elif format == "txt":
                return _format_txt(debate)
            elif format == "md":
                return _format_md(debate)
            elif format in ("latex", "tex"):
                return _format_latex(debate)
            else:  # format == "html"
                return _format_html(debate)

        except RecordNotFoundError:
            logger.info("Export failed - debate not found: %s", debate_id)
            return error_response(f"Debate not found: {debate_id}", 404)
        except (StorageError, DatabaseError) as e:
            logger.error(
                "Export failed for %s (format=%s): %s: %s",
                debate_id,
                format,
                type(e).__name__,
                e,
                exc_info=True,
            )
            return error_response("Database error during export", 500)
        except ValueError as e:
            logger.warning("Export failed for %s - invalid format: %s", debate_id, e)
            return error_response("Invalid export format", 400)


def _format_csv(debate: dict, table: str) -> HandlerResult:
    """Format debate as CSV for the specified table type."""
    from aragora.server.debate_export import format_debate_csv

    result = format_debate_csv(debate, table)
    return HandlerResult(
        status_code=200,
        content_type=result.content_type,
        body=result.content,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )


def _format_html(debate: dict) -> HandlerResult:
    """Format debate as standalone HTML page."""
    from aragora.server.debate_export import format_debate_html

    result = format_debate_html(debate)
    return HandlerResult(
        status_code=200,
        content_type=result.content_type,
        body=result.content,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )


def _format_txt(debate: dict) -> HandlerResult:
    """Format debate as plain text transcript."""
    from aragora.server.debate_export import format_debate_txt

    result = format_debate_txt(debate)
    return HandlerResult(
        status_code=200,
        content_type=result.content_type,
        body=result.content,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )


def _format_md(debate: dict) -> HandlerResult:
    """Format debate as Markdown transcript."""
    from aragora.server.debate_export import format_debate_md

    result = format_debate_md(debate)
    return HandlerResult(
        status_code=200,
        content_type=result.content_type,
        body=result.content,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )


def _format_latex(debate: dict) -> HandlerResult:
    """Format debate as LaTeX document."""
    from aragora.server.debate_export import format_debate_latex

    result = format_debate_latex(debate)
    return HandlerResult(
        status_code=200,
        content_type=result.content_type,
        body=result.content,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )


__all__ = ["ExportOperationsMixin"]
