"""
Queue management endpoint handlers.

Stability: STABLE

Exposes the job queue system for monitoring and management.

Endpoints:
- POST /api/queue/jobs - Submit new job
- GET /api/queue/jobs - List jobs with filters
- GET /api/queue/jobs/:id - Get job status
- POST /api/queue/jobs/:id/retry - Retry failed job
- DELETE /api/queue/jobs/:id - Cancel job
- GET /api/queue/stats - Queue statistics
- GET /api/queue/workers - Worker status
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from aragora.config import DEFAULT_CONSENSUS, DEFAULT_ROUNDS
from aragora.exceptions import REDIS_CONNECTION_ERRORS
from aragora.resilience import CircuitBreaker
from aragora.server.validation import validate_path_segment, SAFE_ID_PATTERN
from aragora.server.validation.query_params import safe_query_int
from aragora.server.versioning.compat import strip_version_prefix
from aragora.audit.unified import audit_admin, audit_data

from ..base import (
    HandlerResult,
    PaginatedHandlerMixin,
    error_response,
    get_string_param,
    json_response,
    safe_error_message,
    handle_errors,
)
from ..secure import SecureHandler
from ..utils.auth import ForbiddenError, UnauthorizedError
from ..utils.auth_mixins import SecureEndpointMixin
from ..utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)

# =============================================================================
# Resilience Configuration
# =============================================================================

# Circuit breaker for queue service
_queue_circuit_breaker = CircuitBreaker(
    name="queue_handler",
    failure_threshold=5,
    cooldown_seconds=30.0,
)


def get_queue_circuit_breaker() -> CircuitBreaker:
    """Get the circuit breaker for queue service."""
    return _queue_circuit_breaker


def get_queue_circuit_breaker_status() -> dict[str, Any]:
    """Get current status of the queue circuit breaker."""
    return _queue_circuit_breaker.to_dict()


# Module-level cache for queue instance
_queue_instance: Any | None = None
_queue_lock = asyncio.Lock()


async def _get_queue() -> Any | None:
    """Get or create the queue instance.

    Returns None if Redis is not available.
    """
    global _queue_instance

    if _queue_instance is not None:
        return _queue_instance

    async with _queue_lock:
        if _queue_instance is not None:
            return _queue_instance

        try:
            from aragora.queue import create_redis_queue

            _queue_instance = await create_redis_queue()
            return _queue_instance
        except ImportError:
            logger.warning("Redis package not available for queue")
            return None
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("Failed to connect to Redis for queue: %s", e)
            return None
        except RuntimeError as e:
            logger.warning("Runtime error creating queue: %s", e)
            return None


class QueueHandler(SecureEndpointMixin, SecureHandler, PaginatedHandlerMixin):  # type: ignore[misc]
    """Handler for job queue management endpoints.

    Stability: STABLE

    Features:
    - Circuit breaker pattern for service resilience
    - Rate limiting (60 requests/minute)
    - Full RBAC permission checks
    - Comprehensive input validation

    RBAC Permissions:
    - queue:read - View jobs, stats, workers
    - queue:manage - Submit, retry, cancel jobs
    - queue:admin - DLQ management, cleanup operations
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    RESOURCE_TYPE = "queue"

    ROUTES = [
        "/api/queue/jobs",
        "/api/queue/jobs/*",
        "/api/queue/jobs/*/retry",
        "/api/queue/stats",
        "/api/queue/workers",
        "/api/queue/dlq",
        "/api/queue/dlq/requeue",
        "/api/queue/dlq/*/requeue",
        "/api/queue/cleanup",
        "/api/queue/stale",
        "/api/v1/queue/jobs",
        "/api/v1/queue/jobs/*",
        "/api/v1/queue/jobs/*/retry",
        "/api/v1/queue/stats",
        "/api/v1/queue/workers",
        "/api/v1/queue/dlq",
        "/api/v1/queue/dlq/requeue",
        "/api/v1/queue/dlq/*/requeue",
        "/api/v1/queue/cleanup",
        "/api/v1/queue/stale",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the request."""
        normalized = strip_version_prefix(path)
        return normalized.startswith("/api/queue/")

    @handle_errors("queue creation")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests - delegates to async handle method which checks permissions."""
        # Permission checking is done in the async handle method
        return None

    def handle_get(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle GET requests - delegates to async handle method which checks permissions."""
        # Permission checking is done in the async handle method
        return None

    @rate_limit(requests_per_minute=60)
    async def handle(  # type: ignore[override]
        self, path: str, method: str, handler: Any | None = None
    ) -> HandlerResult | None:
        """Route request to appropriate handler method."""
        # Require authentication for all queue operations
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        normalized = strip_version_prefix(path)

        # Determine required permission based on operation
        read_ops = {"/api/queue/stats", "/api/queue/workers", "/api/queue/jobs", "/api/queue/stale"}
        admin_ops = {"/api/queue/dlq", "/api/queue/cleanup"}

        if normalized in read_ops or (
            normalized.startswith("/api/queue/jobs/") and method == "GET"
        ):
            permission = "queue:read"
        elif normalized in admin_ops or normalized.startswith("/api/queue/dlq/"):
            permission = "queue:admin"
        else:
            permission = "queue:manage"

        try:
            self.check_permission(auth_context, permission)
        except ForbiddenError:
            logger.warning(
                "Queue permission denied: %s for user %s", permission, auth_context.user_id
            )
            return error_response("Permission denied", 403)

        query_params: dict[str, Any] = {}
        if handler:
            query_str = handler.path.split("?", 1)[1] if "?" in handler.path else ""
            from urllib.parse import parse_qs

            query_params = parse_qs(query_str)

        # GET /api/queue/stats
        if normalized == "/api/queue/stats" and method == "GET":
            return await self._get_stats()

        # GET /api/queue/workers
        if normalized == "/api/queue/workers" and method == "GET":
            return await self._get_workers()

        # GET /api/queue/dlq (list dead-letter queue jobs)
        if normalized == "/api/queue/dlq" and method == "GET":
            return await self._list_dlq(query_params)

        # POST /api/queue/dlq/requeue (requeue all DLQ jobs)
        if normalized == "/api/queue/dlq/requeue" and method == "POST":
            return await self._requeue_all_dlq()

        # POST /api/v1/queue/dlq/:id/requeue (requeue specific DLQ job)
        # Parts: ["", "api", "queue", "dlq", "{job_id}", "requeue"]
        if (
            normalized.startswith("/api/queue/dlq/")
            and normalized.endswith("/requeue")
            and method == "POST"
        ):
            parts = normalized.split("/")
            if len(parts) == 6:
                job_id = parts[4]
                is_valid, err = validate_path_segment(job_id, "job_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return await self._requeue_dlq_job(job_id)

        # POST /api/queue/cleanup (cleanup old completed jobs)
        if normalized == "/api/queue/cleanup" and method == "POST":
            return await self._cleanup_jobs(query_params)

        # GET /api/queue/stale (list stale/stuck jobs)
        if normalized == "/api/queue/stale" and method == "GET":
            return await self._list_stale_jobs(query_params)

        # POST /api/queue/jobs (submit new job)
        if normalized == "/api/queue/jobs" and method == "POST":
            return await self._submit_job(handler)

        # GET /api/queue/jobs (list jobs)
        if normalized == "/api/queue/jobs" and method == "GET":
            return await self._list_jobs(query_params)

        # Handle job-specific endpoints
        if normalized.startswith("/api/queue/jobs/"):
            parts = normalized.split("/")
            # Parts: ['', 'api', 'queue', 'jobs', ':id', ...]

            # POST /api/queue/jobs/:id/retry (6 parts)
            if len(parts) == 6 and parts[5] == "retry" and method == "POST":
                job_id = parts[4]
                is_valid, err = validate_path_segment(job_id, "job_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return await self._retry_job(job_id)

            # GET /api/queue/jobs/:id (5 parts)
            if len(parts) == 5 and method == "GET":
                job_id = parts[4]
                is_valid, err = validate_path_segment(job_id, "job_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return await self._get_job(job_id)

            # DELETE /api/queue/jobs/:id (5 parts)
            if len(parts) == 5 and method == "DELETE":
                job_id = parts[4]
                is_valid, err = validate_path_segment(job_id, "job_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return await self._cancel_job(job_id)

        return None

    async def _get_stats(self) -> HandlerResult:
        """Get queue statistics."""
        queue = await _get_queue()
        if queue is None:
            return json_response(
                {
                    "error": "Queue not available",
                    "message": "Redis queue is not configured or unavailable",
                    "stats": {
                        "pending": 0,
                        "processing": 0,
                        "completed": 0,
                        "failed": 0,
                        "cancelled": 0,
                        "retrying": 0,
                        "stream_length": 0,
                        "pending_in_group": 0,
                    },
                },
                status=503,
            )

        try:
            stats = await queue.get_queue_stats()
            return json_response(
                {
                    "stats": stats,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to get queue stats due to connection error: %s", e)
            return error_response(safe_error_message(e, "get queue stats"), 503)
        except (AttributeError, KeyError) as e:
            logger.error("Data structure error getting queue stats: %s", e)
            return error_response("Internal data error", 500)

    async def _get_workers(self) -> HandlerResult:
        """Get worker status.

        Note: This provides limited info since workers are separate processes.
        Full worker monitoring requires a dedicated worker registry.
        """
        queue = await _get_queue()
        if queue is None:
            return json_response(
                {
                    "workers": [],
                    "total": 0,
                    "message": "Queue not available",
                },
                status=503,
            )

        try:
            # Workers are tracked via consumer group in Redis
            # This gives us consumer info from xinfo groups
            redis_client = queue._redis
            groups_info = await redis_client.xinfo_groups(queue.stream_key)

            workers: list[dict[str, Any]] = []
            for group in groups_info:
                if isinstance(group, dict):
                    # Get consumers in this group
                    try:
                        consumers = await redis_client.xinfo_consumers(
                            queue.stream_key, group.get("name", "")
                        )
                        for consumer in consumers:
                            if isinstance(consumer, dict):
                                workers.append(
                                    {
                                        "worker_id": consumer.get("name", "unknown"),
                                        "group": group.get("name", "unknown"),
                                        "pending": consumer.get("pending", 0),
                                        "idle_ms": consumer.get("idle", 0),
                                    }
                                )
                    except REDIS_CONNECTION_ERRORS as ce:
                        logger.debug("Could not get consumers due to connection error: %s", ce)
                    except (KeyError, TypeError, AttributeError) as ce:
                        logger.debug("Consumer data parsing error: %s", ce)

            return json_response(
                {
                    "workers": workers,
                    "total": len(workers),
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to get worker status due to connection error: %s", e)
            return json_response(
                {
                    "workers": [],
                    "total": 0,
                    "error": "Connection error retrieving worker status",
                }
            )
        except (KeyError, TypeError, AttributeError) as e:
            logger.error("Data structure error getting worker status: %s", e)
            return json_response(
                {
                    "workers": [],
                    "total": 0,
                    "error": "Internal data error",
                }
            )

    async def _submit_job(self, handler: Any) -> HandlerResult:
        """Submit a new job to the queue."""
        queue = await _get_queue()
        if queue is None:
            return error_response("Queue not available", 503)

        # Parse request body
        data = self.read_json_body(handler)
        if data is None:
            return error_response("Invalid or too large request body", 400)

        # Validate required fields
        question = data.get("question")
        if not question:
            return error_response("Missing required field: question", 400)

        try:
            from aragora.queue import create_debate_job

            # Create job from request
            job = create_debate_job(
                question=question,
                agents=data.get("agents"),
                rounds=data.get("rounds", DEFAULT_ROUNDS),
                consensus=data.get("consensus", DEFAULT_CONSENSUS),
                protocol=data.get("protocol", "standard"),
                priority=data.get("priority", 0),
                max_attempts=data.get("max_attempts", 3),
                timeout_seconds=data.get("timeout_seconds"),
                webhook_url=data.get("webhook_url"),
                user_id=data.get("user_id"),
                organization_id=data.get("organization_id"),
                metadata=data.get("metadata"),
            )

            # Enqueue
            job_id = await queue.enqueue(job, priority=data.get("priority", 0))

            audit_data(
                user_id=data.get("user_id", "system"),
                resource_type="queue_job",
                resource_id=job_id,
                action="create",
                job_type="debate",
                priority=data.get("priority", 0),
            )

            return json_response(
                {
                    "job_id": job_id,
                    "status": "pending",
                    "message": "Job submitted successfully",
                },
                status=202,
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid job submission data: %s", e)
            return error_response(safe_error_message(e, "submit job"), 400)
        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to submit job due to connection error: %s", e)
            return error_response(safe_error_message(e, "submit job"), 503)
        except AttributeError as e:
            logger.error("Queue interface error: %s", e)
            return error_response("Queue configuration error", 500)

    async def _list_jobs(self, query_params: dict[str, Any]) -> HandlerResult:
        """List jobs with optional filtering."""
        queue = await _get_queue()
        if queue is None:
            return json_response(
                {
                    "jobs": [],
                    "total": 0,
                    "message": "Queue not available",
                },
                status=503,
            )

        try:
            from aragora.queue import JobStatus

            # Parse filters
            limit, offset = self.get_pagination(query_params)
            status_filter = get_string_param(query_params, "status", None)

            # Convert status string to enum
            status_enum = None
            if status_filter:
                try:
                    status_enum = JobStatus(status_filter)
                except ValueError:
                    return error_response(
                        f"Invalid status: {status_filter}. "
                        f"Valid values: {[s.value for s in JobStatus]}",
                        400,
                    )

            # Get jobs from status tracker
            jobs = await queue._status_tracker.list_jobs(
                status=status_enum,
                limit=limit + offset,  # Get extra for pagination
            )

            # Apply offset
            jobs = jobs[offset : offset + limit]

            # Format response
            jobs_data = [
                {
                    "job_id": job.id,
                    "status": job.status.value,
                    "created_at": datetime.fromtimestamp(job.created_at).isoformat(),
                    "started_at": (
                        datetime.fromtimestamp(job.started_at).isoformat()
                        if job.started_at
                        else None
                    ),
                    "completed_at": (
                        datetime.fromtimestamp(job.completed_at).isoformat()
                        if job.completed_at
                        else None
                    ),
                    "attempts": job.attempts,
                    "max_attempts": job.max_attempts,
                    "priority": job.priority,
                    "error": job.error,
                    "worker_id": job.worker_id,
                    "metadata": {
                        k: v
                        for k, v in job.metadata.items()
                        if not k.startswith("_")  # Hide internal fields
                    },
                }
                for job in jobs
            ]

            # Get total count
            counts = await queue._status_tracker.get_counts_by_status()
            total = sum(counts.values())

            return json_response(
                {
                    "jobs": jobs_data,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "counts_by_status": counts,
                }
            )

        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to list jobs due to connection error: %s", e)
            return error_response(safe_error_message(e, "list jobs"), 503)
        except (AttributeError, KeyError, TypeError) as e:
            logger.error("Data structure error listing jobs: %s", e)
            return error_response("Internal data error", 500)

    async def _get_job(self, job_id: str) -> HandlerResult:
        """Get a specific job's status."""
        queue = await _get_queue()
        if queue is None:
            return error_response("Queue not available", 503)

        try:
            job = await queue.get_status(job_id)
            if job is None:
                return error_response(f"Job not found: {job_id}", 404)

            return json_response(
                {
                    "job_id": job.id,
                    "status": job.status.value,
                    "created_at": datetime.fromtimestamp(job.created_at).isoformat(),
                    "started_at": (
                        datetime.fromtimestamp(job.started_at).isoformat()
                        if job.started_at
                        else None
                    ),
                    "completed_at": (
                        datetime.fromtimestamp(job.completed_at).isoformat()
                        if job.completed_at
                        else None
                    ),
                    "attempts": job.attempts,
                    "max_attempts": job.max_attempts,
                    "priority": job.priority,
                    "error": job.error,
                    "worker_id": job.worker_id,
                    "payload": job.payload,
                    "metadata": {k: v for k, v in job.metadata.items() if not k.startswith("_")},
                    "result": job.metadata.get("result"),
                }
            )

        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to get job %s due to connection error: %s", job_id, e)
            return error_response(safe_error_message(e, "get job"), 503)
        except (AttributeError, KeyError, TypeError) as e:
            logger.error("Data structure error getting job %s: %s", job_id, e)
            return error_response("Internal data error", 500)

    async def _retry_job(self, job_id: str) -> HandlerResult:
        """Retry a failed job."""
        queue = await _get_queue()
        if queue is None:
            return error_response("Queue not available", 503)

        try:
            from aragora.queue import JobStatus

            # Get job status
            job = await queue.get_status(job_id)
            if job is None:
                return error_response(f"Job not found: {job_id}", 404)

            # Can only retry failed or cancelled jobs
            if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
                return error_response(
                    f"Cannot retry job with status: {job.status.value}. "
                    "Only failed or cancelled jobs can be retried.",
                    400,
                )

            # Reset job for retry
            job.status = JobStatus.PENDING
            job.attempts = 0
            job.error = None
            job.started_at = None
            job.completed_at = None
            job.worker_id = None

            # Re-enqueue
            await queue.enqueue(job, priority=job.priority)

            audit_admin(
                admin_id="system",
                action="retry_job",
                target_type="queue_job",
                target_id=job_id,
            )

            return json_response(
                {
                    "job_id": job_id,
                    "status": "pending",
                    "message": "Job queued for retry",
                }
            )

        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to retry job %s due to connection error: %s", job_id, e)
            return error_response(safe_error_message(e, "retry job"), 503)
        except (AttributeError, KeyError) as e:
            logger.error("Data structure error retrying job %s: %s", job_id, e)
            return error_response("Internal data error", 500)

    async def _cancel_job(self, job_id: str) -> HandlerResult:
        """Cancel a pending job."""
        queue = await _get_queue()
        if queue is None:
            return error_response("Queue not available", 503)

        try:
            cancelled = await queue.cancel(job_id)
            if not cancelled:
                # Check if job exists
                job = await queue.get_status(job_id)
                if job is None:
                    return error_response(f"Job not found: {job_id}", 404)
                else:
                    return error_response(
                        f"Cannot cancel job with status: {job.status.value}. "
                        "Only pending or retrying jobs can be cancelled.",
                        400,
                    )

            audit_admin(
                admin_id="system",
                action="cancel_job",
                target_type="queue_job",
                target_id=job_id,
            )

            return json_response(
                {
                    "job_id": job_id,
                    "status": "cancelled",
                    "message": "Job cancelled successfully",
                }
            )

        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to cancel job %s due to connection error: %s", job_id, e)
            return error_response(safe_error_message(e, "cancel job"), 503)
        except (AttributeError, KeyError) as e:
            logger.error("Data structure error cancelling job %s: %s", job_id, e)
            return error_response("Internal data error", 500)

    async def _list_dlq(self, query_params: dict[str, Any]) -> HandlerResult:
        """
        List jobs in the dead-letter queue (failed with max retries exceeded).

        Query params:
        - limit: Max jobs to return (default: 50, max: 100)
        - offset: Pagination offset (default: 0)

        Response:
        {
            "jobs": [
                {
                    "job_id": "...",
                    "job_type": "debate",
                    "status": "failed",
                    "attempts": 3,
                    "max_attempts": 3,
                    "error": "...",
                    "created_at": "...",
                    "failed_at": "...",
                    "age_hours": 24.5
                }
            ],
            "total": 15,
            "limit": 50,
            "offset": 0
        }
        """
        queue = await _get_queue()
        if queue is None:
            return error_response("Queue not available", 503)

        limit = safe_query_int(query_params, "limit", default=50, min_val=1, max_val=100)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=10000)

        try:
            from aragora.queue import JobStatus

            # Get all failed jobs where attempts >= max_attempts
            all_jobs = await queue.list_jobs(status=JobStatus.FAILED, limit=500)

            dlq_jobs = []
            for job in all_jobs:
                if job.attempts >= job.max_attempts:
                    age_hours = 0.0
                    if job.completed_at:
                        age_hours = (datetime.now().timestamp() - job.completed_at) / 3600

                    dlq_jobs.append(
                        {
                            "job_id": job.id,
                            "job_type": job.job_type,
                            "status": job.status.value,
                            "attempts": job.attempts,
                            "max_attempts": job.max_attempts,
                            "error": job.error,
                            "created_at": datetime.fromtimestamp(job.created_at).isoformat(),
                            "failed_at": (
                                datetime.fromtimestamp(job.completed_at).isoformat()
                                if job.completed_at
                                else None
                            ),
                            "age_hours": round(age_hours, 1),
                            "payload": job.payload,
                        }
                    )

            # Apply pagination
            total = len(dlq_jobs)
            dlq_jobs = dlq_jobs[offset : offset + limit]

            return json_response(
                {
                    "jobs": dlq_jobs,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            )

        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to list DLQ due to connection error: %s", e)
            return error_response(safe_error_message(e, "list DLQ"), 503)
        except (AttributeError, KeyError, TypeError) as e:
            logger.error("Data structure error listing DLQ: %s", e)
            return error_response("Internal data error", 500)

    async def _requeue_dlq_job(self, job_id: str) -> HandlerResult:
        """Requeue a specific job from the DLQ."""
        queue = await _get_queue()
        if queue is None:
            return error_response("Queue not available", 503)

        try:
            from aragora.queue import JobStatus

            job = await queue.get_status(job_id)
            if job is None:
                return error_response(f"Job not found: {job_id}", 404)

            if job.status != JobStatus.FAILED:
                return error_response(
                    f"Job is not in DLQ (status: {job.status.value})",
                    400,
                )

            # Reset job and requeue
            job.status = JobStatus.PENDING
            job.attempts = 0
            job.error = None
            job.started_at = None
            job.completed_at = None
            job.worker_id = None
            job.metadata["requeued_from_dlq"] = True
            job.metadata["requeued_at"] = datetime.now().isoformat()

            await queue.enqueue(job, priority=job.priority)

            audit_admin(
                admin_id="system",
                action="requeue_dlq_job",
                target_type="queue_job",
                target_id=job_id,
            )

            return json_response(
                {
                    "job_id": job_id,
                    "status": "pending",
                    "message": "Job requeued from DLQ",
                }
            )

        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to requeue DLQ job %s: %s", job_id, e)
            return error_response(safe_error_message(e, "requeue DLQ job"), 503)
        except (AttributeError, KeyError) as e:
            logger.error("Data structure error requeuing DLQ job %s: %s", job_id, e)
            return error_response("Internal data error", 500)

    async def _requeue_all_dlq(self) -> HandlerResult:
        """Requeue all jobs from the DLQ."""
        queue = await _get_queue()
        if queue is None:
            return error_response("Queue not available", 503)

        try:
            from aragora.queue import JobStatus

            # Get all failed jobs
            all_jobs = await queue.list_jobs(status=JobStatus.FAILED, limit=1000)

            requeued = 0
            errors = []

            for job in all_jobs:
                if job.attempts >= job.max_attempts:
                    try:
                        job.status = JobStatus.PENDING
                        job.attempts = 0
                        job.error = None
                        job.started_at = None
                        job.completed_at = None
                        job.worker_id = None
                        job.metadata["requeued_from_dlq"] = True
                        job.metadata["requeued_at"] = datetime.now().isoformat()

                        await queue.enqueue(job, priority=job.priority)
                        requeued += 1
                    except REDIS_CONNECTION_ERRORS as e:
                        logger.warning("Failed to requeue job %s: %s", job.id, e)
                        errors.append({"job_id": job.id, "error": "Failed to requeue job"})
                    except AttributeError as e:
                        logger.warning("Failed to requeue job %s: %s", job.id, e)
                        errors.append({"job_id": job.id, "error": "Failed to requeue job"})

            if requeued > 0:
                audit_admin(
                    admin_id="system",
                    action="requeue_all_dlq",
                    target_type="queue",
                    target_id="dlq",
                    requeued_count=requeued,
                    error_count=len(errors),
                )

            return json_response(
                {
                    "requeued": requeued,
                    "errors": len(errors),
                    "error_details": errors[:10],  # First 10 errors
                    "message": f"Requeued {requeued} jobs from DLQ",
                }
            )

        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to requeue all DLQ: %s", e)
            return error_response(safe_error_message(e, "requeue all DLQ"), 503)
        except (AttributeError, KeyError) as e:
            logger.error("Data structure error requeuing all DLQ: %s", e)
            return error_response("Internal data error", 500)

    async def _cleanup_jobs(self, query_params: dict[str, Any]) -> HandlerResult:
        """
        Cleanup old completed/failed jobs.

        Query params:
        - older_than_days: Delete jobs older than N days (default: 7)
        - status: Status to cleanup ('completed', 'failed', 'all') (default: 'completed')
        - dry_run: If 'true', only count jobs without deleting (default: 'false')
        """
        queue = await _get_queue()
        if queue is None:
            return error_response("Queue not available", 503)

        older_than_days = safe_query_int(
            query_params, "older_than_days", default=7, min_val=1, max_val=365
        )
        status_filter = query_params.get("status", ["completed"])[0]
        dry_run = query_params.get("dry_run", ["false"])[0].lower() == "true"

        try:
            from aragora.queue import JobStatus

            cutoff = datetime.now().timestamp() - (older_than_days * 86400)
            deleted = 0
            scanned = 0

            statuses_to_check = []
            if status_filter == "all":
                statuses_to_check = [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]
            elif status_filter == "completed":
                statuses_to_check = [JobStatus.COMPLETED]
            elif status_filter == "failed":
                statuses_to_check = [JobStatus.FAILED]
            else:
                return error_response(f"Invalid status: {status_filter}", 400)

            for status in statuses_to_check:
                jobs = await queue.list_jobs(status=status, limit=1000)
                for job in jobs:
                    scanned += 1
                    job_time = job.completed_at or job.created_at
                    if job_time < cutoff:
                        if not dry_run:
                            try:
                                await queue.delete(job.id)
                                deleted += 1
                            except REDIS_CONNECTION_ERRORS as e:
                                logger.warning("Failed to delete job %s: %s", job.id, e)
                        else:
                            deleted += 1

            return json_response(
                {
                    "scanned": scanned,
                    "deleted": deleted if not dry_run else 0,
                    "would_delete": deleted if dry_run else None,
                    "older_than_days": older_than_days,
                    "status_filter": status_filter,
                    "dry_run": dry_run,
                }
            )

        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to cleanup jobs: %s", e)
            return error_response(safe_error_message(e, "cleanup jobs"), 503)
        except (AttributeError, KeyError, TypeError) as e:
            logger.error("Data structure error cleaning up jobs: %s", e)
            return error_response("Internal data error", 500)

    async def _list_stale_jobs(self, query_params: dict[str, Any]) -> HandlerResult:
        """
        List stale/stuck jobs (processing for too long).

        Query params:
        - stale_minutes: Consider job stale after N minutes (default: 60)
        - limit: Max jobs to return (default: 50)
        """
        queue = await _get_queue()
        if queue is None:
            return error_response("Queue not available", 503)

        stale_minutes = safe_query_int(
            query_params, "stale_minutes", default=60, min_val=1, max_val=1440
        )
        limit = safe_query_int(query_params, "limit", default=50, min_val=1, max_val=100)

        try:
            from aragora.queue import JobStatus

            cutoff = datetime.now().timestamp() - (stale_minutes * 60)
            stale_jobs = []

            # Check processing jobs
            processing = await queue.list_jobs(status=JobStatus.PROCESSING, limit=500)
            for job in processing:
                if job.started_at and job.started_at < cutoff:
                    duration_minutes = (datetime.now().timestamp() - job.started_at) / 60
                    stale_jobs.append(
                        {
                            "job_id": job.id,
                            "job_type": job.job_type,
                            "status": job.status.value,
                            "worker_id": job.worker_id,
                            "started_at": datetime.fromtimestamp(job.started_at).isoformat(),
                            "duration_minutes": round(duration_minutes, 1),
                            "attempts": job.attempts,
                        }
                    )

            # Sort by duration (longest first)
            stale_jobs.sort(key=lambda j: j["duration_minutes"], reverse=True)
            stale_jobs = stale_jobs[:limit]

            return json_response(
                {
                    "jobs": stale_jobs,
                    "total": len(stale_jobs),
                    "stale_threshold_minutes": stale_minutes,
                }
            )

        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to list stale jobs: %s", e)
            return error_response(safe_error_message(e, "list stale jobs"), 503)
        except (AttributeError, KeyError, TypeError) as e:
            logger.error("Data structure error listing stale jobs: %s", e)
            return error_response("Internal data error", 500)


__all__ = [
    "QueueHandler",
    "get_queue_circuit_breaker",
    "get_queue_circuit_breaker_status",
]
