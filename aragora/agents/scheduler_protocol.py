"""
Unified Scheduler Protocol.

Defines the common interface for task schedulers, allowing seamless switching
between local (Fabric) and distributed (Control Plane) implementations.

This abstraction enables:
- Development: Use local AgentScheduler for fast iteration
- Production: Use distributed TaskScheduler with Redis for multi-instance
- Testing: Use mock implementations for unit tests

Usage:
    from aragora.agents.scheduler_protocol import (
        SchedulerProtocol,
        get_scheduler,
        TaskInfo,
        SchedulerType,
    )

    # Get scheduler based on environment
    scheduler = get_scheduler()

    # Schedule a task
    handle = await scheduler.schedule_task(
        task_type="debate",
        payload={"topic": "..."},
        priority=Priority.HIGH,
    )

    # Check status
    status = await scheduler.get_task_status(handle.task_id)
"""

from __future__ import annotations

import os
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aragora.control_plane.scheduler import TaskScheduler
    from aragora.fabric.scheduler import AgentScheduler

# Re-export common types
from aragora.fabric.models import Priority, TaskStatus


class SchedulerType(Enum):
    """Available scheduler implementations."""

    LOCAL = "local"  # In-memory AgentScheduler
    DISTRIBUTED = "distributed"  # Redis-backed TaskScheduler
    AUTO = "auto"  # Auto-detect based on environment


@dataclass
class TaskInfo:
    """
    Unified task information returned by all scheduler implementations.

    Provides a common view of task state regardless of backend.
    """

    task_id: str
    task_type: str
    status: TaskStatus
    priority: Priority
    agent_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        """Check if task is in a terminal state."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    @property
    def duration_seconds(self) -> float | None:
        """Get task duration in seconds, if completed."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


@runtime_checkable
class SchedulerProtocol(Protocol):
    """
    Protocol defining the unified scheduler interface.

    Both AgentScheduler (local) and TaskScheduler (distributed)
    implement this interface for interchangeable use.
    """

    @abstractmethod
    async def schedule_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        priority: Priority = Priority.NORMAL,
        agent_id: str | None = None,
        timeout_seconds: float | None = None,
        depends_on: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskInfo:
        """
        Schedule a new task for execution.

        Args:
            task_type: Type of task (e.g., "debate", "analysis", "generation")
            payload: Task-specific data
            priority: Task priority level
            agent_id: Optional specific agent to assign to
            timeout_seconds: Task timeout (None for default)
            depends_on: List of task IDs this task depends on
            metadata: Additional metadata for tracking

        Returns:
            TaskInfo with the scheduled task details
        """
        ...

    @abstractmethod
    async def get_task_status(self, task_id: str) -> TaskInfo | None:
        """
        Get current status of a task.

        Args:
            task_id: The task identifier

        Returns:
            TaskInfo if found, None otherwise
        """
        ...

    @abstractmethod
    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a pending or running task.

        Args:
            task_id: The task identifier

        Returns:
            True if cancelled, False if already completed or not found
        """
        ...

    @abstractmethod
    async def list_tasks(
        self,
        status: TaskStatus | None = None,
        agent_id: str | None = None,
        task_type: str | None = None,
        limit: int = 100,
    ) -> list[TaskInfo]:
        """
        List tasks with optional filtering.

        Args:
            status: Filter by status
            agent_id: Filter by assigned agent
            task_type: Filter by task type
            limit: Maximum number of tasks to return

        Returns:
            List of matching TaskInfo objects
        """
        ...

    @abstractmethod
    async def get_queue_stats(self) -> dict[str, Any]:
        """
        Get scheduler queue statistics.

        Returns:
            Dict with queue depths, agent counts, task stats, etc.
        """
        ...


class LocalSchedulerAdapter:
    """
    Adapter wrapping AgentScheduler to implement SchedulerProtocol.

    Translates between the fabric scheduler's interface and the unified protocol.
    """

    def __init__(self, scheduler: AgentScheduler | None = None):
        """Initialize with optional existing scheduler."""
        if scheduler is None:
            from aragora.fabric.scheduler import AgentScheduler

            scheduler = AgentScheduler()
        self._scheduler = scheduler
        self._task_types: dict[str, str] = {}  # task_id -> task_type

    async def schedule_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        priority: Priority = Priority.NORMAL,
        agent_id: str | None = None,
        timeout_seconds: float | None = None,
        depends_on: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskInfo:
        """Schedule task via local scheduler."""
        import uuid

        from aragora.fabric.models import Task

        # Create task with payload (Task model uses id/type not name)
        task = Task(
            id=str(uuid.uuid4()),
            type=task_type,
            payload=payload,
            timeout_seconds=timeout_seconds,
            metadata={k: str(v) for k, v in (metadata or {}).items()},
            depends_on=depends_on or [],
        )

        # Default agent if not specified
        target_agent = agent_id or "default"

        # Schedule via fabric scheduler
        handle = await self._scheduler.schedule(
            task=task,
            agent_id=target_agent,
            priority=priority,
            depends_on=depends_on,
            timeout_seconds=timeout_seconds,
        )

        # Track task type
        self._task_types[handle.task_id] = task_type

        return TaskInfo(
            task_id=handle.task_id,
            task_type=task_type,
            status=handle.status,
            priority=priority,
            agent_id=target_agent,
            created_at=handle.scheduled_at,
            metadata=metadata or {},
        )

    async def get_task_status(self, task_id: str) -> TaskInfo | None:
        """Get task status from local scheduler."""
        handle = await self._scheduler.get_handle(task_id)
        if handle is None:
            return None

        return TaskInfo(
            task_id=handle.task_id,
            task_type=self._task_types.get(task_id, "unknown"),
            status=handle.status,
            priority=Priority.NORMAL,  # Local scheduler doesn't track priority
            agent_id=handle.agent_id,
            created_at=handle.scheduled_at,
            started_at=handle.started_at,
            completed_at=handle.completed_at,
            result=handle.result,
            error=handle.error,
        )

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel task via local scheduler."""
        return await self._scheduler.cancel(task_id)

    async def list_tasks(
        self,
        status: TaskStatus | None = None,
        agent_id: str | None = None,
        task_type: str | None = None,
        limit: int = 100,
    ) -> list[TaskInfo]:
        """List tasks from local scheduler."""
        tasks = []
        for tid, handle in list(self._scheduler._tasks.items())[:limit]:
            if status and handle.status != status:
                continue
            if agent_id and handle.agent_id != agent_id:
                continue
            if task_type and self._task_types.get(tid) != task_type:
                continue

            tasks.append(
                TaskInfo(
                    task_id=handle.task_id,
                    task_type=self._task_types.get(tid, "unknown"),
                    status=handle.status,
                    priority=Priority.NORMAL,
                    agent_id=handle.agent_id,
                    created_at=handle.scheduled_at,
                    started_at=handle.started_at,
                    completed_at=handle.completed_at,
                    result=handle.result,
                    error=handle.error,
                )
            )

        return tasks[:limit]

    async def get_queue_stats(self) -> dict[str, Any]:
        """Get queue statistics from local scheduler."""
        return {
            "scheduler_type": "local",
            "total_tasks": len(self._scheduler._tasks),
            "tasks_scheduled": self._scheduler._tasks_scheduled,
            "tasks_completed": self._scheduler._tasks_completed,
            "tasks_failed": self._scheduler._tasks_failed,
            "tasks_cancelled": self._scheduler._tasks_cancelled,
            "agent_queues": {
                agent_id: len(queue) for agent_id, queue in self._scheduler._agent_queues.items()
            },
        }


class DistributedSchedulerAdapter:
    """
    Adapter wrapping TaskScheduler to implement SchedulerProtocol.

    Translates between the control plane scheduler's interface and the unified protocol.
    """

    def __init__(self, scheduler: TaskScheduler | None = None):
        """Initialize with optional existing scheduler."""
        if scheduler is None:
            from aragora.control_plane.scheduler import TaskScheduler

            scheduler = TaskScheduler()
        self._scheduler = scheduler

    async def schedule_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        priority: Priority = Priority.NORMAL,
        agent_id: str | None = None,
        timeout_seconds: float | None = None,
        depends_on: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskInfo:
        """Schedule task via distributed scheduler."""
        from aragora.control_plane.scheduler import TaskPriority

        # Map priority
        priority_map = {
            Priority.CRITICAL: TaskPriority.URGENT,
            Priority.HIGH: TaskPriority.HIGH,
            Priority.NORMAL: TaskPriority.NORMAL,
            Priority.LOW: TaskPriority.LOW,
        }
        cp_priority = priority_map.get(priority, TaskPriority.NORMAL)

        # Submit task (returns task_id string)
        task_id = await self._scheduler.submit(
            task_type=task_type,
            payload=payload,
            priority=cp_priority,
            timeout_seconds=timeout_seconds if timeout_seconds is not None else 300.0,
            metadata=metadata,
        )

        return TaskInfo(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            priority=priority,
            agent_id=None,
            metadata=metadata or {},
        )

    async def get_task_status(self, task_id: str) -> TaskInfo | None:
        """Get task status from distributed scheduler."""
        from aragora.control_plane.scheduler import TaskStatus as CPTaskStatus

        task = await self._scheduler.get(task_id)
        if task is None:
            return None

        # Map status
        status_map = {
            CPTaskStatus.PENDING: TaskStatus.PENDING,
            CPTaskStatus.ASSIGNED: TaskStatus.RUNNING,
            CPTaskStatus.RUNNING: TaskStatus.RUNNING,
            CPTaskStatus.COMPLETED: TaskStatus.COMPLETED,
            CPTaskStatus.FAILED: TaskStatus.FAILED,
            CPTaskStatus.CANCELLED: TaskStatus.CANCELLED,
            CPTaskStatus.TIMEOUT: TaskStatus.FAILED,
        }

        return TaskInfo(
            task_id=task.id,
            task_type=task.task_type,
            status=status_map.get(task.status, TaskStatus.PENDING),
            priority=Priority.NORMAL,
            agent_id=task.assigned_agent,
            created_at=datetime.fromtimestamp(task.created_at),
            started_at=datetime.fromtimestamp(task.started_at) if task.started_at else None,
            completed_at=datetime.fromtimestamp(task.completed_at) if task.completed_at else None,
            result=task.result,
            error=task.error,
            metadata=task.metadata or {},
        )

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel task via distributed scheduler."""
        return await self._scheduler.cancel(task_id)

    async def list_tasks(
        self,
        status: TaskStatus | None = None,
        agent_id: str | None = None,
        task_type: str | None = None,
        limit: int = 100,
    ) -> list[TaskInfo]:
        """List tasks from distributed scheduler."""
        from aragora.control_plane.scheduler import TaskStatus as CPTaskStatus

        if status is not None:
            cp_status = CPTaskStatus(status.value)
            raw_tasks = await self._scheduler.list_by_status(
                status=cp_status,
                limit=limit,
            )
        else:
            # No status filter: gather from all statuses
            raw_tasks = []
            for cp_s in CPTaskStatus:
                raw_tasks.extend(await self._scheduler.list_by_status(status=cp_s, limit=limit))
            raw_tasks = raw_tasks[:limit]

        # Apply client-side filters for agent_id and task_type
        results: list[TaskInfo] = []
        for t in raw_tasks:
            if agent_id and t.assigned_agent != agent_id:
                continue
            if task_type and t.task_type != task_type:
                continue
            results.append(
                TaskInfo(
                    task_id=t.id,
                    task_type=t.task_type,
                    status=TaskStatus(t.status.value),
                    priority=Priority.NORMAL,
                    agent_id=t.assigned_agent,
                    created_at=t.created_at,  # type: ignore[arg-type]
                    metadata=t.metadata or {},
                )
            )
        return results[:limit]

    async def get_queue_stats(self) -> dict[str, Any]:
        """Get queue statistics from distributed scheduler."""
        stats = await self._scheduler.get_stats()
        return {
            "scheduler_type": "distributed",
            **stats,
        }


# Module-level singleton
_scheduler: SchedulerProtocol | None = None


def get_scheduler(
    scheduler_type: SchedulerType = SchedulerType.AUTO,
) -> SchedulerProtocol:
    """
    Get the configured scheduler instance.

    Args:
        scheduler_type: Which scheduler to use (AUTO detects from environment)

    Returns:
        SchedulerProtocol implementation

    Environment Variables:
        ARAGORA_SCHEDULER_TYPE: Override scheduler type (local, distributed)
        REDIS_URL: If set and AUTO, uses distributed scheduler
    """
    global _scheduler

    if _scheduler is not None:
        return _scheduler

    # Check environment override
    env_type = os.environ.get("ARAGORA_SCHEDULER_TYPE", "").lower()
    if env_type == "local":
        scheduler_type = SchedulerType.LOCAL
    elif env_type == "distributed":
        scheduler_type = SchedulerType.DISTRIBUTED

    # Auto-detect based on Redis availability
    if scheduler_type == SchedulerType.AUTO:
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            scheduler_type = SchedulerType.DISTRIBUTED
        else:
            scheduler_type = SchedulerType.LOCAL

    # Create appropriate adapter
    if scheduler_type == SchedulerType.DISTRIBUTED:
        _scheduler = DistributedSchedulerAdapter()
    else:
        _scheduler = LocalSchedulerAdapter()

    return _scheduler


def reset_scheduler() -> None:
    """Reset scheduler singleton (for testing)."""
    global _scheduler
    _scheduler = None


__all__ = [
    "SchedulerProtocol",
    "SchedulerType",
    "TaskInfo",
    "Priority",
    "TaskStatus",
    "LocalSchedulerAdapter",
    "DistributedSchedulerAdapter",
    "get_scheduler",
    "reset_scheduler",
]
