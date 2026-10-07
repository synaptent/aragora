"""
Batch document upload and processing endpoint handlers.

Endpoints for enterprise document ingestion:
- POST /api/v1/documents/batch - Upload multiple documents
- GET /api/v1/documents/batch/{job_id} - Get batch job status
- GET /api/v1/documents/batch/{job_id}/results - Get batch job results
- DELETE /api/v1/documents/batch/{job_id} - Cancel a batch job
- GET /api/v1/documents/{doc_id}/chunks - Get document chunks
- GET /api/v1/documents/{doc_id}/context - Get LLM-ready context
- GET /api/v1/documents/processing/stats - Get processing statistics
- GET /api/v1/knowledge/jobs - Get knowledge processing jobs
- GET /api/v1/knowledge/jobs/{job_id} - Get knowledge job status

Every route is scoped to the caller's org: jobs, documents and knowledge jobs
of another org or of an unknown owner answer like missing ones, and lists and
stats hold only the caller's org. A ``workspace_id`` never widens that scope.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Any

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    safe_error_message,
    handle_errors,
)
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.utils.params import get_string_param
from aragora.server.handlers.utils.rate_limit import RateLimiter, get_client_ip
from aragora.server.validation.query_params import safe_query_int
from aragora.tenancy.record_scope import (
    OrgScope,
    record_not_found,
    record_visible,
    require_org_scope,
    scope_denial_first,
)

# Knowledge processing enabled by default
KNOWLEDGE_PROCESSING_DEFAULT = (
    os.environ.get("ARAGORA_KNOWLEDGE_AUTO_PROCESS", "true").lower() == "true"
)

logger = logging.getLogger(__name__)

_batch_upload_limiter = RateLimiter(requests_per_minute=5)

# Maximum files per batch upload
MAX_BATCH_SIZE = 50
MAX_FILE_SIZE_MB = 100
MAX_TOTAL_BATCH_SIZE_MB = 500

# Routes published in the OpenAPI spec and SDK with no implementation yet.
_UNIMPLEMENTED_ROUTES = frozenset({"/api/v1/batch", "/api/v1/batch/queue/status"})


def _not_implemented(method: str, path: str) -> HandlerResult:
    return error_response(f"{method} {path} is not implemented", 501)


class DocumentBatchHandler(BaseHandler):
    """Handler for batch document upload and processing endpoints."""

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    ROUTES = [
        "/api/v1/batch",
        "/api/v1/batch/queue/status",
        "/api/v1/documents/batch",
        "/api/v1/documents/processing/stats",
        "/api/v1/knowledge/jobs",
    ]

    @staticmethod
    def _split_path(path: str) -> list[str]:
        """Split a request path into non-empty segments."""
        stripped = path.strip("/")
        return stripped.split("/") if stripped else []

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        if path in self.ROUTES:
            return True
        parts = self._split_path(path)
        # Handle /api/v1/documents/batch/{job_id} and /results
        if parts[:4] == ["api", "v1", "documents", "batch"]:
            return len(parts) == 5 or (len(parts) == 6 and parts[5] == "results")
        # Handle /api/v1/documents/{doc_id}/chunks and /context
        if parts[:3] == ["api", "v1", "documents"]:
            return len(parts) == 5 and parts[4] in {"chunks", "context"}
        # Handle /api/v1/knowledge/jobs/{job_id}
        if parts[:4] == ["api", "v1", "knowledge", "jobs"]:
            return len(parts) == 5 and bool(parts[4])
        return False

    @handle_errors("document batch retrieval")
    @scope_denial_first
    @require_permission("documents:read")
    async def handle(self, path: str, query_params: dict, handler) -> HandlerResult | None:
        """Route GET requests."""
        if path in _UNIMPLEMENTED_ROUTES:
            return _not_implemented("GET", path)
        parts = self._split_path(path)
        is_knowledge_job = parts[:4] == ["api", "v1", "knowledge", "jobs"] and len(parts) == 5
        is_batch_job = parts[:4] == ["api", "v1", "documents", "batch"] and (
            len(parts) == 5 or (len(parts) == 6 and parts[5] == "results")
        )
        is_document_view = (
            parts[:3] == ["api", "v1", "documents"]
            and len(parts) == 5
            and parts[4] in {"chunks", "context"}
        )
        if not (
            path in ("/api/v1/documents/processing/stats", "/api/v1/knowledge/jobs")
            or is_knowledge_job
            or is_batch_job
            or is_document_view
        ):
            return None

        scope, scope_err = require_org_scope(handler)
        if scope is None:
            return scope_err

        if path == "/api/v1/documents/processing/stats":
            return self._get_processing_stats(scope)

        # GET /api/knowledge/jobs - list the caller org's knowledge processing jobs
        if path == "/api/v1/knowledge/jobs":
            workspace_id = get_string_param(query_params, "workspace_id")
            status = get_string_param(query_params, "status")
            limit = safe_query_int(query_params, "limit", default=100, min_val=1, max_val=1000)
            return self._list_knowledge_jobs(scope, workspace_id, status, limit)

        # GET /api/knowledge/jobs/{job_id} - get specific job status
        if is_knowledge_job:
            return self._get_knowledge_job_status(parts[4], scope)

        # GET /api/documents/batch/{job_id} and /results
        if is_batch_job:
            if len(parts) == 5:
                return await self._get_job_status(parts[4], scope)
            return await self._get_job_results(parts[4], scope)

        doc_id = parts[3]
        # GET /api/documents/{doc_id}/chunks
        if parts[4] == "chunks":
            limit = safe_query_int(query_params, "limit", default=100, min_val=1, max_val=1000)
            offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=1000000)
            return self._get_document_chunks(doc_id, scope, limit, offset)

        # GET /api/documents/{doc_id}/context
        max_tokens = safe_query_int(
            query_params, "max_tokens", default=4096, min_val=1, max_val=128000
        )
        model = get_string_param(query_params, "model", "gpt-4") or "gpt-4"
        return self._get_document_context(doc_id, scope, max_tokens, model)

    @handle_errors("document batch creation")
    @scope_denial_first
    @require_permission("documents:create")
    async def handle_post(self, path: str, query_params: dict, handler) -> HandlerResult | None:
        """Route POST requests."""
        if path == "/api/v1/batch":
            return _not_implemented("POST", path)
        if path != "/api/v1/documents/batch":
            return None

        scope, scope_err = require_org_scope(handler)
        if scope is None:
            return scope_err

        client_ip = get_client_ip(handler)
        if not _batch_upload_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        return await self._upload_batch(handler, scope)

    @handle_errors("document batch deletion")
    @scope_denial_first
    @require_permission("documents:delete")
    async def handle_delete(self, path: str, query_params: dict, handler) -> HandlerResult | None:
        """Route DELETE requests."""
        parts = self._split_path(path)
        if parts[:4] == ["api", "v1", "documents", "batch"] and len(parts) == 5:
            scope, scope_err = require_org_scope(handler)
            if scope is None:
                return scope_err
            return await self._cancel_job(parts[4], scope)
        return None

    def _visible_job(self, job: Any, scope: OrgScope) -> bool:
        return job is not None and record_visible(getattr(job, "org_id", None), scope)

    async def _upload_batch(self, handler, scope: OrgScope) -> HandlerResult:
        """
        Upload multiple documents for batch processing.

        Request body (multipart/form-data):
            files[]: Multiple file uploads
            workspace_id: Optional workspace ID
            chunking_strategy: Optional (semantic, sliding, recursive)
            chunk_size: Optional (default 512)
            chunk_overlap: Optional (default 50)
            priority: Optional (low, normal, high, urgent)
            tags: Optional JSON array of tags
            process_knowledge: Optional boolean (default true) - enable knowledge pipeline

        Response:
            {
                "job_ids": ["job-1", "job-2", ...],
                "batch_id": "batch-uuid",
                "total_files": 3,
                "total_size_bytes": 1024000,
                "estimated_chunks": 150,
                "knowledge_processing": {
                    "enabled": true,
                    "job_ids": ["kp_...", ...]
                }
            }
        """
        try:
            # Parse multipart form data
            content_type = handler.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                return error_response("Content-Type must be multipart/form-data", 400)

            # Extract boundary
            boundary = None
            for part in content_type.split(";"):
                if "boundary=" in part:
                    boundary = part.split("=")[1].strip().strip('"')
                    break

            if not boundary:
                return error_response("Missing multipart boundary", 400)

            # Read body
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > MAX_TOTAL_BATCH_SIZE_MB * 1024 * 1024:
                return error_response(
                    f"Total batch size exceeds {MAX_TOTAL_BATCH_SIZE_MB}MB limit",
                    413,
                )

            body = handler.rfile.read(content_length)

            # Parse multipart data
            files, form_data = self._parse_multipart(body, boundary)

            if not files:
                return error_response("No files provided", 400)

            if len(files) > MAX_BATCH_SIZE:
                return error_response(f"Maximum {MAX_BATCH_SIZE} files per batch", 400)

            # Extract form parameters
            workspace_id = form_data.get("workspace_id", "default") or "default"
            chunking_strategy = form_data.get("chunking_strategy")
            chunk_size = int(form_data.get("chunk_size", "512"))
            chunk_overlap = int(form_data.get("chunk_overlap", "50"))
            priority_str = form_data.get("priority", "normal")
            tags_json = form_data.get("tags", "[]")

            # Parse knowledge processing option
            process_knowledge_str = form_data.get("process_knowledge", "")
            if process_knowledge_str:
                process_knowledge = process_knowledge_str.lower() == "true"
            else:
                process_knowledge = KNOWLEDGE_PROCESSING_DEFAULT

            # Parse tags
            try:
                tags = json.loads(tags_json) if tags_json else []
            except json.JSONDecodeError:
                tags = []

            ingest_metadata = {
                "user_id": scope.user_id,
                "owner_id": scope.user_id,
                "org_id": scope.org_id,
                "workspace_id": workspace_id,
                "tenant_id": workspace_id or scope.org_id,
                "source": "documents_batch_upload",
            }

            # Import batch processor
            from aragora.documents.ingestion.batch_processor import (
                JobPriority,
            )

            # Map priority string
            priority_map = {
                "low": JobPriority.LOW,
                "normal": JobPriority.NORMAL,
                "high": JobPriority.HIGH,
                "urgent": JobPriority.URGENT,
            }
            priority = priority_map.get(priority_str.lower(), JobPriority.NORMAL)

            # Get or create batch processor
            processor = self._get_batch_processor()

            # Submit jobs
            job_ids = []
            total_size = 0
            batch_id = self._generate_batch_id()

            for filename, content in files:
                file_size = len(content)
                if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                    logger.warning("Skipping file %s: exceeds size limit", filename)
                    continue

                total_size += file_size

                job_id = await processor.submit(
                    content=content,
                    filename=filename,
                    workspace_id=workspace_id,
                    uploaded_by=scope.user_id,
                    org_id=scope.org_id,
                    document_id=self._store_document(content, filename, scope),
                    priority=priority,
                    chunking_strategy=chunking_strategy,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    tags=tags,
                )
                job_ids.append(job_id)

            if job_ids and not getattr(processor, "is_running", True):
                # No worker loop on this host (each legacy request runs its own
                # event loop), so run the batch on a thread of its own.
                threading.Thread(
                    target=asyncio.run,
                    args=(processor.process_queued(list(job_ids)),),
                    name=f"documents-{batch_id}",
                    daemon=True,
                ).start()

            # Estimate chunks
            from aragora.documents.chunking.token_counter import get_token_counter

            counter = get_token_counter()
            estimated_chunks = 0
            for _, content in files:
                try:
                    text = content.decode("utf-8", errors="ignore")
                    tokens = counter.count(text)
                    estimated_chunks += max(1, tokens // chunk_size)
                except (ValueError, TypeError, UnicodeDecodeError) as e:
                    # Token counting fallback - use estimate of 1 chunk
                    logger.debug("Token counting failed, using fallback: %s", e)
                    estimated_chunks += 1

            # Queue knowledge processing if enabled
            knowledge_job_ids = []
            if process_knowledge:
                try:
                    from aragora.knowledge.integration import queue_document_processing

                    for filename, content in files:
                        kp_job_id = queue_document_processing(
                            content=content,
                            filename=filename,
                            workspace_id=workspace_id,
                            tags=tags,
                            metadata=ingest_metadata,
                        )
                        knowledge_job_ids.append(kp_job_id)
                    logger.info(
                        "Queued %s knowledge processing jobs for batch %s",
                        len(knowledge_job_ids),
                        batch_id,
                    )
                except ImportError:
                    logger.warning("Knowledge pipeline not available for batch processing")
                except (RuntimeError, ValueError, TypeError, OSError) as ke:
                    logger.warning("Knowledge processing queue failed: %s", ke)

            # Build response
            response_data: dict[str, Any] = {
                "job_ids": job_ids,
                "batch_id": batch_id,
                "total_files": len(job_ids),
                "total_size_bytes": total_size,
                "estimated_chunks": estimated_chunks,
                "chunking_strategy": chunking_strategy or "auto",
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            }

            if knowledge_job_ids:
                response_data["knowledge_processing"] = {
                    "enabled": True,
                    "job_ids": knowledge_job_ids,
                }
            elif process_knowledge:
                response_data["knowledge_processing"] = {
                    "enabled": True,
                    "status": "unavailable",
                }

            return json_response(response_data, status=202)  # Accepted for processing

        except (ValueError, TypeError) as e:
            logger.warning("Batch upload failed (invalid params): %s", e)
            return error_response(safe_error_message(e, "Batch upload"), 400)
        except json.JSONDecodeError as e:
            logger.warning("Batch upload failed (invalid JSON): %s", e)
            return error_response(safe_error_message(e, "Batch upload"), 400)
        except OSError as e:
            logger.exception("Batch upload failed (I/O error): %s", e)
            return error_response(safe_error_message(e, "Batch upload"), 500)
        except RuntimeError as e:
            logger.exception("Batch upload failed")
            return error_response(safe_error_message(e, "Batch upload"), 500)

    def _store_document(self, content: bytes, filename: str, scope: OrgScope) -> str | None:
        """Save a batch file in the document store under the caller's org; its id or None."""
        store = self.ctx.get("document_store")
        if store is None:
            return None
        try:
            from aragora.documents.parsing import parse_document

            doc = parse_document(content, filename, org_id=scope.org_id, created_by=scope.user_id)
            return store.add(doc)
        except (ImportError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.warning("Batch file %s not saved to the document store: %s", filename, e)
            return None

    async def _get_job_status(self, job_id: str, scope: OrgScope) -> HandlerResult:
        """Get status of a batch processing job."""
        processor = self._get_batch_processor()

        status = await processor.get_status(job_id)
        if not status or not record_visible(status.get("org_id"), scope):
            return record_not_found("Job")

        return json_response(status)

    async def _get_job_results(self, job_id: str, scope: OrgScope) -> HandlerResult:
        """Get results of a completed batch job."""
        processor = self._get_batch_processor()

        job = await processor.get_result(job_id)

        if not self._visible_job(job, scope):
            return record_not_found("Job")

        if job.status.value not in ("completed", "failed"):
            return json_response(
                {
                    "status": job.status.value,
                    "progress": job.progress,
                    "message": "Job not yet complete",
                },
                status=202,
            )

        # Build response
        result: dict[str, Any] = {
            "job_id": job.id,
            "status": job.status.value,
            "filename": job.filename,
        }

        if job.document:
            result["document"] = job.document.to_summary()

        if job.chunks:
            result["chunks"] = {
                "total": len(job.chunks),
                "total_tokens": sum(c.token_count for c in job.chunks),
                "items": [
                    {
                        "id": c.id,
                        "sequence": c.sequence,
                        "token_count": c.token_count,
                        "heading_context": c.heading_context,
                        "preview": c.content[:200] + "..." if len(c.content) > 200 else c.content,
                    }
                    for c in job.chunks[:10]  # First 10 chunks in summary
                ],
            }

        if job.error_message:
            result["error"] = job.error_message

        return json_response(result)

    async def _cancel_job(self, job_id: str, scope: OrgScope) -> HandlerResult:
        """Cancel a queued batch job, or delete a finished one."""
        processor = self._get_batch_processor()

        if not self._visible_job(await processor.get_result(job_id), scope):
            return record_not_found("Job")

        if await processor.cancel(job_id):
            return json_response({"cancelled": True, "job_id": job_id})
        if await processor.remove(job_id):
            return json_response({"deleted": True, "job_id": job_id})
        return error_response(f"Cannot cancel job {job_id}: already processing", 400)

    def _visible_document(self, doc_id: str, scope: OrgScope) -> Any | None:
        """The caller org's document ``doc_id`` from the document store, else None."""
        store = self.ctx.get("document_store")
        doc = store.get(doc_id) if store is not None else None
        if doc is None or not record_visible(getattr(doc, "org_id", None), scope):
            return None
        return doc

    def _get_document_chunks(
        self, doc_id: str, scope: OrgScope, limit: int = 100, offset: int = 0
    ) -> HandlerResult:
        """
        Get chunks for a processed document.

        Query params:
            limit: Max chunks to return (default 100)
            offset: Offset for pagination (default 0)
        """
        if self._visible_document(doc_id, scope) is None:
            return record_not_found("Document")

        # For now, return placeholder - will be populated from index
        # In production, this would query Weaviate or the chunk store
        return json_response(
            {
                "document_id": doc_id,
                "chunks": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "message": "Chunk retrieval requires vector store integration (Phase 2)",
            }
        )

    def _get_document_context(
        self, doc_id: str, scope: OrgScope, max_tokens: int = 4096, model: str = "gpt-4"
    ) -> HandlerResult:
        """
        Get LLM-ready context from a document.

        Retrieves and concatenates chunks to fit within token limit.

        Query params:
            max_tokens: Maximum tokens to include (default 4096)
            model: Model for token counting (default gpt-4)
        """
        # For now, try to get from legacy document store
        doc = self._visible_document(doc_id, scope)
        if doc is None:
            return record_not_found("Document")

        from aragora.documents.chunking.token_counter import get_token_counter

        counter = get_token_counter()
        text = doc.text
        tokens = counter.count(text, model)

        if tokens > max_tokens:
            text = counter.truncate_to_tokens(text, max_tokens, model)
            tokens = counter.count(text, model)

        return json_response(
            {
                "document_id": doc_id,
                "context": text,
                "token_count": tokens,
                "max_tokens": max_tokens,
                "model": model,
                "truncated": tokens < counter.count(doc.text, model),
            }
        )

    def _get_processing_stats(self, scope: OrgScope) -> HandlerResult:
        """Get batch processing statistics for the caller's org."""
        processor = self._get_batch_processor()
        stats = processor.get_stats(org_id=scope.org_id)

        return json_response(
            {
                "processor": stats,
                "limits": {
                    "max_batch_size": MAX_BATCH_SIZE,
                    "max_file_size_mb": MAX_FILE_SIZE_MB,
                    "max_total_batch_size_mb": MAX_TOTAL_BATCH_SIZE_MB,
                },
            }
        )

    # Helper methods

    def _get_batch_processor(self):
        """Get or create batch processor from context."""
        from aragora.documents.ingestion.batch_processor import BatchProcessor

        processor = self.ctx.get("batch_processor")
        if not processor:
            processor = BatchProcessor()
            # Note: in production, start() should be called during server startup
            self.ctx["batch_processor"] = processor
        return processor

    def _parse_multipart(
        self, body: bytes, boundary: str
    ) -> tuple[list[tuple[str, bytes]], dict[str, str]]:
        """Parse multipart form data."""
        files = []
        form_data = {}

        boundary_bytes = f"--{boundary}".encode()
        parts = body.split(boundary_bytes)

        for part in parts[1:]:  # Skip preamble
            if part.strip() in (b"", b"--", b"--\r\n"):
                continue

            # Split headers from content
            try:
                header_end = part.find(b"\r\n\r\n")
                if header_end == -1:
                    continue

                headers = part[:header_end].decode("utf-8", errors="ignore")
                content = part[header_end + 4 :]

                # Remove trailing boundary marker
                if content.endswith(b"\r\n"):
                    content = content[:-2]

                # Parse Content-Disposition
                filename = None
                field_name = None

                for line in headers.split("\r\n"):
                    if "Content-Disposition:" in line:
                        if 'filename="' in line:
                            start = line.find('filename="') + 10
                            end = line.find('"', start)
                            filename = line[start:end]
                        if 'name="' in line:
                            start = line.find('name="') + 6
                            end = line.find('"', start)
                            field_name = line[start:end]

                if filename and field_name:
                    files.append((filename, content))
                elif field_name:
                    form_data[field_name] = content.decode("utf-8", errors="ignore")

            except (ValueError, UnicodeDecodeError, IndexError, KeyError) as e:
                logger.warning("Error parsing multipart part: %s", e)
                continue

        return files, form_data

    def _generate_batch_id(self) -> str:
        """Generate unique batch ID."""
        import uuid

        return f"batch-{uuid.uuid4().hex[:12]}"

    # Knowledge processing job handlers

    def _list_knowledge_jobs(
        self,
        scope: OrgScope,
        workspace_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> HandlerResult:
        """List the caller org's knowledge processing jobs with optional filtering."""
        try:
            from aragora.knowledge.integration import get_all_jobs

            jobs = get_all_jobs(
                workspace_id=workspace_id, status=status, limit=limit, org_id=scope.org_id
            )
            return json_response(
                {
                    "jobs": jobs,
                    "count": len(jobs),
                    "filters": {
                        "workspace_id": workspace_id,
                        "status": status,
                        "limit": limit,
                    },
                }
            )
        except ImportError:
            return error_response("Knowledge pipeline not available", 503)
        except (ValueError, TypeError) as e:
            logger.warning("Error listing knowledge jobs (invalid params): %s", e)
            return error_response(safe_error_message(e, "Failed to list jobs"), 400)
        except (KeyError, AttributeError) as e:
            logger.exception("Error listing knowledge jobs: %s", e)
            return error_response(safe_error_message(e, "Failed to list jobs"), 500)

    def _get_knowledge_job_status(self, job_id: str, scope: OrgScope) -> HandlerResult:
        """Get status of a specific knowledge processing job of the caller's org."""
        try:
            from aragora.knowledge.integration import get_job_status, job_org_id

            status = get_job_status(job_id)
            if not status or not record_visible(job_org_id(status), scope):
                return record_not_found("Knowledge job")
            return json_response(status)
        except ImportError:
            return error_response("Knowledge pipeline not available", 503)
        except (KeyError, ValueError) as e:
            logger.warning("Error getting knowledge job status (not found or invalid): %s", e)
            return error_response(safe_error_message(e, "Failed to get job status"), 404)
        except AttributeError as e:
            logger.exception("Error getting knowledge job status: %s", e)
            return error_response(safe_error_message(e, "Failed to get job status"), 500)


# Export for handler registration
__all__ = ["DocumentBatchHandler"]
