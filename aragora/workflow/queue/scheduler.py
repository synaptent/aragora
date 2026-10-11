"""
Dependency-Aware Task Scheduler.

Provides scheduling policies and dependency resolution for workflow tasks.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from collections.abc import Callable

from aragora.workflow.queue.task import (
    TaskPriority,
    TaskResult,
    TaskStatus,
    WorkflowTask,
)
from aragora.workflow.queue.queue import TaskQueue
from aragora.workflow.queue.executor import ExecutorPool

logger = logging.getLogger(__name__)


class SchedulingPolicy(str, Enum):
    """Task scheduling policies."""

    FIFO = "fifo"  # First in, first out
    PRIORITY = "priority"  # Priority-based (default)
    SHORTEST_FIRST = "shortest_first"  # Shortest estimated time first
    DEADLINE = "deadline"  # Earliest deadline first
    FAIR = "fair"  # Fair share among workflows


@dataclass
class SchedulerConfig:
    """Configuration for the scheduler."""

    policy: SchedulingPolicy = SchedulingPolicy.PRIORITY
    max_concurrent_workflows: int = 10
    max_tasks_per_workflow: int = 100
    enable_preemption: bool = False
    starvation_threshold_seconds: float = 300.0  # 5 minutes
    rebalance_interval_seconds: float = 30.0


@dataclass
class WorkflowState:
    """State tracking for a workflow."""

    workflow_id: str
    task_ids: set[str] = field(default_factory=set)
    pending_count: int = 0
    running_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def is_complete(self) -> bool:
        """Check if workflow is complete."""
        return self.pending_count == 0 and self.running_count == 0

    @property
    def progress(self) -> float:
        """Get workflow progress (0.0 to 1.0)."""
        total = len(self.task_ids)
        if total == 0:
            return 0.0
        return self.completed_count / total


class DependencyGraph:
    """
    Directed acyclic graph for task dependencies.

    Tracks task dependencies and provides topological ordering
    for scheduling.
    """

    def __init__(self) -> None:
        # task_id -> set of task IDs it depends on
        self._dependencies: dict[str, set[str]] = defaultdict(set)
        # task_id -> set of task IDs that depend on it
        self._dependents: dict[str, set[str]] = defaultdict(set)
        # All registered tasks
        self._tasks: set[str] = set()

    def add_task(self, task_id: str, depends_on: list[str] | None = None) -> None:
        """Add a task with its dependencies."""
        self._tasks.add(task_id)

        if depends_on:
            for dep_id in depends_on:
                self._dependencies[task_id].add(dep_id)
                self._dependents[dep_id].add(task_id)

    def remove_task(self, task_id: str) -> None:
        """Remove a task from the graph."""
        self._tasks.discard(task_id)

        # Remove from dependencies
        deps = self._dependencies.pop(task_id, set())
        for dep_id in deps:
            self._dependents[dep_id].discard(task_id)

        # Remove from dependents
        dependents = self._dependents.pop(task_id, set())
        for dep_id in dependents:
            self._dependencies[dep_id].discard(task_id)

    def get_ready_tasks(self, completed: set[str]) -> set[str]:
        """
        Get tasks that are ready to execute.

        A task is ready if all its dependencies are in the completed set.
        """
        ready = set()

        for task_id in self._tasks:
            if task_id in completed:
                continue

            deps = self._dependencies.get(task_id, set())
            if deps.issubset(completed):
                ready.add(task_id)

        return ready

    def get_dependencies(self, task_id: str) -> set[str]:
        """Get tasks this task depends on."""
        return self._dependencies.get(task_id, set()).copy()

    def get_dependents(self, task_id: str) -> set[str]:
        """Get tasks that depend on this task."""
        return self._dependents.get(task_id, set()).copy()

    def has_cycle(self) -> bool:
        """Check if the graph has a cycle."""
        visited = set()
        rec_stack = set()

        def dfs(task_id: str) -> bool:
            visited.add(task_id)
            rec_stack.add(task_id)

            for dep_id in self._dependents.get(task_id, set()):
                if dep_id not in visited:
                    if dfs(dep_id):
                        return True
                elif dep_id in rec_stack:
                    return True

            rec_stack.discard(task_id)
            return False

        for task_id in self._tasks:
            if task_id not in visited:
                if dfs(task_id):
                    return True

        return False

    def topological_sort(self) -> list[str]:
        """
        Return tasks in topological order.

        Tasks with no dependencies come first.
        """
        in_degree: dict[str, int] = dict.fromkeys(self._tasks, 0)

        for task_id in self._tasks:
            for dep_id in self._dependencies.get(task_id, set()):
                if dep_id in in_degree:
                    in_degree[task_id] += 1

        # Start with tasks that have no dependencies
        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            task_id = queue.pop(0)
            result.append(task_id)

            for dep_id in self._dependents.get(task_id, set()):
                if dep_id in in_degree:
                    in_degree[dep_id] -= 1
                    if in_degree[dep_id] == 0:
                        queue.append(dep_id)

        return result


class DependencyScheduler:
    """
    Dependency-aware task scheduler.

    Manages workflow execution by scheduling tasks based on
    dependencies and the configured scheduling policy.
    """

    def __init__(
        self,
        config: SchedulerConfig | None = None,
        queue: TaskQueue | None = None,
        executor_pool: ExecutorPool | None = None,
    ):
        self._config = config or SchedulerConfig()
        self._queue = queue or TaskQueue()
        self._executor_pool = executor_pool or ExecutorPool()

        # Workflow tracking
        self._workflows: dict[str, WorkflowState] = {}
        self._dependency_graphs: dict[str, DependencyGraph] = {}

        # Task tracking
        self._tasks: dict[str, WorkflowTask] = {}
        self._completed_tasks: dict[str, set[str]] = defaultdict(
            set
        )  # workflow_id -> completed task_ids

        # Control
        self._started = False
        self._stopping = False
        self._rebalance_task: asyncio.Task | None = None

        # Callbacks
        self._on_workflow_complete: Callable[[str], None] | None = None
        self._on_task_scheduled: Callable[[WorkflowTask], None] | None = None

    async def start(self) -> None:
        """Start the scheduler."""
        if self._started:
            return

        await self._queue.start()
        await self._executor_pool.start()

        # Connect executor to queue
        self._queue.set_executor(self._executor_pool)

        # Set up completion callback
        self._queue.on_task_complete(self._handle_task_complete)

        self._started = True
        self._stopping = False

        # Start rebalancing
        if self._config.policy == SchedulingPolicy.FAIR:
            self._rebalance_task = asyncio.create_task(self._rebalance_loop())

        logger.info("Dependency scheduler started")

    async def stop(self, drain: bool = True) -> None:
        """Stop the scheduler."""
        if not self._started:
            return

        self._stopping = True

        if self._rebalance_task:
            self._rebalance_task.cancel()
            try:
                await self._rebalance_task
            except asyncio.CancelledError:
                pass

        await self._queue.stop(drain=drain)
        await self._executor_pool.stop(drain=drain)

        self._started = False
        logger.info("Dependency scheduler stopped")

    async def submit_workflow(
        self,
        workflow_id: str,
        tasks: list[WorkflowTask],
    ) -> str:
        """
        Submit a workflow for execution.

        Args:
            workflow_id: Unique workflow identifier
            tasks: List of tasks in the workflow

        Returns:
            Workflow ID
        """
        if len(self._workflows) >= self._config.max_concurrent_workflows:
            raise RuntimeError("Maximum concurrent workflows reached")

        if len(tasks) > self._config.max_tasks_per_workflow:
            raise RuntimeError("Too many tasks in workflow")

        # Create workflow state
        state = WorkflowState(
            workflow_id=workflow_id,
            task_ids={t.id for t in tasks},
            pending_count=len(tasks),
            started_at=datetime.now(),
        )
        self._workflows[workflow_id] = state

        # Build dependency graph
        graph = DependencyGraph()
        for task in tasks:
            graph.add_task(task.id, task.depends_on)
            self._tasks[task.id] = task

        if graph.has_cycle():
            del self._workflows[workflow_id]
            raise ValueError("Workflow has circular dependencies")

        self._dependency_graphs[workflow_id] = graph

        # Schedule initial tasks (those with no dependencies)
        ready_tasks = graph.get_ready_tasks(set())
        for task_id in ready_tasks:
            task = self._tasks.get(task_id)
            if task:
                await self._schedule_task(task)

        logger.info("Submitted workflow %s with %s tasks", workflow_id, len(tasks))
        return workflow_id

    async def _schedule_task(self, task: WorkflowTask) -> None:
        """Schedule a task for execution."""
        # Apply scheduling policy
        if self._config.policy == SchedulingPolicy.PRIORITY:
            # Priority is already set on the task
            pass
        elif self._config.policy == SchedulingPolicy.FIFO:
            # Use creation time as tiebreaker
            pass
        elif self._config.policy == SchedulingPolicy.FAIR:
            # Adjust priority based on workflow progress
            workflow = self._workflows.get(task.workflow_id)
            if workflow and workflow.running_count > 2:
                # Reduce priority if workflow has many running tasks
                task.priority = TaskPriority(
                    min(task.priority.value + 10, TaskPriority.BACKGROUND.value)
                )

        await self._queue.enqueue(task)

        if self._on_task_scheduled:
            self._on_task_scheduled(task)

        logger.debug("Scheduled task %s", task.id)

    def _handle_task_complete(self, task: WorkflowTask) -> None:
        """Handle task completion."""
        workflow_id = task.workflow_id
        workflow = self._workflows.get(workflow_id)

        if not workflow:
            return

        # Update workflow state
        workflow.running_count -= 1

        if task.status == TaskStatus.COMPLETED:
            workflow.completed_count += 1
            self._completed_tasks[workflow_id].add(task.id)

            # Schedule dependent tasks
            graph = self._dependency_graphs.get(workflow_id)
            if graph:
                completed = self._completed_tasks[workflow_id]
                ready_tasks = graph.get_ready_tasks(completed)

                for ready_id in ready_tasks:
                    if ready_id not in completed:
                        ready_task = self._tasks.get(ready_id)
                        if ready_task and ready_task.status == TaskStatus.PENDING:
                            asyncio.create_task(self._schedule_task(ready_task))
                            workflow.pending_count -= 1
                            workflow.running_count += 1

        elif task.status in (TaskStatus.FAILED, TaskStatus.TIMEOUT):
            workflow.failed_count += 1
            workflow.pending_count -= 1

        # Check workflow completion
        if workflow.is_complete:
            workflow.completed_at = datetime.now()
            logger.info("Workflow %s completed", workflow_id)

            if self._on_workflow_complete:
                self._on_workflow_complete(workflow_id)

    async def wait_for_workflow(
        self,
        workflow_id: str,
        timeout: float | None = None,
    ) -> dict[str, TaskResult]:
        """
        Wait for a workflow to complete.

        Args:
            workflow_id: Workflow to wait for
            timeout: Maximum wait time in seconds

        Returns:
            Dict mapping task IDs to their results
        """
        return await self._queue.wait_for_workflow(workflow_id, timeout)

    async def cancel_workflow(self, workflow_id: str) -> int:
        """
        Cancel a workflow and all its pending tasks.

        Returns:
            Number of tasks cancelled
        """
        cancelled = self._queue.cancel_workflow(workflow_id)

        workflow = self._workflows.get(workflow_id)
        if workflow:
            workflow.completed_at = datetime.now()

        logger.info("Cancelled workflow %s, %s tasks cancelled", workflow_id, cancelled)
        return cancelled

    def get_workflow_state(self, workflow_id: str) -> WorkflowState | None:
        """Get the current state of a workflow."""
        return self._workflows.get(workflow_id)

    def get_workflow_progress(self, workflow_id: str) -> float:
        """Get workflow progress (0.0 to 1.0)."""
        workflow = self._workflows.get(workflow_id)
        return workflow.progress if workflow else 0.0

    async def _rebalance_loop(self) -> None:
        """Periodically rebalance task priorities for fairness."""
        while not self._stopping:
            try:
                await asyncio.sleep(self._config.rebalance_interval_seconds)
                await self._rebalance()
            except asyncio.CancelledError:
                break
            except (RuntimeError, ValueError, TypeError, OSError) as e:
                logger.error("Rebalance error: %s", e)

    async def _rebalance(self) -> None:
        """Rebalance task priorities based on workflow fairness."""
        # Check for starvation
        now = datetime.now()

        for workflow_id, workflow in self._workflows.items():
            if workflow.is_complete:
                continue

            if workflow.started_at:
                elapsed = (now - workflow.started_at).total_seconds()

                # Check for starvation
                if elapsed > self._config.starvation_threshold_seconds and workflow.progress < 0.1:
                    logger.warning("Workflow %s may be starving", workflow_id)
                    # Could boost priority of pending tasks here

    def on_workflow_complete(self, callback: Callable[[str], None]) -> None:
        """Set callback for workflow completion."""
        self._on_workflow_complete = callback

    def on_task_scheduled(self, callback: Callable[[WorkflowTask], None]) -> None:
        """Set callback for task scheduling."""
        self._on_task_scheduled = callback

    def get_stats(self) -> dict[str, Any]:
        """Get scheduler statistics."""
        queue_stats = self._queue.get_stats()
        pool_stats = self._executor_pool.get_stats()

        workflow_stats = {
            wid: {
                "task_count": len(w.task_ids),
                "pending": w.pending_count,
                "running": w.running_count,
                "completed": w.completed_count,
                "failed": w.failed_count,
                "progress": w.progress,
                "is_complete": w.is_complete,
            }
            for wid, w in self._workflows.items()
        }

        return {
            "policy": self._config.policy.value,
            "active_workflows": len([w for w in self._workflows.values() if not w.is_complete]),
            "total_workflows": len(self._workflows),
            "queue": {
                "pending": queue_stats.pending_count,
                "ready": queue_stats.ready_count,
                "running": queue_stats.running_count,
                "completed": queue_stats.completed_count,
                "failed": queue_stats.failed_count,
            },
            "executor_pool": {
                "executor_count": pool_stats["executor_count"],
                "utilization": pool_stats["utilization"],
            },
            "workflows": workflow_stats,
        }
