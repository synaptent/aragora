"""
Task management handlers for Control Plane.

Provides REST API endpoints for:
- Task submission and status
- Task claiming and completion
- Task queue management
- Deliberation handling
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
from typing import Any, cast

from aragora.server.http_utils import run_async as _run_async
from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
    safe_error_message,
)
from aragora.server.handlers.openapi_decorator import api_endpoint
from aragora.server.handlers.utils.decorators import has_permission as _has_permission
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.validation.query_params import safe_query_int
from aragora.tenancy.record_scope import OrgScope, record_not_found

logger = logging.getLogger(__name__)


def _get_has_permission():
    control_plane = sys.modules.get("aragora.server.handlers.control_plane")
    if control_plane is not None:
        candidate = getattr(control_plane, "has_permission", None)
        if callable(candidate):
            return candidate
    return _has_permission


async def _await_if_needed(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


class TaskHandlerMixin:
    """
    Mixin class providing task management handlers.

    This mixin provides methods for:
    - Getting task details
    - Submitting new tasks
    - Claiming tasks for agents
    - Completing and failing tasks
    - Cancelling tasks
    - Managing the task queue
    - Handling deliberations
    """

    # These methods are expected from the base class (ControlPlaneHandler).
    # Default implementations provide graceful degradation when the mixin
    # is used without the concrete class overriding them.
    def _get_coordinator(self) -> Any | None:
        """Get the control plane coordinator.

        Returns the coordinator instance, or None if not initialized.
        The concrete ControlPlaneHandler overrides this to pull from
        the class attribute or server context.
        """
        return getattr(self, "ctx", {}).get("control_plane_coordinator")

    def _require_coordinator(self) -> tuple[Any, HandlerResult | None]:
        """Return coordinator and None, or None and error response if not initialized."""
        coord = self._get_coordinator()
        if not coord:
            return None, error_response("Control plane not initialized", 503)
        return coord, None

    def _handle_coordinator_error(self, error: Exception, operation: str) -> HandlerResult:
        """Unified error handler for coordinator operations."""
        if isinstance(error, (ValueError, KeyError, AttributeError)):
            logger.warning("Data error in %s: %s: %s", operation, type(error).__name__, error)
            return error_response(safe_error_message(error, "control plane"), 400)
        logger.error("Error in %s: %s", operation, error)
        return error_response(safe_error_message(error, "control plane"), 500)

    def _get_stream(self) -> Any | None:
        """Get the control plane stream server."""
        return getattr(self, "ctx", {}).get("control_plane_stream")

    def _emit_event(
        self,
        emit_method: str,
        *args: Any,
        max_retries: int = 3,
        base_delay: float = 0.1,
        **kwargs: Any,
    ) -> None:
        """Emit an event to the control plane stream.

        Default implementation is a no-op. The concrete ControlPlaneHandler
        overrides this with retry logic and async scheduling.
        """
        stream = self._get_stream()
        if not stream:
            return
        method = getattr(stream, emit_method, None)
        if method:
            try:
                _run_async(method(*args, **kwargs))
            except (RuntimeError, OSError, ValueError, AttributeError, TypeError) as e:
                logger.warning("Stream emission failed for %s: %s", emit_method, e)

    def require_auth_or_error(self, handler: Any) -> tuple[Any, HandlerResult | None]:
        """Require authentication and return user or error."""
        # Cast super() to Any - mixin expects base class to provide this method
        return cast(Any, super()).require_auth_or_error(handler)

    # Attribute declaration - provided by BaseHandler
    ctx: dict[str, Any]

    # =========================================================================
    # Task Handlers
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/control-plane/tasks/{task_id}",
        summary="Get task by ID",
        tags=["Control Plane"],
    )
    @require_permission("controlplane:tasks.read")
    def _handle_get_task(self, task_id: str) -> HandlerResult:
        """Get task by ID."""
        coordinator, err = self._require_coordinator()
        if err:
            return err

        try:
            task = _run_async(coordinator.get_task(task_id))

            if not task:
                return error_response(f"Task not found: {task_id}", 404)

            return json_response(task.to_dict())
        except (ValueError, KeyError, AttributeError, TypeError, RuntimeError, OSError) as e:
            return self._handle_coordinator_error(e, f"get_task:{task_id}")

    @api_endpoint(
        method="POST",
        path="/api/control-plane/tasks",
        summary="Submit a new task",
        tags=["Control Plane"],
    )
    def _handle_submit_task(self, body: dict[str, Any], handler: Any) -> HandlerResult:
        """Submit a new task."""
        # Require authentication for task submission
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        # Check permission for task management
        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        coordinator = self._get_coordinator()
        if not coordinator:
            return error_response("Control plane not initialized", 503)

        task_type = body.get("task_type")
        if not task_type:
            return error_response("task_type is required", 400)

        payload = body.get("payload", {})
        required_capabilities = body.get("required_capabilities", [])
        priority = body.get("priority", "normal")
        timeout_seconds = body.get("timeout_seconds")
        metadata = body.get("metadata", {})

        try:
            from aragora.control_plane.scheduler import TaskPriority

            priority_enum = TaskPriority[priority.upper()]

            task_id = _run_async(
                coordinator.submit_task(
                    task_type=task_type,
                    payload=payload,
                    required_capabilities=required_capabilities,
                    priority=priority_enum,
                    timeout_seconds=timeout_seconds,
                    metadata=metadata,
                )
            )

            # Emit event for real-time streaming
            self._emit_event(
                "emit_task_submitted",
                task_id=task_id,
                task_type=task_type,
                priority=priority,
                required_capabilities=required_capabilities,
            )

            return json_response({"task_id": task_id}, status=201)
        except KeyError:
            return error_response(f"Invalid priority: {priority}", 400)
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Error submitting task: %s", e)
            return error_response(safe_error_message(e, "control plane"), 500)

    async def _handle_submit_task_async(self, body: dict[str, Any], handler: Any) -> HandlerResult:
        """Submit a new task (async context)."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        coordinator = self._get_coordinator()
        if not coordinator:
            return error_response("Control plane not initialized", 503)

        task_type = body.get("task_type")
        if not task_type:
            return error_response("task_type is required", 400)

        payload = body.get("payload", {})
        required_capabilities = body.get("required_capabilities", [])
        priority = body.get("priority", "normal")
        timeout_seconds = body.get("timeout_seconds")
        metadata = body.get("metadata", {})

        try:
            from aragora.control_plane.scheduler import TaskPriority

            priority_enum = TaskPriority[priority.upper()]

            task_id = await _await_if_needed(
                coordinator.submit_task(
                    task_type=task_type,
                    payload=payload,
                    required_capabilities=required_capabilities,
                    priority=priority_enum,
                    timeout_seconds=timeout_seconds,
                    metadata=metadata,
                )
            )

            self._emit_event(
                "emit_task_submitted",
                task_id=task_id,
                task_type=task_type,
                priority=priority,
                required_capabilities=required_capabilities,
            )

            return json_response({"task_id": task_id}, status=201)
        except KeyError:
            return error_response(f"Invalid priority: {priority}", 400)
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Error submitting task: %s", e)
            return error_response(safe_error_message(e, "control plane"), 500)

    @api_endpoint(
        method="POST",
        path="/api/control-plane/tasks/claim",
        summary="Claim next available task",
        tags=["Control Plane"],
    )
    @require_permission("controlplane:tasks.claim")
    def _handle_claim_task(self, body: dict[str, Any], handler: Any) -> HandlerResult:
        """Claim a task for an agent."""
        # Require authentication for claiming tasks
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        # Check permission for task management
        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        coordinator = self._get_coordinator()
        if not coordinator:
            return error_response("Control plane not initialized", 503)

        agent_id = body.get("agent_id")
        if not agent_id:
            return error_response("agent_id is required", 400)

        capabilities = body.get("capabilities", [])
        block_ms = body.get("block_ms", 5000)

        try:
            task = _run_async(
                coordinator.claim_task(
                    agent_id=agent_id,
                    capabilities=capabilities,
                    block_ms=block_ms,
                )
            )

            if not task:
                return json_response({"task": None})

            # Emit event for real-time streaming
            self._emit_event(
                "emit_task_claimed",
                task_id=task.id,
                agent_id=agent_id,
            )

            return json_response({"task": task.to_dict()})
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Error claiming task: %s", e)
            return error_response(safe_error_message(e, "control plane"), 500)

    async def _handle_claim_task_async(self, body: dict[str, Any], handler: Any) -> HandlerResult:
        """Claim a task for an agent (async context)."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        coordinator = self._get_coordinator()
        if not coordinator:
            return error_response("Control plane not initialized", 503)

        agent_id = body.get("agent_id")
        if not agent_id:
            return error_response("agent_id is required", 400)

        capabilities = body.get("capabilities", [])
        block_ms = body.get("block_ms", 5000)

        try:
            task = await _await_if_needed(
                coordinator.claim_task(
                    agent_id=agent_id,
                    capabilities=capabilities,
                    block_ms=block_ms,
                )
            )

            if not task:
                return json_response({"task": None})

            self._emit_event(
                "emit_task_claimed",
                task_id=task.id,
                agent_id=agent_id,
            )

            return json_response({"task": task.to_dict()})
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Error claiming task: %s", e)
            return error_response(safe_error_message(e, "control plane"), 500)

    @api_endpoint(
        method="POST",
        path="/api/control-plane/tasks/{task_id}/complete",
        summary="Complete a task",
        tags=["Control Plane"],
    )
    @require_permission("controlplane:tasks.complete")
    def _handle_complete_task(
        self, task_id: str, body: dict[str, Any], handler: Any
    ) -> HandlerResult:
        """Mark task as completed."""
        # Require authentication for completing tasks
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        # Check permission for task management
        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        coordinator = self._get_coordinator()
        if not coordinator:
            return error_response("Control plane not initialized", 503)

        result = body.get("result")
        agent_id = body.get("agent_id")
        latency_ms = body.get("latency_ms")

        try:
            success = _run_async(
                coordinator.complete_task(
                    task_id=task_id,
                    result=result,
                    agent_id=agent_id,
                    latency_ms=latency_ms,
                )
            )

            if not success:
                return error_response(f"Task not found: {task_id}", 404)

            # Emit event for real-time streaming
            self._emit_event(
                "emit_task_completed",
                task_id=task_id,
                agent_id=agent_id or "unknown",
                result=result,
            )

            return json_response({"completed": True})
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Error completing task: %s", e)
            return error_response(safe_error_message(e, "control plane"), 500)

    async def _handle_complete_task_async(
        self, task_id: str, body: dict[str, Any], handler: Any
    ) -> HandlerResult:
        """Mark task as completed (async context)."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        coordinator = self._get_coordinator()
        if not coordinator:
            return error_response("Control plane not initialized", 503)

        result = body.get("result")
        agent_id = body.get("agent_id")
        latency_ms = body.get("latency_ms")

        try:
            success = await _await_if_needed(
                coordinator.complete_task(
                    task_id=task_id,
                    result=result,
                    agent_id=agent_id,
                    latency_ms=latency_ms,
                )
            )

            if not success:
                return error_response(f"Task not found: {task_id}", 404)

            self._emit_event(
                "emit_task_completed",
                task_id=task_id,
                agent_id=agent_id or "unknown",
                result=result,
            )

            return json_response({"completed": True})
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Error completing task: %s", e)
            return error_response(safe_error_message(e, "control plane"), 500)

    @api_endpoint(
        method="POST",
        path="/api/control-plane/tasks/{task_id}/fail",
        summary="Fail a task",
        tags=["Control Plane"],
    )
    @require_permission("controlplane:tasks.complete")
    def _handle_fail_task(self, task_id: str, body: dict[str, Any], handler: Any) -> HandlerResult:
        """Mark task as failed."""
        # Require authentication for failing tasks
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        # Check permission for task management
        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        coordinator = self._get_coordinator()
        if not coordinator:
            return error_response("Control plane not initialized", 503)

        error = body.get("error", "Unknown error")
        agent_id = body.get("agent_id")
        latency_ms = body.get("latency_ms")
        requeue = body.get("requeue", True)

        try:
            success = _run_async(
                coordinator.fail_task(
                    task_id=task_id,
                    error=error,
                    agent_id=agent_id,
                    latency_ms=latency_ms,
                    requeue=requeue,
                )
            )

            if not success:
                return error_response(f"Task not found: {task_id}", 404)

            # Emit event for real-time streaming
            self._emit_event(
                "emit_task_failed",
                task_id=task_id,
                agent_id=agent_id or "unknown",
                error=error,
                retries_left=0,  # Coordinator tracks retries
            )

            return json_response({"failed": True})
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Error failing task: %s", e)
            return error_response(safe_error_message(e, "control plane"), 500)

    async def _handle_fail_task_async(
        self, task_id: str, body: dict[str, Any], handler: Any
    ) -> HandlerResult:
        """Mark task as failed (async context)."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        coordinator = self._get_coordinator()
        if not coordinator:
            return error_response("Control plane not initialized", 503)

        error = body.get("error", "Unknown error")
        agent_id = body.get("agent_id")
        latency_ms = body.get("latency_ms")
        requeue = body.get("requeue", True)

        try:
            success = await _await_if_needed(
                coordinator.fail_task(
                    task_id=task_id,
                    error=error,
                    agent_id=agent_id,
                    latency_ms=latency_ms,
                    requeue=requeue,
                )
            )

            if not success:
                return error_response(f"Task not found: {task_id}", 404)

            self._emit_event(
                "emit_task_failed",
                task_id=task_id,
                agent_id=agent_id or "unknown",
                error=error,
                retries_left=0,
            )

            return json_response({"failed": True})
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Error failing task: %s", e)
            return error_response(safe_error_message(e, "control plane"), 500)

    @api_endpoint(
        method="POST",
        path="/api/control-plane/tasks/{task_id}/cancel",
        summary="Cancel a task",
        tags=["Control Plane"],
    )
    @require_permission("controlplane:tasks.complete")
    def _handle_cancel_task(self, task_id: str, handler: Any) -> HandlerResult:
        """Cancel a task."""
        # Require authentication for canceling tasks
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        # Check permission for task management
        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        coordinator = self._get_coordinator()
        if not coordinator:
            return error_response("Control plane not initialized", 503)

        try:
            success = _run_async(coordinator.cancel_task(task_id))

            if not success:
                return error_response(f"Task not found or already completed: {task_id}", 404)

            return json_response({"cancelled": True})
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Error cancelling task: %s", e)
            return error_response(safe_error_message(e, "control plane"), 500)

    async def _handle_cancel_task_async(self, task_id: str, handler: Any) -> HandlerResult:
        """Cancel a task (async context)."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        coordinator = self._get_coordinator()
        if not coordinator:
            return error_response("Control plane not initialized", 503)

        try:
            success = await _await_if_needed(coordinator.cancel_task(task_id))

            if not success:
                return error_response(f"Task not found or already completed: {task_id}", 404)

            return json_response({"cancelled": True})
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Error cancelling task: %s", e)
            return error_response(safe_error_message(e, "control plane"), 500)

    @api_endpoint(
        method="GET",
        path="/api/control-plane/queue",
        summary="Get job queue",
        tags=["Control Plane"],
    )
    @require_permission("controlplane:queue.read")
    def _handle_get_queue(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get current job queue (pending and running tasks)."""
        coordinator, err = self._require_coordinator()
        if err:
            return err

        try:
            from aragora.control_plane.scheduler import TaskStatus
            from datetime import datetime

            limit = safe_query_int(query_params, "limit", default=50, max_val=1000)

            # Get pending and running tasks
            pending = _run_async(
                coordinator._scheduler.list_by_status(TaskStatus.PENDING, limit=limit)
            )
            running = _run_async(
                coordinator._scheduler.list_by_status(TaskStatus.RUNNING, limit=limit)
            )

            # Format tasks as jobs for the frontend
            def task_to_job(task: Any) -> dict[str, Any]:
                # Calculate progress based on status
                progress = 0.0
                if task.status.value == "running":
                    # If running, estimate progress or use metadata
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
                        datetime.fromtimestamp(task.started_at).isoformat()
                        if task.started_at
                        else None
                    ),
                    "created_at": (
                        datetime.fromtimestamp(task.created_at).isoformat()
                        if task.created_at
                        else None
                    ),
                    "document_count": task.payload.get("document_count", 0),
                    "agents_assigned": [task.assigned_agent] if task.assigned_agent else [],
                    "priority": task.priority.name.lower(),
                }

            jobs = [task_to_job(t) for t in running] + [task_to_job(t) for t in pending]

            return json_response(
                {
                    "jobs": jobs,
                    "total": len(jobs),
                }
            )
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
            return error_response(safe_error_message(e, "control plane"), 500)

    @api_endpoint(
        method="GET",
        path="/api/control-plane/queue/metrics",
        summary="Get task queue performance metrics",
        tags=["Control Plane"],
    )
    @require_permission("controlplane:queue.read")
    def _handle_queue_metrics(self) -> HandlerResult:
        """Get task queue performance metrics."""
        coordinator = self._get_coordinator()

        try:
            stats = {}
            if coordinator and hasattr(coordinator, "_scheduler"):
                _scheduler = coordinator._scheduler  # noqa: F841
                scheduler_stats = _run_async(coordinator.get_stats())
                stats = {
                    "pending": scheduler_stats.get("pending_tasks", 0),
                    "running": scheduler_stats.get("running_tasks", 0),
                    "completed_today": scheduler_stats.get("completed_tasks", 0),
                    "failed_today": scheduler_stats.get("failed_tasks", 0),
                    "avg_wait_time_ms": scheduler_stats.get("avg_wait_time_ms", 0),
                    "avg_execution_time_ms": scheduler_stats.get("avg_execution_time_ms", 0),
                    "throughput_per_minute": scheduler_stats.get("throughput_per_minute", 0),
                }
            else:
                stats = {
                    "pending": 0,
                    "running": 0,
                    "completed_today": 0,
                    "failed_today": 0,
                    "avg_wait_time_ms": 0,
                    "avg_execution_time_ms": 0,
                    "throughput_per_minute": 0,
                }

            return json_response(stats)
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Error getting queue metrics: %s", e)
            return error_response(safe_error_message(e, "control plane"), 500)

    @api_endpoint(
        method="GET",
        path="/api/control-plane/tasks/history",
        summary="Get task execution history",
        tags=["Control Plane"],
    )
    @require_permission("controlplane:tasks.read")
    def _handle_task_history(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get task execution history for auditing and analysis.

        Returns completed, failed, cancelled, and timed-out tasks with
        full lifecycle metadata for enterprise auditing.

        Query params:
            status: Filter by status (completed, failed, cancelled, timeout)
            task_type: Filter by task type
            agent_id: Filter by assigned agent
            limit: Max results (default 100, max 1000)
            offset: Pagination offset
        """
        coordinator, err = self._require_coordinator()
        if err:
            return err

        try:
            from aragora.control_plane.scheduler import TaskStatus
            from datetime import datetime

            limit = safe_query_int(query_params, "limit", default=100, max_val=1000)
            offset = safe_query_int(query_params, "offset", default=0, max_val=10000)
            status_filter = query_params.get("status")
            task_type_filter = query_params.get("task_type")
            agent_filter = query_params.get("agent_id")

            # Determine which statuses to query
            history_statuses = [
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.TIMEOUT,
            ]

            if status_filter:
                status_map = {
                    "completed": TaskStatus.COMPLETED,
                    "failed": TaskStatus.FAILED,
                    "cancelled": TaskStatus.CANCELLED,
                    "timeout": TaskStatus.TIMEOUT,
                }
                if status_filter.lower() in status_map:
                    history_statuses = [status_map[status_filter.lower()]]

            # Collect tasks from all history statuses
            all_tasks = []
            for status in history_statuses:
                tasks = _run_async(
                    coordinator._scheduler.list_by_status(status, limit=limit + offset)
                )
                all_tasks.extend(tasks)

            # Apply filters
            if task_type_filter:
                all_tasks = [t for t in all_tasks if t.task_type == task_type_filter]
            if agent_filter:
                all_tasks = [t for t in all_tasks if t.assigned_agent == agent_filter]

            # Sort by completion time (most recent first)
            all_tasks.sort(
                key=lambda t: t.completed_at or t.created_at or 0,
                reverse=True,
            )

            # Apply pagination
            total = len(all_tasks)
            paginated = all_tasks[offset : offset + limit]

            def task_to_history(task: Any) -> dict[str, Any]:
                """Convert task to history entry."""
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
                        datetime.fromtimestamp(task.created_at).isoformat()
                        if task.created_at
                        else None
                    ),
                    "started_at": (
                        datetime.fromtimestamp(task.started_at).isoformat()
                        if task.started_at
                        else None
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

            return json_response(
                {
                    "history": history,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "has_more": offset + limit < total,
                }
            )
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
            return error_response(safe_error_message(e, "control plane"), 500)

    # =========================================================================
    # Deliberation Handlers
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/control-plane/deliberations/{request_id}",
        summary="Get deliberation result",
        tags=["Control Plane"],
    )
    def _handle_get_deliberation(
        self, request_id: str, handler: Any, scope: OrgScope
    ) -> HandlerResult:
        """Get a deliberation result the caller's org owns.

        Another org's result and one with no recorded owner answer like a missing one.
        """
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        from aragora.core.decision_results import get_decision_result_for_org

        result = get_decision_result_for_org(request_id, scope.org_id)
        if result is None:
            return record_not_found("Deliberation")
        return json_response(result)

    @api_endpoint(
        method="GET",
        path="/api/control-plane/deliberations/{request_id}/status",
        summary="Get deliberation status",
        tags=["Control Plane"],
    )
    def _handle_get_deliberation_status(
        self, request_id: str, handler: Any, scope: OrgScope
    ) -> HandlerResult:
        """Get the polling status of a deliberation the caller's org owns (404 otherwise)."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        from aragora.core.decision_results import get_decision_status_for_org

        status = get_decision_status_for_org(request_id, scope.org_id)
        if status is None:
            return record_not_found("Deliberation")
        return json_response(status)

    @api_endpoint(
        method="POST",
        path="/api/control-plane/deliberations",
        summary="Submit a deliberation",
        tags=["Control Plane"],
    )
    async def _handle_submit_deliberation(
        self, body: dict[str, Any], handler: Any
    ) -> HandlerResult:
        """Submit a deliberation (sync or async via control plane)."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        if not _get_has_permission()(
            user.role if hasattr(user, "role") else None, "controlplane:tasks"
        ):
            return error_response("Permission denied", 403)

        coordinator = self._get_coordinator()
        if not coordinator:
            return error_response("Control plane not initialized", 503)

        if not body.get("content"):
            return error_response("Missing required field: content", 400)

        try:
            from aragora.core.decision import DecisionRequest
            from aragora.billing.auth import extract_user_from_request

            headers = {}
            if hasattr(handler, "headers"):
                headers = dict(handler.headers)

            request = DecisionRequest.from_http(body, headers)

            auth_ctx = extract_user_from_request(handler)
            if auth_ctx.authenticated:
                if not request.context.user_id:
                    request.context.user_id = auth_ctx.user_id
                if not request.context.workspace_id:
                    request.context.workspace_id = auth_ctx.org_id
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)
        except (TypeError, KeyError, AttributeError, ImportError) as e:
            logger.warning("Failed to parse deliberation request: %s", e)
            return error_response("Failed to parse request", 400)

        async_mode = bool(body.get("async", False)) or body.get("mode") == "async"
        priority = body.get("priority", "normal")
        required_capabilities = body.get("required_capabilities") or ["deliberation"]
        timeout_seconds = body.get("timeout_seconds")

        if async_mode:
            try:
                from aragora.control_plane.scheduler import TaskPriority

                priority_enum = TaskPriority[priority.upper()]

                task_id = _run_async(
                    coordinator.submit_task(
                        task_type="deliberation",
                        payload=request.to_dict(),
                        required_capabilities=required_capabilities,
                        priority=priority_enum,
                        timeout_seconds=timeout_seconds,
                        metadata={"request_id": request.request_id},
                    )
                )

                self._emit_event(
                    "emit_task_submitted",
                    task_id=task_id,
                    task_type="deliberation",
                    priority=priority,
                    required_capabilities=required_capabilities,
                )

                return json_response(
                    {
                        "task_id": task_id,
                        "request_id": request.request_id,
                        "status": "queued",
                    },
                    status=202,
                )
            except KeyError:
                return error_response(f"Invalid priority: {priority}", 400)
            except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
                logger.error("Error submitting deliberation: %s", e)
                return error_response(safe_error_message(e, "control plane"), 500)

        try:
            from aragora.control_plane.deliberation import (
                run_deliberation,
                record_deliberation_error,
            )

            result = await run_deliberation(request)

            return json_response(
                {
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
            )
        except asyncio.TimeoutError:
            record_deliberation_error(request.request_id, "Deliberation timed out", "timeout")
            return error_response("Deliberation request timed out", 408)
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:  # broad catch: last-resort handler
            logger.exception("Deliberation failed: %s", e)
            record_deliberation_error(request.request_id, "Deliberation failed")
            return error_response("Deliberation failed", 500)
