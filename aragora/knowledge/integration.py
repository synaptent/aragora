"""
Knowledge Pipeline Integration with Document Upload System.

Provides hooks to process uploaded documents through the knowledge pipeline
for automatic embedding and fact extraction.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from aragora.knowledge.fact_store import OrgScopeRequiredError
from aragora.knowledge.pipeline import KnowledgePipeline, PipelineConfig, ProcessingResult

logger = logging.getLogger(__name__)

# Pipelines keyed by (org_id, workspace_id): workspace ids are not unique across
# organizations, so two orgs must never share a pipeline. A None org is the
# unscoped pipeline, whose fact reads and writes fail closed.
_pipelines: dict[tuple[str | None, str], KnowledgePipeline] = {}
_pipeline_lock = asyncio.Lock()

# Thread pool for running async code from sync context
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="knowledge-")


@dataclass
class KnowledgeProcessingConfig:
    """Configuration for knowledge processing on upload."""

    # Enable/disable processing
    enabled: bool = True

    # Processing options
    extract_facts: bool = True
    min_fact_confidence: float = 0.5

    # Async options
    process_async: bool = True  # Process in background

    # Callbacks
    on_complete: Callable[[ProcessingResult], None] | None = None
    on_error: Callable[[str, Exception], None] | None = None


@dataclass
class ProcessingJob:
    """Tracks a knowledge processing job."""

    job_id: str
    document_id: str
    filename: str
    workspace_id: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, processing, completed, failed
    result: ProcessingResult | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


# In-memory job tracking (replace with Redis/DB in production)
_jobs: dict[str, ProcessingJob] = {}


async def get_pipeline(
    workspace_id: str = "default", *, org_id: str | None = None
) -> KnowledgePipeline:
    """Get or create the knowledge pipeline for an organization's workspace.

    Args:
        workspace_id: Workspace identifier
        org_id: Organization from verified authentication. Without it the
            pipeline's fact reads and writes fail closed.

    Returns:
        Initialized KnowledgePipeline
    """
    org_id = org_id or None
    key = (org_id, workspace_id)
    async with _pipeline_lock:
        pipeline = _pipelines.get(key)
        if pipeline is None:
            config = PipelineConfig(
                workspace_id=workspace_id,
                org_id=org_id,
                use_weaviate=_should_use_weaviate(),
                extract_facts=True,
                use_knowledge_mound=_should_use_knowledge_mound(),
            )
            pipeline = KnowledgePipeline(config)
            await pipeline.start()
            _pipelines[key] = pipeline
            logger.info("Knowledge pipeline initialized for workspace %s", workspace_id)

        return pipeline


def _should_use_weaviate() -> bool:
    """Check if Weaviate should be used based on environment."""
    import os

    return os.environ.get("ARAGORA_WEAVIATE_ENABLED", "false").lower() == "true"


def _should_use_knowledge_mound() -> bool:
    """Check if Knowledge Mound integration should be enabled."""
    try:
        from aragora.config import get_settings

        return bool(get_settings().integration.knowledge_mound_enabled)
    except (ImportError, AttributeError):
        logger.debug("Settings unavailable for KM check, using env fallback", exc_info=True)
        import os

        return os.environ.get("ARAGORA_INTEGRATION_KNOWLEDGE_MOUND", "true").lower() == "true"


async def process_document_async(
    content: bytes,
    filename: str,
    workspace_id: str = "default",
    document_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    config: KnowledgeProcessingConfig | None = None,
    *,
    org_id: str | None = None,
) -> ProcessingResult:
    """Process a document through the knowledge pipeline.

    Args:
        content: Raw file content
        filename: Original filename
        workspace_id: Workspace identifier
        document_id: Optional existing document ID
        config: Processing configuration
        org_id: Organization from verified authentication

    Returns:
        ProcessingResult with chunks and facts
    """
    config = config or KnowledgeProcessingConfig()

    pipeline = await get_pipeline(workspace_id, org_id=org_id)

    result = await pipeline.process_document(
        content=content,
        filename=filename,
        tags=tags,
        extract_facts=config.extract_facts,
        document_id=document_id,
        metadata=metadata,
    )

    if config.on_complete and result.success:
        try:
            config.on_complete(result)
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
            logger.warning("on_complete callback failed: %s", e)

    if config.on_error and not result.success:
        try:
            config.on_error(result.document_id, Exception(result.error or "Unknown error"))
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
            logger.warning("on_error callback failed: %s", e)

    return result


def process_document_sync(
    content: bytes,
    filename: str,
    workspace_id: str = "default",
    document_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    config: KnowledgeProcessingConfig | None = None,
    *,
    org_id: str | None = None,
) -> ProcessingResult:
    """Synchronous wrapper for process_document_async.

    Runs the async processing in a thread pool.

    Args:
        content: Raw file content
        filename: Original filename
        workspace_id: Workspace identifier
        document_id: Optional existing document ID
        config: Processing configuration
        org_id: Organization from verified authentication

    Returns:
        ProcessingResult with chunks and facts
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            process_document_async(
                content=content,
                filename=filename,
                workspace_id=workspace_id,
                document_id=document_id,
                tags=tags,
                metadata=metadata,
                config=config,
                org_id=org_id,
            )
        )
    finally:
        loop.close()


async def process_text_async(
    text: str,
    filename: str = "text.txt",
    workspace_id: str = "default",
    document_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    config: KnowledgeProcessingConfig | None = None,
    *,
    org_id: str | None = None,
) -> ProcessingResult:
    """Process raw text through the knowledge pipeline.

    Args:
        text: Raw text content
        filename: Logical filename for provenance
        workspace_id: Workspace identifier
        document_id: Optional existing document ID
        tags: Optional tags for categorization
        metadata: Optional metadata to attach to the document
        config: Processing configuration
        org_id: Organization from verified authentication

    Returns:
        ProcessingResult with chunks and facts
    """
    config = config or KnowledgeProcessingConfig()

    pipeline = await get_pipeline(workspace_id, org_id=org_id)

    result = await pipeline.process_text(
        text=text,
        filename=filename,
        tags=tags,
        extract_facts=config.extract_facts,
        document_id=document_id,
        metadata=metadata,
    )

    if config.on_complete and result.success:
        try:
            config.on_complete(result)
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
            logger.warning("on_complete callback failed: %s", e)

    if config.on_error and not result.success:
        try:
            config.on_error(result.document_id, Exception(result.error or "Unknown error"))
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
            logger.warning("on_error callback failed: %s", e)

    return result


def process_text_sync(
    text: str,
    filename: str = "text.txt",
    workspace_id: str = "default",
    document_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    config: KnowledgeProcessingConfig | None = None,
    *,
    org_id: str | None = None,
) -> ProcessingResult:
    """Synchronous wrapper for process_text_async.

    Runs the async processing in a thread pool.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            process_text_async(
                text=text,
                filename=filename,
                workspace_id=workspace_id,
                document_id=document_id,
                tags=tags,
                metadata=metadata,
                config=config,
                org_id=org_id,
            )
        )
    finally:
        loop.close()


def queue_text_processing(
    text: str,
    filename: str = "text.txt",
    workspace_id: str = "default",
    document_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    config: KnowledgeProcessingConfig | None = None,
    *,
    org_id: str | None = None,
) -> str:
    """Queue raw text for background knowledge processing.

    Returns immediately with a job ID that can be used to check status.
    The job runs in the pipeline of ``org_id``, which must come from
    verified authentication.
    """
    import uuid

    job_id = f"kp_{uuid.uuid4().hex[:12]}"
    doc_id = document_id or f"doc_{uuid.uuid4().hex[:12]}"

    job = ProcessingJob(
        job_id=job_id,
        document_id=doc_id,
        filename=filename,
        workspace_id=workspace_id,
        tags=tags or [],
        metadata=metadata or {},
    )
    _jobs[job_id] = job

    def run_processing():
        try:
            job.status = "processing"
            result = process_text_sync(
                text=text,
                filename=filename,
                workspace_id=workspace_id,
                document_id=doc_id,
                tags=tags,
                metadata=metadata,
                config=config,
                org_id=org_id,
            )
            job.result = result
            job.status = "completed" if result.success else "failed"
            job.error = result.error
            job.completed_at = datetime.now(timezone.utc)

            logger.info(
                "Knowledge processing completed: %s chunks=%s facts=%s",
                job_id,
                result.chunk_count,
                result.fact_count,
            )

        except (
            OSError,
            RuntimeError,
            ValueError,
            ConnectionError,
            KeyError,
            OrgScopeRequiredError,
        ) as e:  # noqa: BLE001 - adapter isolation
            job.status = "failed"
            job.error = f"Processing failed: {type(e).__name__}"
            job.completed_at = datetime.now(timezone.utc)
            logger.warning("Knowledge processing failed: %s - %s", job_id, e)

    _executor.submit(run_processing)

    logger.info("Queued knowledge processing: %s for %s", job_id, filename)
    return job_id


def queue_document_processing(
    content: bytes,
    filename: str,
    workspace_id: str = "default",
    document_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    config: KnowledgeProcessingConfig | None = None,
    *,
    org_id: str | None = None,
) -> str:
    """Queue a document for background knowledge processing.

    Returns immediately with a job ID that can be used to check status.

    Args:
        content: Raw file content
        filename: Original filename
        workspace_id: Workspace identifier
        document_id: Optional existing document ID
        config: Processing configuration
        org_id: Organization from verified authentication

    Returns:
        Job ID for tracking
    """
    import uuid

    job_id = f"kp_{uuid.uuid4().hex[:12]}"
    doc_id = document_id or f"doc_{uuid.uuid4().hex[:12]}"

    job = ProcessingJob(
        job_id=job_id,
        document_id=doc_id,
        filename=filename,
        workspace_id=workspace_id,
        tags=tags or [],
        metadata=metadata or {},
    )
    _jobs[job_id] = job

    def run_processing():
        try:
            job.status = "processing"
            result = process_document_sync(
                content=content,
                filename=filename,
                workspace_id=workspace_id,
                document_id=doc_id,
                tags=tags,
                metadata=metadata,
                config=config,
                org_id=org_id,
            )
            job.result = result
            job.status = "completed" if result.success else "failed"
            job.error = result.error
            job.completed_at = datetime.now(timezone.utc)

            logger.info(
                "Knowledge processing completed: %s chunks=%s facts=%s",
                job_id,
                result.chunk_count,
                result.fact_count,
            )

        except (
            OSError,
            RuntimeError,
            ValueError,
            ConnectionError,
            KeyError,
            OrgScopeRequiredError,
        ) as e:  # noqa: BLE001 - adapter isolation
            job.status = "failed"
            job.error = f"Processing failed: {type(e).__name__}"
            job.completed_at = datetime.now(timezone.utc)
            logger.warning("Knowledge processing failed: %s - %s", job_id, e)

    _executor.submit(run_processing)

    logger.info("Queued knowledge processing: %s for %s", job_id, filename)
    return job_id


def get_job_status(job_id: str) -> dict[str, Any] | None:
    """Get the status of a knowledge processing job.

    Args:
        job_id: Job identifier

    Returns:
        Job status dict or None if not found
    """
    job = _jobs.get(job_id)
    if not job:
        return None

    return {
        "job_id": job.job_id,
        "document_id": job.document_id,
        "filename": job.filename,
        "workspace_id": job.workspace_id,
        "tags": job.tags,
        "metadata": job.metadata,
        "status": job.status,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "result": (
            {
                "chunk_count": job.result.chunk_count,
                "fact_count": job.result.fact_count,
                "embedded_count": job.result.embedded_count,
                "duration_ms": job.result.duration_ms,
            }
            if job.result
            else None
        ),
    }


def get_all_jobs(
    workspace_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get all knowledge processing jobs with optional filtering.

    Args:
        workspace_id: Filter by workspace
        status: Filter by status (pending, processing, completed, failed)
        limit: Maximum jobs to return

    Returns:
        List of job status dicts
    """
    jobs = list(_jobs.values())

    if workspace_id:
        jobs = [j for j in jobs if j.workspace_id == workspace_id]

    if status:
        jobs = [j for j in jobs if j.status == status]

    # Sort by created_at descending
    jobs.sort(key=lambda j: j.created_at, reverse=True)

    return [get_job_status(j.job_id) for j in jobs[:limit] if get_job_status(j.job_id)]


async def shutdown_pipeline() -> None:
    """Shutdown the knowledge pipeline gracefully."""
    async with _pipeline_lock:
        if _pipelines:
            for (_, workspace_id), pipeline in list(_pipelines.items()):
                try:
                    await pipeline.stop()
                    logger.info(
                        "Knowledge pipeline shutdown complete for workspace %s", workspace_id
                    )
                except (OSError, RuntimeError) as e:
                    logger.warning(
                        "Failed to shutdown pipeline for workspace %s: %s", workspace_id, e
                    )
            _pipelines.clear()

    _executor.shutdown(wait=True)


# Convenience function for document handlers
def process_uploaded_document(
    content: bytes,
    filename: str,
    workspace_id: str = "default",
    document_id: str | None = None,
    async_processing: bool = True,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    org_id: str | None = None,
) -> dict[str, Any]:
    """Process an uploaded document through the knowledge pipeline.

    This is the main entry point for document handlers.

    Args:
        content: Raw file content
        filename: Original filename
        workspace_id: Workspace identifier
        document_id: Document ID from storage
        async_processing: If True, process in background and return job_id
        tags: Optional tags for categorization
        metadata: Optional metadata to attach to the document
        org_id: Organization of the authenticated uploader. Never take it
            from request input or ``metadata``.

    Returns:
        Dict with processing info:
        - If async: {"job_id": "...", "status": "queued"}
        - If sync: {"success": True, "chunks": N, "facts": N}
    """
    if async_processing:
        job_id = queue_document_processing(
            content=content,
            filename=filename,
            workspace_id=workspace_id,
            document_id=document_id,
            tags=tags,
            metadata=metadata,
            org_id=org_id,
        )
        return {
            "knowledge_processing": {
                "job_id": job_id,
                "status": "queued",
            }
        }
    else:
        result = process_document_sync(
            content=content,
            filename=filename,
            workspace_id=workspace_id,
            document_id=document_id,
            tags=tags,
            metadata=metadata,
            org_id=org_id,
        )
        return {
            "knowledge_processing": {
                "success": result.success,
                "chunks": result.chunk_count,
                "facts": result.fact_count,
                "embedded": result.embedded_count,
                "error": result.error,
            }
        }


def process_uploaded_text(
    text: str,
    filename: str = "text.txt",
    workspace_id: str = "default",
    document_id: str | None = None,
    async_processing: bool = True,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    org_id: str | None = None,
) -> dict[str, Any]:
    """Process uploaded text through the knowledge pipeline.

    ``org_id`` is the authenticated uploader's organization; never take it
    from request input or ``metadata``.
    """
    if async_processing:
        job_id = queue_text_processing(
            text=text,
            filename=filename,
            workspace_id=workspace_id,
            document_id=document_id,
            tags=tags,
            metadata=metadata,
            org_id=org_id,
        )
        return {
            "knowledge_processing": {
                "job_id": job_id,
                "status": "queued",
            }
        }
    result = process_text_sync(
        text=text,
        filename=filename,
        workspace_id=workspace_id,
        document_id=document_id,
        tags=tags,
        metadata=metadata,
        org_id=org_id,
    )
    return {
        "knowledge_processing": {
            "success": result.success,
            "chunks": result.chunk_count,
            "facts": result.fact_count,
            "embedded": result.embedded_count,
            "error": result.error,
        }
    }
