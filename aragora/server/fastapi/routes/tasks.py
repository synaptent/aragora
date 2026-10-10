"""
FastAPI v2 routes for Control Plane Task Management.

Migrated from aragora.server.handlers.control_plane.tasks.TaskHandlerMixin.
Provides endpoints for task CRUD, claiming, queue management, and deliberations.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from aragora.tenancy.record_scope import OrgScope, record_not_found_error, require_org_scope_fastapi

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["Tasks"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


def _empty_queue_metrics() -> dict[str, int]:
    return {
        "pending": 0,
        "running": 0,
        "completed_today": 0,
        "failed_today": 0,
        "avg_wait_time_ms": 0,
        "avg_execution_time_ms": 0,
        "throughput_per_minute": 0,
    }


def _queue_metrics_from_stats(stats: Any) -> dict[str, Any]:
    if not isinstance(stats, dict):
        return _empty_queue_metrics()

    return {
        "pending": stats.get("pending_tasks", 0),
        "running": stats.get("running_tasks", 0),
        "completed_today": stats.get("completed_tasks", 0),
        "failed_today": stats.get("failed_tasks", 0),
        "avg_wait_time_ms": stats.get("avg_wait_time_ms", 0),
        "avg_execution_time_ms": stats.get("avg_execution_time_ms", 0),
        "throughput_per_minute": stats.get("throughput_per_minute", 0),
    }


class SubmitTaskRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_type: str
    payload: dict[str, Any] = {}
    required_capabilities: list[str] = []
    priority: str = "normal"
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = {}


class ClaimTaskRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    agent_id: str
    capabilities: list[str] = []
    block_ms: int = 5000


class CompleteTaskRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    result: Any = None
    agent_id: str | None = None
    latency_ms: float | None = None


class FailTaskRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    error: str = "Unknown error"
    agent_id: str | None = None
    latency_ms: float | None = None
    requeue: bool = True


class SubmitDeliberationRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    content: str
    async_mode: bool = False
    priority: str = "normal"
    required_capabilities: list[str] | None = None
    timeout_seconds: float | None = None
    mode: str | None = None
    context: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def _get_coordinator(request: Any = Depends(lambda request: request)):
    """Get the control plane coordinator from app state."""
    from fastapi import Request as FastAPIRequest

    if not isinstance(request, FastAPIRequest):
        return None
    ctx = getattr(request.app.state, "context", {})
    return ctx.get("control_plane_coordinator")


def _require_coordinator(request: Any = Depends(lambda request: request)):
    """Require coordinator or raise 503."""
    from fastapi import Request as FastAPIRequest

    if not isinstance(request, FastAPIRequest):
        raise HTTPException(status_code=503, detail="Control plane not initialized")
    ctx = getattr(request.app.state, "context", {})
    coord = ctx.get("control_plane_coordinator")
    if not coord:
        raise HTTPException(status_code=503, detail="Control plane not initialized")
    return coord


# ---------------------------------------------------------------------------
# Task endpoints
# ---------------------------------------------------------------------------


@router.post("/tasks", status_code=201)
async def submit_task(body: SubmitTaskRequest):
    """Submit a new task to the control plane."""
    try:
        from aragora.control_plane.integration import get_integrated_control_plane
        from aragora.control_plane.scheduler import TaskPriority

        cp = get_integrated_control_plane()
        if not cp:
            raise HTTPException(status_code=503, detail="Control plane not initialized")

        try:
            priority_enum = TaskPriority[body.priority.upper()]
        except KeyError:
            raise HTTPException(status_code=400, detail=f"Invalid priority: {body.priority}")

        task_id = await cp.submit_task(
            task_type=body.task_type,
            payload=body.payload,
            required_capabilities=body.required_capabilities,
            priority=priority_enum,
            timeout_seconds=body.timeout_seconds,
            metadata=body.metadata,
        )

        return {"data": {"task_id": task_id}}
    except HTTPException:
        raise
    except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Error submitting task: %s", e)
        raise HTTPException(status_code=500, detail="Failed to submit task")


@router.post("/tasks/claim")
async def claim_task(body: ClaimTaskRequest):
    """Claim next available task for an agent."""
    try:
        from aragora.control_plane.integration import get_integrated_control_plane

        cp = get_integrated_control_plane()
        if not cp:
            raise HTTPException(status_code=503, detail="Control plane not initialized")

        task = await cp.coordinator.claim_task(
            agent_id=body.agent_id,
            capabilities=body.capabilities,
            block_ms=body.block_ms,
        )

        if not task:
            return {"data": {"task": None}}

        return {"data": {"task": task.to_dict()}}
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Error claiming task: %s", e)
        raise HTTPException(status_code=500, detail="Failed to claim task")


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: str, body: CompleteTaskRequest):
    """Mark task as completed."""
    try:
        from aragora.control_plane.integration import get_integrated_control_plane

        cp = get_integrated_control_plane()
        if not cp:
            raise HTTPException(status_code=503, detail="Control plane not initialized")

        success = await cp.complete_task(
            task_id=task_id,
            result=body.result,
            agent_id=body.agent_id,
            latency_ms=body.latency_ms,
        )

        if not success:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

        return {"data": {"completed": True}}
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Error completing task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Failed to complete task")


@router.post("/tasks/{task_id}/fail")
async def fail_task(task_id: str, body: FailTaskRequest):
    """Mark task as failed."""
    try:
        from aragora.control_plane.integration import get_integrated_control_plane

        cp = get_integrated_control_plane()
        if not cp:
            raise HTTPException(status_code=503, detail="Control plane not initialized")

        success = await cp.fail_task(
            task_id=task_id,
            error=body.error,
            agent_id=body.agent_id,
            latency_ms=body.latency_ms,
            requeue=body.requeue,
        )

        if not success:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

        return {"data": {"failed": True}}
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Error failing task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Failed to fail task")


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a task."""
    try:
        from aragora.control_plane.integration import get_integrated_control_plane

        cp = get_integrated_control_plane()
        if not cp:
            raise HTTPException(status_code=503, detail="Control plane not initialized")

        success = await cp.coordinator.cancel_task(task_id)
        if not success:
            raise HTTPException(
                status_code=404, detail=f"Task not found or already completed: {task_id}"
            )

        return {"data": {"cancelled": True}}
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Error cancelling task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Failed to cancel task")


# ---------------------------------------------------------------------------
# Queue endpoints
# ---------------------------------------------------------------------------


@router.get("/queue")
async def get_queue(limit: int = Query(default=50, ge=1, le=1000)):
    """Get current job queue (pending and running tasks)."""
    try:
        from aragora.control_plane.integration import get_integrated_control_plane
        from aragora.control_plane.scheduler import TaskStatus
        from datetime import datetime

        cp = get_integrated_control_plane()
        if not cp:
            raise HTTPException(status_code=503, detail="Control plane not initialized")

        scheduler = cp.coordinator._scheduler_bridge._scheduler
        pending = await scheduler.list_by_status(TaskStatus.PENDING, limit=limit)
        running = await scheduler.list_by_status(TaskStatus.RUNNING, limit=limit)

        def task_to_job(task: Any) -> dict[str, Any]:
            progress = 0.0
            if task.status.value == "running":
                progress = task.metadata.get("progress", 0.5)
            elif task.status.value == "completed":
                progress = 1.0

            return {
                "id": task.id,
                "type": task.task_type,
                "name": task.metadata.get("name", f"{task.task_type} task"),
                "status": task.status.value,
                "progress": progress,
                "started_at": (
                    datetime.fromtimestamp(task.started_at).isoformat() if task.started_at else None
                ),
                "created_at": (
                    datetime.fromtimestamp(task.created_at).isoformat() if task.created_at else None
                ),
                "document_count": task.payload.get("document_count", 0),
                "agents_assigned": [task.assigned_agent] if task.assigned_agent else [],
                "priority": task.priority.name.lower(),
            }

        jobs = [task_to_job(t) for t in running] + [task_to_job(t) for t in pending]

        return {"data": {"jobs": jobs, "total": len(jobs)}}
    except HTTPException:
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ImportError,
    ) as e:
        logger.error("Error getting queue: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get queue")


@router.get("/queue/metrics")
async def get_queue_metrics():
    """Get task queue performance metrics."""
    try:
        import inspect

        from aragora.control_plane.integration import get_integrated_control_plane

        cp = get_integrated_control_plane()
        stats = _empty_queue_metrics()

        stats_getter = getattr(cp, "get_stats", None) if cp else None
        if callable(stats_getter):
            maybe_stats = stats_getter()
            if inspect.isawaitable(maybe_stats):
                maybe_stats = await maybe_stats
            stats = _queue_metrics_from_stats(maybe_stats)

        return {"data": stats}
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Error getting queue metrics: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get queue metrics")


# ---------------------------------------------------------------------------
# Task history
# ---------------------------------------------------------------------------


@router.get("/tasks/history")
async def get_task_history(
    status: str | None = Query(default=None),
    task_type: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0, le=10000),
):
    """Get task execution history for auditing and analysis."""
    try:
        from aragora.control_plane.integration import get_integrated_control_plane
        from aragora.control_plane.scheduler import TaskStatus
        from datetime import datetime

        cp = get_integrated_control_plane()
        if not cp:
            raise HTTPException(status_code=503, detail="Control plane not initialized")

        history_statuses = [
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMEOUT,
        ]

        if status:
            status_map = {
                "completed": TaskStatus.COMPLETED,
                "failed": TaskStatus.FAILED,
                "cancelled": TaskStatus.CANCELLED,
                "timeout": TaskStatus.TIMEOUT,
            }
            if status.lower() in status_map:
                history_statuses = [status_map[status.lower()]]

        scheduler = cp.coordinator._scheduler_bridge._scheduler
        all_tasks = []
        for st in history_statuses:
            tasks = await scheduler.list_by_status(st, limit=limit + offset)
            all_tasks.extend(tasks)

        if task_type:
            all_tasks = [t for t in all_tasks if t.task_type == task_type]
        if agent_id:
            all_tasks = [t for t in all_tasks if t.assigned_agent == agent_id]

        all_tasks.sort(
            key=lambda t: t.completed_at or t.created_at or 0,
            reverse=True,
        )

        total = len(all_tasks)
        paginated = all_tasks[offset : offset + limit]

        def task_to_history(task: Any) -> dict[str, Any]:
            duration_ms = None
            if task.started_at and task.completed_at:
                duration_ms = int((task.completed_at - task.started_at) * 1000)

            return {
                "id": task.id,
                "type": task.task_type,
                "status": task.status.value,
                "priority": task.priority.name.lower(),
                "assigned_agent": task.assigned_agent,
                "result": task.result if task.status == TaskStatus.COMPLETED else None,
                "error": task.error if task.status == TaskStatus.FAILED else None,
                "retries": task.retries,
                "duration_ms": duration_ms,
                "created_at": (
                    datetime.fromtimestamp(task.created_at).isoformat() if task.created_at else None
                ),
                "started_at": (
                    datetime.fromtimestamp(task.started_at).isoformat() if task.started_at else None
                ),
                "completed_at": (
                    datetime.fromtimestamp(task.completed_at).isoformat()
                    if task.completed_at
                    else None
                ),
                "metadata": {
                    k: v
                    for k, v in task.metadata.items()
                    if k in ("name", "workspace_id", "user_id", "tags")
                },
            }

        history = [task_to_history(t) for t in paginated]

        return {
            "data": {
                "history": history,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total,
            }
        }
    except HTTPException:
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ImportError,
    ) as e:
        logger.error("Error getting task history: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get task history")


# ---------------------------------------------------------------------------
# Deliberation endpoints
# ---------------------------------------------------------------------------


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get task by ID."""
    try:
        from aragora.control_plane.integration import get_integrated_control_plane

        cp = get_integrated_control_plane()
        if not cp:
            raise HTTPException(status_code=503, detail="Control plane not initialized")

        task = await cp.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

        return {"data": task.to_dict()}
    except HTTPException:
        raise
    except (ValueError, KeyError, AttributeError, TypeError, RuntimeError, OSError) as e:
        logger.error("Error getting task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Failed to get task")


@router.get("/deliberations/{request_id}")
async def get_deliberation(request_id: str, scope: OrgScope = Depends(require_org_scope_fastapi)):
    """Get a deliberation result the caller's org owns (404 otherwise)."""
    try:
        from aragora.core.decision_results import get_decision_result_for_org

        result = get_decision_result_for_org(request_id, scope.org_id)
    except (ImportError, ValueError, KeyError, AttributeError) as e:
        logger.error("Error getting deliberation %s: %s", request_id, e)
        raise HTTPException(status_code=500, detail="Failed to get deliberation")
    if result is None:
        raise record_not_found_error("Deliberation")
    return {"data": result}


@router.get("/deliberations/{request_id}/status")
async def get_deliberation_status(
    request_id: str, scope: OrgScope = Depends(require_org_scope_fastapi)
):
    """Get the polling status of a deliberation the caller's org owns (404 otherwise)."""
    try:
        from aragora.core.decision_results import get_decision_status_for_org

        status = get_decision_status_for_org(request_id, scope.org_id)
    except (ImportError, ValueError, KeyError, AttributeError) as e:
        logger.error("Error getting deliberation status %s: %s", request_id, e)
        raise HTTPException(status_code=500, detail="Failed to get deliberation status")
    if status is None:
        raise record_not_found_error("Deliberation")
    return {"data": status}


@router.post("/deliberations", status_code=202)
async def submit_deliberation(
    body: SubmitDeliberationRequest, scope: OrgScope = Depends(require_org_scope_fastapi)
):
    """Submit a deliberation (sync or async via control plane)."""
    owner = {"org_id": scope.org_id, "created_by": scope.user_id}
    try:
        from aragora.control_plane.integration import get_integrated_control_plane

        cp = get_integrated_control_plane()
        if not cp:
            raise HTTPException(status_code=503, detail="Control plane not initialized")

        if not body.content:
            raise HTTPException(status_code=400, detail="Missing required field: content")

        async_mode = body.async_mode or body.mode == "async"
        required_capabilities = body.required_capabilities or ["deliberation"]

        if async_mode:
            from aragora.control_plane.scheduler import TaskPriority

            try:
                priority_enum = TaskPriority[body.priority.upper()]
            except KeyError:
                raise HTTPException(status_code=400, detail=f"Invalid priority: {body.priority}")

            import uuid

            request_id = str(uuid.uuid4())

            task_id = await cp.submit_task(
                task_type="deliberation",
                payload={
                    "content": body.content,
                    "context": {
                        **body.context,
                        "workspace_id": scope.org_id,
                        "user_id": scope.user_id,
                    },
                },
                required_capabilities=required_capabilities,
                priority=priority_enum,
                timeout_seconds=body.timeout_seconds,
                metadata={"request_id": request_id, **owner},
            )

            return {
                "data": {
                    "task_id": task_id,
                    "request_id": request_id,
                    "status": "queued",
                }
            }

        # Synchronous deliberation
        from aragora.control_plane.deliberation import run_deliberation
        from aragora.core.decision import DecisionRequest

        import asyncio

        request = DecisionRequest(content=body.content)

        try:
            result = await run_deliberation(request, **owner)
            return {
                "data": {
                    "request_id": request.request_id,
                    "status": "completed" if result.success else "failed",
                    "decision_type": result.decision_type.value,
                    "answer": result.answer,
                    "confidence": result.confidence,
                    "consensus_reached": result.consensus_reached,
                    "reasoning": result.reasoning,
                    "evidence_used": result.evidence_used,
                    "duration_seconds": result.duration_seconds,
                    "error": result.error,
                }
            }
        except asyncio.TimeoutError:
            raise HTTPException(status_code=408, detail="Deliberation timed out")
    except HTTPException:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
        OSError,
        ImportError,
    ) as e:
        logger.error("Deliberation failed: %s", e)
        raise HTTPException(status_code=500, detail="Deliberation failed")
